"""Tests for Freshdesk REST API v2 integration service."""

from unittest.mock import MagicMock, patch

import pytest

from schemas.freshdesk_responses import FreshDeskTicket
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    extract_invoice_id,
    extract_refund_amount,
    get_ticket,
)


class TestGetTicket:
    """Test Freshdesk ticket fetching."""

    def test_successful_ticket_fetch(self):
        """Successfully fetch and normalize a Freshdesk ticket."""
        mock_response_data = {
            "id": 2048,
            "subject": "Refund request for INV-88421",
            "description": "Customer requests refund for unsatisfactory service",
            "requester_id": 42,
            "requester": {"name": "Aditi Rao"},
            "status_name": "Open",
            "priority": 2,
            "created_at": "2026-09-24T10:00:00Z",
            "custom_fields": {
                "cf_refund_amount": 32000.0,
                "cf_invoice_id": "INV-88421"
            }
        }

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key-12345"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.ok = True
                mock_response.json.return_value = mock_response_data
                mock_get.return_value = mock_response

                result = get_ticket(2048)

                assert isinstance(result, FreshDeskTicket)
                assert result.ticket_id == 2048
                assert result.subject == "Refund request for INV-88421"
                assert result.requester_name == "Aditi Rao"
                assert result.custom_fields["cf_refund_amount"] == 32000.0

                # Verify API was called correctly
                mock_get.assert_called_once()
                call_args = mock_get.call_args
                assert "2048" in call_args[0][0]
                assert call_args[1]["timeout"] == (3, 10)

    def test_missing_credentials_raises_error(self):
        """Raises FreshDeskUnavailableError when neither MCP nor REST is configured."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = None
            mock_config.MCP_FRESHDESK_URL = None
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = None

            with pytest.raises(FreshDeskUnavailableError):
                get_ticket(2048)

    def test_missing_domain_raises_error(self):
        """Raises FreshDeskUnavailableError when only domain is missing (and MCP absent)."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = "test-key"
            mock_config.MCP_FRESHDESK_URL = None
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = None

            with pytest.raises(FreshDeskUnavailableError):
                get_ticket(2048)

    def test_missing_api_key_raises_error(self):
        """Raises FreshDeskUnavailableError when only API key is missing (and MCP absent)."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = None
            mock_config.MCP_FRESHDESK_URL = None
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = None

            with pytest.raises(FreshDeskUnavailableError):
                get_ticket(2048)

    def test_authentication_failure_401(self):
        """Raises FreshDeskError on 401 authentication failure."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "invalid-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_get.return_value = mock_response

                with pytest.raises(FreshDeskError, match="Authentication failed"):
                    get_ticket(2048)

    def test_authorization_failure_403(self):
        """Raises FreshDeskError on 403 authorization failure."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 403
                mock_get.return_value = mock_response

                with pytest.raises(FreshDeskError, match="Authorization failed"):
                    get_ticket(2048)

    def test_ticket_not_found_404(self):
        """Raises FreshDeskError on 404 ticket not found."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                with pytest.raises(FreshDeskError, match="not found"):
                    get_ticket(2048)

    def test_server_error_500(self):
        """Raises FreshDeskError on 500 server error."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 500
                mock_get.return_value = mock_response

                with pytest.raises(FreshDeskError, match="server error"):
                    get_ticket(2048)

    def test_timeout_error(self):
        """Raises FreshDeskError on request timeout."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                import requests
                mock_get.side_effect = requests.Timeout("API timeout")

                with pytest.raises(FreshDeskError, match="timeout"):
                    get_ticket(2048)

    def test_connection_error(self):
        """Raises FreshDeskError on connection failure."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                import requests
                mock_get.side_effect = requests.ConnectionError("Network unavailable")

                with pytest.raises(FreshDeskError, match="connection error"):
                    get_ticket(2048)

    def test_normalized_ticket_with_minimal_fields(self):
        """Handles tickets with minimal fields gracefully."""
        mock_response_data = {
            "id": 2048,
            "subject": "Simple ticket",
            "description": "No extra fields"
        }

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.ok = True
                mock_response.json.return_value = mock_response_data
                mock_get.return_value = mock_response

                result = get_ticket(2048)

                assert result.ticket_id == 2048
                assert result.subject == "Simple ticket"
                assert result.requester_name is None
                assert result.custom_fields == {}

    def test_api_key_not_logged(self):
        """Ensures API key is never logged."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "super-secret-key-12345"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.ok = True
                mock_response.json.return_value = {"id": 1, "subject": "test"}
                mock_get.return_value = mock_response

                with patch("services.freshdesk_service.logger") as mock_logger:
                    get_ticket(1)

                    # Check all log calls don't contain API key
                    for call in mock_logger.method_calls:
                        call_str = str(call)
                        assert "super-secret-key-12345" not in call_str


