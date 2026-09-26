"""Discover repeating ticket patterns from live Freshdesk tickets.

Flow (all deterministic, no LLM needed):
  1. Read Open/Pending ticket metadata from Freshdesk (subject, type, tags, status).
     Resolved and closed tickets are filtered out in the Freshdesk query.
  2. Put each ticket into a category using keyword rules.
  3. Tickets in the same category form a pattern; frequency = ticket count.
  4. Decide per pattern whether automation is possible: only categories with
     an approved playbook (an orchestrator workflow) are automated. Everything
     else is routed to a human.
"""

import logging
import time
import zlib
from typing import Any, Dict, List, Optional

from config import Config

logger = logging.getLogger(__name__)

# (category key, display name, keywords). First match wins, so order matters.
CATEGORY_RULES = [
    ("refund", "Refund Request",
     ["refund", "money back", "reimburse", "chargeback", "duplicate charge", "charged twice"]),
    ("it_troubleshooting", "Windows Troubleshooting",
     ["windows", "bsod", "blue screen", "boot", "cpu", "disk", "wi-fi", "wifi",
      "network adapter", "slow performance", "crash", "driver"]),
    ("shipping_delay", "Shipping Delay",
     ["shipment", "shipping", "delivery", "delayed", "tracking", "courier"]),
    ("product_defect", "Defective Product",
     ["defective", "damaged", "broken", "faulty", "not working"]),
    ("billing_dispute", "Invoice Dispute",
     ["invoice", "billing", "dispute", "overcharged"]),
    ("account_change", "Account Update",
     ["address", "password", "account", "profile"]),
]
GENERAL_CATEGORY = ("general", "General Inquiry")

# Categories GhostWork is allowed to automate, mapped to the orchestrator
# workflow that runs them. Anything not listed here goes to a human.
PLAYBOOKS = {"refund": "Refund Verification", "it_troubleshooting": "Windows Troubleshooting"}

# Extra context appended to the AUTOMATE reason, specific to what each
# playbook's own deterministic control actually is. Refunds gate on the
# approval threshold; IT troubleshooting has no financial risk, so it never
# needs human approval and is not held to the same gate.
PLAYBOOK_NOTES = {
    "refund": (f"Refunds above ₹{Config.AUTO_APPROVAL_LIMIT:,} or with no amount still "
              "pause for human approval."),
    "it_troubleshooting": "Advice only, no irreversible action, so no human approval is required.",
}
# refund carries financial/approval risk; it_troubleshooting is advice only.
PLAYBOOK_RISK = {"refund": "medium", "it_troubleshooting": "low"}

# How humans handle each pattern today (drawn as the GhostGraph).
REFUND_SIGNATURE = [
    "freshdesk:ticket_opened",
    "crm:customer_lookup",
    "billing:invoice_lookup",
    "policy_engine:policy_check",
    "approval_system:approval_requested",
    "freshdesk:ticket_updated",
]
IT_TROUBLESHOOTING_SIGNATURE = [
    "freshdesk:ticket_opened",
    "ghostwork:diagnose_issue",
    "freshdesk:ticket_updated",
]
HUMAN_SIGNATURE = [
    "freshdesk:ticket_opened",
    "ghostwork:pattern_triage",
    "ghostwork:route_to_human",
    "human:resolve_and_reply",
]
# The automated path's own signature per playbook, used only when a pattern is AUTOMATE.
PLAYBOOK_SIGNATURES = {"refund": REFUND_SIGNATURE, "it_troubleshooting": IT_TROUBLESHOOTING_SIGNATURE}
MANUAL_TOOLS = {"human", "approval_system"}

# Freshdesk has no handling-time metadata, so these are labeled demo estimates.
ESTIMATED_HANDLING_SECONDS = {"refund": 667, "it_troubleshooting": 480}
DEFAULT_HANDLING_SECONDS = 600

STATUS_NAMES = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
ACTIONABLE_STATUSES = {2, 3}
METADATA_FIELDS = ("id", "subject", "type", "tags", "status", "priority", "created_at", "spam")

CACHE_SECONDS = 20
_cache: Dict[str, Any] = {"at": 0.0, "tickets": None}


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["tickets"] = None


