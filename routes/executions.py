"""Execution endpoints: POST to create, GET to retrieve."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from app import InvalidStateError, NotFoundError, ValidationError
from config import Config
from orchestrator.workflow import run_execution
from services.supabase_service import get_service

executions_bp = Blueprint("executions", __name__, url_prefix="/api")

# executions.refund_amount is NUMERIC(12, 2)
MAX_REFUND_AMOUNT = Decimal("10000000000")


def parse_positive_int(value, name: str) -> int:
    """Validate an ID from a request body (an int or a digit string)."""
    if value is None or value == "":
        raise ValidationError(f"{name} is required")
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value)
    else:
        raise ValidationError(f"{name} must be a positive integer")
    if number < 1:
        raise ValidationError(f"{name} must be a positive integer")
    return number


def parse_refund_amount(value):
    """Optional refund amount from a request: None, or a positive number."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError("refund_amount must be a positive number")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError("refund_amount must be a positive number") from None
    if not amount.is_finite() or amount <= 0 or amount >= MAX_REFUND_AMOUNT:
        raise ValidationError("refund_amount must be a positive number")
    return float(amount)


def attach_workflow_names(executions: list) -> list:
    """Add workflow_name to each execution so the UI can show it."""
    names = {w.get("id"): w.get("name") for w in get_service().list_workflows()}
    for execution in executions:
        execution["workflow_name"] = names.get(execution.get("workflow_id"))
    return executions


def start_execution(workflow: dict, ticket_id: int, refund_amount):
    """Create and run an execution, or return the run already active for the ticket.

    Returns (execution, created).
    """
    service = get_service()
    _check_ticket_matches_playbook(ticket_id, workflow)

    active = service.get_active_execution_for_ticket(ticket_id)
    if active:
        return active, False

    try:
        exec_id = service.create_execution(workflow["id"], ticket_id, refund_amount)
    except Exception as exc:
        # A concurrent click can pass the check above before the first insert.
        if "idx_one_active_per_ticket" in str(exc):
            active = service.get_active_execution_for_ticket(ticket_id)
            if active:
                return active, False
        raise

    # Start execution (synchronous for testing, would be async in production)
    run_execution(exec_id)
    return service.get_execution(exec_id), True


@executions_bp.route("/executions", methods=["POST"])
def create_execution():
    """
    POST /api/executions
    Create a new execution for a workflow and start it.

    Request body:
    {
      "workflow_id": 1,
      "ticket_id": 2048,
      "refund_amount": 32000
    }

    Returns: 202 Accepted
    {
      "id": 1,
      "workflow_id": 1,
      "ticket_id": 2048,
      "status": "PENDING",
      ...
    }
    """
    data = request.get_json(silent=True)

    if not data or not isinstance(data, dict):
        raise ValidationError("Request body required")

    workflow_id = parse_positive_int(data.get("workflow_id"), "workflow_id")
    # The demo UI omits ticket_id; use the real Freshdesk demo ticket from config.
    ticket_id = parse_positive_int(data.get("ticket_id") or Config.FRESHDESK_DEMO_TICKET_ID, "ticket_id")
    refund_amount = parse_refund_amount(data.get("refund_amount"))

    # Verify workflow exists
    workflow = get_service().get_workflow(workflow_id)
    if not workflow:
        raise NotFoundError(f"Workflow {workflow_id} not found")

    execution, created = start_execution(workflow, ticket_id, refund_amount)
    attach_workflow_names([execution])
    return jsonify(execution), (202 if created else 200)


def _check_ticket_matches_playbook(ticket_id: int, workflow) -> None:
    """Refuse to automate a Freshdesk ticket that is resolved/closed or belongs to another playbook.

    Skipped when Freshdesk is unavailable, so the cached demo path keeps working.
    """
    from services.discovery_service import discover
    from services.ticket_discovery_service import find_ticket_pattern

    result = discover(min_frequency=1)
    if result["source"] != "freshdesk":
        return
    pattern = find_ticket_pattern(ticket_id, result["workflows"])
    if not pattern:
        # Discovery only returns Open/Pending tickets, so this ticket is resolved, closed or missing.
        raise InvalidStateError(f"Ticket {ticket_id} is not an open or pending Freshdesk ticket")
    if pattern["automation"]["workflow_name"] != workflow.get("name"):
        raise InvalidStateError(
            f"Ticket {ticket_id} is a '{pattern['name']}' ticket, not '{workflow.get('name')}'. "
            f"{pattern['automation']['reason']}"
        )


@executions_bp.route("/executions", methods=["GET"])
def list_executions():
    """
    GET /api/executions
    List recent executions.

    Query params:
    - limit: max results (default 20)
    - offset: pagination offset (default 0)

    Returns: 200 OK
    {
      "executions": [...],
      "count": 5
    }
    """
    limit = request.args.get("limit", default=20, type=int)
    offset = request.args.get("offset", default=0, type=int)

    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    service = get_service()
    executions = attach_workflow_names(service.list_executions(limit=limit, offset=offset))

    return jsonify({"executions": executions, "count": len(executions)}), 200


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

    attach_workflow_names([execution])
    return jsonify(execution), 200
