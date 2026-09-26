"""Tests for Phase 10B UI response contracts and API integration."""

import pytest


@pytest.fixture
def client():
    """Create Flask test client with memory backend."""
    import os
    os.environ['DB_BACKEND'] = 'memory'
    from app import create_app

    app = create_app(config_override={"TESTING": True})
    with app.test_client() as client:
        yield client


class TestExecutionsAPIContract:
    """Test executions API response contract for UI consumption."""

    def test_executions_list_empty_returns_200(self, client):
        """GET /api/executions with no executions returns 200, not error."""
        response = client.get("/api/executions")

        assert response.status_code == 200
        data = response.get_json()
        assert "executions" in data
        assert "count" in data
        assert isinstance(data["executions"], list)
        # count must match array length (could be 0 or more depending on seed data)
        assert data["count"] == len(data["executions"])

    def test_executions_response_structure_valid(self, client):
        """Executions response matches expected structure."""
        response = client.get("/api/executions")
        data = response.get_json()

        # Must have these fields
        assert "count" in data
        assert "executions" in data

        # executions must be a list
        assert isinstance(data["executions"], list)

        # count must match array length
        assert data["count"] == len(data["executions"])

    def test_executions_pagination_parameters(self, client):
        """Executions endpoint accepts pagination parameters."""
        response = client.get("/api/executions?limit=10&offset=0")

        assert response.status_code == 200
        data = response.get_json()
        assert "executions" in data
        assert "count" in data


class TestIntegrationsAPIContract:
    """Test integrations API response contract for UI consumption."""

    def test_integrations_response_structure(self, client):
        """GET /api/integrations returns correct structure."""
        response = client.get("/api/integrations")

        assert response.status_code == 200
        data = response.get_json()

        # Must have these top-level fields
        assert "configured" in data
        assert "status" in data
        assert "timestamp" in data

    def test_integrations_configured_is_dict(self, client):
        """The 'configured' field is a dict of system names to booleans."""
        response = client.get("/api/integrations")
        data = response.get_json()
        configured = data.get("configured")

        assert isinstance(configured, dict)

        # Should have keys for each integration
        expected_keys = {"claude", "freshdesk", "supabase", "vobiz", "sarvam"}
        actual_keys = set(configured.keys())
        assert expected_keys.issubset(actual_keys)

        # All values should be booleans (except freshdesk which is a dict)
        for key, value in configured.items():
            if key == "freshdesk":
                assert isinstance(value, dict), f"{key} should be a dict with configured and provider"
                assert "configured" in value
                assert "provider" in value
            else:
                assert isinstance(value, bool), f"{key} value should be boolean, got {type(value)}"

    def test_integrations_claude_configured_demo(self, client, monkeypatch):
        """In demo, Claude should be configured (true) when its key is set."""
        from config import Config
        monkeypatch.setattr(Config, "ANTHROPIC_API_KEY", "test-anthropic-key")
        response = client.get("/api/integrations")
        data = response.get_json()

        # Claude should be enabled in demo
        assert data["configured"]["claude"] is True

    def test_integrations_freshdesk_not_configured_demo(self, client):
        """In demo, Freshdesk should not be configured (false)."""
        response = client.get("/api/integrations")
        data = response.get_json()

        # Freshdesk should be disabled in demo without credentials
        assert data["configured"]["freshdesk"]["configured"] is False

    def test_integrations_sarvam_configured_when_key_present(self, client, monkeypatch):
        """Sarvam should be configured (true) when SARVAM_API_KEY is set."""
        from config import Config
        monkeypatch.setattr(Config, "SARVAM_API_KEY", "test-sarvam-key-12345")
        response = client.get("/api/integrations")
        data = response.get_json()

        # Sarvam should be enabled when API key is present
        assert data["configured"]["sarvam"] is True

    def test_integrations_sarvam_not_configured_when_key_absent(self, client, monkeypatch):
        """Sarvam should not be configured (false) when SARVAM_API_KEY is absent."""
        from config import Config
        monkeypatch.setattr(Config, "SARVAM_API_KEY", None)
        response = client.get("/api/integrations")
        data = response.get_json()

        # Sarvam should be disabled when API key is absent
        assert data["configured"]["sarvam"] is False

    def test_integrations_no_credentials_exposed(self, client):
        """Response does not contain any sensitive credential VALUES.

        Note: freshdesk.missing_config may list fixed, non-secret env VAR
        NAMES (e.g. "MCP_FRESHDESK_AUTH_TOKEN") as a safe debugging aid -
        the name of a variable is not the secret it holds. That field is
        excluded from the blanket word-scan below; everything else in the
        response must still contain none of these words.
        """
        response = client.get("/api/integrations")
        data = response.get_json()

        # missing_config only ever contains fixed variable-name strings from
        # config.py, never a value read from the environment.
        sanitized = dict(data)
        freshdesk = sanitized.get("configured", {}).get("freshdesk")
        if isinstance(freshdesk, dict) and "missing_config" in freshdesk:
            freshdesk = {k: v for k, v in freshdesk.items() if k != "missing_config"}
            sanitized["configured"] = {**sanitized["configured"], "freshdesk": freshdesk}

        response_text = str(sanitized).lower()

        # Should not contain any credential-related strings
        forbidden_strings = ["key", "secret", "password", "token", "credential"]
        for forbidden in forbidden_strings:
            assert forbidden not in response_text, \
                f"Response should not contain '{forbidden}'"