class TestExtractRefundAmount:
    """Test refund amount extraction."""

    def test_extract_from_custom_field(self):
        """Extracts refund amount from custom field."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund",
            description_text="Test",
            custom_fields={"cf_refund_amount": 32000.0}
        )

        amount = extract_refund_amount(ticket)
        assert amount == 32000.0

    def test_extract_from_custom_field_string(self):
        """Handles string refund amount in custom field."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund",
            description_text="Test",
            custom_fields={"cf_refund_amount": "50000"}
        )

        amount = extract_refund_amount(ticket)
        assert amount == 50000.0

    def test_extract_from_description_rupee_symbol(self):
        """Extracts amount with rupee symbol from description."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund needed",
            description_text="Please refund ₹75000 for this order",
            custom_fields={}
        )

        amount = extract_refund_amount(ticket)
        assert amount == 75000.0

    def test_extract_from_description_plain_number(self):
        """Extracts plain number from description."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund",
            description_text="Amount: 25000",
            custom_fields={}
        )

        amount = extract_refund_amount(ticket)
        assert amount == 25000.0

    def test_returns_none_when_not_found(self):
        """Returns None when no amount found."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Support request",
            description_text="Need technical help",
            custom_fields={}
        )

        amount = extract_refund_amount(ticket)
        assert amount is None


class TestExtractInvoiceId:
    """Test invoice ID extraction."""

    def test_extract_from_custom_field(self):
        """Extracts invoice ID from custom field."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund",
            description_text="Test",
            custom_fields={"cf_invoice_id": "INV-88421"}
        )

        invoice_id = extract_invoice_id(ticket)
        assert invoice_id == "INV-88421"

    def test_extract_from_description(self):
        """Extracts invoice ID from description."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund for INV-88421",
            description_text="Customer purchased on invoice INV-88421",
            custom_fields={}
        )

        invoice_id = extract_invoice_id(ticket)
        assert invoice_id == "INV-88421"

    def test_extract_invoice_underscore_format(self):
        """Handles INV_88421 format."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Refund",
            description_text="Invoice: INV_88421",
            custom_fields={}
        )

        invoice_id = extract_invoice_id(ticket)
        assert invoice_id == "INV-88421"

    def test_returns_none_when_not_found(self):
        """Returns None when no invoice ID found."""
        ticket = FreshDeskTicket(
            ticket_id=1,
            subject="Support request",
            description_text="General support issue",
            custom_fields={}
        )

        invoice_id = extract_invoice_id(ticket)
        assert invoice_id is None


