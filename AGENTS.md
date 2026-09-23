# AGENTS.md — Instructions for AI Coding Agents

## Mission
Help build **GhostWork**, a hackathon prototype that discovers undocumented repetitive enterprise workflows and converts them into governed agentic automations.

The primary demonstration is **Refund Verification** integrated with Freshdesk.

## Product Truth
The core differentiator is **workflow discovery before automation**.

Do not accidentally turn GhostWork into:
- a generic chatbot
- a ticket summarizer
- an RPA clone
- a voice bot
- a generic multi-agent demo

## Architecture Rules
1. Backend: Python + Flask.
2. Frontend: HTML/CSS/JavaScript.
3. Database: Supabase PostgreSQL.
4. Freshdesk integration: REST v2.
5. Claude: semantic reasoning only.
6. Deterministic Python controls all critical enterprise policies.
7. Vobiz: telephony/call transport.
8. Sarvam: speech-to-text and text-to-speech.
9. Do not introduce LangChain, LangGraph, Celery, Redis, Kafka, Kubernetes, Neo4j, React, Next.js, or another major framework unless explicitly requested.
10. Prefer readable functions/classes over clever abstractions.

## Canonical Demo Data
Do not casually change these values:
- Ticket: 2048
- Customer: Aditi Rao
- Invoice: INV-88421
- Issue: Duplicate charge
- Refund amount: ₹32,000
- Auto-approval limit: ₹25,000

Expected behavior: the Risk Agent MUST pause and require human approval.

## Security Rules
- Never hard-code or print secrets.
- Never commit `.env`.
- Never expose privileged Supabase/Freshdesk credentials to frontend JavaScript.
- Never bypass approval rules for demo convenience.
- Never allow LLM output to directly authorize a high-risk action.

## State Rules
Execution states are:
- PENDING
- RUNNING
- WAITING_FOR_APPROVAL
- APPROVED
- REJECTED
- COMPLETED
- FAILED

No downstream action may run while `WAITING_FOR_APPROVAL`.

## Claude Usage Rules
Claude may:
- understand ticket context
- interpret refund policy
- label workflows
- generate explanations
- draft customer responses

Claude may NOT:
- change approval thresholds
- skip approval
- directly perform irreversible enterprise actions

Always request structured outputs and validate them.

## Voice Approval Rules
The voice path must be layered:
1. Vobiz calls the approver.
2. Sarvam TTS reads the approval request.
3. Sarvam STT transcribes spoken response.
4. Ambiguous speech must not approve.
5. High-value approval requires a second confirmation.
6. DTMF 1 = confirm approve; DTMF 2 = reject.
7. Web approval remains a fallback.

## Freshdesk Rules
Freshdesk should be meaningful to the demo:
- read real sandbox ticket
- use ticket as workflow input
- write result back
- verify final state by reading it again

Do not implement a fake "Connected" badge without real API functionality.

## Coding Style
- Small functions.
- Descriptive names.
- Type hints where useful.
- Comments only where behavior is non-obvious.
- Separate external integrations into `services/`.
- Separate business agents into `agents/`.
- Central workflow state in `orchestrator/`.
- API routes should stay thin.

## Change Discipline
Before modifying architecture:
1. Read `PRD.md`.
2. Read `SPEC.md`.
3. Explain why the change is necessary.
4. Prefer the smallest change that solves the problem.

Do not refactor unrelated working code during time-sensitive hackathon debugging.

## Testing Discipline
For each meaningful change:
- add/update a focused test
- run relevant tests
- report exact command used
- do not claim success if tests were not run

Critical tests:
- threshold below limit
- threshold above limit
- pause/resume
- reject
- malformed LLM response
- external API failure
- verification failure

## Demo Reliability
Every external dependency must have a fallback.

Priority order:
1. Core GhostWork execution
2. Freshdesk
3. Claude
4. Web approval
5. Verification
6. Vobiz
7. Sarvam
8. Polish

If a stretch feature threatens the core flow, cut the stretch feature.

## Git Guidance
Use meaningful commits, e.g.:
- `add refund risk agent`
- `integrate freshdesk ticket retrieval`
- `implement approval pause and resume`
- `add vobiz approval callback`

Avoid: `final`, `final2`, `working`, `fix stuff`.
