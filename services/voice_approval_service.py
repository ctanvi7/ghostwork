"""Governed voice approval flow shared by Vobiz callbacks and the web UI.

The approver answers with one key press: 1 approves, 2 rejects. Speech is
never interpreted, so an unclear answer can never approve a refund. No key
press leaves the approval pending and web approval stays available.
"""

import hashlib
import hmac
import io
import logging
import math
import secrets
import struct
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from xml.etree import ElementTree

from config import Config
from orchestrator.workflow import run_execution
from services.approvals_service import decide
from services.approver_service import ApproverUnavailableError, resolve_approver
from services.sarvam_service import SarvamError, synthesize, translate
from services.supabase_service import get_service
from services.vobiz_service import VobizError, place_approval_call

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


# Every message the approver hears, in English. Sarvam translates these into the
# assignee's Freshdesk language and speaks them; Vobiz <Speak> is the fallback.
# Vobiz only listens for keys after the nested audio finishes, so a press made
# while "Press 1..." is still playing is lost. The Sarvam prompts end with a
# short tone that marks the moment listening starts (see _with_tone).
MESSAGES = {
    "request": ("GhostWork refund approval request for {amount} rupees. "
                "After the tone, press 1 to approve, or 2 to reject."),
    "retry": "We didn't get a response. After the tone, press 1 to approve, or 2 to reject.",
    "invalid_key": "That wasn't 1 or 2. After the tone, press 1 to approve, or 2 to reject.",
    "no_response": "No key press received. Please use web approval. This call will now be disconnected.",
    "approved": ("Refund approved. GhostWork will continue the workflow. "
                "Thank you for your response. This call will now be disconnected."),
    "rejected": "Refund rejected. Thank you for your response. This call will now be disconnected.",
}
# Played while the approval is still pending.
PENDING_KINDS = ("request", "retry", "invalid_key", "no_response")
# Played once, right after the decision they announce.
DECISION_KINDS = {"approved": "APPROVED", "rejected": "REJECTED"}
# Prompts that end with the "press now" tone.
TONE_KINDS = ("request", "retry", "invalid_key")
# Seconds Vobiz listens after the tone (documented range 5-60). A missed press
# is retried via <Redirect>, so this doesn't need to be long.
GATHER_TIMEOUT_SECONDS = "10"
# One initial prompt + this many no-input retries before giving up cleanly,
# instead of leaving the caller in an ambiguous silent-timeout loop.
MAX_NO_INPUT_ATTEMPTS = 2
UPLOAD_ATTEMPTS = 3
_bucket_ready = False


def _message(approval: dict, kind: str) -> str:
    amount = approval.get("amount")
    amount_text = f"{Decimal(str(amount)):,.0f}" if amount is not None else "an unspecified amount"
    return MESSAGES[kind].format(amount=amount_text)


def _prompt(amount: object) -> str:
    """English prompt text (kept for callers that only need the words)."""
    return _message({"amount": amount}, "request")


def _with_tone(audio: bytes) -> bytes:
    """Append a short pause and a 1 kHz beep to a PCM WAV, in the same format.

    Returns the audio unchanged if it isn't a 16-bit PCM WAV we can extend.
    """
    try:
        with wave.open(io.BytesIO(audio), "rb") as src:
            params = src.getparams()
            frames = src.readframes(src.getnframes())
        if params.sampwidth != 2:
            return audio
        rate, channels = params.framerate, params.nchannels
        silence = b"\x00\x00" * channels * int(rate * 0.4)
        beep = b"".join(
            struct.pack("<h", int(9000 * math.sin(2 * math.pi * 1000 * i / rate))) * channels
            for i in range(int(rate * 0.3))
        )
        out = io.BytesIO()
        with wave.open(out, "wb") as dst:
            dst.setparams(params)
            dst.writeframes(frames + silence + beep)
        return out.getvalue()
    except (wave.Error, EOFError, struct.error):
        return audio


def _speak_audio(approval: dict, kind: str, language: str) -> bytes:
    """Translate (when not English) and synthesize one message with Sarvam."""
    text = _message(approval, kind)
    if language != "en-IN":
        try:
            text = translate(text, language)
        except SarvamError:
            logger.warning(f"Sarvam translate failed for '{kind}'; speaking English")
            language = "en-IN"
    audio = synthesize(text, language_code=language)
    return _with_tone(audio) if kind in TONE_KINDS else audio


