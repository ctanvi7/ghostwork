"""Discovery API endpoints: workflow discovery and GhostScore calculation."""

import logging

from flask import Blueprint, jsonify, request

from services.discovery_service import discover, get_discovered_workflows

logger = logging.getLogger(__name__)

discovery_bp = Blueprint("discovery", __name__, url_prefix="/api/discovery")


@discovery_bp.route("/workflows", methods=["GET", "POST"])
def list_workflows():
    """
    Discover workflows from activity events.

    GET: Discover from default events.json
    POST: Discover from uploaded events (body: {"events": [...]})

    Query params:
    - min_frequency: Minimum repetitions to consider a pattern (default: 2)
    - sort_by: Field to sort by (default: ghost_score)

    Returns:
        List of discovered workflows sorted by GhostScore descending.
        Each includes: id, name, frequency, sequence, automation_percentage,
        ghost_score, ghost_score_breakdown, privacy_mode, data_sources.
    """
    try:
        # Get discovery parameters
        min_frequency = request.args.get("min_frequency", default=2, type=int)
        min_frequency = max(1, min_frequency)  # Enforce minimum 1

        # Get events
        events = None
        if request.method == "POST":
            data = request.get_json() or {}
            events = data.get("events")

        # Discover workflows (Freshdesk tickets first, activity events as fallback)
        result = discover(events=events, min_frequency=min_frequency)
        workflows = result["workflows"]

        logger.info(f"Discovered {len(workflows)} workflows from {result['source']}")

        return jsonify({
            "workflows": workflows,
            "count": len(workflows),
            "min_frequency_used": min_frequency,
            "source": result["source"],
            "fallback_reason": result["fallback_reason"],
        }), 200

    except Exception as e:
        logger.error(f"Discovery error: {e}")
        return jsonify({
            "error": {
                "code": "DISCOVERY_ERROR",
                "message": str(e)
            }
        }), 500


@discovery_bp.route("/workflows/<int:workflow_id>", methods=["GET"])
def get_workflow_detail(workflow_id: int):
    """
    Get detailed information about a discovered workflow.

    Includes full GhostScore breakdown and session details.
    """
    try:
        # min_frequency=1 so single-ticket patterns shown on the page can be opened too
        workflows = get_discovered_workflows(min_frequency=1)

        # Find workflow by ID
        workflow = None
        for w in workflows:
            if w["id"] == workflow_id:
                workflow = w
                break

        if not workflow:
            return jsonify({
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Workflow {workflow_id} not found"
                }
            }), 404

        return jsonify(workflow), 200

    except Exception as e:
        logger.error(f"Workflow detail error: {e}")
        return jsonify({
            "error": {
                "code": "ERROR",
                "message": str(e)
            }
        }), 500


@discovery_bp.route("/stats", methods=["GET"])
def discovery_stats():
    """
    Get discovery statistics.

    Returns:
        Total events, sessions, discovered workflows, and summary metrics.
    """
    try:
        result = discover()
        workflows = result["workflows"]

        # Calculate aggregate statistics
        total_frequency = sum(w["frequency"] for w in workflows)
        avg_ghostscore = sum(w["ghost_score"] for w in workflows) / len(workflows) if workflows else 0

        return jsonify({
            "source": result["source"],
            # Tickets read (Freshdesk) or activity sessions (fallback)
            "total_events": result["total_items"],
            "total_sessions": result["total_items"],
            "discovered_workflows": len(workflows),
            "total_workflow_instances": total_frequency,
            "average_ghostscore": round(avg_ghostscore, 1),
            "top_workflow": workflows[0] if workflows else None
        }), 200

    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({
            "error": {
                "code": "STATS_ERROR",
                "message": str(e)
            }
        }), 500


@discovery_bp.route("/tickets/<int:ticket_id>/handoff", methods=["POST"])
def handoff_ticket(ticket_id: int):
    """
    Route a discovered ticket to a human agent (private Freshdesk note, then read-back).

    The pattern and reason are looked up server-side, never taken from the request.
    """
    from services.freshdesk_service import FreshDeskError, FreshDeskUnavailableError
    from services.handoff_service import route_to_human
    from services.ticket_discovery_service import find_ticket_pattern

    result = discover(min_frequency=1)
    if result["source"] != "freshdesk":
        return jsonify({"error": {"code": "FRESHDESK_UNAVAILABLE",
                                  "message": result["fallback_reason"] or "Freshdesk unavailable"}}), 503

    pattern = find_ticket_pattern(ticket_id, result["workflows"])
    if not pattern:
        return jsonify({"error": {"code": "NOT_FOUND",
                                  "message": f"Ticket {ticket_id} is not an open or pending Freshdesk ticket"}}), 404

    try:
        handoff = route_to_human(ticket_id, pattern["name"], pattern["automation"]["reason"])
    except (FreshDeskError, FreshDeskUnavailableError) as e:
        logger.error(f"Handoff failed for ticket {ticket_id}: {e}")
        return jsonify({"error": {"code": "HANDOFF_FAILED", "message": str(e)[:200]}}), 502

    return jsonify(handoff), 200
