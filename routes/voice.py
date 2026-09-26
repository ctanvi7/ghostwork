"""Outbound voice approval and Vobiz webhook routes."""

import logging
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from app import InvalidStateError
from routes.approvals import require_signed_in_approver
from services.vobiz_service import VobizError
from services.voice_approval_service import (
    MESSAGES,
    VoiceApprovalError,
    get_audio,
    handle_callback,
    hangup_xml,
    start_call,
)

voice_bp = Blueprint("voice", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@voice_bp.post("/executions/<int:execution_id>/call-approver")
def call_approver(execution_id: int):
    require_signed_in_approver()
    try:
        return jsonify(start_call(execution_id)), 202
    except VoiceApprovalError as exc:
        return jsonify({"error": {"code": "VOICE_UNAVAILABLE", "message": str(exc)}}), 409
    except VobizError:
        return jsonify({"error": {"code": "VOICE_CALL_FAILED", "message": "Call failed. Use web approval."}}), 502


@voice_bp.post("/webhooks/vobiz")
def vobiz_webhook():
    approval_id = request.args.get("approval_id", type=int)
    token = request.args.get("token", "")
    action = request.args.get("action", "")
    if not approval_id or not token:
        logger.warning("Vobiz callback rejected: missing approval_id or token (action=%r)", action)
        return "Invalid callback", 403
    try:
        xml = handle_callback(approval_id, token, action, request.form.to_dict())
    except VoiceApprovalError as exc:
        logger.warning("Vobiz callback rejected for approval %s (action=%r): %s", approval_id, action, exc)
        return "Invalid callback", 403
    except (InvalidStateError, ValueError) as exc:
        # The approval was decided elsewhere (e.g. on the web) during the call.
        logger.warning("Voice decision for approval %s not applied: %s", approval_id, exc)
        xml = hangup_xml("This request was already decided. Goodbye.")
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@voice_bp.get("/voice/audio/<int:approval_id>/<kind>")
def voice_audio(approval_id: int, kind: str):
    if kind not in MESSAGES:
        return "Not found", 404
    try:
        audio = get_audio(approval_id, request.args.get("token", ""), kind)
        logger.info("Voice audio served for approval %s, kind %s", approval_id, kind)
        return send_file(BytesIO(audio), mimetype="audio/wav", max_age=0)
    except VoiceApprovalError:
        logger.warning("Voice audio unavailable for approval %s, kind %s", approval_id, kind)
        return "Not found", 404
