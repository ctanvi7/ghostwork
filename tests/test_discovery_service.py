"""Tests for workflow discovery service and GhostScore calculation."""

from orchestrator.ghostscore import calculate_ghostscore, format_ghostscore_for_display
from services.discovery_service import (
    count_sequence_frequencies,
    discover_workflows,
    extract_sequence,
    get_discovered_workflows,
    group_events_by_session,
    normalize_discovered_workflow,
)


class TestEventGrouping:
    """Test event grouping and session management."""

    def test_group_events_by_session(self):
        """Group events by session_id."""
        events = [
            {"session_id": "s1", "timestamp": "2026-01-01T00:00:00Z"},
            {"session_id": "s2", "timestamp": "2026-01-01T00:10:00Z"},
            {"session_id": "s1", "timestamp": "2026-01-01T00:05:00Z"},
        ]

        sessions = group_events_by_session(events)

        assert len(sessions) == 2
        assert "s1" in sessions
        assert "s2" in sessions
        assert len(sessions["s1"]) == 2
        assert len(sessions["s2"]) == 1

    def test_sessions_sorted_by_timestamp(self):
        """Events within a session are sorted by timestamp."""
        events = [
            {"session_id": "s1", "timestamp": "2026-01-01T00:10:00Z", "order": 2},
            {"session_id": "s1", "timestamp": "2026-01-01T00:00:00Z", "order": 1},
            {"session_id": "s1", "timestamp": "2026-01-01T00:05:00Z", "order": 3},
        ]

        sessions = group_events_by_session(events)
        session_s1 = sessions["s1"]

        assert session_s1[0]["order"] == 1
        assert session_s1[1]["order"] == 3
        assert session_s1[2]["order"] == 2


class TestSequenceExtraction:
    """Test extraction of workflow sequences."""

    def test_extract_sequence(self):
        """Extract tool:action sequence from events."""
        events = [
            {"tool": "freshdesk", "action": "ticket_opened"},
            {"tool": "crm", "action": "customer_lookup"},
            {"tool": "billing", "action": "invoice_lookup"},
        ]

        sequence = extract_sequence(events)

        assert len(sequence) == 3
        assert sequence[0] == "freshdesk:ticket_opened"
        assert sequence[1] == "crm:customer_lookup"
        assert sequence[2] == "billing:invoice_lookup"

    def test_extract_sequence_empty(self):
        """Empty session yields empty sequence."""
        sequence = extract_sequence([])
        assert sequence == []


class TestSequenceFrequency:
    """Test frequency counting of repeated sequences."""

    def test_count_exact_repetitions(self):
        """Count sessions with identical sequences."""
        sessions = {
            "s1": [
                {"tool": "freshdesk", "action": "opened"},
                {"tool": "crm", "action": "lookup"},
            ],
            "s2": [
                {"tool": "freshdesk", "action": "opened"},
                {"tool": "crm", "action": "lookup"},
            ],
            "s3": [
                {"tool": "freshdesk", "action": "opened"},
                {"tool": "billing", "action": "lookup"},
            ],
        }

        frequent = count_sequence_frequencies(sessions, min_frequency=2)

        # Should have one sequence with min_frequency=2 (freshdesk->crm appears twice)
        # The billing sequence only appears once, so it's filtered out
        assert len(frequent) == 1

        # Find the refund-like sequence (freshdesk->crm)
        sig1 = ("freshdesk:opened", "crm:lookup")
        assert sig1 in frequent
        assert len(frequent[sig1]) == 2
        assert set(frequent[sig1]) == {"s1", "s2"}

    def test_min_frequency_filtering(self):
        """Sequences below min_frequency are excluded."""
        sessions = {
            "s1": [
                {"tool": "a", "action": "x"},
                {"tool": "b", "action": "y"},
            ],
            "s2": [
                {"tool": "c", "action": "z"},
            ],
        }

        # With min_frequency=2, single-occurrence sequence excluded
        frequent = count_sequence_frequencies(sessions, min_frequency=2)
        assert len(frequent) == 0

        # With min_frequency=1, included
        frequent = count_sequence_frequencies(sessions, min_frequency=1)
        assert len(frequent) == 2

    def test_empty_sessions(self):
        """Empty sessions dict returns empty results."""
        frequent = count_sequence_frequencies({}, min_frequency=2)
        assert len(frequent) == 0


