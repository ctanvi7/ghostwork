"""Route a ticket to a human when no approved automation exists for its pattern."""

import logging
from typing import Any, Dict

from services.freshdesk_service import add_note, get_last_provider_used, verify_note_exists

logger = logging.getLogger(__name__)

# Marker written into every handoff note; used to detect an earlier handoff.
HANDOFF_MARKER = "[GhostWork handoff]"


def build_handoff_note(pattern_name: str, reason: str) -> str:
    return "\n".join([
        f"{HANDOFF_MARKER} Pattern: {pattern_name}.",
        reason,
        "GhostWork did not take any action on this ticket. A human agent needs to resolve it.",
    ])


def route_to_human(ticket_id: int, pattern_name: str, reason: str) -> Dict[str, Any]:
    """
    Add an internal handoff note to the Freshdesk ticket, then read it back.

    Idempotent: if a handoff note already exists, nothing new is written.
    Raises FreshDeskError / FreshDeskUnavailableError; the route turns these into errors.
    """
    existing = verify_note_exists(ticket_id, execution_reference=HANDOFF_MARKER)
    if existing.get("verified"):
        logger.info(f"Ticket {ticket_id} was already routed to a human")
        return {
            "status": "already_routed",
            "ticket_id": ticket_id,
            "note_id": existing.get("matched_note_id"),
            "verified": True,
            "provider": get_last_provider_used(),
        }

    written = add_note(ticket_id, build_handoff_note(pattern_name, reason))
    note_id = written.get("note_id")
    check = verify_note_exists(ticket_id, expected_note_id=note_id, execution_reference=HANDOFF_MARKER)

    logger.info(f"Routed ticket {ticket_id} to a human (note {note_id}, verified={check.get('verified')})")
    return {
        "status": "routed_to_human",
        "ticket_id": ticket_id,
        "note_id": note_id,
        "verified": bool(check.get("verified")),
        "provider": get_last_provider_used(),
    }
