"""End-to-end: real-Freshdesk-ticket execution through the existing orchestrator.

Only the three MCP adapter calls (and Claude) are mocked. Every REST function
is replaced with one that fails the test, proving no silent REST fallback.
"""

import json
from unittest.mock import patch

import pytest

from schemas.claude_responses import TicketContext
from schemas.freshdesk_responses import FreshDeskTicket

REFUND_WORKFLOW_ID = 1  # seeded "Refund Verification" in the memory backend
TICKET_ID = 1
NOTE_ID = 9001
FAKE_TOKEN = "fwapi_TEST_SECRET_TOKEN_DO_NOT_LEAK"


def _ticket(custom_fields=None):
    return FreshDeskTicket(
        ticket_id=TICKET_ID,
        subject="Shipment Delayed for weeks",
        description_text="I placed an order (#123456) a few weeks ago.",
        requester_id=None,
        requester_name=None,
        status=None,
        priority=3,
        created_at=None,
        custom_fields=custom_fields or {"cf_reference_number": None},
        raw_response={"id": TICKET_ID, "status": 2},
    )


def _fail_rest(*args, **kwargs):
    raise AssertionError("REST fallback must not be used when provider=mcp")


@pytest.fixture
def mcp(monkeypatch):
    """Configure provider=mcp and mock the MCP adapter; record every call."""
    from config import Config

    monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(Config, "FRESHDESK_ALLOW_REST_FALLBACK", False)
    monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", None)
    monkeypatch.setattr(Config, "FRESHDESK_API_KEY", None)

    state = {"ticket": _ticket(), "writes": [], "reads": 0, "readbacks": 0, "notes": [], "closes": []}

    def fetch_ticket(ticket_id):
        state["reads"] += 1
        return state["ticket"]

    def add_ticket_note(ticket_id, body):
        state["writes"].append((ticket_id, body))
        state["notes"].append({"id": NOTE_ID, "body": body})
        return {"status": "success", "note_id": NOTE_ID, "ticket_id": ticket_id}

    def fetch_ticket_conversations(ticket_id):
        state["readbacks"] += 1
        return list(state["notes"])

    def update_ticket_status(ticket_id, status):
        state["closes"].append((ticket_id, status))
        state["ticket"].raw_response["status"] = status
        return {"status": "success", "ticket_id": ticket_id}

    context = TicketContext(issue_category="refund", issue_summary="Refund request", confidence_score=0.9)

    with patch("services.freshdesk_mcp_adapter.fetch_ticket", side_effect=fetch_ticket), \
         patch("services.freshdesk_mcp_adapter.add_ticket_note", side_effect=add_ticket_note), \
         patch("services.freshdesk_mcp_adapter.fetch_ticket_conversations", side_effect=fetch_ticket_conversations),          patch("services.freshdesk_mcp_adapter.update_ticket_status", side_effect=update_ticket_status),          patch("services.freshdesk_service._update_ticket_status_rest", side_effect=_fail_rest), \
         patch("services.freshdesk_service._get_ticket_rest", side_effect=_fail_rest), \
         patch("services.freshdesk_service._add_note_rest", side_effect=_fail_rest), \
         patch("services.freshdesk_service._verify_note_exists_rest", side_effect=_fail_rest), \
         patch("agents.context_agent.extract_ticket_context", return_value=context):
        yield state


def _start(client, **body):
    payload = {"workflow_id": REFUND_WORKFLOW_ID, "ticket_id": TICKET_ID, **body}
    response = client.post("/api/executions", json=payload)
    assert response.status_code == 202, response.get_json()
    return response.get_json()


def _step(execution, name):
    return next(s for s in execution["steps"] if s["step_name"] == name)


def _approve(client, execution):
    approval_id = execution["approvals"][0]["id"]
    return client.post(f"/api/approvals/{approval_id}/approve")


