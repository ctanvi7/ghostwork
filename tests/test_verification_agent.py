"""Tests for verification agent (external action verification)."""

from unittest.mock import MagicMock, patch

import pytest

from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
)


class TestVerificationAgent:
    """Test verification agent external action verification."""

    def test_required_approval_record_is_verified(self, app):
        from agents.verification_agent import run
        from services.supabase_service import get_service

        service = get_service()
        execution_id = service.create_execution(1, ticket_id=2048, refund_amount=32000)
        execution = service.get_execution(execution_id)
        context = {"communication_agent": {"result": {"action_performed": False, "source": "fallback"}}}

        missing = run(execution, context)
        assert missing["status"] == "FAILED"
        assert missing["result"]["verification_status"] == "approval_missing"

        approval_id = service.create_approval(execution_id, amount=32000)
        service.update_approval(approval_id, status="APPROVED")
        approved = run(execution, context)
        assert approved["status"] == "SUCCESS"

    def test_successful_note_verification(self):
        """Successfully verifies that note was created on Freshdesk."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("agents.verification_agent.verify_note_exists") as mock_verify:
                mock_verify.return_value = {
                    "verified": True,
                    "matched_note_id": 12345,
                    "ticket_id": 2048,
                    "reason": "Note 12345 found"
                }

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "writeback_status": "success",
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "external_reference": "freshdesk-note-12345",
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                assert result["status"] == "SUCCESS"
                assert result["result"]["verified"] is True
                assert result["result"]["verification_status"] == "verified"
                assert result["result"]["matched_note_id"] == 12345

    def test_verification_fails_when_note_not_found(self):
        """Returns FAILED when expected note not found on Freshdesk."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.verify_note_exists") as mock_verify:
            mock_verify.return_value = {
                "verified": False,
                "matched_note_id": None,
                "ticket_id": 2048,
                "reason": "Note not found"
            }

            with patch("agents.verification_agent.Config") as mock_config:
                mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
                mock_config.FRESHDESK_API_KEY = "test-key"

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "writeback_status": "success",
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                # Critical: MUST return FAILED so execution doesn't mark as COMPLETED
                assert result["status"] == "FAILED"
                assert result["result"]["verified"] is False
                assert result["result"]["verification_status"] == "verification_failed"

    def test_skips_verification_when_no_action_performed(self):
        """Skips verification when communication_agent skipped write-back."""
        from agents.verification_agent import run

        context = {
            "communication_agent": {
                "result": {
                    "action_performed": False,
                    "writeback_status": "skipped",
                    "source": "fallback"
                }
            }
        }

        result = run({}, context=context)

        assert result["status"] == "SUCCESS"
        assert result["result"]["verified"] is False
        assert result["result"]["verification_status"] == "skipped_fallback"

    def test_skips_verification_for_fallback_source(self):
        """Skips verification when source is fallback (demo mode)."""
        from agents.verification_agent import run

        context = {
            "communication_agent": {
                "result": {
                    "action_performed": False,
                    "writeback_status": "skipped",
                    "source": "fallback"
                }
            }
        }

        result = run({}, context=context)

        assert result["status"] == "SUCCESS"
        assert result["result"]["verification_status"] == "skipped_fallback"

    def test_fails_when_freshdesk_unavailable_after_write(self):
        """Returns FAILED when Freshdesk unavailable during verification."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.verify_note_exists") as mock_verify:
            mock_verify.side_effect = FreshDeskUnavailableError("Not available")

            with patch("agents.verification_agent.Config") as mock_config:
                mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
                mock_config.FRESHDESK_API_KEY = "test-key"

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "writeback_status": "success",
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                # Critical: MUST return FAILED so execution doesn't mark as COMPLETED
                assert result["status"] == "FAILED"
                assert result["result"]["verification_status"] == "unavailable"

    def test_fails_on_freshdesk_error(self):
        """Returns FAILED when Freshdesk API error occurs."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.verify_note_exists") as mock_verify:
            mock_verify.side_effect = FreshDeskError("API error")

            with patch("agents.verification_agent.Config") as mock_config:
                mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
                mock_config.FRESHDESK_API_KEY = "test-key"

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "writeback_status": "success",
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                assert result["status"] == "FAILED"
                assert result["result"]["verification_status"] == "error"

    def test_skips_when_no_communication_result(self):
        """Skips verification when communication_agent result missing (demo mode)."""
        from agents.verification_agent import run

        context = {}  # Empty context

        result = run({}, context=context)

        assert result["status"] == "SUCCESS"
        assert result["result"]["verification_status"] == "skipped_fallback"

    def test_fails_when_ticket_id_missing(self):
        """Returns FAILED when ticket_id missing from communication result."""
        from agents.verification_agent import run

        context = {
            "communication_agent": {
                "result": {
                    "action_performed": True,
                    "writeback_status": "success",
                    "note_id": 12345
                    # Missing ticket_id
                }
            }
        }

        result = run({}, context=context)

        assert result["status"] == "FAILED"
        assert result["result"]["verification_status"] == "verification_failed"

    def test_fails_when_freshdesk_not_configured_after_write(self):
        """Returns FAILED when Freshdesk not configured but action was performed."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = None

            context = {
                "communication_agent": {
                    "result": {
                        "action_performed": True,
                        "writeback_status": "success",
                        "ticket_id": 2048,
                        "note_id": 12345,
                        "source": "freshdesk"
                    }
                }
            }

            result = run({}, context=context)

            # Critical: MUST return FAILED so execution doesn't mark as COMPLETED
            assert result["status"] == "FAILED"
            assert result["result"]["verification_status"] == "unavailable"

    def test_no_real_api_calls(self):
        """Verify verification_agent never makes real Freshdesk calls."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.verify_note_exists") as mock_verify:
            mock_verify.return_value = {
                "verified": True,
                "matched_note_id": 12345,
                "ticket_id": 2048,
                "reason": "Found"
            }

            with patch("agents.verification_agent.Config") as mock_config:
                mock_config.FRESHDESK_DOMAIN = "test.com"
                mock_config.FRESHDESK_API_KEY = "test"

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                assert result["status"] == "SUCCESS"
                # Verify mock was called, not real function
                mock_verify.assert_called_once()