def fetch_unresolved_tickets() -> List[Dict[str, Any]]:
    """Read Open/Pending ticket metadata from Freshdesk, cached briefly so page loads stay fast.

    Resolved and closed tickets are excluded by the Freshdesk query;
    discover_ticket_patterns() re-checks status in case the API ever returns more.
    Raises FreshDeskError / FreshDeskUnavailableError so the caller can fall back.
    """
    from services.freshdesk_service import list_unresolved_tickets

    if _cache["tickets"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["tickets"]

    tickets = [
        _metadata_only(t) for t in list_unresolved_tickets()
        if isinstance(t, dict) and t.get("id") and not t.get("spam")
    ]
    _cache["tickets"] = tickets
    _cache["at"] = time.time()
    logger.info(f"Discovery read {len(tickets)} unresolved tickets from Freshdesk")
    return tickets


def _metadata_only(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Drop message bodies: discovery is metadata-only telemetry."""
    return {key: ticket.get(key) for key in METADATA_FIELDS}


def classify_ticket(ticket: Dict[str, Any]) -> tuple:
    """Return (category_key, display_name) using keyword rules on metadata only."""
    tags = ticket.get("tags") or []
    text = " ".join([ticket.get("subject") or "", ticket.get("type") or "", *map(str, tags)]).lower()
    for key, name, keywords in CATEGORY_RULES:
        if any(word in text for word in keywords):
            return key, name
    return GENERAL_CATEGORY


def assess_automation(category_key: str, category_name: str, frequency: int) -> Dict[str, Any]:
    """Deterministic decision: automate only if an approved playbook exists."""
    workflow_name = PLAYBOOKS.get(category_key)
    if workflow_name:
        note = PLAYBOOK_NOTES.get(category_key, "")
        return {
            "decision": "AUTOMATE",
            "automatable": True,
            "workflow_name": workflow_name,
            "reason": f"Matches the approved '{workflow_name}' playbook. {note}".strip(),
        }
    reason = f"No approved automation playbook for '{category_name}', so tickets are routed to a human agent."
    if frequency >= 2:
        reason += f" It repeats {frequency} times, so it is a candidate for a new GhostSkill."
    return {"decision": "HUMAN_REVIEW", "automatable": False, "workflow_name": None, "reason": reason}


def _pattern_id(category_key: str) -> int:
    """Stable ID across restarts (Python's hash() is randomized per process)."""
    return zlib.crc32(f"freshdesk:{category_key}".encode()) & 0x7FFFFFFF


def _ticket_summary(ticket: Dict[str, Any]) -> Dict[str, Any]:
    status = ticket.get("status")
    return {
        "ticket_id": ticket.get("id"),
        "subject": ticket.get("subject") or "",
        "status": STATUS_NAMES.get(status, str(status)),
        "actionable": status in ACTIONABLE_STATUSES,
        "url": Config.freshdesk_ticket_url(ticket.get("id")),
    }


def discover_ticket_patterns(tickets: List[Dict[str, Any]], min_frequency: int = 1) -> List[Dict[str, Any]]:
    """Group tickets into patterns and score them. Sorted: repeating first, then GhostScore."""
    from orchestrator.ghostscore import calculate_ghostscore

    # Only unresolved work counts: resolved/closed tickets never form or trigger a pattern.
    tickets = [t for t in tickets if t.get("status") in ACTIONABLE_STATUSES]

    groups: Dict[str, Dict[str, Any]] = {}
    for ticket in tickets:
        key, name = classify_ticket(ticket)
        group = groups.setdefault(key, {"name": name, "tickets": []})
        group["tickets"].append(ticket)

    patterns = []
    for key, group in groups.items():
        frequency = len(group["tickets"])
        if frequency < min_frequency:
            continue

        automation = assess_automation(key, group["name"], frequency)
        signature = PLAYBOOK_SIGNATURES.get(key, HUMAN_SIGNATURE) if automation["automatable"] else HUMAN_SIGNATURE
        automated_steps = [s for s in signature if s.split(":")[0] not in MANUAL_TOOLS]
        automation_percentage = len(automated_steps) / len(signature) * 100
        duration = ESTIMATED_HANDLING_SECONDS.get(key, DEFAULT_HANDLING_SECONDS)

        score = calculate_ghostscore(
            frequency=frequency,
            step_count=len(signature),
            average_duration_seconds=duration,
            automation_percentage=automation_percentage,
            step_signatures=signature,
            max_frequency=len(tickets),
        )

        patterns.append({
            "id": _pattern_id(key),
            # Automatable patterns use the workflow name so GhostSkill generation can find it.
            "name": automation["workflow_name"] or group["name"],
            "category": key,
            "frequency": frequency,
            "is_repeating": frequency >= 2,
            "sequence": " → ".join(s.split(":")[0] for s in signature),
            "step_signatures": signature,
            "step_count": len(signature),
            "average_duration_seconds": duration,
            "duration_is_estimate": True,
            "automation_percentage": round(automation_percentage, 1),
            "automation": automation,
            "ghost_score": score["score"],
            "ghost_score_breakdown": score["breakdown"],
            "risk_level": PLAYBOOK_RISK.get(key, "medium") if automation["automatable"] else "low",
            "discovered_from": "freshdesk_tickets",
            "privacy_mode": "metadata_only",
            "data_sources": ["subject", "type", "tags", "status"],
            "tickets": [_ticket_summary(t) for t in group["tickets"]],
            "session_ids": [],
        })

    patterns.sort(key=lambda p: (p["is_repeating"], p["ghost_score"]), reverse=True)
    return patterns


def find_ticket_pattern(ticket_id: int, patterns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the pattern for this ticket, or None if it is not Open/Pending.

    Freshdesk's search index lags a few minutes behind live changes, so a ticket
    missing from the search results is re-read directly before deciding.
    """
    for pattern in patterns:
        if any(t["ticket_id"] == ticket_id for t in pattern.get("tickets", [])):
            return pattern

    from services.freshdesk_service import FreshDeskError, FreshDeskUnavailableError, get_ticket

    try:
        raw = get_ticket(ticket_id).raw_response or {}
    except (FreshDeskError, FreshDeskUnavailableError) as e:
        logger.info(f"Ticket {ticket_id} not readable for pattern lookup: {e}")
        return None
    matches = discover_ticket_patterns([_metadata_only(raw)])  # empty if resolved/closed
    return matches[0] if matches else None