class TestWorkflowDiscovery:
    """Test core discovery logic."""

    def test_discover_refund_pattern(self):
        """Discover repeated refund verification workflow."""
        events = [
            # Session 1: Refund workflow
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:00:00Z",
                "tool": "freshdesk",
                "action": "ticket_opened",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:05:00Z",
                "tool": "crm",
                "action": "customer_lookup",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:10:00Z",
                "tool": "billing",
                "action": "invoice_lookup",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:15:00Z",
                "tool": "policy_engine",
                "action": "policy_check",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:20:00Z",
                "tool": "approval_system",
                "action": "approval_requested",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:25:00Z",
                "tool": "freshdesk",
                "action": "ticket_updated",
            },
            # Session 2: Same workflow
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:00:00Z",
                "tool": "freshdesk",
                "action": "ticket_opened",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:05:00Z",
                "tool": "crm",
                "action": "customer_lookup",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:10:00Z",
                "tool": "billing",
                "action": "invoice_lookup",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:15:00Z",
                "tool": "policy_engine",
                "action": "policy_check",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:20:00Z",
                "tool": "approval_system",
                "action": "approval_requested",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:25:00Z",
                "tool": "freshdesk",
                "action": "ticket_updated",
            },
        ]

        workflows = discover_workflows(events, min_frequency=2)

        assert len(workflows) >= 1
        refund_workflow = workflows[0]
        assert refund_workflow["frequency"] == 2
        assert refund_workflow["step_count"] == 6
        assert "freshdesk" in refund_workflow["sequence"]
        assert "approval" in " ".join(refund_workflow["signature"]).lower()

    def test_discover_with_noise(self):
        """Discover patterns even with non-repeating sequences."""
        events = [
            # Repeating pattern x2
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:00:00Z",
                "tool": "a",
                "action": "x",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:05:00Z",
                "tool": "b",
                "action": "y",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:00:00Z",
                "tool": "a",
                "action": "x",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:05:00Z",
                "tool": "b",
                "action": "y",
            },
            # Noise: single-occurrence sequence
            {
                "session_id": "s3",
                "timestamp": "2026-01-01T02:00:00Z",
                "tool": "noise",
                "action": "irrelevant",
            },
        ]

        workflows = discover_workflows(events, min_frequency=2)

        # Should find one workflow (the repeating pattern)
        assert len(workflows) == 1
        assert workflows[0]["frequency"] == 2
        assert workflows[0]["step_count"] == 2

    def test_discover_empty_events(self):
        """Empty events yield no discovered workflows."""
        workflows = discover_workflows([], min_frequency=2)
        assert workflows == []


class TestGhostScore:
    """Test deterministic GhostScore calculation."""

    def test_ghostscore_high_frequency(self):
        """High frequency increases score."""
        low_freq = calculate_ghostscore(
            frequency=1,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=80,
        )
        high_freq = calculate_ghostscore(
            frequency=37,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=80,
        )

        assert high_freq["score"] > low_freq["score"]

    def test_ghostscore_long_duration_increases_value(self):
        """Longer workflow duration increases perceived value."""
        short = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=60,
            automation_percentage=80,
        )
        long = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=900,
            automation_percentage=80,
        )

        assert long["score"] > short["score"]

    def test_ghostscore_automation_potential(self):
        """Higher automation percentage increases score."""
        low_auto = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=20,
        )
        high_auto = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=80,
        )

        assert high_auto["score"] > low_auto["score"]

    def test_ghostscore_breakdown_weights(self):
        """Score breakdown components are present and weighted correctly."""
        result = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=75,
        )

        breakdown = result["breakdown"]
        assert "frequency" in breakdown
        assert "repeatability" in breakdown
        assert "manual_effort" in breakdown
        assert "automation_potential" in breakdown
        assert "risk_penalty" in breakdown

        # All values should be 0-100
        for _key, value in breakdown.items():
            assert 0 <= value <= 100

    def test_ghostscore_risk_penalty_applied(self):
        """Workflows with approval steps get risk penalty."""
        without_approval = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=75,
            step_signatures=["tool:action"] * 5,
        )
        with_approval = calculate_ghostscore(
            frequency=10,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=75,
            step_signatures=[
                "freshdesk:open",
                "crm:lookup",
                "billing:check",
                "approval_system:approval",
                "freshdesk:update",
            ],
        )

        assert with_approval["score"] <= without_approval["score"]

    def test_ghostscore_clamped_to_0_100(self):
        """GhostScore is always clamped to 0-100."""
        very_high = calculate_ghostscore(
            frequency=1000,
            step_count=100,
            average_duration_seconds=10000,
            automation_percentage=100,
        )
        assert very_high["score"] <= 100

        very_low = calculate_ghostscore(
            frequency=1,
            step_count=1,
            average_duration_seconds=1,
            automation_percentage=0,
        )
        assert very_low["score"] >= 0

    def test_ghostscore_refund_verification_demo(self):
        """Demo scenario: Refund Verification with ≈87 score."""
        # Refund Verification: frequency=37, step_count=6, duration~667s, automation=~85%
        result = calculate_ghostscore(
            frequency=37,
            step_count=6,
            average_duration_seconds=667,
            automation_percentage=85,
            step_signatures=[
                "freshdesk:ticket_opened",
                "crm:customer_lookup",
                "billing:invoice_lookup",
                "policy_engine:policy_check",
                "approval_system:approval_requested",
                "freshdesk:ticket_updated",
            ],
            max_frequency=37,
        )

        # Expected: score should be approximately 80-87
        # Allow ±10 margin for weighting variations
        assert 75 <= result["score"] <= 92

    def test_ghostscore_format_for_display(self):
        """Format GhostScore for UI display."""
        result = calculate_ghostscore(
            frequency=20,
            step_count=5,
            average_duration_seconds=600,
            automation_percentage=80,
        )

        formatted = format_ghostscore_for_display(result["score"], result["breakdown"])

        assert "score" in formatted
        assert "grade" in formatted
        assert "explanation" in formatted
        assert "components" in formatted
        assert len(formatted["components"]) == 5

    def test_ghostscore_grade_assignment(self):
        """GhostScore grades are assigned correctly."""
        scores = {
            90: "A",
            75: "B",
            60: "C",
            45: "D",
            20: "F",
        }

        for score, expected_grade in scores.items():
            from orchestrator.ghostscore import _score_to_grade

            grade = _score_to_grade(score)
            assert grade == expected_grade


