"""IT verification agent: confirms the troubleshooting note landed on Freshdesk.

Same read-back principle as verification_agent, but with no refund/approval
concept - this playbook never requires human approval.
"""

import logging
from typing import Any, Dict, Optional

from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    get_last_provider_used,
    verify_note_exists,
)

logger = logging.getLogger(__name__)


def _freshdesk_configured() -> bool:
    from config import Config
    if Config.FRESHDESK_PROVIDER == "mcp":
        return bool(Config.MCP_FRESHDESK_URL and Config.MCP_FRESHDESK_AUTH_TOKEN)
    return bool(Config.FRESHDESK_DOMAIN and Config.FRESHDESK_API_KEY)


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        comm_result = None
        if context and "it_communication_agent" in context:
            comm_result = context["it_communication_agent"].get("result", {})

        if not comm_result:
            return {"status": "SUCCESS", "result": {"reason": "Verification skipped (no communication result)",
                                                     "verified": False, "verification_status": "skipped_fallback",
                                                     "source": "fallback"}}

        action_performed = comm_result.get("action_performed", False)
        writeback_status = comm_result.get("writeback_status", "skipped")
        source = comm_result.get("source", "fallback")

        if not action_performed and source == "freshdesk":
            return {"status": "FAILED", "result": {
                "reason": f"Verification failed: Freshdesk write-back not performed ({writeback_status})",
                "verified": False, "verification_status": "writeback_not_performed",
                "ticket_id": comm_result.get("ticket_id"), "source": source}}

        if not action_performed:
            return {"status": "SUCCESS", "result": {
                "reason": f"No action to verify (writeback_status: {writeback_status})",
                "verified": False, "verification_status": "skipped_fallback", "source": source}}

        ticket_id = comm_result.get("ticket_id")
        note_id = comm_result.get("note_id")
        external_reference = comm_result.get("external_reference")

        if not ticket_id:
            return {"status": "FAILED", "result": {"reason": "Verification failed: no ticket_id",
                                                    "verified": False, "verification_status": "verification_failed",
                                                    "source": source}}
        if not _freshdesk_configured():
            return {"status": "FAILED", "result": {"reason": "Verification failed: Freshdesk not configured",
                                                    "verified": False, "verification_status": "unavailable",
                                                    "ticket_id": ticket_id, "source": source}}

        try:
            result = verify_note_exists(ticket_id=ticket_id, expected_note_id=note_id,
                                        execution_reference=external_reference)
            provider = get_last_provider_used()
            if result.get("verified"):
                return {"status": "SUCCESS", "result": {
                    "reason": f"Read back ticket #{ticket_id} via {provider}: {result.get('reason')}",
                    "verified": True, "verification_status": "verified", "ticket_id": ticket_id,
                    "matched_note_id": result.get("matched_note_id"), "source": source, "provider": provider}}
            return {"status": "FAILED", "result": {
                "reason": result.get("reason"), "verified": False, "verification_status": "verification_failed",
                "ticket_id": ticket_id, "expected_note_id": note_id, "source": source, "provider": provider}}
        except FreshDeskUnavailableError:
            return {"status": "FAILED", "result": {"reason": "Verification failed: Freshdesk unavailable",
                                                    "verified": False, "verification_status": "unavailable",
                                                    "ticket_id": ticket_id, "source": source}}
        except FreshDeskError as e:
            return {"status": "FAILED", "result": {"reason": f"Verification failed: {str(e)[:50]}",
                                                    "verified": False, "verification_status": "error",
                                                    "ticket_id": ticket_id, "source": source}}
    except Exception as e:
        logger.error(f"IT verification agent error: {e}")
        return {"status": "FAILED", "result": {"reason": f"IT verification agent error: {str(e)[:50]}",
                                                "verified": False, "verification_status": "error"}}
