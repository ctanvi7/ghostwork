"""Windows Troubleshooting playbook: agents, discovery decision, and the end-to-end run.

Unlike Refund Verification, this playbook never requires human approval
(advice only, no financial/irreversible action) - it has no risk_agent or
approval_gate step, so it should complete in one pass.
"""

import json
from unittest.mock import patch

import pytest

from schemas.claude_responses import TicketContext
from schemas.freshdesk_responses import FreshDeskTicket

WORKFLOW_ID = 2  # seeded "Windows Troubleshooting" in the memory backend
TICKET_ID = 5
NOTE_ID = 5001


def _ticket(subject="Blue Screen of Death (BSOD) after Windows Update"):
    return FreshDeskTicket(
        ticket_id=TICKET_ID, subject=subject, description_text="System crashes with BSOD.",
        requester_id=None, requester_name=None, status=None, priority=2, created_at=None,
        custom_fields={}, raw_response={"id": TICKET_ID, "status": 2},
    )


def _fail_rest(*args, **kwargs):
    raise AssertionError("REST fallback must not be used when provider=mcp")


@pytest.fixture
def mcp(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", "fwapi_TEST_TOKEN")
    monkeypatch.setattr(Config, "FRESHDESK_ALLOW_REST_FALLBACK", False)
    monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", None)
    monkeypatch.setattr(Config, "FRESHDESK_API_KEY", None)

    state = {"ticket": _ticket(), "writes": [], "notes": [], "closes": []}

    def fetch_ticket(ticket_id):
        return state["ticket"]

    def add_ticket_note(ticket_id, body):
        state["writes"].append((ticket_id, body))
        state["notes"].append({"id": NOTE_ID, "body": body})
        return {"status": "success", "note_id": NOTE_ID, "ticket_id": ticket_id}

    def fetch_ticket_conversations(ticket_id):
        return list(state["notes"])

    def update_ticket_status(ticket_id, status):
        state["closes"].append((ticket_id, status))
        state["ticket"].raw_response["status"] = status
        return {"status": "success", "ticket_id": ticket_id}

    context = TicketContext(issue_category="support", issue_summary="Windows crash", confidence_score=0.9)

    with patch("services.freshdesk_mcp_adapter.fetch_ticket", side_effect=fetch_ticket), \
         patch("services.freshdesk_mcp_adapter.add_ticket_note", side_effect=add_ticket_note), \
         patch("services.freshdesk_mcp_adapter.fetch_ticket_conversations", side_effect=fetch_ticket_conversations), \
         patch("services.freshdesk_mcp_adapter.update_ticket_status", side_effect=update_ticket_status), \
         patch("services.freshdesk_service._update_ticket_status_rest", side_effect=_fail_rest), \
         patch("services.freshdesk_service._get_ticket_rest", side_effect=_fail_rest), \
         patch("services.freshdesk_service._add_note_rest", side_effect=_fail_rest), \
         patch("services.freshdesk_service._verify_note_exists_rest", side_effect=_fail_rest), \
         patch("agents.context_agent.extract_ticket_context", return_value=context):
        yield state


def _start(client, ticket_id=TICKET_ID):
    response = client.post("/api/executions", json={"workflow_id": WORKFLOW_ID, "ticket_id": ticket_id})
    assert response.status_code == 202, response.get_json()
    return response.get_json()


def _step(execution, name):
    return next((s for s in execution["steps"] if s["step_name"] == name), None)


class TestDiagnosisAgent:
    def test_matches_known_issue_by_keyword(self):
        from agents.diagnosis_agent import run

        result = run({}, {"context_agent": {"result": {"ticket": {"subject": "BSOD after update"}}}})
        assert result["status"] == "SUCCESS"
        assert result["result"]["issue_type"] == "bsod"
        assert result["result"]["resolution_steps"]

    def test_falls_back_to_generic_guide(self):
        from agents.diagnosis_agent import run

        result = run({}, {"context_agent": {"result": {"ticket": {"subject": "My computer is weird"}}}})
        assert result["result"]["issue_type"] == "general"

    def test_never_fails(self):
        from agents.diagnosis_agent import run

        result = run({}, None)
        assert result["status"] == "SUCCESS"


class TestDiscoveryDecision:
    def test_windows_troubleshooting_is_automatable_with_no_approval_gate(self):
        from services.ticket_discovery_service import assess_automation

        automation = assess_automation("it_troubleshooting", "Windows Troubleshooting", 5)
        assert automation["decision"] == "AUTOMATE"
        assert automation["workflow_name"] == "Windows Troubleshooting"
        assert "no human approval is required" in automation["reason"]
        assert "Refunds" not in automation["reason"]  # not the refund playbook's wording


class TestEndToEndRun:
    def test_completes_without_any_approval_step(self, client, mcp):
        execution = _start(client)

        assert execution["status"] == "COMPLETED"
        assert execution["approvals"] == []
        assert _step(execution, "risk_agent") is None
        assert _step(execution, "approval_gate") is None

        diagnosis = _step(execution, "diagnosis_agent")["output_json"]
        assert diagnosis["issue_type"] == "bsod"

        comm = _step(execution, "it_communication_agent")["output_json"]
        assert comm["action_performed"] is True
        assert mcp["writes"][0][0] == TICKET_ID
        assert "Blue Screen of Death" in mcp["writes"][0][1]

        verify = _step(execution, "it_verification_agent")["output_json"]
        assert verify["verified"] is True

        closure = _step(execution, "it_closure_agent")["output_json"]
        assert closure["closed"] is True
        assert closure["ticket_status"] == "Resolved"
        assert mcp["closes"] == [(TICKET_ID, 4)]  # Resolved, not Closed

    def test_write_back_skipped_when_ticket_already_done_fails_loudly(self, client, mcp):
        """Matches communication_agent/verification_agent's convention: a real ticket that
        couldn't be written to must fail the run, not silently report success."""
        mcp["ticket"].raw_response["status"] = 4  # already Resolved before the run starts

        execution = _start(client)

        comm = _step(execution, "it_communication_agent")["output_json"]
        assert comm["writeback_status"] == "skipped_ticket_closed"
        assert mcp["writes"] == [] and mcp["closes"] == []
        assert execution["status"] == "FAILED"
        assert _step(execution, "it_closure_agent") is None  # never reached


class TestNoSecretsExposed:
    def test_token_never_in_execution_api(self, client, mcp):
        execution = _start(client)
        assert "fwapi_TEST_TOKEN" not in json.dumps(execution)
