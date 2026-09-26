"""Approval decision service."""

import logging
from typing import Any, Dict, Optional

from app import InvalidStateError
from orchestrator.state import transition
from services.supabase_service import get_service

logger = logging.getLogger(__name__)


def decide(
    execution_id: int,
    decision: str,  # "approve" or "reject"
    channel: Optional[str] = None,
    approver: Optional[str] = None,
    raw_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Make an approval decision and transition the execution.

    Args:
        execution_id: The execution to approve/reject
        decision: "approve" or "reject"
        channel: "web", "voice", etc.
        approver: User/system approver identifier
        raw_response: Raw response from the approval channel

    Returns:
        Updated approval record
    """
    service = get_service()
    execution = service.get_execution(execution_id)

    if not execution:
        logger.error(f"Execution {execution_id} not found")
        raise ValueError(f"Execution {execution_id} not found")

    # Find the open approval
    approval = service.get_open_approval(execution_id)

    if not approval:
        logger.error(f"No open approval for execution {execution_id}")
        raise ValueError(f"No open approval for execution {execution_id}")

    if execution.get("status") != "WAITING_FOR_APPROVAL":
        raise InvalidStateError("Execution is not waiting for approval")

    decision = decision.lower()
    if decision not in ("approve", "reject"):
        raise ValueError(f"Invalid decision: {decision}")
    target = "APPROVED" if decision == "approve" else "REJECTED"
    # Merge, don't replace: the voice call's metadata (e.g. stored prompt files)
    # is still needed after the decision to finish and clean up the call.
    metadata = {**dict(approval.get("raw_response_json") or {}), **(raw_response or {})}
    if not service.transition_approval(
        approval["id"], approval["status"], target,
        approver=approver, channel=channel, raw_response_json=metadata or None,
    ):
        raise InvalidStateError("Approval was already decided")

    try:
        transition(execution_id, "WAITING_FOR_APPROVAL", target)
    except Exception:
        # A failed state transition must not leave a decided approval on a waiting run.
        service.transition_approval(approval["id"], target, "PENDING", decided_at=None)
        raise

    if decision == "approve":
        # Update the approval_gate execution step to reflect the approved state
        # Find the approval_gate step and update its output
        steps = service.get_execution_steps(execution_id)
        for step in steps:
            if step.get("step_name") == "approval_gate":
                service.update_execution_step(
                    step["id"],
                    output_json={
                        "reason": "Approval granted by human",
                        "approval_id": approval["id"]
                    }
                )
                logger.info(f"Execution {execution_id}: updated approval_gate step output to reflect approval")
                break

        logger.info(f"Execution {execution_id}: approved by {approver}")
        return service.get_execution(execution_id)

    else:
        logger.info(f"Execution {execution_id}: rejected by {approver}")
        return service.get_execution(execution_id)
