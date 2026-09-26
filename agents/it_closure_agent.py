"""IT closure agent: marks the ticket Resolved (not Closed) after a verified reply.

Resolved, not Closed: the customer still needs to confirm the fix worked, so
this playbook is less final than the refund workflow's closure_agent, which
closes only after a human-approved, verified refund.
"""

import logging
from typing import Any, Dict, List, Optional

from config import Config
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    get_last_provider_used,
    get_ticket,
    update_ticket_status,
)

logger = logging.getLogger(__name__)

RESOLVED = 4
ALREADY_DONE = {4: "Resolved", 5: "Closed"}
REQUIRED_STEPS = ["context_agent", "diagnosis_agent", "it_communication_agent", "it_verification_agent"]


def _result(context: Optional[Dict[str, Any]], step_name: str) -> Dict[str, Any]:
    return ((context or {}).get(step_name) or {}).get("result") or {}


def due_diligence_failures(context: Optional[Dict[str, Any]]) -> List[str]:
    failures = []
    context = context or {}
    for step in REQUIRED_STEPS:
        if (context.get(step) or {}).get("status") != "SUCCESS":
            failures.append(f"{step} did not succeed")
    if not _result(context, "it_communication_agent").get("action_performed"):
        failures.append("troubleshooting note was not written to the ticket")
    if not _result(context, "it_verification_agent").get("verified"):
        failures.append("note was not verified by read-back")
    return failures


def _skipped(reason: str, **extra) -> Dict[str, Any]:
    return {"status": "SUCCESS", "result": {"reason": reason, "closed": False, "closure_status": "skipped", **extra}}


def _failed(reason: str, **extra) -> Dict[str, Any]:
    return {"status": "FAILED", "result": {"reason": reason, "closed": False, "closure_status": "failed",
                                           "error": reason, **extra}}


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ticket_id = execution.get("ticket_id")

    if not Config.FRESHDESK_AUTO_CLOSE:
        return _skipped("Auto-resolve disabled (FRESHDESK_AUTO_CLOSE=false); ticket left open")
    if _result(context, "context_agent").get("source") != "freshdesk" or not ticket_id:
        return _skipped("No live Freshdesk ticket to resolve (demo data)")

    failures = due_diligence_failures(context)
    if failures:
        logger.warning(f"Not resolving ticket {ticket_id}: {failures}")
        return _failed("Ticket left open, due diligence not met: " + "; ".join(failures),
                       ticket_id=ticket_id, failed_checks=failures)

    try:
        current = (get_ticket(ticket_id).raw_response or {}).get("status")
        if current in ALREADY_DONE:
            return _skipped(f"Ticket #{ticket_id} is already {ALREADY_DONE[current]}; nothing to resolve",
                            ticket_id=ticket_id, ticket_status=ALREADY_DONE[current])

        update_ticket_status(ticket_id, RESOLVED)

        after = (get_ticket(ticket_id).raw_response or {}).get("status")
        provider = get_last_provider_used()
    except (FreshDeskError, FreshDeskUnavailableError) as e:
        logger.error(f"Resolving ticket {ticket_id} failed: {e}")
        return _failed(f"Could not resolve ticket #{ticket_id}: {str(e)[:150]}", ticket_id=ticket_id)

    if after != RESOLVED:
        return _failed(f"Ticket #{ticket_id} status is {after} after update, expected Resolved",
                       ticket_id=ticket_id)

    from services.ticket_discovery_service import clear_cache
    clear_cache()

    logger.info(f"Resolved ticket {ticket_id} after verified troubleshooting reply via {provider}")
    return {
        "status": "SUCCESS",
        "result": {
            "reason": f"Troubleshooting steps verified on ticket #{ticket_id}; marked Resolved via {provider}",
            "closed": True, "closure_status": "resolved", "ticket_id": ticket_id,
            "ticket_status": "Resolved", "provider": provider,
        },
    }
