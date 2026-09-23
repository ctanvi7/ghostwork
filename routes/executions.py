"""Execution endpoints: POST to create, GET to retrieve."""

from flask import Blueprint, jsonify, request

from app import NotFoundError, ValidationError
from services.supabase_service import get_service

executions_bp = Blueprint("executions", __name__, url_prefix="/api")


@executions_bp.route("/executions", methods=["POST"])
def create_execution():
    """
    POST /api/executions
    Create a new execution for a workflow.

    Request body:
    {
      "workflow_id": 1,
      "ticket_id": 2048
    }

    Returns: 201 Created
    {
      "id": 1,
      "workflow_id": 1,
      "ticket_id": 2048,
      "status": "PENDING",
      ...
    }
    """
    data = request.get_json()

    if not data:
        raise ValidationError("Request body required")

    workflow_id = data.get("workflow_id")
    ticket_id = data.get("ticket_id")

    if not workflow_id:
        raise ValidationError("workflow_id is required")

    service = get_service()

    # Verify workflow exists
    workflow = service.get_workflow(workflow_id)
    if not workflow:
        raise NotFoundError(f"Workflow {workflow_id} not found")

    # Create execution
    exec_id = service.create_execution(workflow_id, ticket_id)
    execution = service.get_execution(exec_id)

    return jsonify(execution), 201


@executions_bp.route("/executions/<int:execution_id>", methods=["GET"])
def get_execution(execution_id: int):
    """
    GET /api/executions/<id>
    Retrieve execution details with steps and approvals.

    Returns: 200 OK
    {
      "id": 1,
      "workflow_id": 1,
      "ticket_id": 2048,
      "status": "PENDING",
      "current_step": null,
      "steps": [
        {
          "id": 1,
          "execution_id": 1,
          "step_name": "context_agent",
          "status": "PENDING",
          ...
        }
      ],
      "approvals": [
        {
          "id": 1,
          "execution_id": 1,
          "status": "PENDING",
          ...
        }
      ]
    }
    """
    service = get_service()
    execution = service.get_execution(execution_id)

    if not execution:
        raise NotFoundError(f"Execution {execution_id} not found")

    return jsonify(execution), 200
