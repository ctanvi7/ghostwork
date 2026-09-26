"""Regression tests for the reliability, governance and integration fixes."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from services.supabase_service import get_service

# --- Request validation -------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"workflow_id": 1, "refund_amount": "abc"},
    {"workflow_id": 1, "refund_amount": -5},
    {"workflow_id": 1, "refund_amount": 0},
    {"workflow_id": 1, "refund_amount": True},
    {"workflow_id": "one"},
    {"workflow_id": 1, "ticket_id": "12x"},
])
def test_invalid_execution_input_is_rejected(client, body):
    response = client.post("/api/executions", json=body)
    assert response.status_code == 422
    assert get_service().select("executions") == []


def test_non_json_body_gets_json_error(client):
    response = client.post("/api/executions", data="workflow_id=1", content_type="text/plain")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_ghostskill_execute_reuses_active_run_for_ticket(client):
    body = {"ticket_id": 2048, "refund_amount": 32000}
    first = client.post("/api/ghostskills/1/execute", json=body)
    second = client.post("/api/ghostskills/1/execute", json=body)

    assert first.status_code == 202 and second.status_code == 200
    assert first.get_json()["id"] == second.get_json()["id"]
    assert len(get_service().select("executions")) == 1


def test_execution_responses_include_workflow_name(client):
    created = client.post("/api/executions", json={"workflow_id": 1, "refund_amount": 10000}).get_json()
    assert created["workflow_name"] == "Refund Verification"

    listed = client.get("/api/executions").get_json()["executions"]
    assert listed[0]["workflow_name"] == "Refund Verification"
    assert client.get(f"/api/executions/{created['id']}").get_json()["workflow_name"] == "Refund Verification"


def test_workflow_detail_returns_its_steps(client):
    steps = client.get("/api/workflows/1").get_json()["steps"]
    assert [s["name"] for s in steps][:2] == ["context_agent", "billing_agent"]
    assert steps[-1]["name"] == "closure_agent"


# --- Approver sign-in (REQUIRE_APPROVER_AUTH) ---------------------------------

def _waiting_approval():
    service = get_service()
    execution_id = service.create_execution(1, ticket_id=2048, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    return execution_id, service.create_approval(execution_id, amount=32000)


def test_require_approver_auth_blocks_anonymous_decisions(client, monkeypatch):
    monkeypatch.setattr(Config, "REQUIRE_APPROVER_AUTH", True)
    execution_id, approval_id = _waiting_approval()

    for path in (f"/api/approvals/{approval_id}/approve", f"/api/approvals/{approval_id}/reject",
                 f"/api/executions/{execution_id}/call-approver"):
        response = client.post(path)
        assert response.status_code == 401
        assert response.get_json()["error"]["code"] == "UNAUTHORIZED"
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_require_approver_auth_allows_signed_in_user(client, monkeypatch):
    monkeypatch.setattr(Config, "REQUIRE_APPROVER_AUTH", True)
    _, approval_id = _waiting_approval()
    with client.session_transaction() as session:
        session["user"] = {"id": "1", "email": "manager@example.com", "name": "Manager"}

    assert client.post(f"/api/approvals/{approval_id}/reject").status_code == 200
    assert get_service().select_one("approvals", {"id": approval_id})["approver"] == "manager@example.com"


# --- Cached demo ticket (FRESHDESK_FALLBACK=cache) -----------------------------

def test_cached_demo_ticket_runs_governed_flow_without_freshdesk(client, monkeypatch):
    monkeypatch.setattr(Config, "FRESHDESK_FALLBACK", "cache")
    paused = client.post("/api/executions", json={"workflow_id": 1}).get_json()

    context = next(s for s in paused["steps"] if s["step_name"] == "context_agent")["output_json"]
    assert context["source"] == "cached_demo"
    assert context["refund_amount_source"] == "freshdesk_custom_field"
    assert context["ticket"]["url"] is None  # never presented as a live Freshdesk link
    assert float(paused["refund_amount"]) == 32000
    assert paused["status"] == "WAITING_FOR_APPROVAL"

    done = client.post(f"/api/approvals/{paused['approvals'][0]['id']}/approve").get_json()
    assert done["status"] == "COMPLETED"
    write = next(s for s in done["steps"] if s["step_name"] == "communication_agent")["output_json"]
    assert write["action_performed"] is False and write["writeback_status"] == "skipped"


def test_cache_is_off_by_default_and_only_for_the_demo_ticket(client, monkeypatch):
    off = client.post("/api/executions", json={"workflow_id": 1}).get_json()
    assert off["refund_amount"] is None and off["status"] == "WAITING_FOR_APPROVAL"

    monkeypatch.setattr(Config, "FRESHDESK_FALLBACK", "cache")
    other = client.post("/api/executions", json={"workflow_id": 1, "ticket_id": 7}).get_json()
    assert other["refund_amount"] is None  # no demo amount for other tickets


# --- Freshdesk MCP: pagination and session refresh ------------------------------

def _envelope(inner, is_error=False):
    response = MagicMock(status_code=200, ok=True)
    response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": json.dumps(inner) if isinstance(inner, dict) else inner}],
        "isError": is_error}}
    return response


@pytest.fixture
def mcp_configured(monkeypatch):
    from services import freshdesk_mcp_adapter

    monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", "fwapi_TEST")
    freshdesk_mcp_adapter.reset_session()
    yield freshdesk_mcp_adapter
    freshdesk_mcp_adapter.reset_session()


def test_mcp_conversations_follow_next_cursor(mcp_configured):
    start = _envelope({"status": "OK", "conversation_id": "conv-1"})
    page1 = _envelope({"results": [{"id": 1}], "nextCursor": "page-2"})
    page2 = _envelope({"results": [{"id": 2, "body": "newest note"}]})
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[start, page1, page2]) as post:
        conversations = mcp_configured.fetch_ticket_conversations(3)

    assert [c["id"] for c in conversations] == [1, 2]
    first_args = post.call_args_list[1].kwargs["json"]["params"]["arguments"]
    second_args = post.call_args_list[2].kwargs["json"]["params"]["arguments"]
    assert first_args["per_page"] == 100 and "cursor" not in first_args
    assert second_args["cursor"] == "page-2"


def test_mcp_expired_conversation_is_renewed_once(mcp_configured):
    start1 = _envelope({"status": "OK", "conversation_id": "old"})
    expired = _envelope("Invalid or expired conversation_id", is_error=True)
    start2 = _envelope({"status": "OK", "conversation_id": "new"})
    ticket = _envelope({"status": "OK", "data": {"id": 3, "subject": "Refund", "description_text": "x",
                                                 "requester": {"name": "Aditi Rao"}}})
    with patch("services.freshdesk_mcp_adapter.requests.post",
               side_effect=[start1, expired, start2, ticket]) as post:
        result = mcp_configured.fetch_ticket(3)

    assert result.ticket_id == 3
    assert post.call_args_list[3].kwargs["json"]["params"]["arguments"]["conversation_id"] == "new"


def test_mcp_other_errors_are_not_retried(mcp_configured):
    start = _envelope({"status": "OK", "conversation_id": "conv-1"})
    broken = _envelope("upstream timeout", is_error=True)
    with patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[start, broken]) as post:
        with pytest.raises(mcp_configured.FreshDeskMCPError):
            mcp_configured.fetch_ticket(3)
    assert post.call_count == 2


def test_rest_readback_pages_through_conversations(monkeypatch):
    from services.freshdesk_service import verify_note_exists

    monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "rest")
    monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", "acme")
    monkeypatch.setattr(Config, "FRESHDESK_API_KEY", "key")
    pages = [[{"id": n, "body": "older"} for n in range(100)], [{"id": 777, "body": "GhostWork note"}]]
    responses = [MagicMock(status_code=200, ok=True, **{"json.return_value": page}) for page in pages]
    with patch("services.freshdesk_service.requests.get", side_effect=responses) as get:
        result = verify_note_exists(5, expected_note_id=777)

    assert result["verified"] is True
    assert get.call_args_list[0].args[0] == "https://acme.freshdesk.com/api/v2/tickets/5/conversations"
    assert [c.kwargs["params"]["page"] for c in get.call_args_list] == [1, 2]


# --- Claude client bounds --------------------------------------------------------

def test_claude_client_has_bounded_timeout(monkeypatch):
    from services import claude_service

    monkeypatch.setattr(Config, "ANTHROPIC_API_KEY", "test-key")
    with patch("services.claude_service.Anthropic") as anthropic:
        claude_service.make_client()
    kwargs = anthropic.call_args.kwargs
    assert kwargs["timeout"] == Config.CLAUDE_TIMEOUT_SECONDS <= 30
    assert kwargs["max_retries"] == Config.CLAUDE_MAX_RETRIES


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_truncated_or_refused_claude_answer_uses_fallback(monkeypatch, stop_reason):
    from services import claude_service

    monkeypatch.setattr(Config, "ANTHROPIC_API_KEY", "test-key")
    with patch("services.claude_service.Anthropic") as anthropic:
        message = MagicMock(stop_reason=stop_reason, content=[MagicMock(text='{"issue_category": "ref')])
        anthropic.return_value.messages.create.return_value = message
        context = claude_service.extract_ticket_context("Please refund INV-88421")
    assert context.confidence_score == 0.3  # deterministic fallback


# --- Discovery -----------------------------------------------------------------

def test_activity_workflow_ids_are_stable_across_processes():
    """Fallback workflow links must survive restarts (hash() differs per process)."""
    script = ("from services.discovery_service import get_discovered_workflows;"
              "print(sorted(w['id'] for w in get_discovered_workflows("
              "filepath='data/activity_events.json', min_frequency=1)))")
    outputs = {
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True,
                       env={**os.environ, "PYTHONHASHSEED": seed}).stdout
        for seed in ("1", "2")
    }
    assert len(outputs) == 1 and outputs != {"[]\n"}


# --- Execution page UI -------------------------------------------------------------

def _render(execution):
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    source = Path("static/js/execution-page.js").resolve()
    script = r"""
