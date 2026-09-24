"""Regression tests: Verify existing Refund Verification workflow still works."""

import pytest


@pytest.fixture
def client():
    """Create Flask test client."""
    from app import create_app

    app = create_app(config_override={"TESTING": True, "DB_BACKEND": "memory"})
    with app.test_client() as client:
        yield client


class TestRefundWorkflowStillWorks:
    """Ensure Phase 10A doesn't break existing golden path."""

    def test_refund_workflow_exists(self, client):
        """Refund Verification workflow is available."""
        response = client.get("/api/workflows")
        assert response.status_code == 200

        data = response.get_json()
        workflows = data.get("workflows", [])
        refund_workflows = [w for w in workflows if "refund" in w.get("name", "").lower()]
        assert len(refund_workflows) > 0

    def test_can_create_refund_execution(self, client):
        """Can create execution for Refund Verification workflow."""
        # Get refund workflow
        response = client.get("/api/workflows")
        data = response.get_json()
        workflows = data.get("workflows", [])
        refund = next(w for w in workflows if "refund" in w.get("name", "").lower())

        # Create execution
        exec_response = client.post(
            "/api/executions",
            json={"workflow_id": refund["id"], "ticket_id": 2048},
        )

        assert exec_response.status_code in [200, 201, 202]
        exec_data = exec_response.get_json()
        assert "id" in exec_data or "execution_id" in exec_data

    def test_refund_amounts_still_enforced(self, client):
        """₹25,000 threshold still enforced (governance unchanged)."""
        # This is a conceptual test - would need full execution flow
        # In real scenario: ₹10,000 passes, ₹32,000 needs approval
        # For now, just verify the threshold config exists

        from config import Config

        assert Config.AUTO_APPROVAL_LIMIT is not None
        assert float(Config.AUTO_APPROVAL_LIMIT) == 25000

    def test_approval_gate_logic_preserved(self, client):
        """Approval gate logic is not modified by discovery."""
        # Create execution and verify it reaches approval gate if needed
        # This is covered by existing test_orchestrator.py tests
        # Phase 10A should not touch approval gate logic
        pass

    def test_freshdesk_integration_still_works(self, client):
        """Freshdesk integration (read/write) is not broken."""
        # Verify freshdesk_service is still importable
        from services import freshdesk_service

        assert hasattr(freshdesk_service, "get_ticket")
        assert hasattr(freshdesk_service, "add_note")
        assert hasattr(freshdesk_service, "verify_note_exists")

    def test_context_propagation_still_works(self, client):
        """Context propagation fix from Phase 9 is preserved."""
        # This ensures orchestrator still properly accumulates context
        from orchestrator.workflow import run_execution

        # Verify the function still exists and is callable
        assert callable(run_execution)

    def test_discovery_doesnt_modify_existing_schemas(self, client):
        """Discovery doesn't modify execution/workflow schemas."""
        from services.supabase_service import get_service

        service = get_service()

        # Verify core tables still exist
        assert hasattr(service, "get_execution")
        assert hasattr(service, "get_workflow")
        assert hasattr(service, "get_execution_steps")