def _storage(create: bool = True):
    """Supabase Storage bucket for prompts, or None on the memory backend.

    create=False skips the one-time create-bucket call (a network round trip on
    every new server instance) for reads and deletes, where the bucket exists.
    """
    global _bucket_ready
    client = getattr(get_service(), "_supabase_client", None)
    if client is None:
        return None
    if create and not _bucket_ready:
        try:
            client.storage.create_bucket(Config.VOICE_PROMPT_BUCKET, options={"public": False})
        except Exception as exc:
            if "exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                raise
        _bucket_ready = True
    return client.storage.from_(Config.VOICE_PROMPT_BUCKET)


def _store_prompt(bucket, approval_id: int, kind: str, audio: bytes):
    """Upload one prompt to private storage; return its path, or None if every attempt failed.

    Retried because a pooled connection left over from a frozen Lambda instance
    fails on reuse ("Server disconnected"); the retry gets a fresh connection.
    """
    path = f"approval-{approval_id}/{secrets.token_hex(8)}-{kind}.wav"
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            bucket.upload(path, audio, {"content-type": "audio/wav", "upsert": "true"})
            return path
        except Exception as exc:
            logger.warning(f"Prompt upload attempt {attempt} failed for '{kind}': {str(exc)[:120]}")
    return None


def _prepare_prompts(approval: dict, language: str) -> dict:
    """
    Build every message as Sarvam audio before dialing.

    The audio is served to Vobiz only through this app's /api/voice/audio route
    (Vobiz does not reliably play Supabase signed URLs). It is also saved to
    private storage, so whichever server instance Vobiz reaches can load it
    quickly instead of calling Sarvam again. Raises SarvamError if TTS is down.
    """
    approval_id = approval["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        audio = dict(zip(MESSAGES, pool.map(lambda kind: _speak_audio(approval, kind, language), MESSAGES)))
    for kind, data in audio.items():
        _audio_cache[(approval_id, kind)] = data

    meta = {"sarvam_audio": True, "prompt_language": language}
    try:
        bucket = _storage()
    except Exception as exc:
        logger.warning(f"Prompt storage unavailable; audio will be regenerated on demand: {str(exc)[:120]}")
        bucket = None
    if bucket is not None:
        # One at a time: parallel uploads over one shared client were what hit
        # "Server disconnected". Six short files take about a second.
        files = {kind: _store_prompt(bucket, approval_id, kind, data) for kind, data in audio.items()}
        meta["prompt_files"] = {kind: path for kind, path in files.items() if path}
        meta["prompt_paths"] = list(meta["prompt_files"].values())
    return meta


def _delete_stored_prompts(metadata: dict) -> None:
    paths = metadata.get("prompt_paths") or []
    if not paths:
        return
    try:
        bucket = _storage(create=False)
        if bucket is not None:
            bucket.remove(paths)
    except Exception as exc:
        logger.info(f"Could not delete stored prompts: {str(exc)[:120]}")


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
    except (InvalidOperation, TypeError) as exc:
        raise VoiceApprovalError("A known refund amount is required for voice approval") from exc
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
        "approver_source": approver["source"],
        "approver_agent_id": approver["agent_id"],
        "approver_number_masked": approver["masked"],
    }
    _clear_audio(approval["id"])

    language = approver.get("language") or Config.VOICE_DEFAULT_LANGUAGE
    if Config.SARVAM_API_KEY:
        try:
            # Persisted (not just cached) so any server instance plays the same audio.
            metadata.update(_prepare_prompts(approval, language))
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
        _clear_audio(approval["id"])
        _delete_stored_prompts(metadata)  # nobody will fetch them
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
        "language": metadata.get("prompt_language") if metadata.get("sarvam_audio") else "en-IN",
    }


