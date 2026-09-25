"""Outbound voice approval and Vobiz webhook routes."""

from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from services.voice_approval_service import (
    VoiceApprovalError,
    get_audio,
    handle_callback,
    start_call,
)
from services.vobiz_service import VobizError

voice_bp = Blueprint("voice", __name__, url_prefix="/api")


@voice_bp.post("/executions/<int:execution_id>/call-approver")
def call_approver(execution_id: int):
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
        return "Invalid callback", 403
    try:
        xml = handle_callback(approval_id, token, action, request.form.to_dict())
        return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}
    except VoiceApprovalError:
        return "Invalid callback", 403


@voice_bp.get("/voice/audio/<int:approval_id>/<kind>")
def voice_audio(approval_id: int, kind: str):
    if kind not in ("request", "confirm"):
        return "Not found", 404
    try:
        audio = get_audio(approval_id, request.args.get("token", ""), kind)
        return send_file(BytesIO(audio), mimetype="audio/wav", max_age=0)
    except VoiceApprovalError:
        return "Not found", 404
