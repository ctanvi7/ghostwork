"""Closure agent: close the Freshdesk ticket only after full due diligence."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents import closure_agent
from services.freshdesk_service import FreshDeskError

STEPS = closure_agent.REQUIRED_STEPS


def _context(requires_approval=False, written=True, verified=True, source="freshdesk"):
    ctx = {step: {"status": "SUCCESS", "result": {}} for step in STEPS}
    ctx["context_agent"]["result"] = {"source": source}
    ctx["risk_agent"]["result"] = {"requires_approval": requires_approval}
    ctx["communication_agent"]["result"] = {"action_performed": written}
    ctx["verification_agent"]["result"] = {"verified": verified}
    return ctx


def _ticket(status):
    return SimpleNamespace(raw_response={"status": status})


EXECUTION = {"id": 1, "ticket_id": 3, "refund_amount": 10000}


@pytest.fixture(autouse=True)
def auto_close_on(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "FRESHDESK_AUTO_CLOSE", True)


def _run(context, statuses, approved=None):
    service = MagicMock()
    service.get_approved_approval.return_value = approved
    with patch("agents.closure_agent.get_ticket", side_effect=[_ticket(s) for s in statuses]), \
         patch("agents.closure_agent.update_ticket_status") as update, \
         patch("agents.closure_agent.get_service", return_value=service):
        result = closure_agent.run(EXECUTION, context)
    return result, update


def test_closes_and_confirms_when_all_checks_pass():
    result, update = _run(_context(), statuses=[2, 5])
    update.assert_called_once_with(3, 5)
    assert result["status"] == "SUCCESS"
    assert result["result"]["closed"] is True


def test_approval_required_and_granted_closes():
    result, update = _run(_context(requires_approval=True), statuses=[2, 5], approved={"id": 9})
    assert result["result"]["closed"] is True


@pytest.mark.parametrize("context,expected", [
    (_context(requires_approval=True), "required human approval not granted"),
    (_context(written=False), "note was not written"),
    (_context(verified=False), "not verified by read-back"),
])
def test_ticket_left_open_when_due_diligence_fails(context, expected):
    result, update = _run(context, statuses=[2, 5])
    update.assert_not_called()
    assert result["status"] == "FAILED"
    assert expected in result["result"]["reason"]


def test_failed_earlier_step_blocks_closure():
    context = _context()
    context["billing_agent"]["status"] = "FAILED"
    result, update = _run(context, statuses=[2, 5])
    update.assert_not_called()
    assert "billing_agent did not succeed" in result["result"]["failed_checks"]


def test_already_resolved_ticket_is_not_touched():
    result, update = _run(_context(), statuses=[4])
    update.assert_not_called()
    assert result["status"] == "SUCCESS"
    assert result["result"]["closure_status"] == "skipped"


def test_readback_not_closed_fails():
    result, _ = _run(_context(), statuses=[2, 2])
    assert result["status"] == "FAILED"
    assert "expected Closed" in result["result"]["reason"]


def test_freshdesk_error_on_close_fails_explicitly():
    service = MagicMock()
    with patch("agents.closure_agent.get_ticket", return_value=_ticket(2)), \
         patch("agents.closure_agent.update_ticket_status", side_effect=FreshDeskError("API error 400")), \
         patch("agents.closure_agent.get_service", return_value=service):
        result = closure_agent.run(EXECUTION, _context())
    assert result["status"] == "FAILED"
    assert "API error 400" in result["result"]["reason"]


def test_demo_data_is_skipped_without_calls():
    result, update = _run(_context(source="fallback"), statuses=[])
    update.assert_not_called()
    assert result["status"] == "SUCCESS" and result["result"]["closed"] is False


def test_auto_close_can_be_disabled(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "FRESHDESK_AUTO_CLOSE", False)
    result, update = _run(_context(), statuses=[])
    update.assert_not_called()
    assert "disabled" in result["result"]["reason"]


def test_refund_workflow_ends_with_closure_step(app):
    from services.supabase_service import get_service

    steps = sorted(get_service().select("workflow_steps", {"workflow_id": 1}), key=lambda s: s["step_order"])
    assert [s["agent"] for s in steps[-2:]] == ["verification_agent", "closure_agent"]
