-- GhostWork demo data seed

-- Insert the Refund Verification workflow
INSERT INTO workflows (name, description, ghost_score, frequency, manual_duration_seconds, automation_percentage)
VALUES ('Refund Verification', 'Process refund requests with approval gates', 87, 37, 667, 78);

-- Get the workflow ID (assume it's 1 for the first insert)
-- Insert workflow steps
INSERT INTO workflow_steps (workflow_id, step_order, name, agent, classification)
VALUES
  (1, 1, 'context_agent', 'context_agent', 'ASSISTED'),
  (1, 2, 'billing_agent', 'billing_agent', 'AUTOMATABLE'),
  (1, 3, 'policy_agent', 'policy_agent', 'ASSISTED'),
  (1, 4, 'risk_agent', 'risk_agent', 'AUTOMATABLE'),
  (1, 5, 'approval_gate', 'approval_gate', 'HUMAN_REQUIRED'),
  (1, 6, 'communication_agent', 'communication_agent', 'AUTOMATABLE'),
  (1, 7, 'verification_agent', 'verification_agent', 'AUTOMATABLE');

-- Insert a GhostSkill definition
INSERT INTO ghost_skills (workflow_id, name, definition_json)
VALUES (
  1,
  'Refund Verification',
  '{
    "trigger": "refund_request",
    "steps": ["context_agent", "billing_agent", "policy_agent", "risk_agent", "approval_gate", "communication_agent", "verification_agent"],
    "approval_rule": {
      "field": "refund_amount",
      "operator": ">",
      "value": 25000
    },
    "expected_outputs": {
      "context_agent": {"is_refund_request": true},
      "verification_agent": {"verified": true}
    }
  }'::jsonb
);