class TestContextAgentWithFreshdesk:
    """Test context_agent integration with Freshdesk."""

    def test_context_agent_fetches_from_freshdesk(self):
        """Context agent fetches and processes Freshdesk ticket."""
        from agents.context_agent import run

        mock_freshdesk_ticket = FreshDeskTicket(
            ticket_id=2048,
            subject="Refund request for INV-88421",
            description_text="Customer requests refund",
            requester_name="Aditi Rao",
            custom_fields={"cf_refund_amount": 32000.0}
        )

        with patch("agents.context_agent.get_ticket") as mock_get:
            with patch("agents.context_agent.extract_ticket_context") as mock_claude:
                from schemas.claude_responses import TicketContext

                mock_get.return_value = mock_freshdesk_ticket
                mock_claude.return_value = TicketContext(
                    issue_category="refund",
                    issue_summary="Refund request",
                    refund_amount_mentioned=None,
                    confidence_score=0.9
                )

                result = run({"ticket_id": 2048})

                assert result["status"] == "SUCCESS"
                assert result["result"]["source"] == "freshdesk"
                assert result["result"]["context"]["issue_category"] == "refund"
                assert result["result"]["context"]["refund_amount_mentioned"] == 32000.0
                assert result["result"]["context"]["customer_name"] == "Aditi Rao"

    def test_context_agent_fallback_when_freshdesk_unavailable(self):
        """Context agent falls back when Freshdesk not configured."""
        from agents.context_agent import run

        with patch("agents.context_agent.get_ticket") as mock_get:
            with patch("agents.context_agent.extract_ticket_context") as mock_claude:
                from schemas.claude_responses import TicketContext

                mock_get.side_effect = FreshDeskUnavailableError("Not configured")
                mock_claude.return_value = TicketContext(
                    issue_category="support",
                    issue_summary="Test",
                    confidence_score=0.5
                )

                result = run({"ticket_id": 2048})

                assert result["status"] == "SUCCESS"
                assert result["result"]["source"] == "fallback"

    def test_context_agent_fallback_on_freshdesk_error(self):
        """Context agent falls back when Freshdesk API error occurs."""
        from agents.context_agent import run

        with patch("agents.context_agent.get_ticket") as mock_get:
            with patch("agents.context_agent.extract_ticket_context") as mock_claude:
                from schemas.claude_responses import TicketContext

                mock_get.side_effect = FreshDeskError("API error")
                mock_claude.return_value = TicketContext(
                    issue_category="support",
                    issue_summary="Test",
                    confidence_score=0.3
                )

                result = run({"ticket_id": 2048})

                assert result["status"] == "SUCCESS"
                assert result["result"]["source"] == "fallback_error"

    def test_context_agent_no_real_api_calls(self):
        """Verify context_agent never makes real API calls during test."""
        from agents.context_agent import run

        with patch("agents.context_agent.get_ticket") as mock_get:
            with patch("agents.context_agent.extract_ticket_context") as mock_claude:
                from schemas.claude_responses import TicketContext

                # Simulate Freshdesk not configured
                mock_get.side_effect = FreshDeskUnavailableError("Not configured")
                mock_claude.return_value = TicketContext(
                    issue_category="support",
                    issue_summary="Test",
                    confidence_score=0.0
                )

                result = run({"ticket_id": 123, "ticket_text": "Test"})

                assert result["status"] == "SUCCESS"
                # Verify mocks were called, not real functions
                mock_get.assert_called_once_with(123)
                mock_claude.assert_called_once()


