"""Every column the Supabase code path writes must exist in migrations/*.sql.

Guards against the PGRST204 class of bug: code starts writing a column
(e.g. execution_steps.step_order) that no migration ever created.
"""

import re
from pathlib import Path

from services.supabase_service import SupabaseService

MIGRATIONS = Path(__file__).parent.parent / "migrations"
NON_COLUMN_KEYWORDS = {"CHECK", "UNIQUE", "PRIMARY", "CONSTRAINT", "FOREIGN"}


def migration_columns() -> dict:
    """Columns per table from CREATE TABLE and ALTER TABLE ... ADD COLUMN, in file order."""
    columns: dict = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
            for line in body.splitlines():
                token = line.strip().split(" ", 1)[0]
                if token and token.upper() not in NON_COLUMN_KEYWORDS and not token.startswith("--"):
                    columns.setdefault(table, set()).add(token)
        for table, column in re.findall(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", sql):
            columns.setdefault(table, set()).add(column)
    return columns


class _Query:
    def __init__(self, recorder, table):
        self.recorder, self.table = recorder, table

    def insert(self, data):
        for row in data if isinstance(data, list) else [data]:
            self.recorder.append((self.table, set(row)))
        return self

    def update(self, data):
        self.recorder.append((self.table, set(data)))
        return self

    def eq(self, *args):
        return self

    def execute(self):
        return type("Response", (), {"data": [{"id": 1}]})()


class _FakeClient:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return _Query(self.writes, name)


def _supabase_service_with_fake_client():
    service = SupabaseService.__new__(SupabaseService)
    service.backend = "supabase"
    service._memory_store = None
    service._supabase_client = _FakeClient()
    return service


def test_migrations_define_execution_steps_step_order():
    assert "step_order" in migration_columns()["execution_steps"]


def test_every_supabase_write_uses_only_migrated_columns():
    service = _supabase_service_with_fake_client()

    # Exercise every write path the orchestrator, approvals and voice flows use,
    # with the field names their real callers pass.
    service.create_execution(1, ticket_id=1, refund_amount=32000)
    service.update_execution(1, refund_amount=32000.0)
    service.transition_execution(1, "PENDING", "RUNNING", current_step="risk_agent", error_message="x")
    service.create_execution_step(1, "context_agent", agent="context_agent", status="RUNNING", step_order=1)
    service.update_execution_step(1, status="SUCCESS", output_json={"reason": "ok"})
    service.create_approval(1, amount=32000, channel="web")
    service.update_approval(1, status="APPROVED")
    service.transition_approval(1, "PENDING", "APPROVED", approver="web_user", channel="web",
                                raw_response_json={"a": 1})
    service.log_audit_event(1, "VOICE_CALL_STARTED", actor="vobiz", detail={"approval_id": 1})
    service.create_ghost_skill(1, "Refund Verification", {"steps": []})

    schema = migration_columns()
    problems = []
    for table, cols in service._supabase_client.writes:
        missing = cols - schema.get(table, set())
        if missing:
            problems.append(f"{table}: {sorted(missing)}")

    assert not problems, "Code writes columns missing from migrations: " + "; ".join(problems)
