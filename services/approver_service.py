"""Find the phone number to call for a voice approval.

Order:
  1. The Freshdesk ticket's assigned agent (responder), mobile first, then phone.
  2. APPROVER_PHONE from config, only as an explicit, visible fallback.
If neither gives a valid number, the call is refused and web approval remains.

Phone numbers are personal data: they are never logged or returned unmasked.
"""

import logging
import re
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


# Freshdesk agent "language" (e.g. "en", "hi", "ta-IN") -> Sarvam voice language.
SARVAM_LANGUAGES = {
    "en": "en-IN", "hi": "hi-IN", "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
    "ml": "ml-IN", "mr": "mr-IN", "gu": "gu-IN", "pa": "pa-IN", "or": "od-IN", "od": "od-IN",
}


def voice_language(freshdesk_language: Optional[str]) -> str:
    """Sarvam language for the call; English when unset or not supported by Sarvam."""
    base = (freshdesk_language or "").strip().lower().replace("_", "-").split("-")[0]
    return SARVAM_LANGUAGES.get(base, Config.VOICE_DEFAULT_LANGUAGE)


class ApproverUnavailableError(Exception):
    """No callable approver number could be found."""


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Return an E.164 number like "+919876543210", or None if it is not a valid number."""
    if not raw or "..." in raw:
        return None
    raw = raw.strip()
    digits = re.sub(r"\D", "", raw)
    country = re.sub(r"\D", "", Config.VOBIZ_DEFAULT_COUNTRY_CODE or "")

    if raw.startswith("+"):
        number = digits
    elif raw.startswith("00"):
        number = digits[2:]
    elif len(digits) == 11 and digits.startswith("0") and country:
        number = country + digits[1:]  # national trunk prefix, e.g. 09876543210
    elif len(digits) == 10 and country:
        number = country + digits  # local number, e.g. 9876543210
    else:
        number = digits

    return f"+{number}" if 8 <= len(number) <= 15 else None


def format_for_vobiz(e164: str) -> str:
    """Use the same style as the configured caller ID (Vobiz accepts both, per its docs)."""
    from_number = (Config.VOBIZ_FROM_NUMBER or "").strip()
    return e164 if from_number.startswith("+") else e164.lstrip("+")


def mask_phone(e164: str) -> str:
    """"+919876543210" -> "+91******10"."""
    return f"{e164[:3]}{'*' * max(len(e164) - 5, 0)}{e164[-2:]}"


def _assignee_number(ticket_id) -> tuple:
    """Return (e164, agent_id, reason_if_missing, language) for the ticket's assigned agent."""
    from services.freshdesk_service import (
        FreshDeskError,
        FreshDeskUnavailableError,
        get_agent_contact,
        get_ticket,
    )

    if not ticket_id:
        return None, None, "execution has no Freshdesk ticket", None
    try:
        ticket = get_ticket(int(ticket_id))
    except FreshDeskUnavailableError:
        return None, None, "Freshdesk is not configured", None
    except FreshDeskError as e:
        # Surface the real reason (e.g. "not found") instead of a generic message,
        # so a stale execution pointing at a since-deleted/renumbered ticket is obvious.
        logger.warning(f"Ticket lookup failed for {ticket_id}: {e}")
        return None, None, f"could not read ticket #{ticket_id} from Freshdesk ({e})", None

    responder_id = (ticket.raw_response or {}).get("responder_id")
    if not responder_id:
        return None, None, f"ticket #{ticket_id} has no assigned agent", None
    try:
        agent = get_agent_contact(responder_id)
    except FreshDeskUnavailableError:
        return None, None, "Freshdesk is not configured", None
    except FreshDeskError as e:
        logger.warning(f"Agent lookup failed for ticket {ticket_id}, agent {responder_id}: {e}")
        return None, None, f"could not read the assigned agent for ticket #{ticket_id} ({e})", None

    language = agent.get("language")
    if agent.get("active") is False:
        return None, responder_id, f"assigned agent on ticket #{ticket_id} is inactive", language
    number = normalize_phone(agent.get("mobile")) or normalize_phone(agent.get("phone"))
    if not number:
        return None, responder_id, f"assigned agent on ticket #{ticket_id} has no valid phone number in Freshdesk", language
    return number, responder_id, None, language


def resolve_approver(ticket_id) -> dict:
    """
    Return {"to": number for Vobiz, "masked", "source", "agent_id", "note", "language"}.
    "language" is the Sarvam voice language (assignee's Freshdesk preference, else English).

    Raises ApproverUnavailableError when no valid number exists.
    """
    number, agent_id, missing, freshdesk_language = _assignee_number(ticket_id)
    if number:
        return {"to": format_for_vobiz(number), "masked": mask_phone(number),
                "source": "ticket_assignee", "agent_id": agent_id, "note": None,
                "language": voice_language(freshdesk_language)}

    fallback = normalize_phone(Config.APPROVER_PHONE)
    if fallback:
        logger.info(f"Using APPROVER_PHONE fallback: {missing}")
        return {"to": format_for_vobiz(fallback), "masked": mask_phone(fallback),
                "source": "config_fallback", "agent_id": None, "note": missing,
                "language": Config.VOICE_DEFAULT_LANGUAGE}

    raise ApproverUnavailableError(f"Cannot call an approver: {missing}. Use web approval.")
