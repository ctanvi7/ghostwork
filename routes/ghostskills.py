"""GhostSkill endpoints: generate, list, retrieve, execute."""

import logging

from flask import Blueprint, jsonify, request

from app import InvalidStateError, NotFoundError, ValidationError
from orchestrator.workflow import run_execution
from services.discovery_service import get_discovered_workflows
from services.ghostskill_service import generate_ghostskill
from services.supabase_service import get_service

logger = logging.getLogger(__name__)

ghostskills_bp = Blueprint("ghostskills", __name__, url_prefix="/api")


@ghostskills_bp.route("/discovery/workflows/<int:workflow_id>/ghostskill", methods=["POST"])
def generate_skill(workflow_id: int):
    """
    POST /api/discovery/workflows/<workflow_id>/ghostskill
    Generate a GhostSkill from a discovered workflow.

    Discovers workflows from activity events, finds the one matching workflow_id,
    maps its steps to orchestrator agents, and persists the skill.

    Returns: 201 Created
    {
      "skill_id": "...",
      "name": "Refund Verification",
      "status": "READY",
      "steps": [...],
      ...
    }
    """
    service = get_service()

    # Fetch discovered workflows
    discovered_workflows = get_discovered_workflows()

    # Find the workflow matching workflow_id
    discovered = None
    for w in discovered_workflows:
        if w.get("id") == workflow_id:
            discovered = w
            break

    if not discovered:
        raise NotFoundError(f"Discovered workflow {workflow_id} not found")

    # Generate GhostSkill (deterministic, or with Claude-enhanced description)
    try:
        skill = generate_ghostskill(discovered, service=service)
    except ValueError as e:
        raise ValidationError(str(e)) from e

    # Get orchestrator workflow_id from the skill's internal state
    orch_workflow_id = skill.__dict__.get("_orchestrator_workflow_id")
    if orch_workflow_id is None:
        raise ValidationError("Failed to resolve orchestrator workflow ID")

    # Persist the skill
    skill_dict = skill.model_dump()
    skill_id = service.create_ghost_skill(
        workflow_id=orch_workflow_id,
        name=skill.name,
        definition_json=skill_dict,
    )

    # Return the persisted skill
    persisted_skill = service.get_ghost_skill(skill_id)
    logger.info(f"Generated GhostSkill {skill_id} from discovered workflow {workflow_id}")

    return jsonify(persisted_skill), 201


@ghostskills_bp.route("/ghostskills", methods=["GET"])
def list_skills():
    """
    GET /api/ghostskills
    List all generated ghost skills.

    Returns: 200 OK
    {
      "skills": [...],
      "count": N
    }
    """
    service = get_service()
    skills = service.list_ghost_skills()

    return jsonify({"skills": skills, "count": len(skills)}), 200


@ghostskills_bp.route("/ghostskills/<int:skill_id>", methods=["GET"])
def get_skill(skill_id: int):
    """
    GET /api/ghostskills/<skill_id>
    Retrieve a ghost skill by ID.

    Returns: 200 OK
    {
      "id": 1,
      "name": "Refund Verification",
      "definition_json": {...},
      ...
    }
    """
    service = get_service()
    skill = service.get_ghost_skill(skill_id)

    if not skill:
        raise NotFoundError(f"Ghost skill {skill_id} not found")

    return jsonify(skill), 200


@ghostskills_bp.route("/ghostskills/<int:skill_id>/execute", methods=["POST"])
def execute_skill(skill_id: int):
    """
    POST /api/ghostskills/<skill_id>/execute
    Execute a ghost skill.

    Request body:
    {
      "ticket_id": 2048,
      "refund_amount": 32000
    }

    Returns: 202 Accepted
    {
      "id": 1,
      "status": "PENDING" or "WAITING_FOR_APPROVAL" or "COMPLETED",
      ...
    }
    """
    data = request.get_json()

    if not data:
        raise ValidationError("Request body required")

    ticket_id = data.get("ticket_id")
    refund_amount = data.get("refund_amount")

    if refund_amount is None:
        raise ValidationError("refund_amount is required")

    service = get_service()

    # Get the skill
    skill = service.get_ghost_skill(skill_id)
    if not skill:
        raise NotFoundError(f"Ghost skill {skill_id} not found")

    # Check skill status
    definition = skill.get("definition_json", {})
    skill_status = definition.get("status", "READY")  # Default to READY if not set
    if skill_status not in ("READY", None):  # Allow None (missing status) or READY
        raise InvalidStateError(
            f"Skill {skill_id} is in status '{skill_status}', cannot execute"
        )

    # Get orchestrator workflow_id from the skill row
    workflow_id = skill.get("workflow_id")
    if not workflow_id:
        raise ValidationError("Skill has no associated workflow")

    # Create execution
    exec_id = service.create_execution(workflow_id, ticket_id, refund_amount)

    # Run execution (synchronous for testing, would be async in production)
    run_execution(exec_id)

    execution = service.get_execution(exec_id)

    logger.info(f"Executed GhostSkill {skill_id} as execution {exec_id}")

    return jsonify(execution), 202
