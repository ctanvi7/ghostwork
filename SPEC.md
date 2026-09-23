# GhostWork — Technical Specification

## 1. Architecture

```text
Freshdesk Sandbox
      │
      │ REST v2 / optional webhook
      ▼
Flask Backend
      │
      ├── Freshdesk Service
      ├── Claude Service
      ├── Sarvam Service
      ├── Vobiz Service
      ├── Supabase Service
      │
      ▼
GhostWork Orchestrator
      │
      ├── Context Agent
      ├── Billing Agent
      ├── Policy Agent
      ├── Risk Agent
      ├── Communication Agent
      └── Verification Agent
      │
      ├── deterministic rules
      ├── approval state machine
      └── GhostSkill executor
      │
      ▼
Supabase PostgreSQL
      │
      ▼
Browser UI
```

## 2. Final Tech Stack
- Frontend: HTML, CSS, JavaScript
- Backend: Python 3.11+ / Flask
- Database: Supabase PostgreSQL
- Auth: Supabase Auth (keep auth out of main demo)
- Freshworks: Freshdesk REST API v2
- LLM: Anthropic Claude API
- Voice telephony: Vobiz
- Speech: Sarvam STT + TTS
- Version control: Git + GitHub
- Testing: pytest
- Prompting during build: Wispr Flow

## 3. Repository Structure

```text
ghostwork/
├── app.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
├── agents/
│   ├── context_agent.py
│   ├── billing_agent.py
│   ├── policy_agent.py
│   ├── risk_agent.py
│   ├── communication_agent.py
│   └── verification_agent.py
├── services/
│   ├── freshdesk.py
│   ├── claude.py
│   ├── sarvam.py
│   ├── vobiz.py
│   └── supabase_service.py
├── orchestrator/
│   └── workflow.py
├── routes/
│   ├── tickets.py
│   ├── workflows.py
│   ├── executions.py
│   ├── approvals.py
│   └── webhooks.py
├── templates/
├── static/
├── data/
│   ├── events.json
│   └── refund_policy.txt
├── tests/
├── PRD.md
├── SPEC.md
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

## 4. Core Domain Models

### Workflow
```json
{
  "id": 1,
  "name": "Refund Verification",
  "ghost_score": 87,
  "frequency": 37,
  "manual_duration_seconds": 667,
  "automation_percentage": 78
}
```

### GhostSkill
```json
{
  "name": "Refund Verification",
  "trigger": "refund_request",
  "steps": [
    "context_agent",
    "billing_agent",
    "policy_agent",
    "risk_agent",
    "approval_gate",
    "communication_agent",
    "verification_agent"
  ],
  "approval_rule": {
    "field": "refund_amount",
    "operator": ">",
    "value": 25000
  }
}
```

### Execution
```json
{
  "id": 51,
  "workflow_id": 1,
  "ticket_id": 2048,
  "status": "WAITING_FOR_APPROVAL",
  "current_step": "risk_agent",
  "refund_amount": 32000
}
```

## 5. Database Schema

### workflows
- id
- name
- description
- ghost_score
- frequency
- manual_duration_seconds
- automation_percentage
- created_at

### workflow_steps
- id
- workflow_id
- step_order
- name
- agent
- classification

### ghost_skills
- id
- workflow_id
- name
- definition_json
- created_at

### executions
- id
- workflow_id
- ticket_id
- status
- current_step
- refund_amount
- started_at
- completed_at

### execution_steps
- id
- execution_id
- step_name
- agent
- status
- result_json
- started_at
- completed_at

### approvals
- id
- execution_id
- amount
- status
- channel
- approver
- raw_response
- created_at
- decided_at

### integrations
- id
- provider
- status
- metadata_json
- updated_at

## 6. State Machine

```text
PENDING
  ↓
RUNNING
  ↓
Risk check
  ├── safe → RUNNING
  └── approval required → WAITING_FOR_APPROVAL
                              ├── approve → APPROVED → RUNNING
                              └── reject  → REJECTED
RUNNING
  ↓
COMPLETED

