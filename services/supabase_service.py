"""Supabase/Memory DB persistence service with unified interface."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import Config
from services.memory_store import MemoryStore


class SupabaseService:
    """Unified persistence layer supporting both Supabase and memory backend."""

    def __init__(self):
        """Initialize service with backend from config."""
        self.backend = Config.DB_BACKEND.lower()
        self._memory_store: Optional[MemoryStore] = None

        if self.backend == "memory":
            self._memory_store = MemoryStore()
        elif self.backend != "supabase":
            raise ValueError(f"Unknown DB_BACKEND: {Config.DB_BACKEND}")

    def _get_store(self) -> MemoryStore:
        """Get memory store (lazy init or error)."""
        if self._memory_store is None:
            raise RuntimeError("Memory store not initialized. Check DB_BACKEND config.")
        return self._memory_store

    # Workflow queries
    def get_workflow(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        """Get workflow by ID."""
        if self.backend == "memory":
            return self._get_store().select_one("workflows", {"id": workflow_id})
        # Supabase: TODO, stub for now
        raise NotImplementedError("Supabase backend not yet implemented")

    def list_workflows(self) -> List[Dict[str, Any]]:
        """List all workflows."""
        if self.backend == "memory":
            return self._get_store().select("workflows")
        raise NotImplementedError("Supabase backend not yet implemented")

    # Execution queries
    def create_execution(
        self,
        workflow_id: int,
        ticket_id: Optional[int] = None,
        refund_amount: Optional[float] = None,
    ) -> int:
        """Create a new execution. Returns execution ID."""
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "workflow_id": workflow_id,
            "ticket_id": ticket_id,
            "status": "PENDING",
            "refund_amount": refund_amount,
            "created_at": now,
            "updated_at": now,
        }

        if self.backend == "memory":
            return self._get_store().insert("executions", data)
        raise NotImplementedError("Supabase backend not yet implemented")

    def get_execution(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """Get execution by ID with all related data (steps, approvals)."""
        if self.backend == "memory":
            store = self._get_store()
            exec_row = store.select_one("executions", {"id": execution_id})
            if not exec_row:
                return None

            # Attach steps and approvals
            steps = store.select("execution_steps", {"execution_id": execution_id})
            approvals = store.select("approvals", {"execution_id": execution_id})

            return {
                **exec_row,
                "steps": steps,
                "approvals": approvals,
            }
        raise NotImplementedError("Supabase backend not yet implemented")

    def update_execution(
        self, execution_id: int, **fields
    ) -> int:
        """Update execution fields. Returns count updated."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()

        if self.backend == "memory":
            return self._get_store().update("executions", execution_id, fields)
        raise NotImplementedError("Supabase backend not yet implemented")

    def transition_execution(
        self,
        execution_id: int,
        from_status: str,
        to_status: str,
        **extra_fields,
    ) -> int:
        """
        Conditional status transition (compare-and-set).
        Returns count updated (0 = condition failed, 1 = success).
        """
        now = datetime.now(timezone.utc).isoformat()
        update_data = {
            "status": to_status,
            "updated_at": now,
            **extra_fields,
        }

        if self.backend == "memory":
            return self._get_store().update_if(
                "executions",
                execution_id,
                {"status": from_status},
                update_data,
            )
        raise NotImplementedError("Supabase backend not yet implemented")

    # Execution steps
    def create_execution_step(
        self,
        execution_id: int,
        step_name: str,
        agent: Optional[str] = None,
        status: str = "RUNNING",
        step_order: Optional[int] = None,
    ) -> int:
        """Create an execution step. Returns step ID."""
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "execution_id": execution_id,
            "step_name": step_name,
            "agent": agent,
            "status": status,
            "step_order": step_order,
            "attempt": 1,
            "started_at": now,
            "created_at": now,
        }

        if self.backend == "memory":
            return self._get_store().insert("execution_steps", data)
        raise NotImplementedError("Supabase backend not yet implemented")

    def update_execution_step(
        self, step_id: int, **fields
    ) -> int:
        """Update an execution step."""
        fields["completed_at"] = datetime.now(timezone.utc).isoformat()

        if self.backend == "memory":
            return self._get_store().update("execution_steps", step_id, fields)
        raise NotImplementedError("Supabase backend not yet implemented")

    def select(
        self, table: str, where: dict = None, limit: int = None
    ) -> List[Dict[str, Any]]:
        """Generic select for testing."""
        if self.backend == "memory":
            return self._get_store().select(table, where, limit)
        raise NotImplementedError("Supabase backend not yet implemented")

    def select_one(self, table: str, where: dict) -> dict | None:
        """Generic select_one for testing."""
        if self.backend == "memory":
            return self._get_store().select_one(table, where)
        raise NotImplementedError("Supabase backend not yet implemented")

    def get_execution_steps(self, execution_id: int) -> List[Dict[str, Any]]:
        """Get all steps for an execution."""
        if self.backend == "memory":
            return self._get_store().select(
                "execution_steps", {"execution_id": execution_id}
            )
        raise NotImplementedError("Supabase backend not yet implemented")

    def get_last_successful_step(
        self, execution_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get the last step with status SUCCESS."""
        if self.backend == "memory":
            steps = self._get_store().select(
                "execution_steps",
                {"execution_id": execution_id, "status": "SUCCESS"},
            )
            return steps[-1] if steps else None
        raise NotImplementedError("Supabase backend not yet implemented")

    # Approvals
    def create_approval(
        self,
        execution_id: int,
        amount: Optional[float] = None,
        channel: Optional[str] = None,
    ) -> int:
        """Create an approval record."""
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "execution_id": execution_id,
            "amount": amount,
            "status": "PENDING",
            "channel": channel,
            "created_at": now,
        }

        if self.backend == "memory":
            return self._get_store().insert("approvals", data)
        raise NotImplementedError("Supabase backend not yet implemented")

    def get_open_approval(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """Get the open approval for an execution (if any)."""
        if self.backend == "memory":
            store = self._get_store()
            approvals = store.select("approvals", {"execution_id": execution_id})
            # Find first approval with status in (PENDING, AWAITING_CONFIRMATION)
            for approval in approvals:
                if approval["status"] in ("PENDING", "AWAITING_CONFIRMATION"):
                    return approval
            return None
        raise NotImplementedError("Supabase backend not yet implemented")

    def get_approved_approval(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """Get the approved approval for an execution (if any)."""
        if self.backend == "memory":
            store = self._get_store()
            return store.select_one(
                "approvals", {"execution_id": execution_id, "status": "APPROVED"}
            )
        raise NotImplementedError("Supabase backend not yet implemented")

    def update_approval(self, approval_id: int, **fields) -> int:
        """Update an approval record."""
        fields["decided_at"] = datetime.now(timezone.utc).isoformat()

        if self.backend == "memory":
            return self._get_store().update("approvals", approval_id, fields)
        raise NotImplementedError("Supabase backend not yet implemented")

    # Audit events
    def log_audit_event(
        self,
        execution_id: Optional[int],
        action: str,
        actor: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Log an audit event."""
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "execution_id": execution_id,
            "actor": actor,
            "action": action,
            "detail_json": detail,
            "created_at": now,
        }

        if self.backend == "memory":
            return self._get_store().insert("audit_events", data)
        raise NotImplementedError("Supabase backend not yet implemented")

    # Test utilities
    def clear_all(self) -> None:
        """Clear all tables (testing only)."""
        if self.backend == "memory":
            self._get_store().clear_all()
        else:
            raise NotImplementedError("Supabase backend not yet implemented")


# Global singleton
_service: Optional[SupabaseService] = None


def get_service() -> SupabaseService:
    """Get or create the service singleton."""
    global _service
    if _service is None:
        _service = SupabaseService()
    return _service
