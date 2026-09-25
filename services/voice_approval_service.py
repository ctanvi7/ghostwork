"""Governed voice approval flow shared by Vobiz callbacks and the web UI."""

import hashlib
import hmac
import logging
import re
import secrets
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree

from config import Config
from orchestrator.workflow import run_execution
from services.approvals_service import decide
from services.approver_service import ApproverUnavailableError, resolve_approver
from services.sarvam_service import SarvamError, synthesize, transcribe
from services.supabase_service import get_service
from services.vobiz_service import VobizError, fetch_recording, place_approval_call

logger = logging.getLogger(__name__)
_audio_cache: dict[tuple[int, str], bytes] = {}


class VoiceApprovalError(Exception):
    """A voice request is invalid or cannot be handled safely."""


def _metadata(approval: dict) -> dict:
    return dict(approval.get("raw_response_json") or {})


def _update_pending(approval_id: int, **fields) -> None:
    if not get_service().transition_approval(approval_id, "PENDING", "PENDING", **fields):
        raise VoiceApprovalError("Approval was already decided")


def _callback_url(approval_id: int, token: str, action: str) -> str:
    query = urlencode({"approval_id": approval_id, "token": token, "action": action})
    return f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/webhooks/vobiz?{query}"


def _prompt(amount: object, confirmation: bool = False) -> str:
    if confirmation:
        return "Final confirmation. Press 1 to confirm approval. Press 2 to reject."
    amount_text = f"{Decimal(str(amount)):,.0f}" if amount is not None else "an unspecified amount"
    return (
        f"GhostWork refund approval request for {amount_text} rupees. "
        "Say approve or reject after the tone, or press 1 to approve or 2 to reject. "
        "Approval needs a second confirmation."
    )


def start_call(execution_id: int) -> dict:
    """Prepare prompts, persist a callback token hash, and ask Vobiz to dial."""
    service = get_service()
    execution = service.get_execution(execution_id)
    if not execution:
        raise VoiceApprovalError("Execution not found")
    if execution["status"] != "WAITING_FOR_APPROVAL":
        raise VoiceApprovalError("Execution is not waiting for approval")
    approval = service.get_open_approval(execution_id)
    if not approval or approval["status"] != "PENDING":
        raise VoiceApprovalError("No pending approval exists")
    try:
        amount = Decimal(str(approval.get("amount")))
    except (InvalidOperation, TypeError):
        raise VoiceApprovalError("A known refund amount is required for voice approval")
    if not amount.is_finite() or amount <= 0:
        raise VoiceApprovalError("A positive refund amount is required for voice approval")
    if not Config.voice_call_configured():
        raise VoiceApprovalError("Voice calling is not configured; use web approval")

    # Call the Freshdesk ticket's assigned agent (APPROVER_PHONE only as a fallback).
    try:
        approver = resolve_approver(execution.get("ticket_id"))
    except ApproverUnavailableError as exc:
        raise VoiceApprovalError(str(exc)) from exc

    token = secrets.token_urlsafe(32)
    metadata = {
        "voice_token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "voice_stage": "choice",
        "approver_source": approver["source"],
        "approver_agent_id": approver["agent_id"],
        "approver_number_masked": approver["masked"],
    }
    _clear_audio(approval["id"])

    if Config.SARVAM_API_KEY:
        try:
            for kind in ("request", "confirm"):
                _audio_cache[(approval["id"], kind)] = _synthesize_prompt(approval, kind)
            # Persisted (not just cached) so any server instance knows to <Play> Sarvam audio.
            metadata["sarvam_audio"] = True
        except SarvamError:
            _clear_audio(approval["id"])
            logger.warning("Sarvam TTS unavailable; Vobiz Speak fallback will be used")

    # Saved before dialing, so the first Vobiz callback always finds the token and audio flag.
    _update_pending(approval["id"], channel="voice", raw_response_json=metadata)

    try:
        call_id = place_approval_call(
            _callback_url(approval["id"], token, "answer"),
            _callback_url(approval["id"], token, "hangup"),
            approver["to"],
        )
    except VobizError:
        _update_pending(approval["id"], channel="web", raw_response_json={"voice_status": "call_failed"})
        raise
    metadata["call_id"] = call_id
    _update_pending(approval["id"], raw_response_json=metadata)
    service.log_audit_event(execution_id, "VOICE_CALL_STARTED", actor="vobiz", detail={
        "approval_id": approval["id"],
        "approver_source": approver["source"],
        "approver_agent_id": approver["agent_id"],
        "approver_number_masked": approver["masked"],
    })
    return {
        "status": "calling",
        "approval_id": approval["id"],
        "call_id": call_id,
        "approver": {"source": approver["source"], "number": approver["masked"], "note": approver["note"]},
    }


def _checked_approval(approval_id: int, token: str) -> dict:
    approval = get_service().select_one("approvals", {"id": approval_id})
    if not approval or approval.get("status") not in ("PENDING", "AWAITING_CONFIRMATION"):
        raise VoiceApprovalError("Approval is no longer pending")
    expected = _metadata(approval).get("voice_token_hash", "")
    actual = hashlib.sha256(token.encode()).hexdigest()
    if not expected or not hmac.compare_digest(expected, actual):
        raise VoiceApprovalError("Invalid voice callback")
    execution = get_service().get_execution(approval["execution_id"])
    if not execution or execution["status"] != "WAITING_FOR_APPROVAL":
        raise VoiceApprovalError("Execution is no longer awaiting approval")
    return approval


def _synthesize_prompt(approval: dict, kind: str) -> bytes:
    if kind == "confirm":
        return synthesize(_prompt(None, confirmation=True))
    return synthesize(_prompt(approval.get("amount")))


