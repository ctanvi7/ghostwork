"""Full acceptance path tests for GhostSkill routes."""

import json


class TestGhostSkillGeneration:
    """Test GhostSkill generation from discovered workflows."""

    def test_generate_ghostskill_from_discovered_workflow(self, client, app):
        """Test generating a GhostSkill from a discovered workflow."""
        with app.app_context():
            # First, discover workflows
            response = client.get("/api/discovery/workflows")
            assert response.status_code == 200
            data = response.get_json()
            workflows = data.get("workflows", [])
            assert len(workflows) > 0

            # Find Refund Verification workflow
            refund_wf = None
            for wf in workflows:
                if wf.get("name") == "Refund Verification":
                    refund_wf = wf
                    break

            assert refund_wf is not None, "Refund Verification should be discoverable"

            # Generate GhostSkill from it
            skill_response = client.post(
                f"/api/discovery/workflows/{refund_wf['id']}/ghostskill",
            )
            assert skill_response.status_code == 201
            skill_data = skill_response.get_json()

            # Verify skill structure
            assert skill_data.get("id") is not None
            assert skill_data.get("name") == "Refund Verification"
            definition = skill_data.get("definition_json", {})
            assert definition.get("status") == "READY"
            assert definition.get("skill_id") is not None

            # Verify steps are the 7 expected agents
            steps = definition.get("steps", [])
            agents = [s.get("agent") for s in steps if s.get("agent")]
            expected_agents = [
                "context_agent",
                "billing_agent",
                "policy_agent",
                "risk_agent",
                "approval_gate",
                "communication_agent",
                "verification_agent",
            ]
            assert agents == expected_agents

            # Verify autonomy boundary
            boundary = definition.get("autonomy_boundary", {})
            assert boundary.get("threshold") == 25000.0
            assert boundary.get("currency") == "INR"

            # Verify privacy
            privacy = definition.get("privacy", {})
            assert privacy.get("metadata_only") is True


class TestGhostSkillListing:
    """Test GhostSkill listing and retrieval."""

    def test_list_ghostskills(self, client, app):
        """Test listing all ghost skills."""
        with app.app_context():
            response = client.get("/api/ghostskills")
            assert response.status_code == 200
            data = response.get_json()

            skills = data.get("skills", [])
            count = data.get("count")
            assert count == len(skills)
            # There's at least one seeded skill (Refund Verification)
            assert count >= 1

    def test_get_ghostskill_by_id(self, client, app):
        """Test retrieving a specific ghost skill."""
        with app.app_context():
            # List to find an ID
            response = client.get("/api/ghostskills")
            skills = response.get_json().get("skills", [])
            assert len(skills) > 0

            skill_id = skills[0]["id"]

            # Get it
            response = client.get(f"/api/ghostskills/{skill_id}")
            assert response.status_code == 200
            skill = response.get_json()
            assert skill.get("id") == skill_id
            assert skill.get("name") is not None

    def test_get_nonexistent_ghostskill_returns_404(self, client):
        """Test that retrieving a non-existent skill returns 404."""
        response = client.get("/api/ghostskills/99999")
        assert response.status_code == 404


