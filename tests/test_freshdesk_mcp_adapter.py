"""MCP adapter parsing against the real JSON-RPC response shapes (HTTP mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from services import freshdesk_mcp_adapter as adapter
from services.freshdesk_mcp_adapter import FreshDeskMCPError

TOKEN = "fwapi_ADAPTER_TEST_TOKEN"


def _envelope(inner: dict, is_error: bool = False) -> MagicMock:
    """Build an HTTP response carrying a JSON-RPC tools/call result (double-encoded)."""
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(inner)}], "isError": is_error},
    }
    return response


START = _envelope({"status": "OK", "conversation_id": "conv-123"})


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", TOKEN)
    adapter.reset_session()
    yield
    adapter.reset_session()


def test_conversations_top_level_results_shape_as_returned_by_live_server():
    convs = {"results": [{"id": 77, "body": "<div>GhostWork note</div>"}]}
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[START, _envelope(convs)]) as post:
        result = adapter.fetch_ticket_conversations(1)

    assert result == convs["results"]
    tool_call = post.call_args_list[1].kwargs["json"]
    assert tool_call["method"] == "tools/call"
    assert tool_call["params"]["name"] == "fetchTicketConversations"
    assert tool_call["params"]["arguments"]["conversation_id"] == "conv-123"


def test_conversations_data_wrapped_shape_also_supported():
    convs = {"status": "OK", "data": {"results": [{"id": 5, "body": "x"}]}}
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[START, _envelope(convs)]):
        assert adapter.fetch_ticket_conversations(1) == [{"id": 5, "body": "x"}]


def test_conversations_unrecognized_shape_fails_closed():
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[START, _envelope({"status": "OK"})]):
        with pytest.raises(FreshDeskMCPError):
            adapter.fetch_ticket_conversations(1)


@pytest.mark.parametrize("inner", [
    {"status": "OK", "data": {"id": 9001, "body": "note"}},
    {"id": 9001, "body": "note"},
])
def test_create_note_parses_wrapped_and_bare_payloads(inner):
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[START, _envelope(inner)]) as post:
        result = adapter.add_ticket_note(1, "GhostWork note")

    assert result == {"status": "success", "note_id": 9001, "ticket_id": 1}
    assert post.call_args_list[1].kwargs["json"]["params"]["name"] == "createTicketNote"


def test_create_note_without_id_fails_closed():
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[START, _envelope({"status": "OK"})]):
        with pytest.raises(FreshDeskMCPError):
            adapter.add_ticket_note(1, "GhostWork note")


def test_tool_error_is_raised_not_treated_as_success():
    with patch("services.freshdesk_mcp_adapter.requests.post",
               side_effect=[START, _envelope({"message": "ticket not found"}, is_error=True)]):
        with pytest.raises(FreshDeskMCPError):
            adapter.fetch_ticket(999)


def test_token_sent_only_in_authorization_header_never_in_body():
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[START, _envelope({"results": []})]) as post:
        adapter.fetch_ticket_conversations(1)

    for call in post.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == TOKEN
        assert TOKEN not in json.dumps(call.kwargs["json"])


def test_readback_matches_string_note_id():
    from services.freshdesk_service import _mcp_verify_note

    with patch("services.freshdesk_mcp_adapter.fetch_ticket_conversations",
               return_value=[{"id": "9001", "body_text": "GhostWork"}]):
        result = _mcp_verify_note(1, expected_note_id=9001)

    assert result["verified"] is True


def test_missing_ticket_404_gives_clear_message():
    """Live server wraps Freshdesk's 404 as JSON text; surface it as 'not found'."""
    upstream = {"error": True, "status": "EXCEPTION", "status_code": 404, "message": "API call failed: 404"}
    with patch("services.freshdesk_mcp_adapter.requests.post",
               side_effect=[START, _envelope(upstream, is_error=True)]):
        with pytest.raises(FreshDeskMCPError, match="Ticket 2048 not found in Freshdesk"):
            adapter.fetch_ticket(2048)


def test_fetch_ticket_looks_up_requester_name():
    ticket = {"status": "OK", "data": {"id": 10, "subject": "Refund", "description_text": "x",
                                        "requester_id": 55, "custom_fields": {}}}
    contact = {"status": "OK", "data": {"id": 55, "name": "Aditi Rao"}}
    with patch("services.freshdesk_mcp_adapter.requests.post",
               side_effect=[START, _envelope(ticket), _envelope(contact)]) as post:
        result = adapter.fetch_ticket(10)

    assert result.requester_name == "Aditi Rao"
    assert post.call_args_list[2].kwargs["json"]["params"]["name"] == "fetchContact"


def test_requester_lookup_failure_does_not_fail_ticket_read():
    ticket = {"status": "OK", "data": {"id": 10, "subject": "Refund", "requester_id": 55}}
    with patch("services.freshdesk_mcp_adapter.requests.post",
               side_effect=[START, _envelope(ticket), _envelope({"status_code": 404}, is_error=True)]):
        result = adapter.fetch_ticket(10)

    assert result.ticket_id == 10
    assert result.requester_name is None


@pytest.mark.parametrize("domain", ["acme", "acme.freshdesk.com", "https://acme.freshdesk.com/"])
def test_rest_host_accepts_any_domain_format(monkeypatch, domain):
    from config import Config

    monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", domain)
    assert Config.freshdesk_rest_host() == "acme.freshdesk.com"
