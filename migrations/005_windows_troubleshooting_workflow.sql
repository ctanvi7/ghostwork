-- Add the Windows Troubleshooting playbook: a second, non-financial automation
-- alongside Refund Verification. It never requires human approval (advice
-- only, no irreversible action), so it has no risk_agent/approval_gate step.
-- Safe to run more than once. Does not drop or rewrite any data.

INSERT INTO workflows (name, description, ghost_score, frequency, manual_duration_seconds, automation_percentage)
SELECT 'Windows Troubleshooting', 'Diagnose common Windows issues and reply with troubleshooting steps',
       69, 5, 480, 100
WHERE NOT EXISTS (SELECT 1 FROM workflows WHERE name = 'Windows Troubleshooting');

INSERT INTO workflow_steps (workflow_id, step_order, name, agent, classification)
SELECT w.id, step.step_order, step.name, step.agent, step.classification
FROM workflows w
CROSS JOIN (VALUES
    (1, 'context_agent', 'context_agent', 'ASSISTED'),
    (2, 'diagnosis_agent', 'diagnosis_agent', 'AUTOMATABLE'),
    (3, 'it_communication_agent', 'it_communication_agent', 'AUTOMATABLE'),
    (4, 'it_verification_agent', 'it_verification_agent', 'AUTOMATABLE'),
    (5, 'it_closure_agent', 'it_closure_agent', 'AUTOMATABLE')
) AS step(step_order, name, agent, classification)
WHERE w.name = 'Windows Troubleshooting'
  AND NOT EXISTS (
    SELECT 1 FROM workflow_steps ws WHERE ws.workflow_id = w.id AND ws.name = step.name
  );

NOTIFY pgrst, 'reload schema';
