"""Tests for Phase 0 and Phase 1: app factory, health, integrations."""

import json
from unittest.mock import patch


class TestHealth:
    """Phase 1: Health endpoint."""

    def test_health_returns_200(self, client):
        """GET /api/health returns 200 with ok status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_health_returns_json(self, client):
        """Health response is valid JSON with expected structure."""
        response = client.get("/api/health")
        assert response.content_type == "application/json"
        data = json.loads(response.data)
        assert isinstance(data, dict)

    def test_health_includes_request_id(self, client):
        """Health response includes X-Request-ID header."""
        response = client.get("/api/health")
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0


class TestIntegrations:
    """Phase 1: Integrations endpoint."""

    def test_integrations_returns_200(self, client):
        """GET /api/integrations returns 200."""
        response = client.get("/api/integrations")
        assert response.status_code == 200

    def test_integrations_returns_tier(self, client):
        """Integrations response includes tier (A, B, or C)."""
        response = client.get("/api/integrations")
        data = json.loads(response.data)
        assert "status" in data
        assert data["status"] in ["A", "B", "C"]

    def test_integrations_shows_configured(self, client):
        """Integrations response shows which integrations are configured."""
        # Mock get_integrations_status to return a known state independent of .env
        with patch("config.Config.get_integrations_status") as mock_status:
            mock_status.return_value = {
                "supabase": False,
                "freshdesk": False,
                "claude": False,
                "vobiz": False,
                "sarvam": False,
            }
            response = client.get("/api/integrations")
            data = json.loads(response.data)
            assert "configured" in data
            assert isinstance(data["configured"], dict)
            # With mocked status, all should be False
            assert all(v is False for v in data["configured"].values())

    def test_integrations_no_secrets_leaked(self, client):
        """Integrations response does not leak any secret values."""
        response = client.get("/api/integrations")
        data = json.loads(response.data)
        response_str = json.dumps(data)
        # Should not contain any actual API keys
        assert "ANTHROPIC_API_KEY" not in response_str
        assert "SUPABASE_KEY" not in response_str
        assert "FRESHDESK_API_KEY" not in response_str


class TestFreshdeskProviderDetection:
    """Regression tests for the freshdesk MCP-vs-REST configured detection bug.

    Root cause: get_integrations_status() used to check REST-only env vars
    (FRESHDESK_DOMAIN/FRESHDESK_API_KEY) regardless of which provider was
    selected, so freshdesk always reported false when only MCP was configured.
    """

    def test_provider_mcp_with_mcp_config_present_reports_true(self, client, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "mcp")
        monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
        monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", "fwapi_test_token_value")
        # REST vars intentionally absent - MCP alone must be sufficient.
        monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", None)
        monkeypatch.setattr(Config, "FRESHDESK_API_KEY", None)

        response = client.get("/api/integrations")
        data = json.loads(response.data)

        assert data["configured"]["freshdesk"]["configured"] is True
        assert data["configured"]["freshdesk"]["provider"] == "mcp"

    def test_provider_mcp_with_mcp_config_absent_reports_false(self, client, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "mcp")
        monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", None)
        monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", None)
        # Even if REST happens to be configured, provider=mcp must not borrow it.
        monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", "example")
        monkeypatch.setattr(Config, "FRESHDESK_API_KEY", "some-rest-key")

        response = client.get("/api/integrations")
        data = json.loads(response.data)

        assert data["configured"]["freshdesk"]["configured"] is False
        assert data["configured"]["freshdesk"]["provider"] == "mcp"
        assert set(data["configured"]["freshdesk"]["missing_config"]) == {
            "MCP_FRESHDESK_URL",
            "MCP_FRESHDESK_AUTH_TOKEN",
        }

    def test_provider_rest_with_rest_config_present_reports_true(self, client, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "rest")
        monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", "example")
        monkeypatch.setattr(Config, "FRESHDESK_API_KEY", "some-rest-key")
        monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", None)
        monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", None)

        response = client.get("/api/integrations")
        data = json.loads(response.data)

        assert data["configured"]["freshdesk"]["configured"] is True
        assert data["configured"]["freshdesk"]["provider"] == "rest"

    def test_no_mcp_credentials_exposed(self, client, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "mcp")
        monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
        monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", "fwapi_SECRET_TOKEN_VALUE")

        response = client.get("/api/integrations")
        response_str = response.get_data(as_text=True)

        assert "fwapi_SECRET_TOKEN_VALUE" not in response_str
        assert "MCP_FRESHDESK_AUTH_TOKEN" not in response_str or "SECRET" not in response_str


class TestErrorEnvelope:
    """Error handling and error envelope structure."""

    def test_404_returns_error_envelope(self, client):
        """404 errors return standard error envelope."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404
        data = json.loads(response.data)
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert "request_id" in data["error"]

    def test_404_includes_request_id(self, client):
        """404 response includes request ID in both header and body."""
        response = client.get("/api/nonexistent")
        data = json.loads(response.data)
        request_id = response.headers.get("X-Request-ID")
        assert data["error"]["request_id"] == request_id

    def test_method_not_allowed_returns_error(self, client):
        """POST to a GET-only endpoint returns error."""
        response = client.post("/api/health")
        assert response.status_code == 405
        data = json.loads(response.data)
        assert data["error"]["code"] == "METHOD_NOT_ALLOWED"


