"""Communication agent: handles Freshdesk write-back after approval."""

import logging
from typing import Any, Dict, Optional

from config import Config
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    add_note,
)

logger = logging.getLogger(__name__)


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
        source = execution.get("source", "fallback")

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

        # Check if Freshdesk is configured
        if not Config.FRESHDESK_DOMAIN or not Config.FRESHDESK_API_KEY:
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
        execution_id = execution.get("execution_id")

        note_body = _build_note_content(refund_amount, execution_id)

        # Attempt to add note to Freshdesk ticket
        try:
            result = add_note(ticket_id, note_body)
            logger.info(f"Freshdesk write-back successful for ticket {ticket_id}")

            return {
                "status": "SUCCESS",
                "result": {
                    "reason": "Freshdesk note created",
                    "action_performed": True,
                    "ticket_id": ticket_id,
                    "note_id": result.get("note_id"),
                    "source": source,
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
