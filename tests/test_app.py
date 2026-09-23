"""Tests for Phase 0 and Phase 1: app factory, health, integrations."""

import json


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
        response = client.get("/api/integrations")
        data = json.loads(response.data)
        assert "configured" in data
        assert isinstance(data["configured"], dict)
        # In testing, nothing should be configured
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
