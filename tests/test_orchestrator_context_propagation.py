"""Regression tests for orchestrator context propagation (Phase 9 integration fix)."""

from unittest.mock import MagicMock, patch


class TestOrchestratorContextPropagation:
    """Test that orchestrator properly propagates step results through context."""

    def test_communication_result_reaches_verification_agent(self):
        """Verify communication_agent result is propagated to verification_agent."""
        from orchestrator.workflow import run_execution

        # Mock service
        mock_service = MagicMock()

        # Mock execution
        execution = {
            "id": 1,
            "status": "APPROVED",
            "workflow_id": 1,
            "ticket_id": 2048,
            "source": "freshdesk"
        }

        mock_service.get_execution.return_value = execution
        mock_service.get_workflow.return_value = {"id": 1, "name": "refund"}
        mock_service.get_execution_steps.return_value = []

        # Mock workflow steps
        steps = [
            {"step_order": 1, "name": "communication_agent", "agent": "communication_agent"},
            {"step_order": 2, "name": "verification_agent", "agent": "verification_agent"}
        ]
        mock_service.select.return_value = steps

        # Mock step creation
        mock_service.create_execution_step.side_effect = [100, 101]
        mock_service.update_execution_step.return_value = None

        # Mock agents
        comm_result = {
            "status": "SUCCESS",
            "result": {
                "action_performed": False,
                "writeback_status": "skipped",
                "source": "fallback"
            }
        }

        verify_result = {
            "status": "SUCCESS",
            "result": {
                "verified": False,
                "verification_status": "skipped_fallback"
            }
        }

        captured_contexts = []

        def mock_communication_agent_run(execution, context=None):
            captured_contexts.append(("communication_agent", context))
            return comm_result

        def mock_verification_agent_run(execution, context=None):
            captured_contexts.append(("verification_agent", context))
            return verify_result

        with patch("orchestrator.workflow.get_service") as mock_get_service:
            with patch("orchestrator.workflow._import_agent") as mock_import:
                with patch("orchestrator.workflow.transition"):
                    mock_get_service.return_value = mock_service

                    def import_side_effect(agent_name):
                        if agent_name == "communication_agent":
                            module = MagicMock()
                            module.run = mock_communication_agent_run
                            return module
                        elif agent_name == "verification_agent":
                            module = MagicMock()
                            module.run = mock_verification_agent_run
                            return module

                    mock_import.side_effect = import_side_effect

                    # Run the orchestrator
                    run_execution(1)

                    # Verify both agents were called
                    assert len(captured_contexts) == 2

                    # Verify communication_agent received initial context
                    comm_agent_name, comm_context = captured_contexts[0]
                    assert comm_agent_name == "communication_agent"
                    assert "execution_id" in comm_context

                    # Verify verification_agent received accumulated context
                    verify_agent_name, verify_context = captured_contexts[1]
                    assert verify_agent_name == "verification_agent"

                    # Critical: verification_agent must see communication_agent result
                    assert "communication_agent" in verify_context
                    assert verify_context["communication_agent"]["status"] == "SUCCESS"
                    assert verify_context["communication_agent"]["result"]["action_performed"] is False
                    assert verify_context["communication_agent"]["result"]["source"] == "fallback"

    def test_freshdesk_communication_result_reaches_verification(self):
        """Verify Freshdesk write-back result is propagated through context."""
        from orchestrator.workflow import run_execution

        # Mock service
        mock_service = MagicMock()

        execution = {
            "id": 1,
            "status": "APPROVED",
            "workflow_id": 1,
            "ticket_id": 2048,
            "source": "freshdesk"
        }

        mock_service.get_execution.return_value = execution
        mock_service.get_workflow.return_value = {"id": 1}
        mock_service.get_execution_steps.return_value = []
        mock_service.select.return_value = [
            {"step_order": 1, "name": "communication_agent", "agent": "communication_agent"},
            {"step_order": 2, "name": "verification_agent", "agent": "verification_agent"}
        ]
        mock_service.create_execution_step.side_effect = [100, 101]

        # Communication agent with real Freshdesk write
        comm_result = {
            "status": "SUCCESS",
            "result": {
                "action_performed": True,
                "ticket_id": 2048,
                "note_id": 12345,
                "external_reference": "freshdesk-note-12345",
                "source": "freshdesk",
                "writeback_status": "success"
            }
        }

        captured_contexts = []

        def mock_communication_agent_run(execution, context=None):
            captured_contexts.append(("communication_agent", context))
            return comm_result

        def mock_verification_agent_run(execution, context=None):
            captured_contexts.append(("verification_agent", context))
            return {
                "status": "SUCCESS",
                "result": {"verified": True, "verification_status": "verified"}
            }

        with patch("orchestrator.workflow.get_service") as mock_get_service:
            with patch("orchestrator.workflow._import_agent") as mock_import:
                with patch("orchestrator.workflow.transition"):
                    mock_get_service.return_value = mock_service

                    def import_side_effect(agent_name):
                        if agent_name == "communication_agent":
                            module = MagicMock()
                            module.run = mock_communication_agent_run
                            return module
                        elif agent_name == "verification_agent":
                            module = MagicMock()
                            module.run = mock_verification_agent_run
                            return module

                    mock_import.side_effect = import_side_effect

                    # Run orchestrator
                    run_execution(1)

                    # Verify verification_agent sees full communication result
                    verify_agent_name, verify_context = captured_contexts[1]
                    assert verify_agent_name == "verification_agent"

                    # Critical: All Freshdesk write-back details must propagate
                    assert "communication_agent" in verify_context
                    comm_data = verify_context["communication_agent"]["result"]
                    assert comm_data["action_performed"] is True
                    assert comm_data["ticket_id"] == 2048
                    assert comm_data["note_id"] == 12345
                    assert comm_data["external_reference"] == "freshdesk-note-12345"
                    assert comm_data["source"] == "freshdesk"

    def test_context_accumulates_across_all_steps(self):
        """Verify context accumulates step results as we progress."""
        from orchestrator.workflow import run_execution

        # Mock service
        mock_service = MagicMock()

        execution = {
            "id": 1,
            "status": "PENDING",
            "workflow_id": 1,
            "ticket_id": 2048
        }

        mock_service.get_execution.return_value = execution
        mock_service.get_workflow.return_value = {"id": 1}
        mock_service.get_execution_steps.return_value = []
        mock_service.select.return_value = [
            {"step_order": 1, "name": "step1", "agent": "context_agent"},
            {"step_order": 2, "name": "step2", "agent": "billing_agent"},
            {"step_order": 3, "name": "step3", "agent": "verification_agent"}
        ]
        mock_service.create_execution_step.side_effect = [100, 101, 102]

        captured_contexts = {}

        def make_agent_run(step_name):
            def run(execution, context=None):
                captured_contexts[step_name] = context or {}
                return {"status": "SUCCESS", "result": {f"{step_name}_data": "value"}}

            return run

        with patch("orchestrator.workflow.get_service") as mock_get_service:
            with patch("orchestrator.workflow._import_agent") as mock_import:
                with patch("orchestrator.workflow.transition"):
                    mock_get_service.return_value = mock_service

                    def import_side_effect(agent_name):
                        if agent_name == "context_agent":
                            module = MagicMock()
                            module.run = make_agent_run("step1")
                            return module
                        elif agent_name == "billing_agent":
                            module = MagicMock()
                            module.run = make_agent_run("step2")
                            return module
                        elif agent_name == "verification_agent":
                            module = MagicMock()
                            module.run = make_agent_run("step3")
                            return module

                    mock_import.side_effect = import_side_effect

                    # Run orchestrator
                    run_execution(1)

                    # Verify context accumulates - each step sees previous step results
                    # step1 gets base context
                    assert "execution_id" in captured_contexts["step1"]

                    # step2 sees step1's result
                    assert "execution_id" in captured_contexts["step2"]
                    assert "step1" in captured_contexts["step2"]
                    assert captured_contexts["step2"]["step1"]["result"]["step1_data"] == "value"

                    # step3 sees both step1 and step2
                    assert "execution_id" in captured_contexts["step3"]
                    assert "step1" in captured_contexts["step3"]
                    assert "step2" in captured_contexts["step3"]
                    assert captured_contexts["step3"]["step1"]["result"]["step1_data"] == "value"
                    assert captured_contexts["step3"]["step2"]["result"]["step2_data"] == "value"
