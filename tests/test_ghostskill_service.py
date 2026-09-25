"""Tests for GhostSkill service layer."""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from config import Config
from services.ghostskill_service import (
    ALLOWED_AGENTS,
    TOOL_ACTION_TO_AGENT,
    generate_ghostskill,
    map_signature_to_steps,
    validate_ghostskill,
    _generate_description,
)
from schemas.ghostskill import GhostSkill


class TestMapSignatureToSteps:
    """Test the deterministic step mapping."""

    def test_maps_refund_verification_signatures(self):
        """Test mapping of all 6 Refund Verification signatures."""
        signatures = [
            "freshdesk:ticket_opened",
            "crm:customer_lookup",
            "billing:invoice_lookup",
            "policy_engine:policy_check",
            "approval_system:approval_requested",
            "freshdesk:ticket_updated",
        ]

        steps = map_signature_to_steps(signatures)

        # Should have 7 steps: 6 mapped + 1 verification_agent auto-appended
        assert len(steps) == 7

        # Check agent sequence (after deduplication and auto-injection)
        agents = [s.agent for s in steps if s.agent]
        expected = ["context_agent", "billing_agent", "policy_agent", "risk_agent", "approval_gate", "communication_agent", "verification_agent"]
        assert agents == expected

    def test_deduplicates_consecutive_same_agent(self):
        """Test that consecutive duplicate agents are collapsed."""
        signatures = [
            "freshdesk:ticket_opened",
            "crm:customer_lookup",  # Also maps to context_agent
        ]

        steps = map_signature_to_steps(signatures)

        context_steps = [s for s in steps if s.agent == "context_agent"]
        assert len(context_steps) == 1, "Consecutive context_agent steps should be deduplicated"

    def test_auto_injects_approval_gate_after_risk_agent(self):
        """Test that approval_gate is injected after risk_agent if missing."""
        signatures = [
            "approval_system:approval_requested",  # Maps to risk_agent
            "freshdesk:ticket_updated",  # Maps to communication_agent
        ]

        steps = map_signature_to_steps(signatures)

        # Find indices
        risk_idx = next((i for i, s in enumerate(steps) if s.agent == "risk_agent"), None)
        approval_idx = next((i for i, s in enumerate(steps) if s.agent == "approval_gate"), None)

        assert risk_idx is not None, "risk_agent should be present"
        assert approval_idx is not None, "approval_gate should be injected"
        assert approval_idx == risk_idx + 1, "approval_gate should be immediately after risk_agent"

    def test_appends_verification_agent_at_end(self):
        """Test that verification_agent is appended if missing."""
        signatures = [
            "freshdesk:ticket_opened",
        ]

        steps = map_signature_to_steps(signatures)

        # Last step should be verification_agent
        assert steps[-1].agent == "verification_agent"
        assert steps[-1].order == len(steps)

    def test_unknown_signature_marked_needs_configuration(self):
        """Test that unknown signatures are marked NEEDS_CONFIGURATION."""
        signatures = [
            "freshdesk:ticket_opened",
            "unknown_tool:unknown_action",
        ]

        steps = map_signature_to_steps(signatures)

        # Find the unknown step
        unknown_steps = [s for s in steps if "unknown" in s.name]
        assert len(unknown_steps) == 1
        assert unknown_steps[0].status == "NEEDS_CONFIGURATION"
        assert unknown_steps[0].agent is None

    def test_steps_have_sequential_order(self):
        """Test that step orders are sequential."""
        signatures = [
            "freshdesk:ticket_opened",
            "billing:invoice_lookup",
            "approval_system:approval_requested",
        ]

        steps = map_signature_to_steps(signatures)

        for i, step in enumerate(steps):
            assert step.order == i + 1


