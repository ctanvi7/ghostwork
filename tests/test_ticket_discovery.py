"""Freshdesk ticket-pattern discovery, automation decision, and human handoff."""

from unittest.mock import patch

import pytest

from services import ticket_discovery_service as tds

# Subjects copied from the live sandbox account (metadata only).
TICKETS = [
    {"id": 9, "subject": "General customer service inquiry", "status": 2},
    {"id": 8, "subject": "Wi-Fi / network adapter not detected or not connecting on Windows", "status": 2},
    {"id": 7, "subject": "Windows Update stuck or failing to install", "status": 2},
    {"id": 6, "subject": "Slow performance / high CPU and disk usage on Windows", "status": 2},
    {"id": 5, "subject": "Windows fails to boot / stuck on loading screen", "status": 2},
    {"id": 4, "subject": "Blue Screen of Death (BSOD) after Windows Update", "status": 5},
    {"id": 3, "subject": "When will I get my refund??", "status": 2},
    {"id": 2, "subject": "Defective Product", "status": 2},
    {"id": 1, "subject": "Shipment Delayed for weeks", "status": 2},
]


@pytest.fixture(autouse=True)
def fresh_cache():
    tds.clear_cache()
    yield
    tds.clear_cache()


def _by_category(patterns):
    return {p["category"]: p for p in patterns}


@pytest.mark.parametrize("subject,expected", [
    ("When will I get my refund??", "refund"),
    ("Blue Screen of Death (BSOD) after Windows Update", "it_troubleshooting"),
    ("Shipment Delayed for weeks", "shipping_delay"),
    ("Defective Product", "product_defect"),
    ("General customer service inquiry", "general"),
])
def test_classify_real_subjects(subject, expected):
    assert tds.classify_ticket({"subject": subject})[0] == expected


def test_repeating_pattern_ranked_first_and_counted():
    patterns = tds.discover_ticket_patterns(TICKETS)
    assert patterns[0]["category"] == "it_troubleshooting"
    assert patterns[0]["frequency"] == 4  # #4 is Closed and excluded
    assert patterns[0]["is_repeating"] is True
    assert _by_category(patterns)["refund"]["is_repeating"] is False


def test_only_patterns_with_a_playbook_are_automatable():
    patterns = _by_category(tds.discover_ticket_patterns(TICKETS))
    refund = patterns["refund"]
    assert refund["automation"]["decision"] == "AUTOMATE"
    assert refund["name"] == "Refund Verification"  # lets GhostSkill generation resolve the workflow
    for key in ("it_troubleshooting", "shipping_delay", "product_defect", "general"):
        assert patterns[key]["automation"]["decision"] == "HUMAN_REVIEW"


def test_resolved_and_closed_tickets_are_excluded():
    tickets = TICKETS + [{"id": 10, "subject": "Refund for order", "status": 4}]
    patterns = tds.discover_ticket_patterns(tickets)
    ticket_ids = {t["ticket_id"] for p in patterns for t in p["tickets"]}
    assert 4 not in ticket_ids and 10 not in ticket_ids
    assert _by_category(patterns)["refund"]["frequency"] == 1


def test_fetch_queries_only_unresolved_tickets_and_strips_bodies():
    from services.freshdesk_service import UNRESOLVED_TICKETS_QUERY

    raw = [{"id": 3, "subject": "Refund", "status": 2, "description_text": "private message"}]
    with patch("services.freshdesk_service.list_unresolved_tickets", return_value=raw) as fetch:
        tickets = tds.fetch_unresolved_tickets()

    fetch.assert_called_once()
    assert UNRESOLVED_TICKETS_QUERY == "status:2 OR status:3"
    assert "description_text" not in tickets[0]


def test_mcp_search_sends_status_query_and_pages():
    import json
    from unittest.mock import MagicMock

    from services import freshdesk_mcp_adapter as adapter

    def envelope(inner):
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": json.dumps(inner)}], "isError": False}}
        return response

    start = envelope({"conversation_id": "c1"})
    page1 = envelope({"status": "OK", "data": {"results": [{"id": i} for i in range(30)], "total": 31}})
    page2 = envelope({"status": "OK", "data": {"results": [{"id": 99}], "total": 31}})
    adapter.reset_session()
    with patch("config.Config.MCP_FRESHDESK_URL", "https://x.freshdesk.com/mcp"),          patch("config.Config.MCP_FRESHDESK_AUTH_TOKEN", "t"),          patch("services.freshdesk_mcp_adapter.requests.post", side_effect=[start, page1, page2]) as post:
        tickets = adapter.search_tickets("status:2 OR status:3")
    adapter.reset_session()

    assert len(tickets) == 31
    args = post.call_args_list[1].kwargs["json"]["params"]
    assert args["name"] == "fetchSearchTickets"
    assert args["arguments"]["query"] == "status:2 OR status:3"
    assert post.call_args_list[2].kwargs["json"]["params"]["arguments"]["page"] == 2


