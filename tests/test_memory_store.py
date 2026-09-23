"""Tests for in-memory data store."""

from services.memory_store import MemoryStore


class TestMemoryStore:
    """Test the in-memory store backend."""

    def test_init_creates_seeded_data(self):
        """MemoryStore initializes with Refund Verification workflow."""
        store = MemoryStore()
        workflows = store.select("workflows")
        assert len(workflows) >= 1
        assert workflows[0]["name"] == "Refund Verification"

    def test_insert_workflow(self):
        """Insert a new workflow."""
        store = MemoryStore()
        store.clear_all()  # Start fresh (reseeds with Refund Verification workflow)

        # After clear_all, the seeded workflow is ID 1, so next insert is ID 2
        id_val = store.insert("workflows", {"name": "Test Workflow"})
        assert id_val == 2

        result = store.select_one("workflows", {"id": 2})
        assert result["name"] == "Test Workflow"

    def test_insert_auto_increments(self):
        """Inserts auto-increment ID."""
        store = MemoryStore()
        store.clear_all()  # Reseeds with workflow ID=1

        id1 = store.insert("workflows", {"name": "WF1"})
        id2 = store.insert("workflows", {"name": "WF2"})
        assert id1 == 2
        assert id2 == 3

    def test_select_all(self):
        """Select returns all rows when no where clause."""
        store = MemoryStore()
        store.clear_all()  # Has seeded workflow ID=1

        store.insert("workflows", {"name": "WF1"})
        store.insert("workflows", {"name": "WF2"})

        rows = store.select("workflows")
        assert len(rows) == 3  # Seeded + 2 inserted

    def test_select_with_where(self):
        """Select filters by where clause."""
        store = MemoryStore()
        store.clear_all()

        store.insert("workflows", {"name": "WF1", "status": "active"})
        store.insert("workflows", {"name": "WF2", "status": "inactive"})

        rows = store.select("workflows", {"status": "active"})
        assert len(rows) == 1
        assert rows[0]["name"] == "WF1"

    def test_select_with_limit(self):
        """Select respects limit."""
        store = MemoryStore()
        store.clear_all()

        store.insert("workflows", {"name": "WF1"})
        store.insert("workflows", {"name": "WF2"})
        store.insert("workflows", {"name": "WF3"})

        rows = store.select("workflows", limit=2)
        assert len(rows) == 2

    def test_select_one(self):
        """Select one returns single row or None."""
        store = MemoryStore()
        store.clear_all()

        store.insert("workflows", {"name": "WF1"})

        result = store.select_one("workflows", {"name": "WF1"})
        assert result is not None
        assert result["name"] == "WF1"

        result = store.select_one("workflows", {"name": "nonexistent"})
        assert result is None

    def test_update(self):
        """Update modifies a row."""
        store = MemoryStore()
        store.clear_all()

        store.insert("workflows", {"name": "WF1", "status": "active"})
        count = store.update("workflows", 1, {"status": "inactive"})
        assert count == 1

        result = store.select_one("workflows", {"id": 1})
        assert result["status"] == "inactive"

    def test_update_nonexistent(self):
        """Update nonexistent row returns 0."""
        store = MemoryStore()
        store.clear_all()

        count = store.update("workflows", 999, {"status": "inactive"})
        assert count == 0

    def test_update_if_success(self):
        """Update if succeeds when condition matches."""
        store = MemoryStore()
        store.clear_all()

        store.insert("executions", {"status": "PENDING", "workflow_id": 1})

        # Condition matches
        count = store.update_if(
            "executions", 1, {"status": "PENDING"}, {"status": "RUNNING"}
        )
        assert count == 1

        result = store.select_one("executions", {"id": 1})
        assert result["status"] == "RUNNING"

    def test_update_if_failure_wrong_condition(self):
        """Update if fails when condition doesn't match (CAS)."""
        store = MemoryStore()
        store.clear_all()

        store.insert("executions", {"status": "PENDING", "workflow_id": 1})

        # Condition doesn't match
        count = store.update_if(
            "executions", 1, {"status": "RUNNING"}, {"status": "COMPLETED"}
        )
        assert count == 0

        # Status unchanged
        result = store.select_one("executions", {"id": 1})
        assert result["status"] == "PENDING"

    def test_delete(self):
        """Delete removes matching rows."""
        store = MemoryStore()
        store.clear_all()

        store.insert("workflows", {"name": "WF1", "status": "active"})
        store.insert("workflows", {"name": "WF2", "status": "inactive"})

        count = store.delete("workflows", {"status": "active"})
        assert count == 1

        rows = store.select("workflows")
        # Seeded workflow + WF2 (WF1 was deleted)
        assert len(rows) == 2
        names = [r["name"] for r in rows]
        assert "WF2" in names
        assert "WF1" not in names

    def test_clear_all(self):
        """Clear all resets store and reloads seed data."""
        store = MemoryStore()

        # Store should have seed data
        assert len(store.select("workflows")) >= 1

        # Add more data
        store.insert("workflows", {"name": "Test"})
        assert len(store.select("workflows")) >= 2

        # Clear
        store.clear_all()

        # Should be back to seed data only
        workflows = store.select("workflows")
        assert len(workflows) >= 1
        assert workflows[0]["name"] == "Refund Verification"

    def test_concurrent_access(self):
        """Multiple threads can access store safely (basic lock test)."""
        import threading

        store = MemoryStore()
        store.clear_all()

        results = []

        def insert_workflow(name):
            id_val = store.insert("workflows", {"name": name})
            results.append(id_val)

        threads = [
            threading.Thread(target=insert_workflow, args=(f"WF{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All IDs should be unique
        assert len(set(results)) == 5
        # Seeded workflow + 5 inserted
        assert len(store.select("workflows")) == 6

    def test_execution_workflow(self):
        """Test a realistic execution creation and update workflow."""
        store = MemoryStore()
        store.clear_all()

        # Create execution
        exec_id = store.insert(
            "executions",
            {
                "workflow_id": 1,
                "ticket_id": 2048,
                "status": "PENDING",
            },
        )

        # Verify creation
        exec_row = store.select_one("executions", {"id": exec_id})
        assert exec_row["status"] == "PENDING"

        # Update status
        store.update_if(
            "executions", exec_id, {"status": "PENDING"}, {"status": "RUNNING"}
        )

        # Verify update
        exec_row = store.select_one("executions", {"id": exec_id})
        assert exec_row["status"] == "RUNNING"

        # Create step
        store.insert(
            "execution_steps",
            {
                "execution_id": exec_id,
                "step_name": "context_agent",
                "agent": "context_agent",
                "status": "RUNNING",
            },
        )

        # Verify step
        steps = store.select("execution_steps", {"execution_id": exec_id})
        assert len(steps) == 1
        assert steps[0]["step_name"] == "context_agent"