const vm = require('vm');
const fs = require('fs');
const container = {innerHTML: '', dataset: {executionId: '1'}};
const document = {getElementById(id) { return id === 'execution-content' ? container : null; }, addEventListener() {}};
const context = {document, window: {addEventListener(){}}, URL, console, ui: {showInfo(){}, showError(){}},
  escapeHtml(value) { return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;'); }};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
vm.runInContext('renderExecution', context)(JSON.parse(process.argv[2]));
process.stdout.write(container.innerHTML);
"""
    result = subprocess.run(["node", "-e", script, str(source), json.dumps(execution)],
                            capture_output=True, text=True, encoding="utf-8", check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_execution_page_labels_cached_ticket_and_offers_call_again():
    html = _render({
        "id": 1, "status": "WAITING_FOR_APPROVAL", "refund_amount": 32000,
        "approvals": [{"id": 3, "status": "PENDING", "channel": "voice",
                       "raw_response_json": {"voice_status": "ended"}}],
        "steps": [{"step_name": "context_agent", "status": "SUCCESS", "output_json": {
            "source": "cached_demo", "refund_amount_source": "freshdesk_custom_field",
            "freshdesk_error": "Freshdesk not configured",
            "ticket": {"ticket_id": 2048, "subject": "Duplicate charge refund", "status": 2, "url": None}}},
            {"step_name": "risk_agent", "status": "SUCCESS", "output_json": {"effective_limit": "20000"}},
            {"step_name": "approval_gate", "status": "SUCCESS", "output_json": {"reason": "Awaiting human approval"}}],
    })
    # A paused run is not "3 of 3 complete": the open gate itself isn't done yet.
    assert "2 of 3 steps completed" in html and "Waiting for approval" in html
    assert "Cached demo ticket" in html and "nothing is written to Freshdesk" in html
    assert "View in Freshdesk" not in html
    assert "Call again" in html and "disabled" not in html.split('id="call-btn"')[1].split(">")[0]
    assert "₹20,000" in html  # the Risk Agent's effective limit, not a hard-coded one
