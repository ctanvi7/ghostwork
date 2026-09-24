"""Discovery API endpoints: workflow discovery and GhostScore calculation."""

import logging

from flask import Blueprint, jsonify, request

from services.discovery_service import get_discovered_workflows

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

        # Discover workflows
        workflows = get_discovered_workflows(
            events=events,
            min_frequency=min_frequency
        )

        logger.info(f"Discovered {len(workflows)} workflows")

        return jsonify({
            "workflows": workflows,
            "count": len(workflows),
            "min_frequency_used": min_frequency
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
        workflows = get_discovered_workflows()

        # Find workflow by ID (hash-based)
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
        from services.discovery_service import (
            group_events_by_session,
            load_activity_events,
        )

        events = load_activity_events()
        sessions = group_events_by_session(events)
        workflows = get_discovered_workflows()

        # Calculate aggregate statistics
        total_frequency = sum(w["frequency"] for w in workflows)
        avg_ghostscore = sum(w["ghost_score"] for w in workflows) / len(workflows) if workflows else 0

        return jsonify({
            "total_events": len(events),
            "total_sessions": len(sessions),
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
