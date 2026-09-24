"""Tests for the orchestrator and approval workflow."""

from decimal import Decimal

from orchestrator.workflow import run_execution
from services.supabase_service import get_service


class TestBasicExecution:
    """Test basic execution flow."""

    def test_10k_refund_no_approval_needed(self, app, client):
        """Low amount refund does not require approval."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("10000")
            )

            result = run_execution(exec_id)

            assert result["status"] == "COMPLETED"

            approvals = service.select("approvals", {"execution_id": exec_id})
            assert len(approvals) == 0

    def test_25k_refund_at_limit_no_approval(self, app, client):
        """Amount at limit does not require approval."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("25000")
            )

            result = run_execution(exec_id)

            assert result["status"] == "COMPLETED"

            approvals = service.select("approvals", {"execution_id": exec_id})
            assert len(approvals) == 0

    def test_25001_refund_requires_approval(self, app, client):
        """Amount above limit requires approval."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("25001")
            )

            result = run_execution(exec_id)

            assert result["status"] == "WAITING_FOR_APPROVAL"

            approvals = service.select("approvals", {"execution_id": exec_id})
            assert len(approvals) == 1
            assert approvals[0]["status"] == "PENDING"

    def test_32k_refund_requires_approval(self, app, client):
        """Demo amount above limit requires approval."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )

            result = run_execution(exec_id)

            assert result["status"] == "WAITING_FOR_APPROVAL"

            approvals = service.select("approvals", {"execution_id": exec_id})
            assert len(approvals) == 1
            assert approvals[0]["status"] == "PENDING"
            assert approvals[0]["amount"] == Decimal("32000")