def get_audio(approval_id: int, token: str, kind: str) -> bytes:
    approval = _checked_approval(approval_id, token)
    audio = _audio_cache.get((approval_id, kind))
    if audio:
        return audio
    # Serverless: Vobiz may reach a different instance than the one that
    # prepared the prompt, so regenerate it instead of failing the call.
    if not _metadata(approval).get("sarvam_audio"):
        raise VoiceApprovalError("Audio is unavailable")
    try:
        audio = _synthesize_prompt(approval, kind)
    except SarvamError as exc:
        raise VoiceApprovalError("Audio is unavailable") from exc
    _audio_cache[(approval_id, kind)] = audio
    return audio


def _xml_prompt(approval: dict, token: str, confirmation: bool = False) -> str:
    approval_id = approval["id"]
    kind = "confirm" if confirmation else "request"
    root = ElementTree.Element("Response")
    gather = ElementTree.SubElement(root, "Gather", {
        "action": _callback_url(approval_id, token, "confirm" if confirmation else "choice"),
        "method": "POST",
        "inputType": "dtmf",
        "numDigits": "1",
        "executionTimeout": "8",
    })
    if _metadata(approval).get("sarvam_audio") or (approval_id, kind) in _audio_cache:
        audio_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/voice/audio/{approval_id}/{kind}?{urlencode({'token': token})}"
        ElementTree.SubElement(gather, "Play").text = audio_url
    else:
        ElementTree.SubElement(gather, "Speak").text = _prompt(approval.get("amount"), confirmation)
    if confirmation:
        ElementTree.SubElement(root, "Speak").text = "No confirmation received. Please use web approval."
    elif Config.SARVAM_API_KEY:
        ElementTree.SubElement(root, "Speak").text = "After the tone, say approve or reject."
        ElementTree.SubElement(root, "Record", {
            "action": _callback_url(approval_id, token, "record"),
            "method": "POST",
            "maxLength": "15",
            "playBeep": "true",
        })
    else:
        ElementTree.SubElement(root, "Speak").text = "No response received. Please use web approval."
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding="unicode")


def _hangup(message: str) -> str:
    root = ElementTree.Element("Response")
    ElementTree.SubElement(root, "Speak").text = message
    ElementTree.SubElement(root, "Hangup")
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding="unicode")


def _clear_audio(approval_id: int) -> None:
    _audio_cache.pop((approval_id, "request"), None)
    _audio_cache.pop((approval_id, "confirm"), None)


def _intent(transcript: str) -> str | None:
    phrase = " ".join(re.findall(r"[a-z]+", transcript.lower()))
    if phrase in {
        "approve", "approved", "i approve", "i approve this refund",
        "i approve the refund", "yes i approve", "yes approve",
    }:
        return "approve"
    if phrase in {
        "reject", "rejected", "i reject", "i reject this refund",
        "i reject the refund", "no", "do not approve", "don t approve",
    }:
        return "reject"
    return None


def handle_callback(approval_id: int, token: str, action: str, form: dict) -> str:
    approval = _checked_approval(approval_id, token)
    service = get_service()
    metadata = _metadata(approval)
    execution_id = approval["execution_id"]

    if action == "hangup":
        _clear_audio(approval_id)
        service.log_audit_event(execution_id, "VOICE_CALL_ENDED", actor="vobiz", detail={"approval_id": approval_id})
        return _hangup("Web approval remains available.")
    if action == "answer":
        return _xml_prompt(approval, token)
    if action == "choice":
        digit = form.get("Digits") or form.get("digits")
        if digit == "1":
            metadata["voice_stage"] = "confirm"
            _update_pending(approval_id, raw_response_json=metadata)
            return _xml_prompt(approval, token, confirmation=True)
        if digit == "2":
            decide(execution_id, "reject", channel="voice", approver="phone_approver", raw_response={"method": "dtmf"})
            _clear_audio(approval_id)
            return _hangup("Refund rejected.")
        return _xml_prompt(approval, token)
    if action == "confirm":
        if metadata.get("voice_stage") != "confirm":
            raise VoiceApprovalError("Confirmation was not requested")
        digit = form.get("Digits") or form.get("digits")
        if digit == "1":
            decide(execution_id, "approve", channel="voice", approver="phone_approver", raw_response={"method": "dtmf_confirmed"})
            run_execution(execution_id)
            _clear_audio(approval_id)
            return _hangup("Approval confirmed. GhostWork will continue the workflow.")
        if digit == "2":
            decide(execution_id, "reject", channel="voice", approver="phone_approver", raw_response={"method": "dtmf"})
            _clear_audio(approval_id)
            return _hangup("Refund rejected.")
        return _xml_prompt(approval, token, confirmation=True)
    if action == "record":
        recording_url = (
            form.get("RecordingUrl") or form.get("RecordingURL")
            or form.get("RecordUrl") or form.get("recording_url")
        )
        try:
            extension = urlparse(recording_url or "").path.lower().rsplit(".", 1)[-1]
            filename = "response.mp3" if extension == "mp3" else "response.wav"
            transcript = transcribe(fetch_recording(recording_url or ""), filename=filename)
            intent = _intent(transcript)
        except (SarvamError, VobizError):
            logger.warning("Voice recognition failed; approval remains pending")
            intent = None
        if intent == "reject":
            decide(execution_id, "reject", channel="voice", approver="phone_approver", raw_response={"method": "speech"})
            _clear_audio(approval_id)
            return _hangup("Refund rejected.")
        if intent == "approve":
            metadata["voice_stage"] = "confirm"
            _update_pending(approval_id, raw_response_json=metadata)
            return _xml_prompt(approval, token, confirmation=True)
        return _xml_prompt(approval, token)
    raise VoiceApprovalError("Unknown voice callback action")
