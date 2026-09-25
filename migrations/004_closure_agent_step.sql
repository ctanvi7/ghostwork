-- Add the closure_agent step to the Refund Verification workflow.
-- It runs after verification_agent and closes the Freshdesk ticket only when
-- approval, write-back and read-back verification have all passed.
-- Safe to run more than once. Does not drop or rewrite any data.

INSERT INTO workflow_steps (workflow_id, step_order, name, agent, classification)
SELECT w.id, 8, 'closure_agent', 'closure_agent', 'AUTOMATABLE'
FROM workflows w
WHERE w.name = 'Refund Verification'
  AND NOT EXISTS (
    SELECT 1 FROM workflow_steps ws
    WHERE ws.workflow_id = w.id AND ws.name = 'closure_agent'
  );