def test_pattern_ids_are_stable():
    first = tds.discover_ticket_patterns(TICKETS)
    second = tds.discover_ticket_patterns(list(reversed(TICKETS)))
    assert {p["id"] for p in first} == {p["id"] for p in second}


def test_min_frequency_filters_one_off_patterns():
    patterns = tds.discover_ticket_patterns(TICKETS, min_frequency=2)
    assert [p["category"] for p in patterns] == ["it_troubleshooting"]


def test_discover_falls_back_to_events_when_freshdesk_unconfigured():
    from services.discovery_service import discover

    result = discover()
    assert result["source"] == "activity_events"
    assert result["fallback_reason"] == "Freshdesk not configured"
    assert result["workflows"]


def test_discover_uses_freshdesk_when_available():
    from services.discovery_service import discover

    with patch("services.ticket_discovery_service.fetch_unresolved_tickets", return_value=TICKETS):
        result = discover(min_frequency=1)
    assert result["source"] == "freshdesk"
    assert result["total_items"] == 9


def test_handoff_writes_private_note_then_reads_back():
    from services import handoff_service

    with patch("services.handoff_service.verify_note_exists",
               side_effect=[{"verified": False}, {"verified": True, "matched_note_id": 77}]), \
         patch("services.handoff_service.add_note", return_value={"note_id": 77}) as add:
        result = handoff_service.route_to_human(8, "Windows Troubleshooting", "No playbook.")

    assert result["status"] == "routed_to_human"
    assert (result["ticket_id"], result["note_id"], result["verified"]) == (8, 77, True)
    assert handoff_service.HANDOFF_MARKER in add.call_args.args[1]


def test_handoff_is_idempotent():
    from services import handoff_service

    with patch("services.handoff_service.verify_note_exists",
               return_value={"verified": True, "matched_note_id": 77}), \
         patch("services.handoff_service.add_note") as add:
        result = handoff_service.route_to_human(8, "Windows Troubleshooting", "No playbook.")

    assert result["status"] == "already_routed"
    add.assert_not_called()


def test_handoff_route_unavailable_without_freshdesk(client):
    response = client.post("/api/discovery/tickets/8/handoff")
    assert response.status_code == 503


def test_handoff_route_uses_server_side_reason(client):
    with patch("services.ticket_discovery_service.fetch_unresolved_tickets", return_value=TICKETS), \
         patch("services.handoff_service.route_to_human",
               return_value={"status": "routed_to_human", "verified": True}) as route:
        response = client.post("/api/discovery/tickets/8/handoff")

    assert response.status_code == 200
    ticket_id, name, reason = route.call_args.args
    assert (ticket_id, name) == (8, "Windows Troubleshooting")
    assert "No approved automation playbook" in reason


def test_refund_workflow_refused_for_non_refund_ticket(client):
    with patch("services.ticket_discovery_service.fetch_unresolved_tickets", return_value=TICKETS):
        response = client.post("/api/executions", json={"workflow_id": 1, "ticket_id": 5})

    assert response.status_code == 409
    assert "Windows Troubleshooting" in response.get_json()["error"]["message"]


def test_closed_ticket_cannot_be_automated(client):
    with patch("services.ticket_discovery_service.fetch_unresolved_tickets", return_value=TICKETS):
        response = client.post("/api/executions", json={"workflow_id": 1, "ticket_id": 4})

    assert response.status_code == 409
    assert "not an open or pending" in response.get_json()["error"]["message"]


def test_closed_ticket_cannot_be_handed_off(client):
    with patch("services.ticket_discovery_service.fetch_unresolved_tickets", return_value=TICKETS),          patch("services.handoff_service.route_to_human") as route:
        response = client.post("/api/discovery/tickets/4/handoff")

    assert response.status_code == 404
    route.assert_not_called()


def test_ticket_missing_from_lagging_search_is_read_directly():
    """Freshdesk search lags; a just-reopened ticket is confirmed with a direct read."""
    from types import SimpleNamespace

    reopened = SimpleNamespace(raw_response={"id": 3, "subject": "When will I get my refund??", "status": 2})
    patterns = tds.discover_ticket_patterns([t for t in TICKETS if t["id"] != 3])
    with patch("services.freshdesk_service.get_ticket", return_value=reopened):
        pattern = tds.find_ticket_pattern(3, patterns)
    assert pattern["automation"]["workflow_name"] == "Refund Verification"


def test_closed_ticket_missing_from_search_stays_refused():
    from types import SimpleNamespace

    closed = SimpleNamespace(raw_response={"id": 4, "subject": "BSOD", "status": 5})
    with patch("services.freshdesk_service.get_ticket", return_value=closed):
        assert tds.find_ticket_pattern(4, tds.discover_ticket_patterns(TICKETS)) is None
