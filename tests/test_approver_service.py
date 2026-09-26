"""Voice approval dials the Freshdesk ticket assignee, not a hard-coded number."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config import Config
from services import approver_service
from services.approver_service import ApproverUnavailableError, normalize_phone, resolve_approver
from services.freshdesk_service import FreshDeskError


@pytest.fixture(autouse=True)
def india_defaults(monkeypatch):
    monkeypatch.setattr(Config, "VOBIZ_DEFAULT_COUNTRY_CODE", "91")
    monkeypatch.setattr(Config, "VOBIZ_FROM_NUMBER", "+911111111111")
    monkeypatch.setattr(Config, "APPROVER_PHONE", None)


@pytest.mark.parametrize("raw,expected", [
    ("+91 98765-43210", "+919876543210"),
    ("9876543210", "+919876543210"),
    ("09876543210", "+919876543210"),
    ("0091 98765 43210", "+919876543210"),
    ("+1 (415) 555-1234", "+14155551234"),
    ("+91...", None),
    ("123", None),
    ("", None),
    (None, None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_number_style_follows_caller_id(monkeypatch):
    assert approver_service.format_for_vobiz("+919876543210") == "+919876543210"
    monkeypatch.setattr(Config, "VOBIZ_FROM_NUMBER", "911111111111")
    assert approver_service.format_for_vobiz("+919876543210") == "919876543210"


def test_mask_hides_middle_digits():
    assert approver_service.mask_phone("+919876543210") == "+91********10"


def _freshdesk(responder_id=55, mobile=None, phone=None, active=True):
    ticket = SimpleNamespace(raw_response={"id": 3, "responder_id": responder_id})
    agent = {"agent_id": responder_id, "name": "Agent", "mobile": mobile, "phone": phone, "active": active}
    return (patch("services.freshdesk_service.get_ticket", return_value=ticket),
            patch("services.freshdesk_service.get_agent_contact", return_value=agent))


def test_calls_assignee_mobile_first():
    ticket, agent = _freshdesk(mobile="98765 43210", phone="+91 80 1234 5678")
    with ticket, agent:
        result = resolve_approver(3)
    assert result["to"] == "+919876543210"
    assert result["source"] == "ticket_assignee"
    assert result["agent_id"] == 55


def test_uses_assignee_phone_when_no_mobile():
    ticket, agent = _freshdesk(phone="+91 80 1234 5678")
    with ticket, agent:
        assert resolve_approver(3)["to"] == "+918012345678"


@pytest.mark.parametrize("kwargs,reason", [
    ({"responder_id": None}, "has no assigned agent"),
    ({"phone": "n/a"}, "has no valid phone number"),
    ({"phone": "+919876543210", "active": False}, "is inactive"),
])
def test_falls_back_to_config_number_with_visible_reason(monkeypatch, kwargs, reason):
    monkeypatch.setattr(Config, "APPROVER_PHONE", "+912222222222")
    ticket, agent = _freshdesk(**kwargs)
    with ticket, agent:
        result = resolve_approver(3)
    assert result["source"] == "config_fallback"
    assert result["to"] == "+912222222222"
    assert reason in result["note"]


def test_refuses_when_no_assignee_number_and_no_fallback():
    ticket, agent = _freshdesk(responder_id=None)
    with ticket, agent, pytest.raises(ApproverUnavailableError, match="no assigned agent"):
        resolve_approver(3)


def test_freshdesk_error_does_not_call_a_wrong_number():
    with patch("services.freshdesk_service.get_ticket", side_effect=FreshDeskError("down")), \
         pytest.raises(ApproverUnavailableError, match="could not read ticket #3.*down"):
        resolve_approver(3)


def test_ticket_not_found_gives_a_specific_reason_not_a_generic_one():
    """A stale execution pointing at a since-renumbered/deleted ticket must say so clearly."""
    with patch("services.freshdesk_service.get_ticket",
               side_effect=FreshDeskError("Ticket 2048 not found")), \
         pytest.raises(ApproverUnavailableError, match="Ticket 2048 not found"):
        resolve_approver(2048)


def test_agent_lookup_failure_is_distinguished_from_ticket_lookup_failure():
    ticket, _ = _freshdesk(responder_id=55)
    with ticket, patch("services.freshdesk_service.get_agent_contact",
                       side_effect=FreshDeskError("agent API down")), \
         pytest.raises(ApproverUnavailableError, match="could not read the assigned agent.*agent API down"):
        resolve_approver(3)


def test_call_approver_dials_assignee_and_never_exposes_full_number(client, monkeypatch):
    import services.voice_approval_service as voice
    from services.supabase_service import get_service

    monkeypatch.setattr(Config, "VOBIZ_AUTH_ID", "test-id")
    monkeypatch.setattr(Config, "VOBIZ_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", "https://demo.example.org")
    monkeypatch.setattr(Config, "SARVAM_API_KEY", None)
    service = get_service()
    execution_id = service.create_execution(1, ticket_id=3, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    service.create_approval(execution_id, amount=32000)

    dialed = {}
    monkeypatch.setattr(voice, "place_approval_call",
                        lambda answer, hangup, to: dialed.setdefault("to", to) and "call-1")
    ticket, agent = _freshdesk(mobile="+919876543210")
    with ticket, agent:
        response = client.post(f"/api/executions/{execution_id}/call-approver")

    assert response.status_code == 202
    assert dialed["to"] == "+919876543210"
    assert response.get_json()["approver"] == {"source": "ticket_assignee", "number": "+91********10", "note": None}
    execution_json = json.dumps(client.get(f"/api/executions/{execution_id}").get_json())
    assert "9876543210" not in execution_json


def test_call_approver_refused_without_any_number(client, monkeypatch):
    from services.supabase_service import get_service

    monkeypatch.setattr(Config, "VOBIZ_AUTH_ID", "test-id")
    monkeypatch.setattr(Config, "VOBIZ_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", "https://demo.example.org")
    service = get_service()
    execution_id = service.create_execution(1, ticket_id=5, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    service.create_approval(execution_id, amount=32000)

    ticket, agent = _freshdesk(responder_id=None)
    with ticket, agent:
        response = client.post(f"/api/executions/{execution_id}/call-approver")

    assert response.status_code == 409
    assert "no assigned agent" in response.get_json()["error"]["message"]
