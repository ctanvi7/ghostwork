"""Workflow endpoints: list and detail."""

from flask import Blueprint, jsonify

from app import NotFoundError
from services.supabase_service import get_service

workflows_bp = Blueprint("workflows", __name__, url_prefix="/api")


@workflows_bp.route("/workflows", methods=["GET"])
def list_workflows():
    """
    GET /api/workflows
    List all discovered workflows.

    Returns: 200 OK
    {
      "workflows": [
        {
          "id": 1,
          "name": "Refund Verification",
          "ghost_score": 87,
          "frequency": 37,
          ...
        }
      ]
    }
    """
    service = get_service()
    workflows = service.list_workflows()

    return jsonify({"workflows": workflows}), 200


@workflows_bp.route("/workflows/<int:workflow_id>", methods=["GET"])
def get_workflow(workflow_id: int):
    """
    GET /api/workflows/<id>
    Get workflow details with steps.

    Returns: 200 OK
    {
      "workflow": {
        "id": 1,
        "name": "Refund Verification",
        "description": "...",
        "ghost_score": 87,
        ...
      },
      "steps": [
        {
          "id": 1,
          "workflow_id": 1,
          "step_order": 1,
          "name": "context_agent",
          "agent": "context_agent",
          "classification": "ASSISTED"
        },
        ...
      ]
    }
    """
    service = get_service()
    workflow = service.get_workflow(workflow_id)

    if not workflow:
        raise NotFoundError(f"Workflow {workflow_id} not found")

    steps = service.select("workflow_steps", {"workflow_id": workflow_id})
    steps.sort(key=lambda s: s.get("step_order", 0))

    return jsonify({"workflow": workflow, "steps": steps}), 200
