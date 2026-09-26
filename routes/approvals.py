"""Approval endpoints."""

import logging

from flask import Blueprint, jsonify, request, session

from app import AppError, InvalidStateError, NotFoundError
from config import Config
from orchestrator.workflow import run_execution
from services.approvals_service import decide
from services.supabase_service import get_service

logger = logging.getLogger(__name__)

approvals_bp = Blueprint("approvals", __name__, url_prefix="/api")


def _approver_identity() -> str:
    """Signed-in user's email for the audit trail; "web_user" when sign-in is off."""
    user = session.get("user") or {}
    return user.get("email") or "web_user"


def require_signed_in_approver() -> None:
    """REQUIRE_APPROVER_AUTH=true: only a signed-in user may decide or call an approver."""
    if Config.REQUIRE_APPROVER_AUTH and not session.get("user"):
        raise AppError("Sign in to approve or reject", code="UNAUTHORIZED", status_code=401)


@approvals_bp.route("/approvals/<int:approval_id>/approve", methods=["POST"])
def approve_execution(approval_id: int):
    """
    POST /api/approvals/<id>/approve
    Approve a pending approval and resume execution.

    Returns: 200 OK with the updated execution
    Returns: 409 if the approval is not in PENDING state (already decided)
    """
    require_signed_in_approver()
    service = get_service()

    # Get the approval
    approval = service.select_one("approvals", {"id": approval_id})
    if not approval:
        raise NotFoundError(f"Approval {approval_id} not found")

    execution_id = approval.get("execution_id")
    current_status = approval.get("status")

    # Check if already decided
    if current_status != "PENDING":
        # Already decided (409 Conflict)
        logger.warning(f"Approval {approval_id} already {current_status}")
        return (
            jsonify({
                "error": {
                    "code": "ALREADY_DECIDED",
                    "message": f"Approval is already {current_status}",
                    "request_id": request.headers.get("X-Request-ID", "")
                }
            }),
            409,
        )

    # Make the decision
    try:
        decide(
            execution_id,
            decision="approve",
            channel="web",
            approver=_approver_identity()
        )
    except (InvalidStateError, ValueError) as e:
        return (
            jsonify({
                "error": {
                    "code": "INVALID_STATE",
                    "message": str(e),
                    "request_id": request.headers.get("X-Request-ID", "")
                }
            }),
            409,
        )
    except Exception as e:
        logger.error(f"Failed to approve: {e}")
        raise

    # Resume execution from APPROVED state
    run_execution(execution_id)

    # Return the updated execution
    execution = service.get_execution(execution_id)
    return jsonify(execution), 200


@approvals_bp.route("/approvals/<int:approval_id>/reject", methods=["POST"])
def reject_execution(approval_id: int):
    """
    POST /api/approvals/<id>/reject
    Reject a pending approval and mark execution as REJECTED.

    Returns: 200 OK with the updated execution
    Returns: 409 if the approval is not in PENDING state (already decided)
    """
    require_signed_in_approver()
    service = get_service()

    # Get the approval
    approval = service.select_one("approvals", {"id": approval_id})
    if not approval:
        raise NotFoundError(f"Approval {approval_id} not found")

    execution_id = approval.get("execution_id")
    current_status = approval.get("status")

    # Check if already decided
    if current_status != "PENDING":
        # Already decided (409 Conflict)
        logger.warning(f"Approval {approval_id} already {current_status}")
        return (
            jsonify({
                "error": {
                    "code": "ALREADY_DECIDED",
                    "message": f"Approval is already {current_status}",
                    "request_id": request.headers.get("X-Request-ID", "")
                }
            }),
            409,
        )

    # Make the decision
    try:
        decide(
            execution_id,
            decision="reject",
            channel="web",
            approver=_approver_identity()
        )
    except (InvalidStateError, ValueError) as e:
        return (
            jsonify({
                "error": {
                    "code": "INVALID_STATE",
                    "message": str(e),
                    "request_id": request.headers.get("X-Request-ID", "")
                }
            }),
            409,
        )
    except Exception as e:
        logger.error(f"Failed to reject: {e}")
        raise

    # Return the updated execution
    execution = service.get_execution(execution_id)
    return jsonify(execution), 200
