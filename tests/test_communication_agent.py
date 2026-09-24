"""Tests for communication agent (Freshdesk write-back)."""

from unittest.mock import MagicMock, patch

import pytest

from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
)


class TestCommunicationAgent:
    """Test communication agent Freshdesk write-back."""

    def test_successful_freshdesk_write_back(self):
        """Successfully writes note to Freshdesk after approval."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("agents.communication_agent.add_note") as mock_add_note:
                mock_add_note.return_value = {
                    "status": "success",
                    "note_id": 12345,
                    "ticket_id": 2048
                }

                result = run({
                    "ticket_id": 2048,
                    "source": "freshdesk",
                    "refund_amount": 32000.0,
                    "execution_id": "exec-001"
                })

                assert result["status"] == "SUCCESS"
                assert result["result"]["action_performed"] is True
                assert result["result"]["writeback_status"] == "success"
                assert result["result"]["note_id"] == 12345
                assert "freshdesk-note-12345" in result["result"]["external_reference"]

                # Verify add_note was called with correct content
                mock_add_note.assert_called_once()
                call_args = mock_add_note.call_args
                assert call_args[0][0] == 2048  # ticket_id
                assert "₹32,000.00" in call_args[0][1]  # amount in note body
                assert "exec-001" in call_args[0][1]  # execution_id in note body

    def test_no_write_back_for_fallback_source(self):
        """Skips write-back when source is fallback (not Freshdesk)."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.add_note") as mock_add_note:
            result = run({
                "ticket_id": 2048,
                "source": "fallback",
                "refund_amount": 32000.0
            })

            assert result["status"] == "SUCCESS"
            assert result["result"]["action_performed"] is False
            assert result["result"]["writeback_status"] == "skipped"
            # Verify add_note was never called
            mock_add_note.assert_not_called()

    def test_no_write_back_when_missing_ticket_id(self):
        """Skips write-back when ticket_id is missing."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.add_note") as mock_add_note:
            result = run({
                "source": "freshdesk",
                "refund_amount": 32000.0
            })

            assert result["status"] == "SUCCESS"
            assert result["result"]["action_performed"] is False
            assert result["result"]["writeback_status"] == "skipped"
            mock_add_note.assert_not_called()

    def test_fallback_when_freshdesk_not_configured(self):
        """Falls back gracefully when Freshdesk not configured."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = None

            with patch("agents.communication_agent.add_note") as mock_add_note:
                result = run({
                    "ticket_id": 2048,
                    "source": "freshdesk",
                    "refund_amount": 32000.0
                })

                assert result["status"] == "SUCCESS"
                assert result["result"]["action_performed"] is False
                assert result["result"]["writeback_status"] == "fallback_unavailable"
                mock_add_note.assert_not_called()

    def test_fallback_when_freshdesk_unavailable_error(self):
        """Falls back when Freshdesk raises unavailable error."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("agents.communication_agent.add_note") as mock_add_note:
                mock_add_note.side_effect = FreshDeskUnavailableError("Not available")

                result = run({
                    "ticket_id": 2048,
                    "source": "freshdesk",
                    "refund_amount": 32000.0
                })

                assert result["status"] == "SUCCESS"
                assert result["result"]["action_performed"] is False
                assert result["result"]["writeback_status"] == "fallback_unavailable"

    def test_fallback_when_freshdesk_error(self):
        """Falls back when Freshdesk returns an error."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("agents.communication_agent.add_note") as mock_add_note:
                mock_add_note.side_effect = FreshDeskError("API error")

                result = run({
                    "ticket_id": 2048,
                    "source": "freshdesk"
                })

                assert result["status"] == "SUCCESS"
                assert result["result"]["action_performed"] is False
                assert result["result"]["writeback_status"] == "error"
                assert result["result"]["error_category"] == "freshdesk_error"

    def test_note_content_with_refund_amount(self):
        """Verifies note content includes refund amount."""
        from agents.communication_agent import _build_note_content

        note = _build_note_content(refund_amount=32000.0, execution_id="exec-001")

        assert "GhostWork refund workflow approved by human reviewer" in note
        assert "₹32,000.00" in note
        assert "exec-001" in note
        assert "Automated checks completed successfully" in note

    def test_note_content_without_optional_fields(self):
        """Verifies note content works without optional fields."""
        from agents.communication_agent import _build_note_content

        note = _build_note_content()

        assert "GhostWork refund workflow approved by human reviewer" in note
        assert "Automated checks completed successfully" in note
        # Should not have execution ID line if not provided
        assert "Execution ID:" not in note or "None" not in note

    def test_note_content_with_execution_id_only(self):
        """Verifies note content with execution_id but no amount."""
        from agents.communication_agent import _build_note_content

        note = _build_note_content(execution_id="exec-123")

        assert "exec-123" in note
        assert "Execution ID: exec-123" in note

    def test_always_returns_success_status(self):
        """Communication agent always returns SUCCESS (fail-open)."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.add_note") as mock_add_note:
            mock_add_note.side_effect = Exception("Unexpected error")

            result = run({
                "ticket_id": 2048,
                "source": "freshdesk"
            })

            # Should never crash; always succeed
            assert result["status"] == "SUCCESS"

    def test_api_key_never_logged_in_errors(self):
        """Ensures API key is never logged in error messages."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "super-secret-api-key-12345"

            with patch("agents.communication_agent.add_note") as mock_add_note:
                mock_add_note.side_effect = FreshDeskError("Auth failed")

                with patch("agents.communication_agent.logger") as mock_logger:
                    run({
                        "ticket_id": 2048,
                        "source": "freshdesk"
                    })

                    # Check all log calls don't contain API key
                    for call in mock_logger.method_calls:
                        call_str = str(call)
                        assert "super-secret-api-key-12345" not in call_str

    def test_no_real_api_calls(self):
        """Verify communication agent never makes real Freshdesk calls."""
        from agents.communication_agent import run

        with patch("agents.communication_agent.add_note") as mock_add_note:
            with patch("agents.communication_agent.Config") as mock_config:
                mock_config.FRESHDESK_DOMAIN = "test.com"
                mock_config.FRESHDESK_API_KEY = "test"
                mock_add_note.return_value = {"note_id": 1}

                result = run({
                    "ticket_id": 2048,
                    "source": "freshdesk"
                })

                assert result["status"] == "SUCCESS"
                # Verify mock was called, not real function
                mock_add_note.assert_called_once()