class TestMCPProviderSelectionAndFallback:
    """Regression tests for the freshdesk=false bug and the silent-fallback risk.

    Root cause #1: get_ticket()/add_note()/verify_note_exists() gated on
    REST-only credentials before ever trying MCP, so an MCP-only setup
    (no FRESHDESK_DOMAIN/FRESHDESK_API_KEY) raised FreshDeskUnavailableError
    without attempting MCP at all.

    Root cause #2: _use_mcp_provider() had dead code
    ("... in sys.modules or True") that always returned True regardless of
    whether MCP was actually configured.
    """

    def test_get_ticket_uses_mcp_when_only_mcp_configured(self):
        """An MCP-only setup (no REST vars) must not raise unavailable and must use MCP."""
        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_PROVIDER = "mcp"
            mock_config.MCP_FRESHDESK_URL = "https://example.freshdesk.com/mcp"
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = "fwapi_test_token"
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = None

            with patch("services.freshdesk_mcp_adapter.is_configured", return_value=True):
                with patch("services.freshdesk_mcp_adapter.fetch_ticket") as mock_fetch:
                    mock_fetch.return_value = FreshDeskTicket(
                        ticket_id=1,
                        subject="Test via MCP",
                        description_text="",
                        requester_id=None,
                        requester_name=None,
                        status=None,
                        priority=1,
                        created_at=None,
                        custom_fields={},
                        raw_response={},
                    )

                    result = get_ticket(1)

                    assert result.subject == "Test via MCP"
                    mock_fetch.assert_called_once_with(1)

    def test_mcp_failure_does_not_silently_fall_back_when_disabled(self):
        """allow_rest_fallback=False must propagate MCP errors, never mask them via REST."""
        from services.freshdesk_mcp_adapter import FreshDeskMCPError

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_PROVIDER = "mcp"
            mock_config.MCP_FRESHDESK_URL = "https://example.freshdesk.com/mcp"
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = "fwapi_test_token"
            # REST is fully configured too - it must NOT be used to mask an MCP failure.
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "some-rest-key"

            with patch("services.freshdesk_mcp_adapter.is_configured", return_value=True):
                with patch("services.freshdesk_mcp_adapter.fetch_ticket") as mock_fetch:
                    mock_fetch.side_effect = FreshDeskMCPError("simulated MCP outage")

                    with patch("services.freshdesk_service.requests.get") as mock_rest_get:
                        with pytest.raises(FreshDeskMCPError):
                            get_ticket(1, allow_rest_fallback=False)

                        # REST must never have been attempted - no silent masking.
                        mock_rest_get.assert_not_called()

    def test_mcp_failure_does_not_fall_back_by_default(self):
        """With FRESHDESK_ALLOW_REST_FALLBACK=false (the default), MCP errors propagate."""
        from services.freshdesk_mcp_adapter import FreshDeskMCPError

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_PROVIDER = "mcp"
            mock_config.FRESHDESK_ALLOW_REST_FALLBACK = False
            mock_config.MCP_FRESHDESK_URL = "https://example.freshdesk.com/mcp"
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = "fwapi_test_token"
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "some-rest-key"

            with patch("services.freshdesk_mcp_adapter.fetch_ticket") as mock_fetch:
                mock_fetch.side_effect = FreshDeskMCPError("simulated MCP outage")
                with patch("services.freshdesk_service.requests.get") as mock_rest_get:
                    with pytest.raises(FreshDeskMCPError):
                        get_ticket(1)
                    mock_rest_get.assert_not_called()

    def test_mcp_failure_falls_back_to_rest_when_fallback_allowed(self):
        """FRESHDESK_ALLOW_REST_FALLBACK=true opts back in to REST resilience."""
        from services.freshdesk_mcp_adapter import FreshDeskMCPError

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_PROVIDER = "mcp"
            mock_config.FRESHDESK_ALLOW_REST_FALLBACK = True
            mock_config.MCP_FRESHDESK_URL = "https://example.freshdesk.com/mcp"
            mock_config.MCP_FRESHDESK_AUTH_TOKEN = "fwapi_test_token"
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "some-rest-key"

            with patch("services.freshdesk_mcp_adapter.is_configured", return_value=True):
                with patch("services.freshdesk_mcp_adapter.fetch_ticket") as mock_fetch:
                    mock_fetch.side_effect = FreshDeskMCPError("simulated MCP outage")

                    with patch("services.freshdesk_service.requests.get") as mock_rest_get:
                        mock_response = MagicMock()
                        mock_response.status_code = 200
                        mock_response.ok = True
                        mock_response.json.return_value = {"id": 1, "subject": "via REST fallback"}
                        mock_rest_get.return_value = mock_response

                        result = get_ticket(1)  # default allow_rest_fallback=True

                        assert result.subject == "via REST fallback"
                        mock_rest_get.assert_called_once()