def _token_checked_approval(approval_id: int, token: str) -> dict:
    """The approval this call belongs to, if the callback carries the call's secret token."""
    approval = get_service().select_one("approvals", {"id": approval_id})
    if not approval:
        raise VoiceApprovalError("Invalid voice callback")
    expected = _metadata(approval).get("voice_token_hash", "")
    actual = hashlib.sha256(token.encode()).hexdigest()
    if not expected or not hmac.compare_digest(expected, actual):
        raise VoiceApprovalError("Invalid voice callback")
    return approval


def _checked_approval(approval_id: int, token: str) -> dict:
    approval = _token_checked_approval(approval_id, token)
    if approval.get("status") not in ("PENDING", "AWAITING_CONFIRMATION"):
        raise VoiceApprovalError("Approval is no longer pending")
    execution = get_service().get_execution(approval["execution_id"])
    if not execution or execution["status"] != "WAITING_FOR_APPROVAL":
        raise VoiceApprovalError("Execution is no longer awaiting approval")
    return approval


def _audio_approval(approval_id: int, token: str, kind: str) -> dict:
    """The approval whose audio may be served for this kind and token.

    Prompts are served only while the approval is pending; each decision
    message only once that decision has been recorded.
    """
    if kind in PENDING_KINDS:
        return _checked_approval(approval_id, token)
    if kind in DECISION_KINDS:
        approval = _token_checked_approval(approval_id, token)
        if approval.get("status") != DECISION_KINDS[kind]:
            raise VoiceApprovalError("Decision audio does not match the recorded decision")
        return approval
    raise VoiceApprovalError("Audio is unavailable")


def _download_prompt(path: str):
    try:
        bucket = _storage(create=False)
        return bucket.download(path) if bucket is not None else None
    except Exception as exc:
        logger.warning(f"Stored prompt download failed: {str(exc)[:120]}")
        return None


def get_audio(approval_id: int, token: str, kind: str) -> bytes:
    """Prompt audio for Vobiz: memory cache, then private storage, then Sarvam."""
    started = time.monotonic()
    approval = _audio_approval(approval_id, token, kind)
    metadata = _metadata(approval)
    source = "cache"
    audio = _audio_cache.get((approval_id, kind))
    if not audio:
        # Serverless: Vobiz may reach a different instance than the one that
        # prepared the prompt, so load the stored copy (fast, no Sarvam call).
        path = (metadata.get("prompt_files") or {}).get(kind)
        audio = _download_prompt(path) if path else None
        source = "storage"
    if not audio:
        if not metadata.get("sarvam_audio"):
            raise VoiceApprovalError("Audio is unavailable")
        try:
            audio = _speak_audio(approval, kind, metadata.get("prompt_language", "en-IN"))
        except SarvamError as exc:
            raise VoiceApprovalError("Audio is unavailable") from exc
        source = "sarvam"
    _audio_cache[(approval_id, kind)] = audio
    logger.info("Voice audio %s for approval %s served from %s in %.0f ms",
                kind, approval_id, source, (time.monotonic() - started) * 1000)
    return audio


def _add_message(parent, approval: dict, token: str, kind: str) -> None:
    """Exactly one spoken element per message: Sarvam audio via <Play>, else Vobiz <Speak>.

    The Play URL is always this app's audio route: Vobiz plays it reliably,
    while Supabase signed URLs were silently skipped (a blank call). Never both
    Play and Speak - Gather only starts listening after every nested element
    finishes, so a second message makes the caller press their key too early.
    """
    approval_id = approval["id"]
    if _metadata(approval).get("sarvam_audio") and kind in MESSAGES:
        query = urlencode({"token": token})
        ElementTree.SubElement(parent, "Play").text = (
            f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/voice/audio/{approval_id}/{kind}?{query}")
    else:
        # No Sarvam audio for this call (not configured, or synthesis failed
        # before dialing) - Vobiz's own voice is the only option here.
        ElementTree.SubElement(parent, "Speak").text = _message(approval, kind)


def _xml_prompt(approval: dict, token: str, kind: str = "request") -> str:
    """Ask for one key press: 1 approves, 2 rejects. No speech input is accepted.

    `kind` selects which message is spoken before listening: "request" the
    first time, "retry" after a silent timeout, "invalid_key" after a key
    press that wasn't 1 or 2 - so a retry doesn't sound like a stuck loop.
    """
    approval_id = approval["id"]
    root = ElementTree.Element("Response")
    gather = ElementTree.SubElement(root, "Gather", {
        "action": _callback_url(approval_id, token, "choice"),
        "method": "POST",
        "inputType": "dtmf",
        "numDigits": "1",
        "executionTimeout": GATHER_TIMEOUT_SECONDS,
    })
    _add_message(gather, approval, token, kind)
    # Reached when no key is pressed: Vobiz moves on to the next element without
    # calling the Gather action, so redirect back to our choice handler with no
    # digit. It plays the retry prompt, or ends the call after the last retry.
    ElementTree.SubElement(root, "Redirect", {"method": "POST"}).text = (
        _callback_url(approval_id, token, "choice"))
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding="unicode")


