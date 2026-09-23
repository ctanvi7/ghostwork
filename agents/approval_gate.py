"""Approval gate agent: checks for existing approval."""

import json
from typing import Any, Dict, Optional

from services.supabase_service import get_service


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Check if approval is required based on prior steps, and if one exists.

    Returns:
    - SUCCESS if no approval required (risk_agent determined no approval needed)
    - SUCCESS if approval was required and is now APPROVED
    - FAILED if approval was required but has been REJECTED
    - PAUSE if approval is required and still PENDING
    """
    execution_id = execution.get("id")
    service = get_service()

    # Get the risk_agent step output to see if approval was required
    steps = service.get_execution_steps(execution_id)
    risk_step = None
    requires_approval = None

    for step in steps:
        if step.get("step_name") == "risk_agent":
            risk_step = step
            break

    # Check if risk_agent said approval is required
    if risk_step and risk_step.get("status") == "SUCCESS":
        try:
            output = risk_step.get("output_json", {})
            if isinstance(output, str):
                output = json.loads(output)
            requires_approval = output.get("requires_approval", False)
        except (json.JSONDecodeError, KeyError, TypeError):
            # If we can't parse, assume approval is required (fail-closed)
            requires_approval = True

    # Case 1: Approval was not required
    if requires_approval is False:
        return {
            "status": "SUCCESS",
            "result": {
                "reason": "Approval not required"
            }
        }

    # Approval is required - check its status
    approved = service.get_approved_approval(execution_id)
    rejected = service.select_one("approvals", {"execution_id": execution_id, "status": "REJECTED"})

    # Case 2: Approval was required and has been APPROVED
    if approved:
        return {
            "status": "SUCCESS",
            "result": {
                "reason": "Approval granted by human",
                "approval_id": approved.get("id")
            }
        }

    # Case 4: Approval was required but has been REJECTED
    if rejected:
        return {
            "status": "FAILED",
            "result": {
                "reason": "Approval was rejected",
                "approval_id": rejected.get("id")
            }
        }

    # Case 3: Approval is required and still PENDING
    return {
        "status": "PAUSE",
        "result": {
            "reason": "Awaiting human approval"
        }
    }
