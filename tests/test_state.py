"""Tests for state machine and transitions."""

import pytest

from app import InvalidStateError
from orchestrator.state import (
    ALLOWED_TRANSITIONS,
    is_terminal,
    transition,
    validate_transition,
)
from services.supabase_service import get_service


class TestStateTransitions:
    """Test state machine transitions."""

    def test_allowed_transitions_defined(self):
        """ALLOWED_TRANSITIONS dict has all expected states."""
        expected_states = {
            "PENDING",
            "RUNNING",
            "WAITING_FOR_APPROVAL",
            "APPROVED",
            "REJECTED",
            "COMPLETED",
            "FAILED",
        }
        assert set(ALLOWED_TRANSITIONS.keys()) == expected_states

    def test_pending_to_running(self):
        """PENDING can transition to RUNNING."""
        assert validate_transition("PENDING", "RUNNING")

    def test_pending_to_failed(self):
        """PENDING can transition to FAILED."""
        assert validate_transition("PENDING", "FAILED")

    def test_running_to_waiting_for_approval(self):
        """RUNNING can transition to WAITING_FOR_APPROVAL."""
        assert validate_transition("RUNNING", "WAITING_FOR_APPROVAL")

    def test_running_to_completed(self):
        """RUNNING can transition to COMPLETED."""
        assert validate_transition("RUNNING", "COMPLETED")

    def test_waiting_for_approval_to_approved(self):
        """WAITING_FOR_APPROVAL can transition to APPROVED."""
        assert validate_transition("WAITING_FOR_APPROVAL", "APPROVED")

    def test_waiting_for_approval_to_rejected(self):
        """WAITING_FOR_APPROVAL can transition to REJECTED."""
        assert validate_transition("WAITING_FOR_APPROVAL", "REJECTED")

    def test_approved_to_running(self):
        """APPROVED can transition back to RUNNING."""
        assert validate_transition("APPROVED", "RUNNING")

    def test_rejected_is_terminal(self):
        """REJECTED has no outgoing transitions."""
        assert len(ALLOWED_TRANSITIONS["REJECTED"]) == 0
        assert not validate_transition("REJECTED", "RUNNING")
        assert not validate_transition("REJECTED", "COMPLETED")

    def test_completed_is_terminal(self):
        """COMPLETED has no outgoing transitions."""
        assert len(ALLOWED_TRANSITIONS["COMPLETED"]) == 0

    def test_failed_is_terminal(self):
        """FAILED has no outgoing transitions."""
        assert len(ALLOWED_TRANSITIONS["FAILED"]) == 0

    def test_invalid_transition_pending_to_approved(self):
        """PENDING cannot directly transition to APPROVED."""
        assert not validate_transition("PENDING", "APPROVED")

    def test_invalid_transition_running_to_rejected(self):
        """RUNNING cannot directly transition to REJECTED."""
        assert not validate_transition("RUNNING", "REJECTED")

    def test_is_terminal_rejected(self):
        """is_terminal returns True for REJECTED."""
        assert is_terminal("REJECTED")

    def test_is_terminal_completed(self):
        """is_terminal returns True for COMPLETED."""
        assert is_terminal("COMPLETED")

    def test_is_terminal_failed(self):
        """is_terminal returns True for FAILED."""
        assert is_terminal("FAILED")

    def test_is_terminal_pending(self):
        """is_terminal returns False for PENDING."""
        assert not is_terminal("PENDING")

    def test_is_terminal_running(self):
        """is_terminal returns False for RUNNING."""
        assert not is_terminal("RUNNING")


class TestTransitionFunction:
    """Test the transition() function with database."""

    def test_transition_pending_to_running(self):
        """Transition PENDING -> RUNNING succeeds."""
        service = get_service()
        service.clear_all()

        # Create execution in PENDING state
        exec_id = service.create_execution(workflow_id=1, ticket_id=2048)

        # Transition to RUNNING
        count = transition(exec_id, "PENDING", "RUNNING")
        assert count == 1

        # Verify status changed
        exec_row = service.get_execution(exec_id)
        assert exec_row["status"] == "RUNNING"

    def test_transition_invalid_raises_error(self):
        """Invalid transition raises InvalidStateError."""
        service = get_service()
        service.clear_all()

        # Create execution in PENDING state
        exec_id = service.create_execution(workflow_id=1)

        # Try invalid transition PENDING -> APPROVED
        with pytest.raises(InvalidStateError):
            transition(exec_id, "PENDING", "APPROVED")

    def test_transition_cas_failure_raises_error(self):
        """CAS failure (wrong from_status) raises InvalidStateError."""
        service = get_service()
        service.clear_all()

        # Create execution in PENDING state
        exec_id = service.create_execution(workflow_id=1)

        # Try to transition from RUNNING (but it's in PENDING)
        with pytest.raises(InvalidStateError):
            transition(exec_id, "RUNNING", "COMPLETED")

    def test_transition_with_extra_fields(self):
        """Transition can include extra fields like current_step."""
        service = get_service()
        service.clear_all()

        exec_id = service.create_execution(workflow_id=1)

        # Transition with extra fields
        count = transition(
            exec_id, "PENDING", "RUNNING", current_step="context_agent"
        )
        assert count == 1

        # Verify extra fields were set
        exec_row = service.get_execution(exec_id)
        assert exec_row["current_step"] == "context_agent"

    def test_transition_terminal_states_cannot_transition(self):
        """Terminal states reject transitions."""
        service = get_service()
        service.clear_all()

        exec_id = service.create_execution(workflow_id=1)

        # Move to COMPLETED (terminal)
        service.update_execution(exec_id, status="COMPLETED")

        # Try to transition from COMPLETED
        with pytest.raises(InvalidStateError):
            transition(exec_id, "COMPLETED", "RUNNING")

    def test_concurrent_transition_one_wins(self):
        """When two transitions race, only one succeeds."""
        service = get_service()
        service.clear_all()

        exec_id = service.create_execution(workflow_id=1)

        # First transition succeeds
        count1 = transition(exec_id, "PENDING", "RUNNING")
        assert count1 == 1

        # Second transition from PENDING fails (status is now RUNNING)
        with pytest.raises(InvalidStateError):
            transition(exec_id, "PENDING", "FAILED")

    def test_multiple_step_transitions(self):
        """Test a realistic sequence of transitions."""
        service = get_service()
        service.clear_all()

        exec_id = service.create_execution(workflow_id=1)

        # PENDING -> RUNNING
        transition(exec_id, "PENDING", "RUNNING")
        assert service.get_execution(exec_id)["status"] == "RUNNING"

        # RUNNING -> WAITING_FOR_APPROVAL
        transition(exec_id, "RUNNING", "WAITING_FOR_APPROVAL")
        assert service.get_execution(exec_id)["status"] == "WAITING_FOR_APPROVAL"

        # WAITING_FOR_APPROVAL -> APPROVED
        transition(exec_id, "WAITING_FOR_APPROVAL", "APPROVED")
        assert service.get_execution(exec_id)["status"] == "APPROVED"

        # APPROVED -> RUNNING
        transition(exec_id, "APPROVED", "RUNNING")
        assert service.get_execution(exec_id)["status"] == "RUNNING"

        # RUNNING -> COMPLETED
        transition(exec_id, "RUNNING", "COMPLETED")
        assert service.get_execution(exec_id)["status"] == "COMPLETED"