def _hangup(message: str, approval: dict = None, token: str = "", kind: str = None) -> str:
    """End the call; play the Sarvam audio for `kind` when available."""
    root = ElementTree.Element("Response")
    if approval is not None and kind:
        _add_message(root, approval, token, kind)
    else:
        ElementTree.SubElement(root, "Speak").text = message
    ElementTree.SubElement(root, "Hangup")
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding="unicode")


def hangup_xml(message: str) -> str:
    """Vobiz XML that speaks a message and ends the call."""
    return _hangup(message)


def _clear_audio(approval_id: int) -> None:
    for kind in MESSAGES:
        _audio_cache.pop((approval_id, kind), None)


def handle_callback(approval_id: int, token: str, action: str, form: dict) -> str:
    service = get_service()
    if action == "hangup":
        # Cleanup only (no decision possible), so it also runs after approve/reject.
        approval = _token_checked_approval(approval_id, token)
        _clear_audio(approval_id)
        metadata = _metadata(approval)
        # Vobiz runs <Hangup> only after the preceding <Play> finishes, so by
        # the time this callback arrives no prompt is still being fetched.
        _delete_stored_prompts(metadata)
        if approval.get("status") == "PENDING":
            # No decision on this call (missed, declined or hung up): let the
            # UI offer another call. A 0-row update means it was just decided.
            metadata["voice_status"] = "ended"
            service.transition_approval(approval_id, "PENDING", "PENDING", raw_response_json=metadata)
        service.log_audit_event(approval["execution_id"], "VOICE_CALL_ENDED", actor="vobiz",
                                detail={"approval_id": approval_id})
        return _hangup("Web approval remains available.")

    approval = _checked_approval(approval_id, token)
    execution_id = approval["execution_id"]
    if action == "answer":
        logger.info("Voice answer callback for approval %s", approval_id)
        return _xml_prompt(approval, token)
    if action == "choice":
        digit = (form.get("Digits") or form.get("digits") or "").strip()
        logger.info("Voice choice callback for approval %s: digit=%r", approval_id, digit)
        if digit == "1":
            decide(execution_id, "approve", channel="voice", approver="phone_approver",
                   raw_response={"method": "dtmf", "digit": "1"})
            run_execution(execution_id)
            return _hangup(MESSAGES["approved"], approval, token, "approved")
        if digit == "2":
            decide(execution_id, "reject", channel="voice", approver="phone_approver",
                   raw_response={"method": "dtmf", "digit": "2"})
            return _hangup(MESSAGES["rejected"], approval, token, "rejected")

        metadata = _metadata(approval)
        if digit:
            # A real key press, just not 1 or 2. Doesn't count against the
            # no-input retry budget - they're clearly on the line and responding.
            return _xml_prompt(approval, token, kind="invalid_key")

        # No key pressed before the timeout. Cap retries so a quiet line ends
        # with a clear message instead of an ambiguous silent timeout.
        attempts = metadata.get("voice_no_input_attempts", 0) + 1
        if attempts > MAX_NO_INPUT_ATTEMPTS:
            logger.info("Voice approval %s: giving up after %s silent timeouts", approval_id, attempts - 1)
            return _hangup(MESSAGES["no_response"], approval, token, "no_response")
        metadata["voice_no_input_attempts"] = attempts
        _update_pending(approval_id, raw_response_json=metadata)
        return _xml_prompt(approval, token, kind="retry")
    raise VoiceApprovalError("Unknown voice callback action")