class TestGenerateGhostskill:
    """Test the full generation flow."""

    def test_validates_required_fields(self):
        """Test that missing required fields raise ValueError."""
        incomplete = {
            "id": "hash123",
            "name": "Refund Verification",
            # Missing: step_signatures, ghost_score
        }

        with pytest.raises(ValueError, match="missing required field"):
            generate_ghostskill(incomplete)

    def test_resolves_orchestrator_workflow_id(self):
        """Test that generation resolves the orchestrator workflow_id."""
        discovered = {
            "id": "discovered_123",
            "name": "Refund Verification",
            "step_signatures": ["freshdesk:ticket_opened"],
            "ghost_score": 87.0,
            "frequency": 37,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification", "description": "..."},
        ]

        skill = generate_ghostskill(discovered, service=mock_service)

        # Check internal state has orchestrator workflow ID
        assert skill.__dict__.get("_orchestrator_workflow_id") == 1

    def test_raises_when_no_matching_orchestrator_workflow(self):
        """Test that generation fails if no matching workflow exists."""
        discovered = {
            "id": "discovered_456",
            "name": "Unknown Workflow",
            "step_signatures": ["freshdesk:ticket_opened"],
            "ghost_score": 50.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = []

        with pytest.raises(ValueError, match="No matching GhostWork workflow"):
            generate_ghostskill(discovered, service=mock_service)

    def test_sets_autonomy_boundary_to_auto_approval_limit(self):
        """Test that autonomy_boundary threshold is set to Config.AUTO_APPROVAL_LIMIT."""
        discovered = {
            "id": "discovered_789",
            "name": "Refund Verification",
            "step_signatures": ["freshdesk:ticket_opened"],
            "ghost_score": 87.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification"},
        ]

        skill = generate_ghostskill(discovered, service=mock_service)

        assert skill.autonomy_boundary.threshold == float(Config.AUTO_APPROVAL_LIMIT)
        assert skill.autonomy_boundary.threshold == 25000.0

    def test_sets_privacy_metadata_only_true(self):
        """Test that privacy.metadata_only is always True."""
        discovered = {
            "id": "discovered_privacy",
            "name": "Refund Verification",
            "step_signatures": ["freshdesk:ticket_opened"],
            "ghost_score": 87.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification"},
        ]

        skill = generate_ghostskill(discovered, service=mock_service)

        assert skill.privacy.metadata_only is True

    def test_skill_status_ready_when_all_steps_mapped(self):
        """Test that skill status is READY when all steps are MAPPED."""
        discovered = {
            "id": "discovered_ready",
            "name": "Refund Verification",
            "step_signatures": [
                "freshdesk:ticket_opened",
                "crm:customer_lookup",
                "billing:invoice_lookup",
                "policy_engine:policy_check",
                "approval_system:approval_requested",
                "freshdesk:ticket_updated",
            ],
            "ghost_score": 87.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification"},
        ]

        skill = generate_ghostskill(discovered, service=mock_service)

        # All steps should be mapped (including auto-injected approval_gate and verification_agent)
        assert skill.status == "READY"
        assert all(step.status == "MAPPED" for step in skill.steps)

    def test_skill_status_needs_configuration_with_unmapped_steps(self):
        """Test that skill status is NEEDS_CONFIGURATION with unmapped steps."""
        discovered = {
            "id": "discovered_config",
            "name": "Refund Verification",
            "step_signatures": [
                "freshdesk:ticket_opened",
                "unknown_tool:unknown_action",
            ],
            "ghost_score": 50.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification"},
        ]

        skill = generate_ghostskill(discovered, service=mock_service)

        assert skill.status == "NEEDS_CONFIGURATION"

    def test_generates_unique_skill_ids(self):
        """Test that each generated skill gets a unique UUID."""
        discovered = {
            "id": "discovered_uuid",
            "name": "Refund Verification",
            "step_signatures": ["freshdesk:ticket_opened"],
            "ghost_score": 87.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification"},
        ]

        skill1 = generate_ghostskill(discovered, service=mock_service)
        skill2 = generate_ghostskill(discovered, service=mock_service)

        assert skill1.skill_id != skill2.skill_id

    def test_description_fallback_without_claude(self):
        """Test that description falls back to deterministic template when Claude unavailable."""
        discovered = {
            "id": "discovered_no_claude",
            "name": "Test Workflow",
            "step_signatures": ["freshdesk:ticket_opened"],
            "ghost_score": 42.0,
            "frequency": 10,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Test Workflow"},
        ]

        with patch("services.ghostskill_service.Config.ANTHROPIC_API_KEY", None):
            skill = generate_ghostskill(discovered, service=mock_service)

        # Should have a fallback description mentioning frequency
        assert "Test Workflow" in skill.description
        assert "10" in skill.description

    def test_all_steps_in_allowed_agents(self):
        """Test that all generated steps use allowed agents or are unmapped."""
        discovered = {
            "id": "discovered_agents",
            "name": "Refund Verification",
            "step_signatures": [
                "freshdesk:ticket_opened",
                "crm:customer_lookup",
                "billing:invoice_lookup",
                "policy_engine:policy_check",
                "approval_system:approval_requested",
                "freshdesk:ticket_updated",
            ],
            "ghost_score": 87.0,
        }

        mock_service = MagicMock()
        mock_service.list_workflows.return_value = [
            {"id": 1, "name": "Refund Verification"},
        ]

        skill = generate_ghostskill(discovered, service=mock_service)

        for step in skill.steps:
            if step.agent is not None:
                assert step.agent in ALLOWED_AGENTS, f"Step has disallowed agent: {step.agent}"


class TestValidateGhostskill:
    """Test schema validation."""

    def test_valid_ghostskill_passes(self):
        """Test that a valid GhostSkill dict passes validation."""
        from datetime import datetime, timezone

        valid_dict = {
            "skill_id": "test_skill_123",
            "name": "Refund Verification",
            "version": "1.0",
            "description": "Test skill",
            "source_workflow_id": "discovered_123",
            "ghost_score": 87.0,
            "trigger": {"type": "refund_request", "description": "Test trigger"},
            "inputs": [
                {"name": "refund_amount", "type": "number", "required": True},
            ],
            "steps": [
                {
                    "order": 1,
                    "name": "step1",
                    "agent": "context_agent",
                    "status": "MAPPED",
                },
            ],
            "autonomy_boundary": {
                "type": "amount_threshold",
                "threshold": 25000.0,
                "currency": "INR",
            },
            "approval_policy": {"required_when_exceeded": True, "channel": "web"},
            "verification": {"required": True, "method": "reread_and_compare"},
            "privacy": {"metadata_only": True},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "READY",
        }

        assert validate_ghostskill(valid_dict) is True

    def test_missing_required_field_raises(self):
        """Test that missing required fields raise ValidationError."""
        invalid_dict = {
            "skill_id": "test_skill_456",
            "name": "Missing status",
            # Missing many required fields
        }

        with pytest.raises(Exception):  # pydantic.ValidationError
            validate_ghostskill(invalid_dict)


class TestGenerateDescription:
    """Test the description generation logic."""

    def test_fallback_description_includes_name_and_frequency(self):
        """Test that fallback description includes workflow name and frequency."""
        with patch("services.ghostskill_service.Config.ANTHROPIC_API_KEY", None):
            desc = _generate_description("Test Workflow", 15)

        assert "Test Workflow" in desc
        assert "15" in desc

    def test_description_under_150_chars(self):
        """Test that description is capped at 150 characters."""
        # Mock Claude to return a very long response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "x" * 200  # 200 chars

        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response

        # Patch Anthropic in the context where it's imported
        import services.ghostskill_service as gss_module
        with patch.object(gss_module, "Anthropic", return_value=mock_client, create=True):
            with patch.object(gss_module.Config, "ANTHROPIC_API_KEY", "test_key"):
                desc = _generate_description("Test", 1)

        assert len(desc) <= 150
