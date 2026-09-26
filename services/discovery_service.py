"""Workflow discovery service: identify repeated activity sequences."""

import json
import logging
import zlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def load_activity_events(filepath: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load activity events from JSON file."""
    if not filepath:
        filepath = str(Path(__file__).parent.parent / "data" / "activity_events.json")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load activity events: {e}")
        return []


def group_events_by_session(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by session_id, sorted by timestamp."""
    sessions = defaultdict(list)
    for event in events:
        session_id = event.get("session_id")
        if session_id:
            sessions[session_id].append(event)

    # Sort each session by timestamp
    for session_id in sessions:
        sessions[session_id].sort(key=lambda e: e.get("timestamp", ""))

    return sessions


def extract_sequence(session_events: List[Dict[str, Any]]) -> List[str]:
    """Extract tool sequence from session events: tool-action pairs."""
    sequence = []
    for event in session_events:
        tool = event.get("tool", "unknown")
        action = event.get("action", "unknown")
        sequence.append(f"{tool}:{action}")
    return sequence


def count_sequence_frequencies(
    sessions: Dict[str, List[Dict[str, Any]]],
    min_frequency: int = 2
) -> Dict[str, List[str]]:
    """
    Group sessions by sequence pattern.

    Returns dict of sequence_signature -> list of matching session_ids.
    Only includes sequences with at least min_frequency occurrences.
    """
    sequence_map = {}
    for session_id, session_events in sessions.items():
        seq = extract_sequence(session_events)
        sig = tuple(seq)
        if sig not in sequence_map:
            sequence_map[sig] = []
        sequence_map[sig].append(session_id)

    # Filter by minimum frequency
    frequent = {
        sig: sessions_list
        for sig, sessions_list in sequence_map.items()
        if len(sessions_list) >= min_frequency
    }

    return frequent


def calculate_sequence_duration(
    session_events: List[Dict[str, Any]]
) -> float:
    """Calculate session duration in seconds."""
    if not session_events or len(session_events) < 2:
        return 0

    try:
        first_ts = datetime.fromisoformat(session_events[0]["timestamp"].replace("Z", "+00:00"))
        last_ts = datetime.fromisoformat(session_events[-1]["timestamp"].replace("Z", "+00:00"))
        return (last_ts - first_ts).total_seconds()
    except Exception as e:
        logger.warning(f"Failed to calculate duration: {e}")
        return 0


def discover_workflows(
    events: Optional[List[Dict[str, Any]]] = None,
    filepath: Optional[str] = None,
    min_frequency: int = 2
) -> List[Dict[str, Any]]:
    """
    Discover repeated workflows from activity events.

    Returns list of discovered workflows sorted by frequency descending.
    Each workflow includes: sequence, frequency, average_duration, step_count.
    """
    if events is None:
        events = load_activity_events(filepath)

    if not events:
        logger.warning("No events loaded for discovery")
        return []

    # Group and count
    sessions = group_events_by_session(events)
    frequent_sequences = count_sequence_frequencies(sessions, min_frequency)

    # Build workflow summaries
    workflows = []
    for sequence_tuple, session_ids in frequent_sequences.items():
        sequence = list(sequence_tuple)

        # Calculate statistics
        durations = []
        for session_id in session_ids:
            session_events = sessions[session_id]
            duration = calculate_sequence_duration(session_events)
            if duration > 0:
                durations.append(duration)

        avg_duration = sum(durations) / len(durations) if durations else 0

        workflow = {
            "signature": sequence,
            "sequence": " → ".join([s.split(":")[0] for s in sequence]),
            "frequency": len(session_ids),
            "session_ids": session_ids,
            "step_count": len(sequence),
            "average_duration_seconds": round(avg_duration, 1),
            "detected_sessions": len(session_ids),
        }
        workflows.append(workflow)

    # Sort by frequency descending
    workflows.sort(key=lambda w: w["frequency"], reverse=True)

    return workflows


def normalize_discovered_workflow(
    workflow: Dict[str, Any],
    workflow_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Normalize a discovered workflow to API response format.

    Includes privacy metadata and GhostScore calculation.
    """
    from orchestrator.ghostscore import calculate_ghostscore

    signature = workflow.get("signature", [])
    frequency = workflow.get("frequency", 0)
    avg_duration = workflow.get("average_duration_seconds", 0)
    step_count = workflow.get("step_count", 0)

    # Estimate automation potential (simplified: most enterprise tools are automatable)
    automatable_steps = step_count - 1 if step_count > 0 else 0  # First step often needs human
    automation_percentage = (automatable_steps / step_count * 100) if step_count > 0 else 0

    # Calculate GhostScore
    ghostscore_result = calculate_ghostscore(
        frequency=frequency,
        step_count=step_count,
        average_duration_seconds=avg_duration,
        automation_percentage=automation_percentage,
        step_signatures=signature
    )

    # Same deterministic playbook rule as the Freshdesk path, so the UI shows
    # one automation decision whichever data source was used.
    from services.ticket_discovery_service import PLAYBOOKS, assess_automation

    name = _label_workflow(signature)
    category = next((key for key, workflow_name in PLAYBOOKS.items() if workflow_name == name), "activity")

    return {
        "id": workflow_id or _signature_id(signature),
        "name": name,
        "frequency": frequency,
        "is_repeating": frequency >= 2,
        "automation": assess_automation(category, name, frequency),
        "sequence": workflow.get("sequence", ""),
        "step_signatures": signature,
        "step_count": step_count,
        "average_duration_seconds": avg_duration,
        "automation_percentage": round(automation_percentage, 1),
        "ghost_score": ghostscore_result["score"],
        "ghost_score_breakdown": ghostscore_result["breakdown"],
        "risk_level": "medium",
        "discovered_from": "activity_metadata",
        "privacy_mode": "metadata_only",
        "data_sources": ["tool", "action", "timestamp", "session"],
        "session_ids": workflow.get("session_ids", []),
    }


def _signature_id(signature: List[str]) -> int:
    """Stable ID across restarts and server instances (Python's hash() is randomized per process)."""
    return zlib.crc32("activity:{}".format("|".join(signature)).encode()) & 0x7FFFFFFF


def _label_workflow(signature: List[str]) -> str:
    """Generate a human-readable label for a workflow."""
    if not signature:
        return "Unknown Workflow"

    # Map common patterns
    if len(signature) >= 5:
        # Refund-like: freshdesk → crm/billing → policy → approval
        if any("freshdesk" in s for s in signature):
            if any("approval" in s for s in signature):
                return "Refund Verification"
            if any("identity" in s for s in signature):
                return "Customer Address Change"
            if any("dispute" in s for s in signature):
                return "Invoice Dispute Review"

    # Fallback: show tool sequence
    tools = [s.split(":")[0] for s in signature]
    return " → ".join(tools)


def _discover_from_events(events, filepath, min_frequency) -> List[Dict[str, Any]]:
    workflows = discover_workflows(events, filepath, min_frequency)
    normalized = [normalize_discovered_workflow(w) for w in workflows]
    normalized.sort(key=lambda w: w["ghost_score"], reverse=True)
    return normalized


def discover(
    events: Optional[List[Dict[str, Any]]] = None,
    filepath: Optional[str] = None,
    min_frequency: int = 2
) -> Dict[str, Any]:
    """
    Discover patterns and report which data source was used.

    Live Freshdesk tickets are the primary source. If Freshdesk is unavailable
    (or events are passed in explicitly), the synthetic activity events are used.

    Returns: {"source", "workflows", "total_items", "fallback_reason"}
    """
    from services.freshdesk_service import FreshDeskError, FreshDeskUnavailableError
    from services.ticket_discovery_service import discover_ticket_patterns, fetch_unresolved_tickets

    fallback_reason = None
    if events is None and filepath is None:
        try:
            tickets = fetch_unresolved_tickets()
            return {
                "source": "freshdesk",
                "workflows": discover_ticket_patterns(tickets, min_frequency),
                "total_items": len(tickets),
                "fallback_reason": None,
            }
        except FreshDeskUnavailableError:
            fallback_reason = "Freshdesk not configured"
        except FreshDeskError as e:
            fallback_reason = f"Freshdesk read failed: {str(e)[:100]}"
            logger.warning(f"Discovery falling back to activity events: {e}")

    if events is None:
        events = load_activity_events(filepath)
    return {
        "source": "activity_events",
        "workflows": _discover_from_events(events, None, min_frequency),
        "total_items": len(group_events_by_session(events)),
        "fallback_reason": fallback_reason,
    }


def get_discovered_workflows(
    events: Optional[List[Dict[str, Any]]] = None,
    filepath: Optional[str] = None,
    min_frequency: int = 2
) -> List[Dict[str, Any]]:
    """
    Get all discovered workflows (Freshdesk tickets first, activity events as fallback).

    Args:
        events: Raw activity events (if given, Freshdesk is not queried)
        filepath: Path to activity events JSON
        min_frequency: Minimum number of repetitions to consider a pattern

    Returns:
        List of normalized discovered workflows with GhostScore
    """
    return discover(events, filepath, min_frequency)["workflows"]