class TestApprovalFlow:
    """Test approval and rejection flow."""

    def test_approve_32k_resumes_execution(self, app, client):
        """Approving paused execution resumes and completes."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            execution = service.get_execution(exec_id)
            assert execution["status"] == "WAITING_FOR_APPROVAL"

            approvals = service.select("approvals", {"execution_id": exec_id})
            approval_id = approvals[0]["id"]

            response = client.post(f"/api/approvals/{approval_id}/approve")
            assert response.status_code == 200

            execution = service.get_execution(exec_id)
            assert execution["status"] == "COMPLETED"

            approval = service.select_one("approvals", {"id": approval_id})
            assert approval["status"] == "APPROVED"

    def test_approve_doesnt_rerun_earlier_steps(self, app, client):
        """Approval resume does not re-run earlier steps."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            steps_before = service.get_execution_steps(exec_id)
            context_steps_before = [s for s in steps_before if s.get("step_name") == "context_agent"]

            approval = service.select_one("approvals", {"execution_id": exec_id})
            client.post(f"/api/approvals/{approval['id']}/approve")

            steps_after = service.get_execution_steps(exec_id)
            context_steps_after = [s for s in steps_after if s.get("step_name") == "context_agent"]
            assert len(context_steps_after) == len(context_steps_before)

    def test_reject_execution(self, app, client):
        """Rejecting paused execution marks it as REJECTED."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            approval = service.select_one("approvals", {"execution_id": exec_id})
            approval_id = approval["id"]

            response = client.post(f"/api/approvals/{approval_id}/reject")
            assert response.status_code == 200

            execution = service.get_execution(exec_id)
            assert execution["status"] == "REJECTED"

            approval = service.select_one("approvals", {"id": approval_id})
            assert approval["status"] == "REJECTED"

    def test_already_decided_approval(self, app, client):
        """Attempting to approve again returns 409 Conflict."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            approval = service.select_one("approvals", {"execution_id": exec_id})
            approval_id = approval["id"]

            response1 = client.post(f"/api/approvals/{approval_id}/approve")
            assert response1.status_code == 200

            response2 = client.post(f"/api/approvals/{approval_id}/approve")
            assert response2.status_code == 409
            json_data = response2.get_json()
            assert json_data["error"]["code"] == "ALREADY_DECIDED"

    def test_concurrent_approves_only_one_succeeds(self, app, client):
        """Two concurrent approves: one succeeds (200), one fails (409)."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            approval = service.select_one("approvals", {"execution_id": exec_id})
            approval_id = approval["id"]

            response1 = client.post(f"/api/approvals/{approval_id}/approve")
            response2 = client.post(f"/api/approvals/{approval_id}/approve")

            statuses = sorted([response1.status_code, response2.status_code])
            assert statuses == [200, 409]

            execution = service.get_execution(exec_id)
            assert execution["status"] == "COMPLETED"


class TestFailureHandling:
    """Test failure scenarios."""

    def test_missing_refund_amount_fails_closed(self, app, client):
        """Missing refund_amount requires approval."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=None
            )

            result = run_execution(exec_id)

            assert result["status"] == "WAITING_FOR_APPROVAL"

            approvals = service.select("approvals", {"execution_id": exec_id})
            assert len(approvals) == 1

    def test_invalid_refund_amount_fails_closed(self, app, client):
        """Invalid refund_amount requires approval."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount="invalid"
            )

            result = run_execution(exec_id)

            assert result["status"] == "WAITING_FOR_APPROVAL"

            approvals = service.select("approvals", {"execution_id": exec_id})
            assert len(approvals) == 1


class TestExecutionSteps:
    """Test execution step tracking."""

    def test_completion_has_all_steps(self, app, client):
        """Completed execution has all 7 steps."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("10000")
            )
            run_execution(exec_id)

            steps = service.get_execution_steps(exec_id)
            step_names = [s["step_name"] for s in steps]

            expected = [
                "context_agent",
                "billing_agent",
                "policy_agent",
                "risk_agent",
                "approval_gate",
                "communication_agent",
                "verification_agent"
            ]
            assert step_names == expected

    def test_paused_has_up_to_approval_gate(self, app, client):
        """Paused execution has steps up to approval_gate."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            steps = service.get_execution_steps(exec_id)
            step_names = [s["step_name"] for s in steps]

            expected = [
                "context_agent",
                "billing_agent",
                "policy_agent",
                "risk_agent",
                "approval_gate"
            ]
            assert step_names == expected

            for step in steps:
                assert step["status"] == "SUCCESS"

class TestApprovalGateMessages:
    """Test approval_gate output messages are semantically correct."""

    def test_no_approval_required_message(self, app, client):
        """When approval not required, message is clear."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("10000")
            )
            run_execution(exec_id)

            steps = service.get_execution_steps(exec_id)
            approval_gate_step = [s for s in steps if s["step_name"] == "approval_gate"][0]

            assert approval_gate_step["output_json"]["reason"] == "Approval not required"

    def test_approval_granted_completes_execution(self, app, client):
        """After approval is granted, execution completes with all remaining steps."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            # Should be paused at approval_gate
            exec_paused = service.get_execution(exec_id)
            assert exec_paused["status"] == "WAITING_FOR_APPROVAL"

            # Approve it
            approval = service.select_one("approvals", {"execution_id": exec_id})
            client.post(f"/api/approvals/{approval['id']}/approve")

            # Check final execution is completed
            exec_final = service.get_execution(exec_id)
            assert exec_final["status"] == "COMPLETED"

            # Check all steps including communication and verification were executed
            steps = service.get_execution_steps(exec_id)
            step_names = [s["step_name"] for s in steps]
            assert "communication_agent" in step_names
            assert "verification_agent" in step_names


class TestApprovalGateStepUpdate:
    """Test that approval_gate step output is updated when approval is granted."""

    def test_approval_gate_output_updated_after_approval(self, app, client):
        """Approval_gate step output is updated to reflect approval decision."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            # Check initial approval_gate output (waiting)
            steps_before = service.get_execution_steps(exec_id)
            approval_gate_before = [s for s in steps_before if s["step_name"] == "approval_gate"][0]
            approval_gate_id = approval_gate_before["id"]

            assert approval_gate_before["output_json"]["reason"] == "Awaiting human approval"
            assert approval_gate_before["attempt"] == 1

            # Approve it
            approval = service.select_one("approvals", {"execution_id": exec_id})
            client.post(f"/api/approvals/{approval['id']}/approve")

            # Check that approval_gate step was UPDATED, not duplicated
            steps_after = service.get_execution_steps(exec_id)
            approval_gate_after = [s for s in steps_after if s["step_name"] == "approval_gate"]

            # Should still have exactly one approval_gate step (same one, updated)
            assert len(approval_gate_after) == 1
            assert approval_gate_after[0]["id"] == approval_gate_id
            assert approval_gate_after[0]["attempt"] == 1

            # Output should now reflect the approval
            assert approval_gate_after[0]["output_json"]["reason"] == "Approval granted by human"

    def test_no_duplicate_approval_gate_steps(self, app, client):
        """Approval_gate step is not duplicated on approval; same step is updated."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            # Count approval_gate steps before approval
            steps_before = service.get_execution_steps(exec_id)
            count_before = len([s for s in steps_before if s["step_name"] == "approval_gate"])
            assert count_before == 1

            # Approve it
            approval = service.select_one("approvals", {"execution_id": exec_id})
            client.post(f"/api/approvals/{approval['id']}/approve")

            # Count approval_gate steps after approval (should still be 1)
            steps_after = service.get_execution_steps(exec_id)
            count_after = len([s for s in steps_after if s["step_name"] == "approval_gate"])
            assert count_after == 1


class TestCurrentStepTracking:
    """Test that current_step accurately reflects execution progress."""

    def test_current_step_after_completion(self, app, client):
        """After successful completion, current_step should be the last executed step."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("10000")  # No approval needed
            )

            result = run_execution(exec_id)

            assert result["status"] == "COMPLETED"
            # current_step should be set to the last step
            assert result.get("current_step") == "verification_agent"

    def test_current_step_at_approval_pause(self, app, client):
        """While WAITING_FOR_APPROVAL, current_step should be approval_gate."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")  # Requires approval
            )

            result = run_execution(exec_id)

            assert result["status"] == "WAITING_FOR_APPROVAL"
            # When paused at approval_gate, current_step should be set to it
            assert result.get("current_step") == "approval_gate"

    def test_current_step_after_approval_resume(self, app, client):
        """After approval and resume, current_step should be verification_agent (final step)."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("32000")
            )
            run_execution(exec_id)

            # Approve the execution
            approval = service.select_one("approvals", {"execution_id": exec_id})
            client.post(f"/api/approvals/{approval['id']}/approve")

            # After resume and completion, current_step should be the last step
            result = service.get_execution(exec_id)
            assert result["status"] == "COMPLETED"
            assert result.get("current_step") == "verification_agent"

    def test_current_step_null_initially(self, app, client):
        """Initially created execution has current_step null/missing."""
        with app.app_context():
            service = get_service()

            exec_id = service.create_execution(
                workflow_id=1,
                ticket_id=2048,
                refund_amount=Decimal("10000")
            )

            # Check that current_step is not set initially (or is None)
            exec_initial = service.get_execution(exec_id)
            assert exec_initial.get("current_step") is None

            # After execution
            run_execution(exec_id)
            result = service.get_execution(exec_id)
            assert result["status"] == "COMPLETED"
            assert result.get("current_step") == "verification_agent"
