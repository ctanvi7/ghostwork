"""Workflow execution orchestrator."""

import logging
from typing import Any, Dict

from orchestrator.state import transition
from services.supabase_service import get_service

logger = logging.getLogger(__name__)


def run_execution(execution_id: int) -> Dict[str, Any]:
    """
    Execute a workflow synchronously (for testing).

    Assumes PENDING or APPROVED state and claims the run with CAS.
    Executes steps in order, resuming after the last successful step.
    Returns the final execution record.
    """
    service = get_service()
    execution = service.get_execution(execution_id)

    if not execution:
        logger.error(f"Execution {execution_id} not found")
        return {}

    workflow_id = execution.get("workflow_id")
    if not workflow_id:
        logger.error(f"Execution {execution_id} has no workflow_id")
        return {}

    workflow = service.get_workflow(workflow_id)
    if not workflow:
        logger.error(f"Workflow {workflow_id} not found")
        return {}

    current_status = execution.get("status")

    # Claim the execution with CAS: PENDING -> RUNNING or APPROVED -> RUNNING
    try:
        if current_status == "PENDING":
            transition(execution_id, "PENDING", "RUNNING")
        elif current_status == "APPROVED":
            # Resume from APPROVED (after approval was granted)
            transition(execution_id, "APPROVED", "RUNNING")
        else:
            logger.warning(f"Execution {execution_id} is in {current_status}, cannot run")
            return service.get_execution(execution_id)
    except Exception as e:
        logger.warning(f"Failed to claim execution {execution_id}: {e}")
        # CAS failed (another process is running it), return current state
        return service.get_execution(execution_id)

    # Get workflow steps in order
    all_steps = service.select("workflow_steps", {"workflow_id": workflow_id})
    all_steps.sort(key=lambda s: s.get("step_order", 0))

    # Find the last successful step
    execution_steps = service.get_execution_steps(execution_id)
    last_success = None
    if execution_steps:
        successful = [s for s in execution_steps if s.get("status") == "SUCCESS"]
        if successful:
            last_success = max(successful, key=lambda s: s.get("step_order", 0))

    # Resume after the last successful step
    resume_order = last_success.get("step_order", 0) if last_success else 0
    remaining_steps = [s for s in all_steps if s.get("step_order", 0) > resume_order]

    logger.info(f"Execution {execution_id}: resuming from step {resume_order}, {len(remaining_steps)} steps remain")

    # Track last executed step for current_step field
    last_executed_step = None

    # Build context that accumulates results from previous steps
    step_context = {"execution_id": execution_id}

    # Look up associated GhostSkill and seed approval limit
    skill = service.get_ghost_skill_for_workflow(workflow_id)
    if skill:
        definition = skill.get("definition_json", {})
        # New schema (autonomy_boundary) takes precedence; fall back to legacy seed shape (approval_rule)
        threshold = (
            definition.get("autonomy_boundary", {}).get("threshold")
            if definition.get("autonomy_boundary")
            else definition.get("approval_rule", {}).get("value")
        )
        if threshold is not None:
            step_context["skill_approval_limit"] = threshold
            logger.info(f"Execution {execution_id}: using skill approval limit {threshold}")

    # Execute remaining steps
    for step_def in remaining_steps:
        step_name = step_def.get("name")
        agent_name = step_def.get("agent")
        step_order = step_def.get("step_order")

        logger.info(f"Execution {execution_id}: executing step {step_order} ({step_name})")

        # Create execution_step record
        step_id = service.create_execution_step(
            execution_id=execution_id,
            step_name=step_name,
            agent=agent_name,
            status="RUNNING",
            step_order=step_order
        )

        try:
            # Import and run the agent, passing accumulated context from previous steps
            agent_module = _import_agent(agent_name)
            result = agent_module.run(execution, context=step_context)

            status = result.get("status", "SUCCESS")
            output = result.get("result", {})

            # Update the step - convert PAUSE to SUCCESS for internal tracking
            step_status = "SUCCESS" if status in ("SUCCESS", "PAUSE") else status
            service.update_execution_step(
                step_id,
                status=step_status,
                output_json=output
            )

            logger.info(f"Execution {execution_id}: step {step_name} returned {status}")

            # Track last executed step
            last_executed_step = step_name

            # Add this step's result to context for subsequent steps
            step_context[step_name] = {"status": status, "result": output}

            if status == "PAUSE":
                # approval_gate returned PAUSE: transition to WAITING_FOR_APPROVAL and stop
                transition(execution_id, "RUNNING", "WAITING_FOR_APPROVAL", current_step=step_name)

                # Create an approval record if needed
                amount = execution.get("refund_amount")
                existing = service.get_open_approval(execution_id)
                if not existing:
                    service.create_approval(execution_id, amount=amount)

                logger.info(f"Execution {execution_id}: paused at {step_name} for approval")
                return service.get_execution(execution_id)
            elif status == "SUCCESS":
                # Continue to next step
                continue
            elif status == "FAILED":
                # Transition to FAILED and stop, update current_step to reflect the failed step
                error_msg = output.get("error", "Step failed")
                transition(execution_id, "RUNNING", "FAILED", error_message=error_msg, current_step=step_name)
                logger.error(f"Execution {execution_id}: step {step_name} failed: {error_msg}")
                return service.get_execution(execution_id)
        except Exception as e:
            # Unexpected error: fail safely
            error_msg = str(e)
            try:
                service.update_execution_step(step_id, status="FAILED")
                transition(execution_id, "RUNNING", "FAILED", error_message=error_msg, current_step=last_executed_step or step_name)
            except Exception as te:
                logger.error(f"Failed to mark execution as FAILED: {te}")
            logger.error(f"Execution {execution_id}: unexpected error in step {step_name}: {e}")
            return service.get_execution(execution_id)

    # All steps succeeded: transition to COMPLETED with last executed step
    try:
        transition(execution_id, "RUNNING", "COMPLETED", current_step=last_executed_step)
        logger.info(f"Execution {execution_id}: completed successfully")
    except Exception as e:
        logger.error(f"Failed to mark execution as completed: {e}")

    return service.get_execution(execution_id)


def _import_agent(agent_name: str):
    """Dynamically import an agent module."""
    if agent_name == "risk_agent":
        from agents import risk_agent
        return risk_agent
    elif agent_name == "approval_gate":
        from agents import approval_gate
        return approval_gate
    elif agent_name == "context_agent":
        from agents import context_agent
        return context_agent
    elif agent_name == "billing_agent":
        from agents import billing_agent
        return billing_agent
    elif agent_name == "policy_agent":
        from agents import policy_agent
        return policy_agent
    elif agent_name == "communication_agent":
        from agents import communication_agent
        return communication_agent
    elif agent_name == "verification_agent":
        from agents import verification_agent
        return verification_agent
    else:
        raise ValueError(f"Unknown agent: {agent_name}")
