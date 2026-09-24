"""Supabase/Memory DB persistence service with unified interface."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import Config
from services.memory_store import MemoryStore

logger = logging.getLogger(__name__)


class SupabaseService:
    """Unified persistence layer supporting both Supabase and memory backend."""

    def __init__(self):
        """Initialize service with backend from config."""
        self.backend = Config.DB_BACKEND.lower()
        self._memory_store: Optional[MemoryStore] = None
        self._supabase_client = None

        if self.backend == "memory":
            self._memory_store = MemoryStore()
        elif self.backend == "supabase":
            try:
                from supabase import create_client
                if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
                    raise ValueError("SUPABASE_URL and SUPABASE_KEY required for supabase backend")
                self._supabase_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
            except ImportError as e:
                raise ImportError("supabase-py not installed. Install with: pip install supabase") from e
        else:
            raise ValueError(f"Unknown DB_BACKEND: {Config.DB_BACKEND}")

    def _get_store(self) -> MemoryStore:
        """Get memory store (lazy init or error)."""
        if self._memory_store is None:
            raise RuntimeError("Memory store not initialized. Check DB_BACKEND config.")
        return self._memory_store

    def _map_output_to_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map output_json field to result_json for Supabase schema."""
        mapped = {k: v for k, v in data.items()}
        if "output_json" in mapped:
            mapped["result_json"] = mapped.pop("output_json")
        return mapped

    def _map_result_to_output(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Map result_json field back to output_json for code consistency."""
        if isinstance(row, dict) and "result_json" in row:
            row["output_json"] = row.pop("result_json")
        return row

    def _map_raw_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map raw_response_json field to raw_response for Supabase schema."""
        mapped = {k: v for k, v in data.items()}
        if "raw_response_json" in mapped:
            mapped["raw_response"] = mapped.pop("raw_response_json")
        return mapped

    def _unmap_raw_response(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Map raw_response field back to raw_response_json for code consistency."""
        if isinstance(row, dict) and "raw_response" in row:
            row["raw_response_json"] = row.pop("raw_response")
        return row

    # Workflow queries
    def get_workflow(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        """Get workflow by ID."""
        if self.backend == "memory":
            return self._get_store().select_one("workflows", {"id": workflow_id})

        try:
            response = self._supabase_client.table("workflows").select("*").eq("id", workflow_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            raise

    def list_workflows(self) -> List[Dict[str, Any]]:
        """List all workflows."""
        if self.backend == "memory":
            return self._get_store().select("workflows")

        try:
            response = self._supabase_client.table("workflows").select("*").execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            raise

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

        try:
            response = self._supabase_client.table("executions").insert(data).execute()
            return response.data[0]["id"] if response.data else None
        except Exception as e:
            logger.error(f"Failed to create execution: {e}")
            raise

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

        try:
            exec_response = self._supabase_client.table("executions").select("*").eq("id", execution_id).execute()
            if not exec_response.data:
                return None

            exec_row = exec_response.data[0]

            # Fetch related steps
            steps_response = self._supabase_client.table("execution_steps").select("*").eq("execution_id", execution_id).execute()
            steps = steps_response.data or []
            # Map result_json back to output_json for consistency with code
            steps = [self._map_result_to_output(step) for step in steps]

            # Fetch related approvals
            approvals_response = self._supabase_client.table("approvals").select("*").eq("execution_id", execution_id).execute()
            approvals = approvals_response.data or []
            # Map raw_response back to raw_response_json for consistency
            approvals = [self._unmap_raw_response(approval) for approval in approvals]

            return {
                **exec_row,
                "steps": steps,
                "approvals": approvals,
            }
        except Exception as e:
            logger.error(f"Failed to get execution {execution_id}: {e}")
            raise

    def update_execution(
        self, execution_id: int, **fields
    ) -> int:
        """Update execution fields. Returns count updated."""
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()

        if self.backend == "memory":
            return self._get_store().update("executions", execution_id, fields)

        try:
            response = self._supabase_client.table("executions").update(fields).eq("id", execution_id).execute()
            return len(response.data) if response.data else 0
        except Exception as e:
            logger.error(f"Failed to update execution {execution_id}: {e}")
            raise

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

        try:
            # Supabase CAS: fetch current, verify status, then update if match
            current = self._supabase_client.table("executions").select("status").eq("id", execution_id).execute()
            if not current.data or current.data[0]["status"] != from_status:
                return 0

            response = self._supabase_client.table("executions").update(update_data).eq("id", execution_id).execute()
            return len(response.data) if response.data else 0
        except Exception as e:
            logger.error(f"Failed to transition execution {execution_id} from {from_status} to {to_status}: {e}")
            raise

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

        try:
            response = self._supabase_client.table("execution_steps").insert(data).execute()
            return response.data[0]["id"] if response.data else None
        except Exception as e:
            logger.error(f"Failed to create execution step for execution {execution_id}: {e}")
            raise

    def update_execution_step(
        self, step_id: int, **fields
    ) -> int:
        """Update an execution step."""
        fields["completed_at"] = datetime.now(timezone.utc).isoformat()

        if self.backend == "memory":
            return self._get_store().update("execution_steps", step_id, fields)

        # Map output_json to result_json for Supabase
        fields = self._map_output_to_result(fields)

        try:
            response = self._supabase_client.table("execution_steps").update(fields).eq("id", step_id).execute()
            return len(response.data) if response.data else 0
        except Exception as e:
            logger.error(f"Failed to update execution step {step_id}: {e}")
            raise

    def select(
        self, table: str, where: dict = None, limit: int = None
    ) -> List[Dict[str, Any]]:
        """Generic select for testing."""
        if self.backend == "memory":
            return self._get_store().select(table, where, limit)

        try:
            query = self._supabase_client.table(table).select("*")
            if where:
                for key, value in where.items():
                    query = query.eq(key, value)
            if limit:
                query = query.limit(limit)
            response = query.execute()
            rows = response.data or []
            # Map result_json fields for execution_steps table
            if table == "execution_steps":
                rows = [self._map_result_to_output(row) for row in rows]
            # Map raw_response fields for approvals table
            if table == "approvals":
                rows = [self._unmap_raw_response(row) for row in rows]
            return rows
        except Exception as e:
            logger.error(f"Failed to select from {table}: {e}")
            raise

    def select_one(self, table: str, where: dict) -> dict | None:
        """Generic select_one for testing."""
        if self.backend == "memory":
            return self._get_store().select_one(table, where)

        try:
            query = self._supabase_client.table(table).select("*")
            for key, value in where.items():
                query = query.eq(key, value)
            response = query.limit(1).execute()
            if not response.data:
                return None
            row = response.data[0]
            # Map result_json fields for execution_steps table
            if table == "execution_steps":
                row = self._map_result_to_output(row)
            # Map raw_response fields for approvals table
            if table == "approvals":
                row = self._unmap_raw_response(row)
            return row
        except Exception as e:
            logger.error(f"Failed to select_one from {table}: {e}")
            raise

    def get_execution_steps(self, execution_id: int) -> List[Dict[str, Any]]:
        """Get all steps for an execution."""
        if self.backend == "memory":
            return self._get_store().select(
                "execution_steps", {"execution_id": execution_id}
            )

        return self.select("execution_steps", {"execution_id": execution_id})

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

        try:
            response = self._supabase_client.table("execution_steps").select("*").eq("execution_id", execution_id).eq("status", "SUCCESS").execute()
            if not response.data:
                return None
            # Return the last one (order by step_order desc is better, but we'll sort in Python)
            steps = response.data
            steps.sort(key=lambda s: s.get("step_order", 0))
            return self._map_result_to_output(steps[-1]) if steps else None
        except Exception as e:
            logger.error(f"Failed to get last successful step for execution {execution_id}: {e}")
            raise

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

        try:
            response = self._supabase_client.table("approvals").insert(data).execute()
            return response.data[0]["id"] if response.data else None
        except Exception as e:
            logger.error(f"Failed to create approval for execution {execution_id}: {e}")
            raise

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

        try:
            # Try PENDING first
            response = self._supabase_client.table("approvals").select("*").eq("execution_id", execution_id).eq("status", "PENDING").limit(1).execute()
            if response.data:
                return self._unmap_raw_response(response.data[0])

            # Try AWAITING_CONFIRMATION
            response = self._supabase_client.table("approvals").select("*").eq("execution_id", execution_id).eq("status", "AWAITING_CONFIRMATION").limit(1).execute()
            if response.data:
                return self._unmap_raw_response(response.data[0])

            return None
        except Exception as e:
            logger.error(f"Failed to get open approval for execution {execution_id}: {e}")
            raise

    def get_approved_approval(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """Get the approved approval for an execution (if any)."""
        if self.backend == "memory":
            store = self._get_store()
            return store.select_one(
                "approvals", {"execution_id": execution_id, "status": "APPROVED"}
            )

        try:
            response = self._supabase_client.table("approvals").select("*").eq("execution_id", execution_id).eq("status", "APPROVED").limit(1).execute()
            if response.data:
                return self._unmap_raw_response(response.data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get approved approval for execution {execution_id}: {e}")
            raise

    def update_approval(self, approval_id: int, **fields) -> int:
        """Update an approval record."""
        fields["decided_at"] = datetime.now(timezone.utc).isoformat()

        if self.backend == "memory":
            return self._get_store().update("approvals", approval_id, fields)

        # Map raw_response_json to raw_response for Supabase
        fields = self._map_raw_response(fields)

        try:
            response = self._supabase_client.table("approvals").update(fields).eq("id", approval_id).execute()
            return len(response.data) if response.data else 0
        except Exception as e:
            logger.error(f"Failed to update approval {approval_id}: {e}")
            raise

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

        try:
            response = self._supabase_client.table("audit_events").insert(data).execute()
            return response.data[0]["id"] if response.data else None
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
            raise

    # Test utilities
    def clear_all(self) -> None:
        """Clear all tables (testing only)."""
        if self.backend == "memory":
            self._get_store().clear_all()
        else:
            # Supabase: delete all rows from tables (in reverse dependency order)
            # This is only for testing, not recommended for production
            try:
                logger.warning("Clearing all Supabase tables - this should only be done in testing")
                tables_to_clear = [
                    "audit_events",
                    "execution_steps",
                    "approvals",
                    "executions",
                    "ghost_skills",
                    "workflow_steps",
                    "integrations",
                    "workflows",
                ]
                for table in tables_to_clear:
                    try:
                        self._supabase_client.table(table).delete().neq("id", 0).execute()
                    except Exception as e:
                        logger.warning(f"Could not clear table {table}: {e}")
                # Re-seed the Refund Verification workflow after clearing
                self._reseed_demo_data()
            except Exception as e:
                logger.error(f"Failed to clear Supabase tables: {e}")
                raise

    def _reseed_demo_data(self) -> None:
        """Reseed demo data after clearing (Supabase only)."""
        if self.backend != "supabase":
            return

        try:
            # Re-insert the Refund Verification workflow
            now = datetime.now(timezone.utc).isoformat()

            workflow_data = {
                "name": "Refund Verification",
                "description": "Process refund requests with approval gates",
                "ghost_score": 87.0,
                "frequency": 37,
                "manual_duration_seconds": 667,
                "automation_percentage": 78.0,
                "created_at": now,
                "updated_at": now,
            }

            workflow_response = self._supabase_client.table("workflows").insert(workflow_data).execute()
            workflow_id = workflow_response.data[0]["id"] if workflow_response.data else 1

            # Re-insert workflow steps
            steps = [
                {"workflow_id": workflow_id, "step_order": 1, "name": "context_agent", "agent": "context_agent", "classification": "ASSISTED", "created_at": now},
                {"workflow_id": workflow_id, "step_order": 2, "name": "billing_agent", "agent": "billing_agent", "classification": "AUTOMATABLE", "created_at": now},
                {"workflow_id": workflow_id, "step_order": 3, "name": "policy_agent", "agent": "policy_agent", "classification": "ASSISTED", "created_at": now},
                {"workflow_id": workflow_id, "step_order": 4, "name": "risk_agent", "agent": "risk_agent", "classification": "AUTOMATABLE", "created_at": now},
                {"workflow_id": workflow_id, "step_order": 5, "name": "approval_gate", "agent": "approval_gate", "classification": "HUMAN_REQUIRED", "created_at": now},
                {"workflow_id": workflow_id, "step_order": 6, "name": "communication_agent", "agent": "communication_agent", "classification": "AUTOMATABLE", "created_at": now},
                {"workflow_id": workflow_id, "step_order": 7, "name": "verification_agent", "agent": "verification_agent", "classification": "AUTOMATABLE", "created_at": now},
            ]
            self._supabase_client.table("workflow_steps").insert(steps).execute()

            # Re-insert ghost skill
            skill_data = {
                "workflow_id": workflow_id,
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
                "created_at": now,
            }
            self._supabase_client.table("ghost_skills").insert(skill_data).execute()

            logger.info("Demo data reseeded in Supabase")
        except Exception as e:
            logger.error(f"Failed to reseed demo data: {e}")
            # Don't raise, allow tests to continue


# Global singleton
_service: Optional[SupabaseService] = None


def get_service() -> SupabaseService:
    """Get or create the service singleton."""
    global _service
    if _service is None:
        _service = SupabaseService()
    return _service
