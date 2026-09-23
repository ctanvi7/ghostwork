# GhostWork — Product Requirements Document (PRD)

## 1. Product Summary
GhostWork discovers repetitive enterprise workflows that are not formally documented, evaluates which parts can be safely automated, converts them into reusable agentic workflows called **GhostSkills**, and executes them with human approval at defined **Autonomy Boundaries**.

**Core positioning:**
> Most automation platforms automate workflows companies already know. GhostWork discovers the ones they don't.

## 2. Problem
Enterprise employees repeatedly perform multi-step work across tools such as Freshdesk, CRM systems, billing systems, policies, approvals, and communications. These workflows are often undocumented, so automation teams do not know they exist or how often they occur.

Traditional automation usually starts only after a process has already been identified and documented. GhostWork starts earlier by detecting recurring patterns in privacy-safe activity events, reconstructing the workflow, and identifying automation opportunities.

## 3. Target Users
### Primary
- Customer support and service operations teams
- Mid-size and enterprise organizations using Freshdesk/Freshservice
- Operations leaders looking to reduce repetitive manual work

### Secondary
- IT service teams
- Finance operations teams
- Automation / transformation teams

## 4. Demo Use Case — Refund Verification
Canonical demo data:
- Ticket ID: 2048
- Customer: Aditi Rao
- Invoice: INV-88421
- Issue: Duplicate charge
- Refund amount: ₹32,000
- Automatic approval threshold: ₹25,000

Expected flow:
1. GhostWork reads a Freshdesk ticket.
2. Context Agent identifies it as a refund workflow.
3. Billing Agent verifies the invoice / duplicate charge.
4. Policy Agent evaluates refund eligibility using Claude.
5. Risk Agent applies deterministic rules.
6. Because ₹32,000 > ₹25,000, execution pauses.
7. Human approval is requested through the web UI or Vobiz voice call.
8. Sarvam provides speech-to-text/text-to-speech for multilingual approval.
9. On confirmed approval, execution resumes.
10. Freshdesk is updated.
11. Communication Agent prepares/sends the customer response.
12. Verification Agent confirms the final Freshdesk state.

## 5. Product Vocabulary
- **Ghost Workflow** — a recurring workflow discovered from activity/event sequences.
- **GhostGraph** — visual representation of the discovered workflow.
- **GhostScore** — explainable automation-opportunity score.
- **GhostSkill** — reusable executable automation generated from a discovered workflow.
- **Autonomy Boundary** — the point where AI stops and requires human judgment.

## 6. Core Features
### F1. Freshworks Integration
- Read Freshdesk sandbox tickets through REST v2.
- Normalize ticket data into GhostWork's internal format.
- Update ticket status and create notes/replies after execution.
- Optional: trigger GhostWork from a Freshdesk webhook/event.

### F2. Workflow Discovery
- Ingest privacy-safe activity events.
- Group events into ordered sequences.
- Detect recurring patterns using deterministic sequence matching/counting.
- Label/interpret the discovered pattern using Claude where useful.

### F3. GhostScore
Explainable weighted score (0–100) using:
- Frequency: 30%
- Manual effort/time: 25%
- Automation potential: 25%
- Sequence consistency: 20%

The score must be transparent and reproducible.

### F4. GhostGraph
- Render workflow steps visually.
- Show system/tool used at each step.
- Show automation classification per step:
  - AUTOMATABLE
  - ASSISTED
  - HUMAN_REQUIRED

### F5. GhostSkill Generation
Generate a configuration-driven workflow describing:
- Trigger
- Ordered agent/tool steps
- Approval rules
- Expected outputs
- Verification conditions

### F6. Agentic Execution
Specialized agents:
- Context Agent
- Billing Agent
- Policy Agent
- Risk Agent
- Communication Agent
- Verification Agent

A central orchestrator controls execution state.

### F7. Human-in-the-Loop Approval
Execution states:
- PENDING
- RUNNING
- WAITING_FOR_APPROVAL
- APPROVED
- REJECTED
- COMPLETED
- FAILED

A high-risk action must pause before execution.

### F8. Vobiz Voice Approval
- Initiate an outbound approval call.
- Read approval message to the manager.
- Receive speech/DTMF response.
- Require a second confirmation for high-value approval.
- DTMF fallback: press 1 to approve, 2 to reject.

### F9. Sarvam Voice Layer
- Text-to-speech for approval prompts.
- Speech-to-text for manager responses.
- Support English and at least one Indian-language/code-mixed path where practical.

### F10. Claude Reasoning
Use Claude for semantic tasks only:
- Ticket intent/context extraction
- Policy interpretation
- Workflow semantic labeling
- Customer response generation

Claude must not be allowed to override deterministic enterprise controls.

### F11. Verification
After execution:
- Re-fetch Freshdesk ticket.
- Verify status/note/reply.
- Verify approval record exists.
- Mark execution VERIFIED only after checks pass.

### F12. Impact Dashboard
Show prototype/demo metrics such as:
- Manual time: 11m 07s
- Automated time: 1m 48s
- Human touches: 6 → 1
- Workflow frequency: 37
- Automation potential: 78%
- GhostScore: 87

Label unvalidated values as demo estimates.

## 7. Privacy & Governance Requirements
GhostWork must be positioned as workflow telemetry, not employee surveillance.

Do not require:
- keystroke capture
- private-message capture
- screenshots
- screen recording

Use privacy-safe operational events such as:
- ticket opened
- customer searched
- invoice fetched
- policy checked
- approval requested
- ticket updated

## 8. MVP Scope
Must-have:
- Freshdesk read/write integration
- Refund Verification demo workflow
- Claude policy reasoning
- Deterministic Risk Agent
- Pause/resume execution
- Web approval
- Verification Agent
- GhostGraph
- GhostScore

High-value extension:
- Vobiz outbound approval call
- Sarvam STT/TTS
- Freshdesk event/webhook trigger

Out of scope for MVP:
- Advanced process-mining algorithms
- Full RAG platform
- General-purpose chatbot
- Complex RBAC
- Multi-tenant enterprise billing
- Kubernetes/microservices
- Neo4j
- LangChain/LangGraph unless later proven necessary

## 9. User Flow
### Discovery
Dashboard → Discovery → Select Refund Verification → GhostGraph → GhostScore → Generate GhostSkill

### Execution
Run GhostSkill → Agents execute → Risk Agent pauses → Human approval → Resume → Freshdesk update → Verify → Impact

## 10. Success Criteria
A successful hackathon prototype must demonstrate end-to-end:

**Freshdesk ticket → GhostWork reasoning → deterministic approval gate → human approval → execution resumes → Freshdesk updated → verification succeeds.**

The demo should still complete if voice services fail by falling back to web approval.

## 11. Non-Functional Requirements
- Local-first reliability
- External integrations must have fallback paths
- No secrets committed to Git
- Clear logging of agent/tool actions
- Every approval/action auditable
- Core demo should survive temporary LLM/telephony failure
- Code must remain understandable to a two-person second-year CS team
