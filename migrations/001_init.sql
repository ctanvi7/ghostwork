-- GhostWork schema initialization

-- Workflows table
CREATE TABLE IF NOT EXISTS workflows (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  ghost_score NUMERIC(5, 2),
  frequency INT,
  manual_duration_seconds INT,
  automation_percentage NUMERIC(5, 2),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Workflow steps
CREATE TABLE IF NOT EXISTS workflow_steps (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workflow_id BIGINT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  step_order INT NOT NULL,
  name TEXT NOT NULL,
  agent TEXT NOT NULL,
  classification TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(workflow_id, step_order)
);

-- GhostSkills
CREATE TABLE IF NOT EXISTS ghost_skills (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workflow_id BIGINT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  definition_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Execution states: PENDING, RUNNING, WAITING_FOR_APPROVAL, APPROVED, REJECTED, COMPLETED, FAILED
CREATE TABLE IF NOT EXISTS executions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workflow_id BIGINT NOT NULL REFERENCES workflows(id),
  ticket_id BIGINT,
  status TEXT NOT NULL DEFAULT 'PENDING',
  current_step TEXT,
  refund_amount NUMERIC(12, 2),
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CHECK (status IN ('PENDING', 'RUNNING', 'WAITING_FOR_APPROVAL', 'APPROVED', 'REJECTED', 'COMPLETED', 'FAILED'))
);

-- Execution steps (one row per step per execution)
CREATE TABLE IF NOT EXISTS execution_steps (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  execution_id BIGINT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
  step_name TEXT NOT NULL,
  agent TEXT,
  status TEXT NOT NULL,
  attempt INT DEFAULT 1,
  result_json JSONB,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Approvals
CREATE TABLE IF NOT EXISTS approvals (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  execution_id BIGINT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
  amount NUMERIC(12, 2),
  status TEXT NOT NULL DEFAULT 'PENDING',
  channel TEXT,
  approver TEXT,
  raw_response JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  decided_at TIMESTAMPTZ,
  CHECK (status IN ('PENDING', 'AWAITING_CONFIRMATION', 'APPROVED', 'REJECTED', 'EXPIRED'))
);

-- Integrations status
CREATE TABLE IF NOT EXISTS integrations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  provider TEXT NOT NULL UNIQUE,
  status TEXT,
  metadata_json JSONB,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit events (for compliance and debugging)
CREATE TABLE IF NOT EXISTS audit_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  execution_id BIGINT REFERENCES executions(id) ON DELETE CASCADE,
  actor TEXT,
  action TEXT NOT NULL,
  detail_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
CREATE INDEX IF NOT EXISTS idx_executions_ticket_id ON executions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_execution_steps_execution_id ON execution_steps(execution_id);
CREATE INDEX IF NOT EXISTS idx_approvals_execution_id ON approvals(execution_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_audit_events_execution_id ON audit_events(execution_id);

-- Partial unique index: only one active execution per ticket
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_per_ticket
  ON executions(ticket_id)
  WHERE status IN ('PENDING', 'RUNNING', 'WAITING_FOR_APPROVAL', 'APPROVED');

-- Partial unique index: only one open approval per execution
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_approval_per_execution
  ON approvals(execution_id)
  WHERE status IN ('PENDING', 'AWAITING_CONFIRMATION');

-- Row Level Security (RLS) - empty policies for demo (all access allowed with service key)
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE ghost_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

-- Allow all access with service role (no public access)
-- Policies would be defined here but are omitted for demo; RLS is enabled to enforce security.