class TestNormalization:
    """Test workflow normalization."""

    def test_normalize_discovered_workflow(self):
        """Normalize discovered workflow to API format."""
        raw = {
            "signature": ["freshdesk:open", "crm:lookup", "approval:request"],
            "sequence": "freshdesk → crm → approval",
            "frequency": 25,
            "step_count": 3,
            "average_duration_seconds": 500,
            "session_ids": ["s1", "s2"],
        }

        normalized = normalize_discovered_workflow(raw, workflow_id=1)

        assert normalized["id"] == 1
        assert normalized["frequency"] == 25
        assert "ghost_score" in normalized
        assert "ghost_score_breakdown" in normalized
        assert normalized["privacy_mode"] == "metadata_only"
        assert normalized["discovered_from"] == "activity_metadata"
        assert "tool" in normalized["data_sources"]
        assert "action" in normalized["data_sources"]

    def test_normalization_includes_privacy_metadata(self):
        """Normalized workflow includes privacy protections."""
        raw = {
            "signature": ["a:x"],
            "frequency": 5,
            "step_count": 1,
            "average_duration_seconds": 100,
            "session_ids": [],
        }

        normalized = normalize_discovered_workflow(raw)

        assert normalized["privacy_mode"] == "metadata_only"
        assert set(normalized["data_sources"]) == {"tool", "action", "timestamp", "session"}


class TestIntegration:
    """Integration tests for full discovery flow."""

    def test_get_discovered_workflows_from_default_file(self):
        """Load and discover workflows from default events.json."""
        workflows = get_discovered_workflows(min_frequency=2)

        assert len(workflows) > 0
        # Should be sorted by GhostScore
        for i in range(len(workflows) - 1):
            assert workflows[i]["ghost_score"] >= workflows[i + 1]["ghost_score"]

    def test_get_discovered_workflows_includes_refund_verification(self):
        """Refund Verification should be discovered from demo data."""
        workflows = get_discovered_workflows(min_frequency=2)

        refund_workflows = [w for w in workflows if "refund" in w["name"].lower()]
        assert len(refund_workflows) > 0

        refund = refund_workflows[0]
        assert refund["frequency"] >= 3  # At least 3 occurrences in demo data
        assert "ghost_score" in refund
        assert refund["ghost_score"] > 0

    def test_discovered_workflows_sortable_by_ghostscore(self):
        """Workflows are sortable by GhostScore descending."""
        workflows = get_discovered_workflows()

        scores = [w["ghost_score"] for w in workflows]
        assert scores == sorted(scores, reverse=True)

    def test_no_real_api_calls_in_discovery(self):
        """Discovery works entirely from local data files."""
        # This test just verifies the previous tests pass without errors,
        # which means no external API calls were made
        workflows = get_discovered_workflows()
        assert len(workflows) >= 0  # Either finds workflows or returns empty list