class TestAddNoteFunction:
    """Test Freshdesk add_note function directly."""

    def test_successful_note_creation(self):
        """Successfully creates a note on Freshdesk ticket."""
        from services.freshdesk_service import add_note

        mock_response_data = {
            "id": 12345,
            "body": "Test note",
            "user_id": 1
        }

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 201
                mock_response.ok = True
                mock_response.json.return_value = mock_response_data
                mock_post.return_value = mock_response

                result = add_note(2048, "Test note")

                assert result["status"] == "success"
                assert result["note_id"] == 12345
                assert result["ticket_id"] == 2048

                # Verify API was called correctly
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                assert "2048/notes" in call_args[0][0]
                assert call_args[1]["json"]["body"] == "Test note"
                assert call_args[1]["timeout"] == (3, 10)

    def test_add_note_authentication_failure(self):
        """Raises FreshDeskError on 401 authentication failure."""
        from services.freshdesk_service import add_note

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "invalid-key"

            with patch("services.freshdesk_service.requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_post.return_value = mock_response

                with pytest.raises(FreshDeskError, match="Authentication failed"):
                    add_note(2048, "Test note")

    def test_add_note_authorization_failure(self):
        """Raises FreshDeskError on 403 authorization failure."""
        from services.freshdesk_service import add_note

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 403
                mock_post.return_value = mock_response

                with pytest.raises(FreshDeskError, match="Authorization failed"):
                    add_note(2048, "Test note")

    def test_add_note_ticket_not_found(self):
        """Raises FreshDeskError on 404 ticket not found."""
        from services.freshdesk_service import add_note

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_post.return_value = mock_response

                with pytest.raises(FreshDeskError, match="not found"):
                    add_note(2048, "Test note")

    def test_add_note_timeout(self):
        """Raises FreshDeskError on timeout."""
        from services.freshdesk_service import add_note

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.post") as mock_post:
                import requests
                mock_post.side_effect = requests.Timeout("timeout")

                with pytest.raises(FreshDeskError, match="timeout"):
                    add_note(2048, "Test note")

    def test_add_note_connection_error(self):
        """Raises FreshDeskError on connection error."""
        from services.freshdesk_service import add_note

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.post") as mock_post:
                import requests
                mock_post.side_effect = requests.ConnectionError("connection error")

                with pytest.raises(FreshDeskError, match="connection error"):
                    add_note(2048, "Test note")

    def test_add_note_not_configured(self):
        """Raises FreshDeskUnavailableError when not configured."""
        from services.freshdesk_service import add_note

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = None

            with pytest.raises(FreshDeskUnavailableError):
                add_note(2048, "Test note")
