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

import pytest

from app import create_app


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