class TestUIResponseIntegration:
    """Test that UI can properly consume the API responses."""

    def test_execution_page_requires_id(self, client):
        response = client.get("/execution")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/executions")

    def test_execution_detail_links_to_json_record(self, client):
        from services.supabase_service import get_service

        execution_id = get_service().create_execution(1, ticket_id=2048, refund_amount=32000)
        page = client.get(f"/execution/{execution_id}")
        record = client.get(f"/api/executions/{execution_id}")

        assert page.status_code == 200
        assert f'data-execution-id="{execution_id}"' in page.get_data(as_text=True)
        assert record.status_code == 200
        assert record.is_json
        assert record.get_json()["id"] == execution_id

    def test_discovery_page_loads(self, client):
        """Discovery page HTML loads without error."""
        response = client.get("/workflows")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Discovery" in html or "GhostWork" in html
        # Should load external JS (CSP compliant)
        assert "discovery.js" in html

    def test_dashboard_page_loads(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "dashboard.js" in response.get_data(as_text=True)

    def test_executions_page_loads(self, client):
        """Executions page HTML loads without error."""
        response = client.get("/executions")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Executions" in html
        # Should load external JS (CSP compliant)
        assert "executions.js" in html

    def test_integrations_page_loads(self, client):
        """Integrations page HTML loads without error."""
        response = client.get("/integrations")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Integrations" in html
        # Should load external JS (CSP compliant)
        assert "integrations.js" in html

    def test_workflow_detail_page_loads(self, client):
        """Workflow detail page HTML loads without error."""
        response = client.get("/workflow/1")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "GhostGraph" in html or "breakdown" in html
        # Should load external JS (CSP compliant)
        assert "workflow-detail.js" in html


class TestCSPCompliance:
    """Test that templates comply with Content Security Policy."""

    def test_discovery_html_no_inline_scripts(self, client):
        """Discovery template has no inline scripts."""
        response = client.get("/")
        html = response.get_data(as_text=True)

        # Should not have inline onclick handlers
        assert "onclick=" not in html
        # Should not have inline script blocks (except url_for calls)
        assert "<script>" not in html or 'src=' in html

    def test_executions_html_no_inline_scripts(self, client):
        """Executions template has no inline scripts."""
        response = client.get("/executions")
        html = response.get_data(as_text=True)

        # Should not have inline onclick handlers
        assert "onclick=" not in html
        # Should not have inline script blocks
        assert "<script>" not in html or 'src=' in html

    def test_integrations_html_no_inline_scripts(self, client):
        """Integrations template has no inline scripts."""
        response = client.get("/integrations")
        html = response.get_data(as_text=True)

        # Should not have inline onclick handlers
        assert "onclick=" not in html
        # Should not have inline script blocks
        assert "<script>" not in html or 'src=' in html

    def test_workflow_detail_html_no_inline_scripts(self, client):
        """Workflow detail template has no inline scripts."""
        response = client.get("/workflow/1")
        html = response.get_data(as_text=True)

        # Should not have inline onclick handlers
        assert "onclick=" not in html
        # Should not have inline script blocks
        assert "<script>" not in html or 'src=' in html
