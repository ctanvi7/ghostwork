"""Shared test fixtures and configuration."""

import os

# Set DB_BACKEND before any imports
os.environ["DB_BACKEND"] = "memory"

# Keep tests hermetic: never let the suite reach the real Freshdesk account.
# load_dotenv() does not override variables that are already set, so these
# empty values win over any live credentials in .env.
os.environ["MCP_FRESHDESK_URL"] = ""
os.environ["MCP_FRESHDESK_AUTH_TOKEN"] = ""
os.environ["FRESHDESK_DOMAIN"] = ""
os.environ["FRESHDESK_API_KEY"] = ""
# Tests use the default field name, whatever the live account calls it.
os.environ["FRESHDESK_REFUND_AMOUNT_FIELD"] = "cf_refund_amount"
# Same for Claude, Sarvam and Vobiz: tests that exercise them mock the provider
# and set a fake key themselves, so the suite never calls (or bills) a real API.
for _name in ("ANTHROPIC_API_KEY", "SARVAM_API_KEY", "VOBIZ_API_KEY", "VOBIZ_AUTH_ID",
              "VOBIZ_AUTH_TOKEN", "VOBIZ_FROM_NUMBER", "APPROVER_PHONE", "FRESHDESK_FALLBACK",
              "REQUIRE_APPROVER_AUTH"):
    os.environ[_name] = ""
os.environ["PUBLIC_BASE_URL"] = "http://localhost:5000"
os.environ["FRESHDESK_DEMO_TICKET_ID"] = "2048"
# Sign-in off by default in tests; auth tests turn it on explicitly.
os.environ["AUTH_REQUIRED"] = "false"
os.environ["REGISTRATION_CODE"] = ""

import socket  # noqa: E402 (env vars above must be set first)

import pytest  # noqa: E402

from app import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail fast if code under test tries to reach a real host (DNS lookup is blocked)."""
    def blocked(*args, **kwargs):
        raise OSError("Network access is disabled in tests")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def app():
    """Create application for testing."""
    # Reset the service singleton so a new one is created with the memory backend
    import services.supabase_service as svc_module
    svc_module._service = None

    app = create_app({"TESTING": True})

    # Clear data between tests
    from services.supabase_service import get_service
    get_service().clear_all()

    yield app

    # Cleanup after each test
    svc_module._service = None


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Flask CLI test runner."""
    return app.test_cli_runner()
