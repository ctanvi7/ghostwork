"""Verification agent: verifies that external actions (Freshdesk write-back) occurred."""

import logging
from typing import Any, Dict, Optional

from config import Config
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    verify_note_exists,
)

logger = logging.getLogger(__name__)


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Verify that external actions were successfully executed.

    For real Freshdesk write-backs: verifies that the note exists on Freshdesk.
    For fallback/demo: marks verification as skipped safely.

    Args:
        execution: Execution context
        context: Optional context dict with earlier step outputs

    Returns:
        - status: "SUCCESS" or "FAILED"
        - result: verified, verification_status, reason, ticket_id, matched_note_id
    """
    try:
        # Get communication result from context
        comm_result = None
        if context and "communication_agent" in context:
            comm_result = context["communication_agent"].get("result", {})

        # If no communication result, verification is skipped (fallback demo)
        if not comm_result:
            logger.info("No communication result found, verification skipped (fallback mode)")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": "Verification skipped (no communication result)",
                    "verified": False,
                    "verification_status": "skipped_fallback",
                    "source": "fallback"
                }
            }

        # Check if communication agent actually performed an action
        action_performed = comm_result.get("action_performed", False)
        writeback_status = comm_result.get("writeback_status", "skipped")
        source = comm_result.get("source", "fallback")

        # If no action was performed, mark as skipped (safe for demo)
        if not action_performed:
            logger.info(f"No action performed (status: {writeback_status}), verification skipped")
            return {
                "status": "SUCCESS",
                "result": {
                    "reason": f"No action to verify (writeback_status: {writeback_status})",
                    "verified": False,
                    "verification_status": "skipped_fallback",
                    "source": source
                }
            }

        # Action WAS performed. We must verify it succeeded.
        # If verification fails, return FAILED to prevent marking execution as COMPLETED.

        ticket_id = comm_result.get("ticket_id")
        note_id = comm_result.get("note_id")
        external_reference = comm_result.get("external_reference")

        if not ticket_id:
            logger.warning("Verification: no ticket_id in communication result")
            return {
                "status": "FAILED",
                "result": {
                    "reason": "Verification failed: no ticket_id",
                    "verified": False,
                    "verification_status": "verification_failed",
                    "source": source
                }
            }

        # Check if Freshdesk is configured
        if not Config.FRESHDESK_DOMAIN or not Config.FRESHDESK_API_KEY:
            logger.warning("Freshdesk not configured for verification, but action was performed")
            return {
                "status": "FAILED",
                "result": {
                    "reason": "Verification failed: Freshdesk not configured",
                    "verified": False,
                    "verification_status": "unavailable",
                    "ticket_id": ticket_id,
                    "source": source
                }
            }

        # Attempt to verify the note on Freshdesk
        try:
            result = verify_note_exists(
                ticket_id=ticket_id,
                expected_note_id=note_id,
                execution_reference=external_reference
            )

            if result.get("verified"):
                logger.info(f"Verification successful for ticket {ticket_id}")
                return {
                    "status": "SUCCESS",
                    "result": {
                        "reason": result.get("reason"),
                        "verified": True,
                        "verification_status": "verified",
                        "ticket_id": ticket_id,
                        "matched_note_id": result.get("matched_note_id"),
                        "source": source
                    }
                }
            else:
                # Verification failed - note not found
                logger.warning(f"Verification failed for ticket {ticket_id}: {result.get('reason')}")
                return {
                    "status": "FAILED",
                    "result": {
                        "reason": result.get("reason"),
                        "verified": False,
                        "verification_status": "verification_failed",
                        "ticket_id": ticket_id,
                        "expected_note_id": note_id,
                        "source": source
                    }
                }

        except FreshDeskUnavailableError:
            logger.warning("Freshdesk unavailable during verification")
            return {
                "status": "FAILED",
                "result": {
                    "reason": "Verification failed: Freshdesk unavailable",
                    "verified": False,
                    "verification_status": "unavailable",
                    "ticket_id": ticket_id,
                    "source": source
                }
            }

        except FreshDeskError as e:
            logger.warning(f"Freshdesk error during verification: {e}")
            return {
                "status": "FAILED",
                "result": {
                    "reason": f"Verification failed: {str(e)[:50]}",
                    "verified": False,
                    "verification_status": "error",
                    "ticket_id": ticket_id,
                    "source": source
                }
            }

    except Exception as e:
        logger.error(f"Verification agent error: {e}")
        return {
            "status": "FAILED",
            "result": {
                "reason": f"Verification agent error: {str(e)[:50]}",
                "verified": False,
                "verification_status": "error"
            }
        }