class TestVerifyNoteExistsFunction:
    """Test verify_note_exists function directly."""

    def test_successful_verification_by_note_id(self):
        """Successfully verifies note by exact note_id match."""
        from services.freshdesk_service import verify_note_exists

        mock_response_data = {
            "id": 2048,
            "conversations": [
                {"id": 99999, "body": "Customer message"},
                {"id": 12345, "body": "GhostWork refund workflow approved"},
                {"id": 88888, "body": "Another message"}
            ]
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

                result = verify_note_exists(2048, expected_note_id=12345)

                assert result["verified"] is True
                assert result["matched_note_id"] == 12345
                assert result["status"] == "verified"

    def test_verification_by_execution_reference(self):
        """Verifies note by searching for execution reference in body."""
        from services.freshdesk_service import verify_note_exists

        mock_response_data = {
            "id": 2048,
            "conversations": [
                {"id": 99999, "body": "Customer message"},
                {"id": 12345, "body": "GhostWork refund workflow approved\nExecution ID: exec-001"}
            ]
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

                result = verify_note_exists(2048, execution_reference="exec-001")

                assert result["verified"] is True
                assert result["matched_note_id"] == 12345
                assert "Execution reference found" in result["reason"]

    def test_verification_fails_note_not_found(self):
        """Returns verified=False when expected note not found."""
        from services.freshdesk_service import verify_note_exists

        mock_response_data = {
            "id": 2048,
            "conversations": [
                {"id": 99999, "body": "Customer message"},
                {"id": 88888, "body": "Another message"}
            ]
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

                result = verify_note_exists(2048, expected_note_id=12345)

                assert result["verified"] is False
                assert result["status"] == "verification_failed"
                assert result["matched_note_id"] is None

    def test_verify_note_401_authentication_failure(self):
        """Raises FreshDeskError on 401."""
        from services.freshdesk_service import verify_note_exists

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "invalid-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_get.return_value = mock_response

                with pytest.raises(FreshDeskError, match="Authentication failed"):
                    verify_note_exists(2048)

    def test_verify_note_not_found(self):
        """Raises FreshDeskError on 404 ticket not found."""
        from services.freshdesk_service import verify_note_exists

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_get.return_value = mock_response

                with pytest.raises(FreshDeskError, match="not found"):
                    verify_note_exists(2048)

    def test_verify_note_timeout(self):
        """Raises FreshDeskError on timeout."""
        from services.freshdesk_service import verify_note_exists

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("services.freshdesk_service.requests.get") as mock_get:
                import requests
                mock_get.side_effect = requests.Timeout("timeout")

                with pytest.raises(FreshDeskError, match="timeout"):
                    verify_note_exists(2048)

    def test_verify_note_not_configured(self):
        """Raises FreshDeskUnavailableError when not configured."""
        from services.freshdesk_service import verify_note_exists

        with patch("services.freshdesk_service.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = None
            mock_config.FRESHDESK_API_KEY = None

            with pytest.raises(FreshDeskUnavailableError):
                verify_note_exists(2048)


class TestCompletionSemantics:
    """Test that verification failures prevent COMPLETED state."""

    def test_real_write_back_verified_allows_completion(self):
        """When real write-back is verified, SUCCESS allows execution to complete."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.Config") as mock_config:
            mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
            mock_config.FRESHDESK_API_KEY = "test-key"

            with patch("agents.verification_agent.verify_note_exists") as mock_verify:
                mock_verify.return_value = {
                    "verified": True,
                    "matched_note_id": 12345,
                    "ticket_id": 2048,
                    "reason": "Found"
                }

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "writeback_status": "success",
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                # SUCCESS allows orchestrator to mark execution as COMPLETED
                assert result["status"] == "SUCCESS"

    def test_real_write_back_unverified_blocks_completion(self):
        """When real write-back fails verification, FAILED prevents COMPLETED."""
        from agents.verification_agent import run

        with patch("agents.verification_agent.verify_note_exists") as mock_verify:
            mock_verify.return_value = {
                "verified": False,
                "matched_note_id": None,
                "ticket_id": 2048,
                "reason": "Not found"
            }

            with patch("agents.verification_agent.Config") as mock_config:
                mock_config.FRESHDESK_DOMAIN = "acme.freshdesk.com"
                mock_config.FRESHDESK_API_KEY = "test-key"

                context = {
                    "communication_agent": {
                        "result": {
                            "action_performed": True,
                            "writeback_status": "success",
                            "ticket_id": 2048,
                            "note_id": 12345,
                            "source": "freshdesk"
                        }
                    }
                }

                result = run({}, context=context)

                # FAILED prevents orchestrator from marking execution as COMPLETED
                # The execution will remain in RUNNING or FAILED state
                assert result["status"] == "FAILED"

    def test_fallback_demo_always_allows_completion(self):
        """Fallback/demo mode always returns SUCCESS (never blocks completion)."""
        from agents.verification_agent import run

        context = {
            "communication_agent": {
                "result": {
                    "action_performed": False,
                    "writeback_status": "skipped",
                    "source": "fallback"
                }
            }
        }

        result = run({}, context=context)

        # Fallback always succeeds, allowing normal demo completion
        assert result["status"] == "SUCCESS"
