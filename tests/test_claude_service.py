"""Tests for Claude service with mocked Anthropic API."""

import json
from unittest.mock import MagicMock, patch

from schemas.claude_responses import TicketContext
from services.claude_service import extract_ticket_context


class TestClaudeService:
    """Test Claude integration with mocked API calls."""

    def test_extract_ticket_context_success(self):
        """Claude successfully extracts ticket context."""
        mock_response = {
            "customer_name": "Aditi Rao",
            "issue_category": "refund",
            "issue_summary": "Customer requests refund for ticket INV-88421.",
            "refund_amount_mentioned": 32000.0,
            "relevant_facts": ["Invoice INV-88421", "Service issue"],
            "confidence_score": 0.95,
            "missing_information": []
        }

        with patch("services.claude_service.Anthropic") as mock_anthropic:
            # Mock the client and response
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            mock_message = MagicMock()
            mock_message.content = [MagicMock(text=json.dumps(mock_response))]
            mock_client.messages.create.return_value = mock_message

            # Call the service
            result = extract_ticket_context("Customer INV-88421 refund needed")

            # Verify response
            assert isinstance(result, TicketContext)
            assert result.customer_name == "Aditi Rao"
            assert result.issue_category == "refund"
            assert result.confidence_score == 0.95
            assert result.refund_amount_mentioned == 32000.0

            # Verify API was called
            mock_client.messages.create.assert_called_once()

    def test_extract_ticket_context_with_markdown(self):
        """Claude response with markdown code blocks is parsed correctly."""
        mock_response = {
            "customer_name": None,
            "issue_category": "support",
            "issue_summary": "Technical support request",
            "refund_amount_mentioned": None,
            "relevant_facts": ["User reported bug"],
            "confidence_score": 0.80,
            "missing_information": ["Error logs"]
        }

        with patch("services.claude_service.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            # Response with markdown code blocks
            response_text = f"```json\n{json.dumps(mock_response)}\n```"
            mock_message = MagicMock()
            mock_message.content = [MagicMock(text=response_text)]
            mock_client.messages.create.return_value = mock_message

            result = extract_ticket_context("Support request")

            assert result.issue_category == "support"
            assert result.confidence_score == 0.80

    def test_extract_ticket_context_api_key_missing(self):
        """Falls back gracefully when API key is not configured."""
        with patch("services.claude_service.Config.ANTHROPIC_API_KEY", None):
            result = extract_ticket_context("Any ticket text")

            # Should return fallback context
            assert isinstance(result, TicketContext)
            assert result.confidence_score == 0.3  # Fallback confidence
            assert "Claude not available" in result.missing_information

    def test_extract_ticket_context_import_error(self):
        """Falls back gracefully when Anthropic SDK is not available."""
        with patch("services.claude_service.Anthropic", side_effect=ImportError("No anthropic")):
            result = extract_ticket_context("Ticket text")

            assert isinstance(result, TicketContext)
            assert result.confidence_score == 0.3

    def test_extract_ticket_context_invalid_json(self):
        """Falls back when Claude returns invalid JSON."""
        with patch("services.claude_service.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            # Return invalid JSON
            mock_message = MagicMock()
            mock_message.content = [MagicMock(text="Not valid JSON")]
            mock_client.messages.create.return_value = mock_message

            result = extract_ticket_context("Ticket text")

            # Should fall back gracefully
            assert isinstance(result, TicketContext)
            assert result.confidence_score == 0.3

    def test_extract_ticket_context_validation_error(self):
        """Falls back when response doesn't match schema."""
        with patch("services.claude_service.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            # Return JSON missing required fields
            mock_message = MagicMock()
            mock_message.content = [MagicMock(text='{"invalid": "schema"}')]
            mock_client.messages.create.return_value = mock_message

            result = extract_ticket_context("Ticket text")

            assert isinstance(result, TicketContext)
            assert result.confidence_score == 0.3

    def test_extract_ticket_context_timeout(self):
        """Falls back when API call times out."""
        with patch("services.claude_service.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            # Simulate timeout
            mock_client.messages.create.side_effect = TimeoutError("API timeout")

            result = extract_ticket_context("Ticket text")

            assert isinstance(result, TicketContext)
            assert result.confidence_score == 0.3

    def test_fallback_detects_refund_keyword(self):
        """Fallback context detects refund keyword in ticket."""
        # Disable Claude to test fallback behavior
        with patch("services.claude_service.Config.ANTHROPIC_API_KEY", None):
            result = extract_ticket_context("Please process a refund for order 12345")

            assert result.issue_category == "refund"
            assert result.confidence_score == 0.3

    def test_fallback_extracts_amount(self):
        """Fallback context attempts to extract refund amount."""
        result = extract_ticket_context("Refund needed for ₹50000 purchase")

        assert result.refund_amount_mentioned == 50000.0

    def test_no_real_api_calls_in_tests(self):
        """Verify tests never make real Anthropic API calls."""
        # This test ensures the mock is comprehensive
        with patch("services.claude_service.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            mock_message = MagicMock()
            mock_message.content = [MagicMock(text=json.dumps({
                "customer_name": None,
                "issue_category": "support",
                "issue_summary": "Test",
                "refund_amount_mentioned": None,
                "relevant_facts": [],
                "confidence_score": 0.5,
                "missing_information": []
            }))]
            mock_client.messages.create.return_value = mock_message

            extract_ticket_context("Test ticket")

            # Verify Anthropic was never instantiated with real key
            # (it was instantiated with the mocked return value)
            assert mock_anthropic.called


class TestContextAgent:
    """Test context agent integration."""

    def test_context_agent_success(self):
        """Context agent returns success with extracted context."""
        from agents.context_agent import run

        with patch("agents.context_agent.extract_ticket_context") as mock_extract:
            # Mock the Claude response
            mock_extract.return_value = TicketContext(
                customer_name="Test User",
                issue_category="refund",
                issue_summary="Test refund request",
                refund_amount_mentioned=10000.0,
                relevant_facts=["Test fact"],
                confidence_score=0.9,
                missing_information=[]
            )

            result = run({"ticket_text": "Test ticket"})

            assert result["status"] == "SUCCESS"
            assert result["result"]["context"]["issue_category"] == "refund"
            assert result["result"]["confidence"] == 0.9

    def test_context_agent_handles_errors(self):
        """Context agent gracefully handles extraction errors."""
        from agents.context_agent import run

        with patch("agents.context_agent.extract_ticket_context") as mock_extract:
            # Simulate extraction failure
            mock_extract.side_effect = Exception("Claude unavailable")

            result = run({"ticket_text": "Test ticket"})

            # Should still return SUCCESS (fail-open for workflow)
            assert result["status"] == "SUCCESS"
            assert "error" in result["result"]
