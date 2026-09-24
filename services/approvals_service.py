"""Approval decision service."""

import logging
from typing import Any, Dict, Optional

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

    if decision.lower() == "approve":
        # Update the approval to APPROVED
        service.update_approval(
            approval["id"],
            status="APPROVED",
            approver=approver,
            channel=channel,
            raw_response_json=raw_response
        )

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

        # Transition execution: WAITING_FOR_APPROVAL -> APPROVED
        try:
            transition(execution_id, "WAITING_FOR_APPROVAL", "APPROVED")
        except Exception as e:
            logger.error(f"Failed to transition execution to APPROVED: {e}")
            raise

        logger.info(f"Execution {execution_id}: approved by {approver}")
        return service.get_execution(execution_id)

    elif decision.lower() == "reject":
        # Update the approval to REJECTED
        service.update_approval(
            approval["id"],
            status="REJECTED",
            approver=approver,
            channel=channel,
            raw_response_json=raw_response
        )

        # Transition execution: WAITING_FOR_APPROVAL -> REJECTED
        try:
            transition(execution_id, "WAITING_FOR_APPROVAL", "REJECTED")
        except Exception as e:
            logger.error(f"Failed to transition execution to REJECTED: {e}")
            raise

        logger.info(f"Execution {execution_id}: rejected by {approver}")
        return service.get_execution(execution_id)

    else:
        raise ValueError(f"Invalid decision: {decision}")
