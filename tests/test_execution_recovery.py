"""Regression checks for existing runs and older Supabase step schemas."""

from decimal import Decimal
from unittest.mock import Mock

from services.supabase_service import SupabaseService, get_service


def test_starting_same_ticket_returns_active_run(client):
    first = client.post(
        "/api/executions",
        json={"workflow_id": 1, "ticket_id": 2048, "refund_amount": 32000},
    )
    assert first.status_code == 202
    assert first.get_json()["status"] == "WAITING_FOR_APPROVAL"

    second = client.post(
        "/api/executions",
        json={"workflow_id": 1, "ticket_id": 2048, "refund_amount": 32000},
    )
    assert second.status_code == 200
    assert second.get_json()["id"] == first.get_json()["id"]
    assert len(get_service().list_executions()) == 1


def test_resume_reconstructs_order_when_old_schema_has_no_step_order(client):
    started = client.post(
        "/api/executions",
        json={"workflow_id": 1, "ticket_id": 2048, "refund_amount": 32000},
    ).get_json()
    service = get_service()
    for row in service._get_store().tables["execution_steps"]:
        row.pop("step_order", None)

    approval_id = started["approvals"][0]["id"]
    response = client.post(f"/api/approvals/{approval_id}/approve")
    assert response.status_code == 200
    steps = response.get_json()["steps"]
    assert len([step for step in steps if step["step_name"] == "context_agent"]) == 1


def test_supabase_step_insert_retries_without_missing_column(monkeypatch):
    monkeypatch.setattr("config.Config.DB_BACKEND", "memory")
    service = SupabaseService()
    service.backend = "supabase"
    table = Mock()
    table.insert.return_value.execute.side_effect = [
        Exception("PGRST204: execution_steps.step_order not found"),
        Mock(data=[{"id": 7}]),
    ]
    service._supabase_client = Mock()
    service._supabase_client.table.return_value = table

    assert service.create_execution_step(1, "context_agent", step_order=1) == 7
    assert "step_order" not in table.insert.call_args_list[1].args[0]
    assert table.insert.call_count == 2


def test_supabase_step_output_serializes_decimal_exactly(monkeypatch):
    monkeypatch.setattr("config.Config.DB_BACKEND", "memory")
    service = SupabaseService()
    service.backend = "supabase"
    table = Mock()
    table.update.return_value.eq.return_value.execute.return_value.data = [{"id": 1}]
    service._supabase_client = Mock()
    service._supabase_client.table.return_value = table

    assert service.update_execution_step(
        1,
        status="SUCCESS",
        output_json={"amount": Decimal("32000.00"), "nested": [Decimal("25000.00")]},
    ) == 1
    payload = table.update.call_args.args[0]
    assert payload["result_json"] == {"amount": "32000.00", "nested": ["25000.00"]}
