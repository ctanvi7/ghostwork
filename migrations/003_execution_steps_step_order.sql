-- Add execution_steps.step_order.
-- The orchestrator records each step's position so it can resume an execution
-- after human approval from the correct step. 001_init.sql defined step_order
-- only on workflow_steps, not on execution_steps.
-- Safe to run more than once. Does not drop or rewrite any data.

ALTER TABLE execution_steps ADD COLUMN IF NOT EXISTS step_order INT;

-- Backfill rows recorded before this column existed, from the workflow definition.
UPDATE execution_steps es
SET step_order = ws.step_order
FROM executions e, workflow_steps ws
WHERE es.execution_id = e.id
  AND ws.workflow_id = e.workflow_id
  AND ws.name = es.step_name
  AND es.step_order IS NULL;

-- Make the new column visible to the Supabase REST API immediately.
NOTIFY pgrst, 'reload schema';