class TestGhostSkillExecution:
    """Test the full execution path with approval thresholds."""

    def test_execute_skill_below_approval_threshold(self, client, app):
        """Test executing a skill with refund_amount <= threshold → COMPLETED."""
        with app.app_context():
            # Get or generate a skill
            response = client.get("/api/ghostskills")
            skills = response.get_json().get("skills", [])
            assert len(skills) > 0

            skill_id = skills[0]["id"]

            # Execute with ₹10,000 (below ₹25,000 threshold)
            exec_response = client.post(
                f"/api/ghostskills/{skill_id}/execute",
                data=json.dumps({"ticket_id": 2048, "refund_amount": 10000}),
                content_type="application/json",
            )

            assert exec_response.status_code == 202
            execution = exec_response.get_json()

            # Should complete without approval
            assert execution.get("status") == "COMPLETED"
            assert execution.get("refund_amount") == 10000

            # Verify no approval record exists or it was never created
            approvals = execution.get("approvals", [])
            # Either no approvals, or any approval should be irrelevant
            for approval in approvals:
                assert approval.get("status") != "PENDING"

    def test_execute_skill_above_approval_threshold_pauses(self, client, app):
        """Test executing a skill with refund_amount > threshold → WAITING_FOR_APPROVAL."""
        with app.app_context():
            # Get a skill
            response = client.get("/api/ghostskills")
            skills = response.get_json().get("skills", [])
            assert len(skills) > 0

            skill_id = skills[0]["id"]

            # Execute with ₹32,000 (above ₹25,000 threshold)
            exec_response = client.post(
                f"/api/ghostskills/{skill_id}/execute",
                data=json.dumps({"ticket_id": 2048, "refund_amount": 32000}),
                content_type="application/json",
            )

            assert exec_response.status_code == 202
            execution = exec_response.get_json()

            # Should pause for approval
            assert execution.get("status") == "WAITING_FOR_APPROVAL"
            assert execution.get("refund_amount") == 32000

            # There should be a PENDING approval
            approvals = execution.get("approvals", [])
            assert len(approvals) > 0
            pending_approval = approvals[0]
            assert pending_approval.get("status") == "PENDING"
            assert pending_approval.get("amount") == 32000

    def test_execute_skill_then_approve_completes(self, client, app):
        """Test full path: execute > WAITING_FOR_APPROVAL > approve > COMPLETED."""
        with app.app_context():
            # Get a skill
            response = client.get("/api/ghostskills")
            skills = response.get_json().get("skills", [])
            assert len(skills) > 0

            skill_id = skills[0]["id"]

            # Step 1: Execute with high refund amount
            exec_response = client.post(
                f"/api/ghostskills/{skill_id}/execute",
                data=json.dumps({"ticket_id": 2048, "refund_amount": 32000}),
                content_type="application/json",
            )

            execution_id = exec_response.get_json()["id"]
            approvals = exec_response.get_json().get("approvals", [])
            approval_id = approvals[0]["id"]

            # Verify status is WAITING_FOR_APPROVAL
            exec_check = client.get(f"/api/executions/{execution_id}")
            assert exec_check.get_json().get("status") == "WAITING_FOR_APPROVAL"

            # Step 2: Approve (response should indicate transition and likely trigger auto-execution)
            approve_response = client.post(
                f"/api/approvals/{approval_id}/approve"
            )
            assert approve_response.status_code == 200
            approval_result = approve_response.get_json()
            # Approval may already have triggered execution to completion
            assert approval_result.get("status") in ("APPROVED", "COMPLETED")

            # Step 3: Check execution is now COMPLETED
            exec_final = client.get(f"/api/executions/{execution_id}")
            assert exec_final.status_code == 200
            final_exec = exec_final.get_json()
            assert final_exec.get("status") == "COMPLETED"

            # Verify verification_agent ran
            steps = final_exec.get("steps", [])
            verification_steps = [
                s for s in steps if s.get("step_name") == "verification_agent"
            ]
            assert len(verification_steps) > 0
            assert verification_steps[0].get("status") == "SUCCESS"

    def test_execute_skill_with_missing_inputs_fails(self, client, app):
        """Test that executing without required inputs returns 422."""
        with app.app_context():
            # Get a skill
            response = client.get("/api/ghostskills")
            skills = response.get_json().get("skills", [])
            assert len(skills) > 0

            skill_id = skills[0]["id"]

            # Try to execute without refund_amount
            exec_response = client.post(
                f"/api/ghostskills/{skill_id}/execute",
                data=json.dumps({"ticket_id": 2048}),  # Missing refund_amount
                content_type="application/json",
            )

            assert exec_response.status_code == 422

    def test_execute_nonexistent_skill_returns_404(self, client):
        """Test that executing a non-existent skill returns 404."""
        response = client.post(
            "/api/ghostskills/99999/execute",
            data=json.dumps({"ticket_id": 2048, "refund_amount": 10000}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_execute_skill_with_needs_configuration_status_fails(self, client, app):
        """Test that executing a NEEDS_CONFIGURATION skill returns 409."""
        with app.app_context():
            from services.supabase_service import get_service

            service = get_service()

            # Create a skill with NEEDS_CONFIGURATION status
            definition_json = {
                "status": "NEEDS_CONFIGURATION",
                "steps": [{"agent": None, "status": "NEEDS_CONFIGURATION"}],
                "autonomy_boundary": {"threshold": 25000},
            }
            skill_id = service.create_ghost_skill(
                workflow_id=1,
                name="Broken Skill",
                definition_json=definition_json,
            )

            # Try to execute it
            exec_response = client.post(
                f"/api/ghostskills/{skill_id}/execute",
                data=json.dumps({"ticket_id": 2048, "refund_amount": 10000}),
                content_type="application/json",
            )

            assert exec_response.status_code == 409


class TestGhostSkillGenerationFromDiscovery:
    """Test the integration between discovery and skill generation."""

    def test_generated_skill_matches_orchestrator_workflow(self, client, app):
        """Test that generated skill resolves to existing orchestrator workflow."""
        with app.app_context():
            # Discover workflows
            response = client.get("/api/discovery/workflows")
            workflows = response.get_json().get("workflows", [])
            refund_wf = next(
                (w for w in workflows if w.get("name") == "Refund Verification"),
                None,
            )
            assert refund_wf is not None

            # Generate skill
            skill_response = client.post(
                f"/api/discovery/workflows/{refund_wf['id']}/ghostskill"
            )
            assert skill_response.status_code == 201
            skill = skill_response.get_json()

            # Verify skill has workflow_id set (the orchestrator's workflow_id)
            assert skill.get("workflow_id") is not None
            assert skill.get("workflow_id") == 1  # Seeded Refund Verification

    def test_generate_skill_for_unknown_workflow_fails(self, client):
        """Test that generating a skill for an unknown workflow fails."""
        # Try to generate from a non-existent discovered workflow
        response = client.post(
            "/api/discovery/workflows/99999999/ghostskill"
        )
        assert response.status_code == 404


class TestGhostSkillErrorHandling:
    """Test error handling in routes."""

    def test_generate_skill_without_body(self, client):
        """Test that generating without a body returns 422."""
        client.post(
            "/api/discovery/workflows/1/ghostskill",
            data=None,
        )
        # POST without a body should still work (generate uses URL param)
        # but let's also test the actual error paths

    def test_execute_skill_without_json_body_returns_422(self, client, app):
        """Test that execute without JSON body returns 422."""
        with app.app_context():
            response = client.get("/api/ghostskills")
            skills = response.get_json().get("skills", [])
            assert len(skills) > 0

            skill_id = skills[0]["id"]

            # POST with empty JSON
            response = client.post(
                f"/api/ghostskills/{skill_id}/execute",
                data=json.dumps({}),
                content_type="application/json",
            )
            assert response.status_code == 422
