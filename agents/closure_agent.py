"""Closure agent: closes the Freshdesk ticket only after every due-diligence check passes.

Runs as the last step, after the verification agent. Deterministic: no LLM.

Due diligence (all must pass, otherwise the ticket is left open):
  1. The ticket really came from Freshdesk.
  2. Every earlier step succeeded.
  3. If the Risk Agent required approval, a human APPROVED it.
  4. The GhostWork note was written to the ticket.
  5. That note was independently read back (verification agent).
  6. The ticket is still Open/Pending right now (a human may have acted meanwhile).
Then: set status to Closed, re-read the ticket, and confirm it is Closed.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from config import Config
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    get_last_provider_used,
    get_ticket,
    update_ticket_status,
)
from services.supabase_service import get_service

logger = logging.getLogger(__name__)

CLOSED = 5
ALREADY_DONE = {4: "Resolved", 5: "Closed"}
REQUIRED_STEPS = [
    "context_agent", "billing_agent", "policy_agent", "risk_agent",
    "approval_gate", "communication_agent", "verification_agent",
]


def _result(context: Optional[Dict[str, Any]], step_name: str) -> Dict[str, Any]:
    return ((context or {}).get(step_name) or {}).get("result") or {}


def _approval_required(execution: Dict[str, Any], context: Optional[Dict[str, Any]]) -> bool:
    """The Risk Agent's decision, else the global limit. Fails closed."""
    risk = _result(context, "risk_agent")
    if "requires_approval" in risk:
        return bool(risk["requires_approval"])
    try:
        amount = Decimal(str(execution.get("refund_amount")))
    except (InvalidOperation, TypeError, ValueError):
        return True
    return not amount.is_finite() or amount <= 0 or amount > Config.AUTO_APPROVAL_LIMIT


def due_diligence_failures(execution: Dict[str, Any], context: Optional[Dict[str, Any]]) -> List[str]:
    """Return the checks that did not pass (empty list = safe to close)."""
    failures = []
    context = context or {}

    for step in REQUIRED_STEPS:
        if (context.get(step) or {}).get("status") != "SUCCESS":
            failures.append(f"{step} did not succeed")

    if _approval_required(execution, context):
        if not execution.get("id") or not get_service().get_approved_approval(execution["id"]):
            failures.append("required human approval not granted")

    if not _result(context, "communication_agent").get("action_performed"):
        failures.append("GhostWork note was not written to the ticket")

    if not _result(context, "verification_agent").get("verified"):
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
        return _skipped("Auto-close disabled (FRESHDESK_AUTO_CLOSE=false); ticket left open")
    if _result(context, "context_agent").get("source") != "freshdesk" or not ticket_id:
        return _skipped("No live Freshdesk ticket to close (demo data)")

    failures = due_diligence_failures(execution, context)
    if failures:
        logger.warning(f"Not closing ticket {ticket_id}: {failures}")
        return _failed("Ticket left open, due diligence not met: " + "; ".join(failures),
                       ticket_id=ticket_id, failed_checks=failures)

    try:
        current = (get_ticket(ticket_id).raw_response or {}).get("status")
        if current in ALREADY_DONE:
            return _skipped(f"Ticket #{ticket_id} is already {ALREADY_DONE[current]}; nothing to close",
                            ticket_id=ticket_id, ticket_status=ALREADY_DONE[current])

        update_ticket_status(ticket_id, CLOSED)

        # Independent read-back: never report "closed" on the write's word alone.
        after = (get_ticket(ticket_id).raw_response or {}).get("status")
        provider = get_last_provider_used()
    except (FreshDeskError, FreshDeskUnavailableError) as e:
        logger.error(f"Closing ticket {ticket_id} failed: {e}")
        return _failed(f"Could not close ticket #{ticket_id}: {str(e)[:150]}", ticket_id=ticket_id)

    if after != CLOSED:
        return _failed(f"Ticket #{ticket_id} status is {after} after update, expected Closed",
                       ticket_id=ticket_id)

    from services.ticket_discovery_service import clear_cache
    clear_cache()  # so Discovery stops listing the ticket immediately

    logger.info(f"Closed ticket {ticket_id} after verified automation via {provider}")
    return {
        "status": "SUCCESS",
        "result": {
            "reason": f"All due-diligence checks passed; ticket #{ticket_id} closed and confirmed via {provider}",
            "closed": True,
            "closure_status": "closed",
            "ticket_id": ticket_id,
            "ticket_status": "Closed",
            "provider": provider,
        },
    }
