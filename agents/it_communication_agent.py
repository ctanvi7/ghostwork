"""IT communication agent: writes the diagnosis_agent's guide to Freshdesk.

Unlike the refund communication_agent, this playbook never requires human
approval (advice, not a financial or irreversible action), so there is no
approval gate to check here.
"""

import logging
from typing import Any, Dict, Optional

from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    add_note,
    get_last_provider_used,
    get_ticket,
)

logger = logging.getLogger(__name__)

TICKET_DONE_STATUSES = {4: "Resolved", 5: "Closed"}


def _freshdesk_configured() -> bool:
    from config import Config
    if Config.FRESHDESK_PROVIDER == "mcp":
        return bool(Config.MCP_FRESHDESK_URL and Config.MCP_FRESHDESK_AUTH_TOKEN)
    return bool(Config.FRESHDESK_DOMAIN and Config.FRESHDESK_API_KEY)


def _step_result(context: Optional[Dict[str, Any]], step_name: str) -> Dict[str, Any]:
    return ((context or {}).get(step_name) or {}).get("result") or {}


def _skipped(reason: str, source: str, **extra) -> Dict[str, Any]:
    return {"status": "SUCCESS", "result": {"reason": reason, "action_performed": False,
                                             "source": source, "writeback_status": "skipped", **extra}}


def _build_note_content(issue_name: str, steps: list, execution_id: Optional[Any]) -> str:
    lines = [f"GhostWork Windows Troubleshooting: matched '{issue_name}'.", "Suggested steps:"]
    lines += [f"{i}. {step}" for i, step in enumerate(steps, start=1)]
    if execution_id:
        lines.append(f"Execution ID: {execution_id}.")
    return "\n".join(lines)


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Post the diagnosis as a Freshdesk note. Always SUCCESS (fail-open, like communication_agent)."""
    try:
        ticket_id = execution.get("ticket_id")
        source = _step_result(context, "context_agent").get("source") or execution.get("source", "fallback")

        if source != "freshdesk":
            return _skipped("Write-back skipped (no Freshdesk ticket)", source)
        if not ticket_id:
            return _skipped("Write-back skipped (no ticket_id)", source)

        diagnosis = _step_result(context, "diagnosis_agent")
        if not diagnosis.get("resolution_steps"):
            return _skipped("Write-back skipped (no diagnosis available)", source)

        if not _freshdesk_configured():
            return _skipped("Freshdesk not configured, using fallback", source, writeback_status="fallback_unavailable")

        try:
            current_status = (get_ticket(ticket_id).raw_response or {}).get("status")
            if current_status in TICKET_DONE_STATUSES:
                return {
                    "status": "SUCCESS",
                    "result": {
                        "reason": f"Write-back skipped: ticket #{ticket_id} was already "
                                  f"{TICKET_DONE_STATUSES[current_status]} in Freshdesk",
                        "action_performed": False, "ticket_id": ticket_id, "source": source,
                        "writeback_status": "skipped_ticket_closed",
                    },
                }

            note_body = _build_note_content(
                diagnosis.get("issue_name", "General Windows Issue"),
                diagnosis.get("resolution_steps", []),
                execution.get("execution_id") or execution.get("id"),
            )
            result = add_note(ticket_id, note_body)
            provider = get_last_provider_used()
            logger.info(f"Freshdesk write-back successful for ticket {ticket_id} via {provider}")

            return {
                "status": "SUCCESS",
                "result": {
                    "reason": f"Freshdesk note {result.get('note_id')} added to ticket #{ticket_id} via {provider}",
                    "action_performed": True, "ticket_id": ticket_id, "note_id": result.get("note_id"),
                    "source": source, "provider": provider, "writeback_status": "success",
                    "external_reference": f"freshdesk-note-{result.get('note_id')}",
                },
            }
        except FreshDeskUnavailableError:
            return {
                "status": "SUCCESS",
                "result": {"reason": "Freshdesk write-back failed (unavailable), workflow continues",
                          "action_performed": False, "ticket_id": ticket_id, "source": source,
                          "writeback_status": "fallback_unavailable"},
            }
        except FreshDeskError as e:
            return {
                "status": "SUCCESS",
                "result": {"reason": f"Freshdesk write-back failed: {str(e)[:50]}",
                          "action_performed": False, "ticket_id": ticket_id, "source": source,
                          "writeback_status": "error", "error_category": "freshdesk_error"},
            }
    except Exception as e:
        logger.error(f"IT communication agent error: {e}")
        return {"status": "SUCCESS", "result": {"reason": f"IT communication agent error: {str(e)[:50]}",
                                                "action_performed": False, "source": "fallback",
                                                "writeback_status": "error"}}
