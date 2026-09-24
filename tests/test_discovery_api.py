"""Tests for discovery API endpoints."""

import json

import pytest


@pytest.fixture
def client():
    """Create Flask test client."""
    from app import create_app

    app = create_app(config_override={"TESTING": True})
    with app.test_client() as client:
        yield client


class TestDiscoveryWorkflowsEndpoint:
    """Test GET /api/discovery/workflows endpoint."""

    def test_get_workflows_returns_list(self, client):
        """GET /api/discovery/workflows returns list of workflows."""
        response = client.get("/api/discovery/workflows")

        assert response.status_code == 200
        data = response.get_json()
        assert "workflows" in data
        assert isinstance(data["workflows"], list)
        assert "count" in data

    def test_workflows_include_ghostscore(self, client):
        """Each workflow includes GhostScore."""
        response = client.get("/api/discovery/workflows")
        data = response.get_json()

        if data["count"] > 0:
            workflow = data["workflows"][0]
            assert "ghost_score" in workflow
            assert "ghost_score_breakdown" in workflow
            assert isinstance(workflow["ghost_score"], int)
            assert 0 <= workflow["ghost_score"] <= 100

    def test_workflows_include_privacy_metadata(self, client):
        """Each workflow includes privacy protection metadata."""
        response = client.get("/api/discovery/workflows")
        data = response.get_json()

        if data["count"] > 0:
            workflow = data["workflows"][0]
            assert workflow["privacy_mode"] == "metadata_only"
            assert "data_sources" in workflow
            assert "discovered_from" in workflow
            assert workflow["discovered_from"] == "activity_metadata"

    def test_workflows_sorted_by_ghostscore(self, client):
        """Workflows are sorted by GhostScore descending."""
        response = client.get("/api/discovery/workflows")
        data = response.get_json()

        workflows = data["workflows"]
        if len(workflows) > 1:
            for i in range(len(workflows) - 1):
                assert workflows[i]["ghost_score"] >= workflows[i + 1]["ghost_score"]

    def test_min_frequency_parameter(self, client):
        """Query parameter min_frequency filters results."""
        # Default (min_frequency=2)
        response1 = client.get("/api/discovery/workflows")
        data1 = response1.get_json()
        count1 = data1["count"]

        # Higher minimum should return same or fewer workflows
        response2 = client.get("/api/discovery/workflows?min_frequency=5")
        data2 = response2.get_json()
        count2 = data2["count"]

        assert count2 <= count1

    def test_post_with_custom_events(self, client):
        """POST /api/discovery/workflows with custom events."""
        custom_events = [
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:00:00Z",
                "tool": "tool_a",
                "action": "action_1",
            },
            {
                "session_id": "s1",
                "timestamp": "2026-01-01T00:05:00Z",
                "tool": "tool_b",
                "action": "action_2",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:00:00Z",
                "tool": "tool_a",
                "action": "action_1",
            },
            {
                "session_id": "s2",
                "timestamp": "2026-01-01T01:05:00Z",
                "tool": "tool_b",
                "action": "action_2",
            },
        ]

        response = client.post(
            "/api/discovery/workflows",
            data=json.dumps({"events": custom_events}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] > 0
        assert len(data["workflows"]) == data["count"]


class TestDiscoveryWorkflowDetailEndpoint:
    """Test GET /api/discovery/workflows/<id> endpoint."""

    def test_get_workflow_detail(self, client):
        """GET /api/discovery/workflows/<id> returns workflow detail."""
        # First, get the workflow list
        list_response = client.get("/api/discovery/workflows")
        workflows = list_response.get_json()["workflows"]

        if len(workflows) > 0:
            workflow_id = workflows[0]["id"]

            # Get workflow detail
            response = client.get(f"/api/discovery/workflows/{workflow_id}")

            assert response.status_code == 200
            detail = response.get_json()
            assert detail["id"] == workflow_id
            assert "ghost_score" in detail
            assert "ghost_score_breakdown" in detail

    def test_get_nonexistent_workflow_returns_404(self, client):
        """GET /api/discovery/workflows/<nonexistent> returns 404."""
        response = client.get("/api/discovery/workflows/99999")

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data


class TestDiscoveryStatsEndpoint:
    """Test GET /api/discovery/stats endpoint."""

    def test_get_stats_returns_metrics(self, client):
        """GET /api/discovery/stats returns discovery metrics."""
        response = client.get("/api/discovery/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert "total_events" in data
        assert "total_sessions" in data
        assert "discovered_workflows" in data
        assert "total_workflow_instances" in data
        assert "average_ghostscore" in data
        assert "top_workflow" in data

    def test_stats_consistent_with_workflows(self, client):
        """Stats metrics are consistent with discovered workflows."""
        # Get stats
        stats_response = client.get("/api/discovery/stats")
        stats = stats_response.get_json()

        # Get workflows
        workflows_response = client.get("/api/discovery/workflows")
        workflows_data = workflows_response.get_json()

        assert stats["discovered_workflows"] == workflows_data["count"]

    def test_top_workflow_has_highest_ghostscore(self, client):
        """Top workflow in stats has highest GhostScore."""
        stats_response = client.get("/api/discovery/stats")
        stats = stats_response.get_json()

        if stats["top_workflow"]:
            workflows_response = client.get("/api/discovery/workflows")
            workflows = workflows_response.get_json()["workflows"]

            if len(workflows) > 0:
                highest_score = workflows[0]["ghost_score"]
                top_score = stats["top_workflow"]["ghost_score"]
                assert top_score == highest_score


class TestRefundVerificationDiscovery:
    """Test that Refund Verification is discovered correctly."""

    def test_refund_verification_discovered(self, client):
        """Refund Verification workflow is discovered from demo data."""
        response = client.get("/api/discovery/workflows")
        data = response.get_json()

        refund_workflows = [
            w for w in data["workflows"] if "refund" in w["name"].lower()
        ]
        assert len(refund_workflows) > 0

    def test_refund_verification_ghostscore_reasonable(self, client):
        """Refund Verification has reasonable GhostScore (50-95)."""
        response = client.get("/api/discovery/workflows")
        data = response.get_json()

        refund_workflows = [
            w for w in data["workflows"] if "refund" in w["name"].lower()
        ]
        if len(refund_workflows) > 0:
            refund = refund_workflows[0]
            # Expected: 50+ (demo data has different characteristics than pure frequency/duration)
            assert 50 <= refund["ghost_score"] <= 95

    def test_refund_verification_has_breakdown(self, client):
        """Refund Verification breakdown is transparent."""
        response = client.get("/api/discovery/workflows")
        data = response.get_json()

        refund_workflows = [
            w for w in data["workflows"] if "refund" in w["name"].lower()
        ]
        if len(refund_workflows) > 0:
            refund = refund_workflows[0]
            breakdown = refund["ghost_score_breakdown"]

            required_components = [
                "frequency",
                "repeatability",
                "manual_effort",
                "automation_potential",
                "risk_penalty",
            ]
            for component in required_components:
                assert component in breakdown
                assert isinstance(breakdown[component], int)
                assert 0 <= breakdown[component] <= 100