Any unrecoverable error → FAILED
```

No downstream action may execute while status is WAITING_FOR_APPROVAL.

## 7. API Contract

### Health
`GET /api/health`

### Workflows
`GET /api/workflows`

`GET /api/workflows/<id>`

`POST /api/discover`
- input: event dataset
- output: discovered workflows

### GhostSkills
`POST /api/skills/generate`
- input: workflow id
- output: GhostSkill definition

### Executions
`POST /api/executions`
```json
{
  "workflow_id": 1,
  "ticket_id": 2048
}
```

`GET /api/executions/<id>`

### Approval
`POST /api/executions/<id>/approve`

`POST /api/executions/<id>/reject`

### Vobiz
`POST /api/executions/<id>/call-approver`

`POST /api/webhooks/vobiz`

### Freshdesk
`POST /api/webhooks/freshdesk` (optional stretch)

## 8. Freshdesk Integration
### Required operations
1. Fetch ticket
2. Fetch ticket conversations if needed
3. Update ticket
4. Add note or reply
5. Re-fetch ticket for verification

### Internal normalized ticket
```json
{
  "ticket_id": 2048,
  "customer": "Aditi Rao",
  "subject": "Duplicate charge refund",
  "description": "...",
  "invoice_id": "INV-88421",
  "refund_amount": 32000
}
```

Do not expose Freshdesk API credentials to the browser.

## 9. Claude Integration
Claude is used for semantic reasoning only.

### Allowed
- Extract structured intent/context
- Interpret policy text
- Explain decisions
- Label discovered sequences
- Generate customer-facing drafts

### Not allowed
- Override the approval threshold
- Execute irreversible actions directly
- Decide that a required approval can be skipped

Prefer structured JSON outputs and validate all fields.

## 10. Risk Agent
Deterministic policy:

```python
AUTO_APPROVAL_LIMIT = 25000

if refund_amount > AUTO_APPROVAL_LIMIT:
    require_human_approval()
```

The threshold must be server-side and test-covered.

## 11. Vobiz + Sarvam Flow

```text
Risk Agent → WAITING_FOR_APPROVAL
        ↓
User clicks "Call Approver"
        ↓
Vobiz initiates outbound call
        ↓
Sarvam TTS creates prompt audio
        ↓
Manager hears request
        ↓
Manager responds by speech or DTMF
        ↓
Sarvam STT converts speech to text
        ↓
GhostWork parses intent
        ↓
Require second confirmation
        ↓
APPROVED / REJECTED
        ↓
Resume or stop workflow
```

### Safety
- Speech approval alone is not final for high-value actions.
- Require "CONFIRM APPROVE" or DTMF 1.
- DTMF 2 rejects.
- Ambiguous speech → ask again.

## 12. Workflow Discovery
Use deterministic sequence grouping for MVP.

Algorithm:
1. Group events by case/work item.
2. Sort by timestamp.
3. Build sequence signature.
4. Count repeated signatures.
5. Rank by frequency.
6. Optionally use Claude to assign a business label.

No advanced process-mining framework is required.

## 13. GhostScore

```text
GhostScore =
0.30 * frequency_score +
0.25 * effort_score +
0.25 * automation_score +
0.20 * consistency_score
```

All component scores normalized to 0–100.

## 14. Frontend Screens
1. Dashboard
2. Discovery
3. Workflow Detail / GhostGraph
4. GhostSkill
5. Execution
6. Impact
7. Integrations (optional)

Execution screen must visibly show:
- each agent status
- current step
- approval warning
- amount vs threshold
- Approve / Reject / Call Approver
- post-approval continuation
- verification result

## 15. Fallback Strategy
### Tier A
Freshdesk + Claude + Vobiz + Sarvam

### Tier B
Freshdesk + Claude + web approval

### Tier C
Cached Freshdesk ticket + deterministic/local path + web approval

The demo must never depend on telephony or the LLM to finish.

## 16. Environment Variables

```text
FLASK_SECRET_KEY=
SUPABASE_URL=
SUPABASE_KEY=
ANTHROPIC_API_KEY=
FRESHDESK_DOMAIN=
FRESHDESK_API_KEY=
SARVAM_API_KEY=
VOBIZ_API_KEY=
VOBIZ_FROM_NUMBER=
APPROVER_PHONE=
```

Never commit `.env`.

## 17. Testing Requirements
Minimum tests:
- ₹10,000 refund does not pause
- ₹32,000 refund pauses
- approval resumes execution
- rejection stops execution
- Freshdesk failure marks step failed
- Claude malformed JSON is handled
- verification fails if expected Freshdesk update is missing
- Vobiz/Sarvam failure falls back to web approval

## 18. Implementation Principles
- Favor simple code over framework-heavy abstractions.
- Keep every agent independently testable.
- Persist state before external actions.
- Validate all external API responses.
- Time out external calls.
- Log tool calls, decisions, and failures.
- Never hide errors behind fake success states.