class TestHighRiskFreshdeskMCPFlow:
    def test_32k_pauses_with_freshdesk_mcp_source_and_no_write(self, client, mcp):
        execution = _start(client, refund_amount=32000)

        assert execution["status"] == "WAITING_FOR_APPROVAL"
        context = _step(execution, "context_agent")["output_json"]
        assert context["source"] == "freshdesk"
        assert context["provider"] == "mcp"
        assert context["ticket"]["ticket_id"] == TICKET_ID
        assert context["ticket"]["subject"] == "Shipment Delayed for weeks"
        assert context["ticket"]["url"] == "https://example.freshdesk.com/a/tickets/1"
        assert _step(execution, "risk_agent")["output_json"]["requires_approval"] is True

        assert mcp["reads"] == 1
        assert mcp["writes"] == []  # NO Freshdesk write before approval
        assert not any(s["step_name"] == "communication_agent" for s in execution["steps"])

    def test_approval_resumes_writes_via_mcp_and_verifies_via_mcp_readback(self, client, mcp):
        paused = _start(client, refund_amount=32000)
        assert mcp["writes"] == []

        response = _approve(client, paused)
        assert response.status_code == 200
        execution = response.get_json()

        assert execution["status"] == "COMPLETED"
        assert len(mcp["writes"]) == 1
        assert mcp["writes"][0][0] == TICKET_ID
        assert "₹32,000.00" in mcp["writes"][0][1]

        write = _step(execution, "communication_agent")["output_json"]
        assert write["action_performed"] is True
        assert write["provider"] == "mcp"
        assert write["note_id"] == NOTE_ID
        assert write["source"] == "freshdesk"  # rehydrated from context_agent after resume

        verify = _step(execution, "verification_agent")["output_json"]
        assert verify["verified"] is True
        assert verify["provider"] == "mcp"
        assert verify["matched_note_id"] == NOTE_ID
        assert mcp["readbacks"] == 1

        closure = _step(execution, "closure_agent")["output_json"]
        assert closure["closed"] is True
        assert mcp["closes"] == [(TICKET_ID, 5)]

    def test_duplicate_approval_is_rejected_and_writes_once(self, client, mcp):
        paused = _start(client, refund_amount=32000)
        assert _approve(client, paused).status_code == 200
        assert _approve(client, paused).status_code == 409
        assert len(mcp["writes"]) == 1

    def test_readback_missing_note_fails_instead_of_completing(self, client, mcp):
        paused = _start(client, refund_amount=32000)
        mcp["notes"].clear()
        with patch("services.freshdesk_mcp_adapter.add_ticket_note",
                   return_value={"status": "success", "note_id": NOTE_ID, "ticket_id": TICKET_ID}):
            execution = _approve(client, paused).get_json()

        assert execution["status"] == "FAILED"
        assert _step(execution, "verification_agent")["output_json"]["verified"] is False
        assert mcp["closes"] == []  # unverified note: ticket stays open

    def test_mcp_write_failure_fails_execution_without_rest_fallback(self, client, mcp):
        from services.freshdesk_mcp_adapter import FreshDeskMCPError

        paused = _start(client, refund_amount=32000)
        with patch("services.freshdesk_mcp_adapter.add_ticket_note",
                   side_effect=FreshDeskMCPError("simulated MCP outage")):
            execution = _approve(client, paused).get_json()

        # _add_note_rest would raise AssertionError if REST had been attempted.
        assert execution["status"] == "FAILED"
        assert _step(execution, "communication_agent")["output_json"]["action_performed"] is False
        assert _step(execution, "verification_agent")["output_json"]["verification_status"] == "writeback_not_performed"


    def test_ticket_closed_during_approval_gets_no_note_and_is_not_touched(self, client, mcp):
        paused = _start(client, refund_amount=32000)
        mcp["ticket"].raw_response["status"] = 5  # a human closed it while we waited

        execution = _approve(client, paused).get_json()

        assert mcp["writes"] == [] and mcp["closes"] == []
        assert _step(execution, "communication_agent")["output_json"]["writeback_status"] == "skipped_ticket_closed"
        assert execution["status"] == "FAILED"


class TestLowRiskAndAmountSource:
    def test_10k_completes_without_approval_via_mcp(self, client, mcp):
        execution = _start(client, refund_amount=10000)

        assert execution["status"] == "COMPLETED"
        assert execution["approvals"] == []
        assert len(mcp["writes"]) == 1
        assert _step(execution, "verification_agent")["output_json"]["verified"] is True
        assert mcp["closes"] == [(TICKET_ID, 5)]

    def test_refund_amount_from_freshdesk_custom_field_not_regex(self, client, mcp):
        mcp["ticket"] = _ticket({"cf_refund_amount": 32000})
        execution = _start(client)  # no refund_amount in the request

        assert float(execution["refund_amount"]) == 32000
        assert execution["status"] == "WAITING_FOR_APPROVAL"
        assert _step(execution, "context_agent")["output_json"]["refund_amount_source"] == "freshdesk_custom_field"

    def test_missing_amount_fails_closed_and_ignores_order_number(self, client, mcp):
        # Description contains "#123456"; that must never become the refund amount.
        execution = _start(client)

        assert execution["refund_amount"] is None
        assert execution["status"] == "WAITING_FOR_APPROVAL"
        assert _step(execution, "context_agent")["output_json"]["refund_amount_source"] == "missing"


class TestNoSecretsExposed:
    def test_token_never_in_execution_api_or_page(self, client, mcp):
        paused = _start(client, refund_amount=32000)
        completed = _approve(client, paused).get_json()

        api_text = json.dumps(client.get(f"/api/executions/{completed['id']}").get_json())
        page_text = client.get(f"/execution/{completed['id']}").get_data(as_text=True)
        integrations_text = client.get("/api/integrations").get_data(as_text=True)

        for text in (api_text, page_text, integrations_text):
            assert FAKE_TOKEN not in text
            assert "Authorization" not in text


class TestCommunicationGovernanceGuard:
    def test_write_blocked_if_approval_required_but_missing(self, app, mcp):
        """Defense in depth: even if called directly, no write without approval."""
        from agents import communication_agent
        from services.supabase_service import get_service

        execution_id = get_service().create_execution(REFUND_WORKFLOW_ID, ticket_id=TICKET_ID, refund_amount=32000)
        execution = get_service().get_execution(execution_id)
        context = {"context_agent": {"result": {"source": "freshdesk"}},
                   "risk_agent": {"result": {"requires_approval": True}}}

        result = communication_agent.run(execution, context)

        assert result["result"]["writeback_status"] == "blocked_no_approval"
        assert mcp["writes"] == []


def test_refund_amount_field_name_is_configurable(monkeypatch):
    """Freshdesk may name the field cf_cf_refund_amount; the configured name is used."""
    from agents.context_agent import _deterministic_refund_amount
    from config import Config

    ticket = _ticket({"cf_cf_refund_amount": 32000, "cf_refund_amount": 999})
    monkeypatch.setattr(Config, "FRESHDESK_REFUND_AMOUNT_FIELD", "cf_cf_refund_amount")
    assert _deterministic_refund_amount(ticket) == 32000
