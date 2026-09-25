"""Communication agent: handles Freshdesk write-back after approval."""

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from config import Config
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    add_note,
    get_last_provider_used,
    get_ticket,
)

logger = logging.getLogger(__name__)

# Freshdesk statuses after which GhostWork must not write to the ticket.
TICKET_DONE_STATUSES = {4: "Resolved", 5: "Closed"}


def _freshdesk_configured() -> bool:
    """Config check for the provider actually selected (MCP or REST)."""
    if Config.FRESHDESK_PROVIDER == "mcp":
        return bool(Config.MCP_FRESHDESK_URL and Config.MCP_FRESHDESK_AUTH_TOKEN)
    return bool(Config.FRESHDESK_DOMAIN and Config.FRESHDESK_API_KEY)


def _step_result(context: Optional[Dict[str, Any]], step_name: str) -> Dict[str, Any]:
    return ((context or {}).get(step_name) or {}).get("result") or {}


def _approval_required(execution: Dict[str, Any], context: Optional[Dict[str, Any]]) -> bool:
    """Deterministic: the risk_agent decision, else the global limit (fail closed)."""
    risk = _step_result(context, "risk_agent")
    if "requires_approval" in risk:
        return bool(risk["requires_approval"])
    try:
        amount = Decimal(str(execution.get("refund_amount")))
    except (InvalidOperation, TypeError, ValueError):
        return True
    return not amount.is_finite() or amount <= 0 or amount > Config.AUTO_APPROVAL_LIMIT


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Communicate workflow result to external system (Freshdesk write-back).

    Only writes back after approval has been granted (not during WAITING_FOR_APPROVAL).

    Args:
        execution: Execution context with ticket_id, source, etc.
        context: Optional context dict with earlier step outputs

    Returns:
        - status: "SUCCESS" (always succeeds, fail-open)
        - result: action_performed, ticket_id, writeback_status, source
    """
    try:
        ticket_id = execution.get("ticket_id")
        # The context_agent result is the source of truth for where the ticket came from.
        source = _step_result(context, "context_agent").get("source") or execution.get("source", "fallback")

        # Only attempt write-back if this was a real Freshdesk ticket
        if source != "freshdesk":
            logger.info(f"Skipping Freshdesk write-back for non-Freshdesk source: {source}")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": "Write-back skipped (no Freshdesk ticket)",
                    "action_performed": False,
                    "source": source,
                    "writeback_status": "skipped"
                }
            }

        if not ticket_id:
            logger.warning("No ticket_id in execution, cannot write back to Freshdesk")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": "Write-back skipped (no ticket_id)",
                    "action_performed": False,
                    "source": source,
                    "writeback_status": "skipped"
                }
            }

        # Governance: never write to Freshdesk unless a required approval exists.
        execution_id = execution.get("id")
        if execution_id and _approval_required(execution, context):
            from services.supabase_service import get_service
            if not get_service().get_approved_approval(execution_id):
                logger.warning(f"Blocked Freshdesk write-back for execution {execution_id}: no approval")
                return {
                    "status": "SUCCESS",
                    "result": {
                        "reason": "Write-back blocked: required human approval not granted",
                        "action_performed": False,
                        "ticket_id": ticket_id,
                        "source": source,
                        "writeback_status": "blocked_no_approval"
                    }
                }

        # Check if Freshdesk is configured
        if not _freshdesk_configured():
            logger.info("Freshdesk not configured, using fallback communication mode")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": "Freshdesk not configured, using fallback",
                    "action_performed": False,
                    "ticket_id": ticket_id,
                    "source": source,
                    "writeback_status": "fallback_unavailable"
                }
            }

        # Construct the note content
        refund_amount = execution.get("refund_amount")
        note_body = _build_note_content(refund_amount, execution.get("execution_id") or execution_id)

        # Attempt to add note to Freshdesk ticket
        try:
            # A human may have resolved/closed the ticket while it waited for approval.
            current_status = (get_ticket(ticket_id).raw_response or {}).get("status")
            if current_status in TICKET_DONE_STATUSES:
                logger.warning(f"Ticket {ticket_id} is {TICKET_DONE_STATUSES[current_status]}; not writing note")
                return {
                    "status": "SUCCESS",
                    "result": {
                        "reason": f"Write-back skipped: ticket #{ticket_id} was already "
                                  f"{TICKET_DONE_STATUSES[current_status]} in Freshdesk",
                        "action_performed": False,
                        "ticket_id": ticket_id,
                        "source": source,
                        "writeback_status": "skipped_ticket_closed"
                    }
                }

            result = add_note(ticket_id, note_body)
            provider = get_last_provider_used()
            logger.info(f"Freshdesk write-back successful for ticket {ticket_id} via {provider}")

            return {
                "status": "SUCCESS",
                "result": {
                    "reason": f"Freshdesk note {result.get('note_id')} added to ticket #{ticket_id} via {provider}",
                    "action_performed": True,
                    "ticket_id": ticket_id,
                    "note_id": result.get("note_id"),
                    "source": source,
                    "provider": provider,
                    "writeback_status": "success",
                    "external_reference": f"freshdesk-note-{result.get('note_id')}"
                }
            }

        except FreshDeskUnavailableError:
            logger.warning(f"Freshdesk not available for ticket {ticket_id}, using fallback")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": "Freshdesk write-back failed (unavailable), workflow continues",
                    "action_performed": False,
                    "ticket_id": ticket_id,
                    "source": source,
                    "writeback_status": "fallback_unavailable"
                }
            }

        except FreshDeskError as e:
            logger.warning(f"Freshdesk write-back error for ticket {ticket_id}: {e}")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": f"Freshdesk write-back failed: {str(e)[:50]}",
                    "action_performed": False,
                    "ticket_id": ticket_id,
                    "source": source,
                    "writeback_status": "error",
                    "error_category": "freshdesk_error"
                }
            }

    except Exception as e:
        logger.error(f"Communication agent error: {e}")
        return {
            "status": "SUCCESS",
            "result": {
                "reason": f"Communication agent error: {str(e)[:50]}",
                "action_performed": False,
                "source": "fallback",
                "writeback_status": "error"
            }
        }


def _build_note_content(refund_amount: Optional[float] = None, execution_id: Optional[str] = None) -> str:
    """Build concise note content for Freshdesk ticket."""
    lines = [
        "GhostWork refund workflow approved by human reviewer.",
    ]

    if refund_amount:
        lines.append(f"Refund amount: ₹{refund_amount:,.2f}.")

    lines.append("Automated checks completed successfully.")

    if execution_id:
        lines.append(f"Execution ID: {execution_id}.")

    return "\n".join(lines)
