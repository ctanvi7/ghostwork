"""In-memory data store for testing and Tier C fallback."""

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class MemoryStore:
    """Thread-safe in-memory database using dicts."""

    def __init__(self):
        """Initialize empty store with tables."""
        self._lock = threading.Lock()
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "workflows": [],
            "workflow_steps": [],
            "ghost_skills": [],
            "executions": [],
            "execution_steps": [],
            "approvals": [],
            "integrations": [],
            "audit_events": [],
        }
        self._id_counters: Dict[str, int] = {t: 0 for t in self.tables}
        self._seed_data()

    def _seed_data(self) -> None:
        """Load seed data (Refund Verification workflow)."""
        with self._lock:
            # Workflows
            workflow = {
                "id": 1,
                "name": "Refund Verification",
                "description": "Process refund requests with approval gates",
                "ghost_score": 87.0,
                "frequency": 37,
                "manual_duration_seconds": 667,
                "automation_percentage": 78.0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.tables["workflows"].append(workflow)
            self._id_counters["workflows"] = 1

            # Workflow steps
            steps = [
                {"id": 1, "workflow_id": 1, "step_order": 1, "name": "context_agent", "agent": "context_agent", "classification": "ASSISTED", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 2, "workflow_id": 1, "step_order": 2, "name": "billing_agent", "agent": "billing_agent", "classification": "AUTOMATABLE", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 3, "workflow_id": 1, "step_order": 3, "name": "policy_agent", "agent": "policy_agent", "classification": "ASSISTED", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 4, "workflow_id": 1, "step_order": 4, "name": "risk_agent", "agent": "risk_agent", "classification": "AUTOMATABLE", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 5, "workflow_id": 1, "step_order": 5, "name": "approval_gate", "agent": "approval_gate", "classification": "HUMAN_REQUIRED", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 6, "workflow_id": 1, "step_order": 6, "name": "communication_agent", "agent": "communication_agent", "classification": "AUTOMATABLE", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 7, "workflow_id": 1, "step_order": 7, "name": "verification_agent", "agent": "verification_agent", "classification": "AUTOMATABLE", "created_at": datetime.now(timezone.utc).isoformat()},
                {"id": 8, "workflow_id": 1, "step_order": 8, "name": "closure_agent", "agent": "closure_agent", "classification": "AUTOMATABLE", "created_at": datetime.now(timezone.utc).isoformat()},
            ]
            self.tables["workflow_steps"].extend(steps)
            self._id_counters["workflow_steps"] = 8

            # Ghost skills
            skill = {
                "id": 1,
                "workflow_id": 1,
                "name": "Refund Verification",
                "definition_json": {
                    "trigger": "refund_request",
                    "steps": ["context_agent", "billing_agent", "policy_agent", "risk_agent", "approval_gate", "communication_agent", "verification_agent"],
                    "approval_rule": {
                        "field": "refund_amount",
                        "operator": ">",
                        "value": 25000,
                    },
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.tables["ghost_skills"].append(skill)
            self._id_counters["ghost_skills"] = 1

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """Insert a row, auto-increment ID."""
        with self._lock:
            if table not in self.tables:
                raise ValueError(f"Unknown table: {table}")

            row_id = self._id_counters[table] + 1
            self._id_counters[table] = row_id

            row = {"id": row_id, **data}
            self.tables[table].append(row)
            return row_id

    def select(
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Select rows matching where clause."""
        with self._lock:
            if table not in self.tables:
                raise ValueError(f"Unknown table: {table}")

            rows = self.tables[table]
            if where:
                rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
            if limit:
                rows = rows[:limit]
            return rows

    def select_one(self, table: str, where: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Select single row or None."""
        results = self.select(table, where, limit=1)
        return results[0] if results else None

    def update(
        self, table: str, id_val: int, data: Dict[str, Any]
    ) -> int:
        """Update a row by ID. Return count of rows updated."""
        with self._lock:
            if table not in self.tables:
                raise ValueError(f"Unknown table: {table}")

            count = 0
            for row in self.tables[table]:
                if row["id"] == id_val:
                    row.update(data)
                    count += 1
            return count

    def update_if(
        self,
        table: str,
        id_val: int,
        where: Dict[str, Any],
        data: Dict[str, Any],
    ) -> int:
        """Conditional update (compare-and-set). Return count of rows updated."""
        with self._lock:
            if table not in self.tables:
                raise ValueError(f"Unknown table: {table}")

            count = 0
            for row in self.tables[table]:
                if row["id"] == id_val and all(
                    row.get(k) == v for k, v in where.items()
                ):
                    row.update(data)
                    count += 1
            return count

    def delete(self, table: str, where: Dict[str, Any]) -> int:
        """Delete rows matching where clause."""
        with self._lock:
            if table not in self.tables:
                raise ValueError(f"Unknown table: {table}")

            original_count = len(self.tables[table])
            self.tables[table] = [
                r for r in self.tables[table]
                if not all(r.get(k) == v for k, v in where.items())
            ]
            return original_count - len(self.tables[table])

    def clear_all(self) -> None:
        """Clear all tables and reseed (for testing)."""
        with self._lock:
            for table in self.tables:
                self.tables[table].clear()
            self._id_counters = {t: 0 for t in self.tables}
        # Call _seed_data outside the lock to avoid deadlock on re-entrant lock
        self._seed_data()