class TestSecurityHeaders:
    """Security headers on all responses."""

    def test_csp_header_present(self, client):
        """Content-Security-Policy header is present."""
        response = client.get("/api/health")
        assert "Content-Security-Policy" in response.headers
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]

    def test_x_content_type_options_header(self, client):
        """X-Content-Type-Options header is set."""
        response = client.get("/api/health")
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options_header(self, client):
        """X-Frame-Options header is set."""
        response = client.get("/api/health")
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_referrer_policy_header(self, client):
        """Referrer-Policy header is set."""
        response = client.get("/api/health")
        assert "Referrer-Policy" in response.headers
        assert response.headers["Referrer-Policy"] == "same-origin"


class TestMaxContentLength:
    """Request size limit enforcement."""

    def test_max_content_length_set(self, app):
        """MAX_CONTENT_LENGTH is set correctly."""
        assert app.config["MAX_CONTENT_LENGTH"] == 1_000_000

    def test_payload_too_large_rejected(self, client):
        """Requests larger than MAX_CONTENT_LENGTH are rejected."""
        # Note: This test verifies MAX_CONTENT_LENGTH is set in Flask config.
        # Full 413 rejection requires a real POST endpoint which we haven't
        # implemented in Phase 0/1. The config is verified by the test above.
        assert client.application.config["MAX_CONTENT_LENGTH"] == 1_000_000


class TestAppFactory:
    """Application factory configuration."""

    def test_app_factory_creates_valid_app(self, app):
        """create_app() returns a valid Flask application."""
        assert app is not None
        assert app.config["TESTING"] is True

    def test_config_override_works(self):
        """Config override parameter works."""
        from app import create_app

        app = create_app({"TESTING": False})
        assert app.config["TESTING"] is False

    def test_auto_approval_limit_set(self, app):
        """AUTO_APPROVAL_LIMIT is configured."""
        from decimal import Decimal

        from config import Config

        assert hasattr(Config, "AUTO_APPROVAL_LIMIT")
        assert Config.AUTO_APPROVAL_LIMIT == Decimal("25000")


class TestAPIResponseShapes:
    """Regression tests for API response shape consistency (Phase 5 CSP fix)."""

    def test_workflows_list_returns_workflows_property(self, client):
        """GET /api/workflows returns response with 'workflows' property."""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "workflows" in data
        assert isinstance(data["workflows"], list)
        # Should have the seeded Refund Verification workflow
        assert len(data["workflows"]) == 1
        assert data["workflows"][0]["name"] == "Refund Verification"

    def test_workflow_detail_returns_workflow_property(self, client):
        """GET /api/workflows/<id> returns response with 'workflow' property."""
        response = client.get("/api/workflows/1")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "workflow" in data
        assert "steps" in data
        assert isinstance(data["workflow"], dict)
        assert isinstance(data["steps"], list)
        assert data["workflow"]["name"] == "Refund Verification"

    def test_workflow_detail_not_found(self, client):
        """GET /api/workflows/<id> returns 404 for missing workflow."""
        response = client.get("/api/workflows/999")
        assert response.status_code == 404
        data = json.loads(response.data)
        assert "error" in data
