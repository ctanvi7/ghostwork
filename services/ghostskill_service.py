"""GhostSkill generation and validation service."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from config import Config
from schemas.ghostskill import (
    ApprovalPolicy,
    AutonomyBoundary,
    GhostSkill,
    PrivacySpec,
    SkillInput,
    SkillStep,
    TriggerSpec,
    VerificationSpec,
)

logger = logging.getLogger(__name__)

# Canonical agents that can be executed by the orchestrator
ALLOWED_AGENTS = {
    "context_agent",
    "billing_agent",
    "policy_agent",
    "risk_agent",
    "approval_gate",
    "communication_agent",
    "verification_agent",
}

# Deterministic mapping from discovered "tool:action" to agent
TOOL_ACTION_TO_AGENT = {
    "freshdesk:ticket_opened": "context_agent",
    "crm:customer_lookup": "context_agent",
    "billing:invoice_lookup": "billing_agent",
    "policy_engine:policy_check": "policy_agent",
    "approval_system:approval_requested": "risk_agent",
    "freshdesk:ticket_updated": "communication_agent",
}


def map_signature_to_steps(step_signatures: List[str]) -> List[SkillStep]:
    """
    Map discovered tool:action signatures to orchestrator agents.

    Deterministically collapses duplicates, injects approval_gate after risk_agent,
    and appends verification_agent.

    Args:
        step_signatures: List of "tool:action" strings from discovery

    Returns:
        List of SkillStep objects, possibly with unmapped steps (agent=None).
    """
    steps: List[SkillStep] = []
    current_order = 1

    # Map each signature to an agent
    last_agent = None
    for sig in step_signatures:
        agent_name = TOOL_ACTION_TO_AGENT.get(sig)
        status = "MAPPED" if agent_name and agent_name in ALLOWED_AGENTS else "NEEDS_CONFIGURATION"

        # Skip consecutive duplicates
        if agent_name == last_agent:
            continue

        steps.append(
            SkillStep(
                order=current_order,
                name=sig.replace(":", "_"),
                agent=agent_name,
                action=f"Execute {sig}",
                automation="automatic",
                status=status,
            )
        )
        last_agent = agent_name
        current_order += 1

    # Inject approval_gate immediately after risk_agent if not already adjacent
    risk_agent_idx = None
    approval_gate_idx = None
    for i, step in enumerate(steps):
        if step.agent == "risk_agent":
            risk_agent_idx = i
        if step.agent == "approval_gate":
            approval_gate_idx = i

    if risk_agent_idx is not None:
        # Check if approval_gate is immediately after risk_agent
        if approval_gate_idx is None or approval_gate_idx != risk_agent_idx + 1:
            # Insert approval_gate right after risk_agent
            approval_step = SkillStep(
                order=steps[risk_agent_idx].order + 1,
                name="approval_gate",
                agent="approval_gate",
                action="Check approval requirements",
                automation="human_required",
                status="MAPPED",
            )
            steps.insert(risk_agent_idx + 1, approval_step)

            # Re-order all steps after insertion
            for i, step in enumerate(steps):
                step.order = i + 1

    # Append verification_agent as the final step if missing
    if not any(step.agent == "verification_agent" for step in steps):
        verification_step = SkillStep(
            order=len(steps) + 1,
            name="verification_agent",
            agent="verification_agent",
            action="Verify workflow completion",
            automation="automatic",
            status="MAPPED",
        )
        steps.append(verification_step)

    return steps


def generate_ghostskill(
    discovered_workflow: Dict[str, Any],
    service: Optional[Any] = None,  # supabase_service instance for workflow lookup
) -> GhostSkill:
    """
    Generate a GhostSkill from a discovered workflow.

    Deterministically maps steps to agents, resolves orchestrator workflow_id,
    and sets policy thresholds. Claude is optional and only enhances descriptions.

    Args:
        discovered_workflow: Discovered workflow dict with id, name, step_signatures, ghost_score
        service: SupabaseService instance for workflow name resolution (optional for tests)

    Returns:
        GhostSkill instance with status READY or NEEDS_CONFIGURATION

    Raises:
        ValueError: If required fields are missing or no matching orchestrator workflow exists
    """
    # Validate required fields
    required_fields = ["id", "name", "step_signatures", "ghost_score"]
    for field in required_fields:
        if field not in discovered_workflow:
            raise ValueError(f"Discovered workflow missing required field: {field}")

    source_workflow_id = str(discovered_workflow["id"])
    name = discovered_workflow["name"]
    step_signatures = discovered_workflow.get("step_signatures", [])
    ghost_score = discovered_workflow.get("ghost_score", 0)
    frequency = discovered_workflow.get("frequency", 0)

    # Map signatures to steps
    steps = map_signature_to_steps(step_signatures)

    # Resolve orchestrator workflow_id by matching name
    orchestrator_workflow_id = None
    if service:
        from services.supabase_service import get_service
        svc = service or get_service()
        workflows = svc.list_workflows()
        for wf in workflows:
            if wf.get("name", "").lower() == name.lower():
                orchestrator_workflow_id = wf.get("id")
                break

    if orchestrator_workflow_id is None:
        raise ValueError(f"No matching GhostWork workflow found for '{name}'")

    # Deterministically set autonomy boundary to the global approval limit
    autonomy_boundary = AutonomyBoundary(
        type="amount_threshold",
        threshold=float(Config.AUTO_APPROVAL_LIMIT),
        currency="INR",
        on_exceed="require_human_approval",
    )

    # Generate skill ID
    skill_id = str(uuid4())

    # Generate description: try Claude if available, else fallback
    description = _generate_description(name, frequency)

    # Determine overall skill status
    skill_status = "READY" if all(step.status == "MAPPED" for step in steps) else "NEEDS_CONFIGURATION"

    # Build trigger
    trigger = TriggerSpec(
        type="workflow_trigger",
        description=f"Trigger for {name} workflow",
    )

    # Build inputs (generic for refund workflows, can be customized)
    inputs = [
        SkillInput(name="ticket_id", type="id", required=True),
        SkillInput(name="refund_amount", type="number", required=True),
    ]

    # Assemble and validate
    skill = GhostSkill(
        skill_id=skill_id,
        name=name,
        version="1.0",
        description=description,
        source_workflow_id=source_workflow_id,
        ghost_score=ghost_score,
        trigger=trigger,
        inputs=inputs,
        steps=steps,
        autonomy_boundary=autonomy_boundary,
        approval_policy=ApprovalPolicy(
            required_when_exceeded=True,
            channel="web",
        ),
        verification=VerificationSpec(
            required=True,
            method="reread_and_compare",
        ),
        privacy=PrivacySpec(metadata_only=True),
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=skill_status,
    )

    # Store orchestrator workflow ID in skill for later lookup during execution
    # This is stored in the skill definition via a private field that won't be exposed
    skill.__dict__["_orchestrator_workflow_id"] = orchestrator_workflow_id

    return skill


def _generate_description(name: str, frequency: int) -> str:
    """
    Generate a human-readable skill description.

    Tries Claude if available, falls back to a deterministic template.
    """
    # Try Claude if configured
    if Config.ANTHROPIC_API_KEY:
        try:
            from services.claude_service import Anthropic, make_client

            if Anthropic is None:
                raise ImportError("Anthropic SDK not installed")

            client = make_client()
            # Room for adaptive thinking; the text itself is capped at 150 chars below.
            response = client.messages.create(
                model=Config.CLAUDE_MODEL,
                max_tokens=1000,
                messages=[
                    {
                        "role": "user",
                        "content": f"Write a one-line description of this workflow: {name} (repeated {frequency} times). Be concise.",
                    }
                ],
            )

            # Extract text from response
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    if text:
                        return text[:150]  # Limit to 150 chars
                    break
        except Exception as e:
            logger.debug(f"Claude description generation failed (expected fallback): {e}")

    # Fallback: deterministic template
    return f"Automates the {name} workflow, discovered from {frequency} repeated occurrences."


def validate_ghostskill(skill_dict: Dict[str, Any]) -> bool:
    """
    Validate a GhostSkill definition against the schema.

    Args:
        skill_dict: Dictionary representation of a GhostSkill

    Returns:
        True if valid, raises pydantic.ValidationError otherwise
    """
    GhostSkill(**skill_dict)
    return True
