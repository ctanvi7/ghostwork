# GhostWork

> **Find the work nobody documented, and turn it into safe AI automation.**

GhostWork is an enterprise agentic-AI prototype that discovers repetitive workflows hidden across day-to-day operational activity, evaluates which steps can be automated safely, and converts them into reusable **GhostSkills** with human-in-the-loop governance.

## Why GhostWork?
Most automation platforms start after an organization already knows what process it wants to automate.

GhostWork starts one step earlier:

**Observe → Discover → Understand → Prioritize → Generate → Execute → Verify**

## Demo Use Case
The hackathon demo focuses on **Refund Verification**.

A Freshdesk ticket requests a ₹32,000 refund for a duplicate charge. GhostWork:
1. reads the Freshdesk ticket
2. identifies the refund workflow
3. verifies billing context
4. evaluates policy with Claude
5. enforces a ₹25,000 deterministic approval limit
6. pauses execution
7. requests human approval via web or Vobiz voice call
8. uses Sarvam text-to-speech for the approval call
9. resumes after approval
10. updates Freshdesk
11. verifies the final outcome

## Key Concepts
- **Ghost Workflow** — discovered recurring process
- **GhostGraph** — visualized process
- **GhostScore** — automation-opportunity score
- **GhostSkill** — reusable executable automation
- **Autonomy Boundary** — point where AI must stop for human judgment

## Tech Stack
- Python / Flask
- HTML / CSS / JavaScript
- Supabase PostgreSQL + Auth
- Freshdesk REST API v2
- Anthropic Claude API
- Vobiz
- Sarvam AI TTS
- pytest

## Architecture

```text
Freshdesk
   ↓
Flask API
   ↓
GhostWork Orchestrator
   ↓
Context → Billing → Policy → Risk
                         ↓
                  Human Approval
                         ↓
              Communication → Verify
   ↓
Freshdesk update
```

## Project Structure
See `SPEC.md` for the full architecture and API specification.

## Local Setup

```bash
python -m venv venv
```

Windows:
```bash
venv\Scripts\activate
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Copy environment variables:
```bash
copy .env.example .env
```

Start Flask:
```bash
python app.py
```

Health check:
```text
http://localhost:5000/api/health
```

## Environment Variables
See `.env.example`.

Never commit real API keys.

## Core Demo Path

```text
Freshdesk ticket
→ GhostSkill execution
→ Risk Agent detects ₹32,000 > ₹25,000
→ execution pauses
→ human approves
→ workflow resumes
→ Freshdesk updated
→ Verification Agent confirms success
```

## Reliability Strategy
- Voice fails → web approval
- Sarvam fails → Vobiz built-in voice reads the prompt
- Vobiz fails → web approval
- Claude fails → deterministic/cached demo response
- Freshdesk temporarily fails → cached demo ticket

## Product Principle
> **LLM for interpretation; deterministic code for enforcement.**

Claude can understand and explain. It cannot override enterprise approval rules.

## Documentation
- `PRD.md` — product requirements and user flows
- `SPEC.md` — architecture, APIs, database, implementation details
- `AGENTS.md` — rules for any AI coding agent
- `CLAUDE.md` — persistent Claude Code project instructions
- `TASKS.md` — build checklist
- `DEMO_RUNBOOK.md` — stage-demo sequence and fallbacks

## Status
Hackathon prototype in active development.

## Voice approval setup

Voice calling is optional. Set `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`,
`VOBIZ_FROM_NUMBER`, and a provider-reachable HTTPS `PUBLIC_BASE_URL` in
`.env`. The approver called is the Freshdesk ticket's assigned agent (mobile,
then phone, from the agent profile); `APPROVER_PHONE` is only a fallback. The old `VOBIZ_API_KEY` name is accepted as an
auth-token fallback, but an auth ID is still required. Set `SARVAM_API_KEY`
to use Sarvam-voiced prompts. Localhost is not a public
callback URL; use an HTTPS tunnel for a local live-call test.

On a refund above the limit, click **Call Approver**. Vobiz reads the request
using Sarvam TTS when available, or its built-in speech fallback. Press 1
to approve or 2 to reject; only key presses are accepted. Any other key
repeats the prompt. No key press, a missed call, and failed calls leave
the execution waiting so web approval can be used.

The execution page shows estimated impact after completion. Those values are
demo estimates; it separately reports whether Freshdesk write-back was
verified. The in-memory backend loses executions when the server restarts.
Supabase remains the durable backend.

The discovery dataset in `data/activity_events.json` is synthetic operational
metadata (43 events across 8 sessions). It contains no ticket text, customer
name, phone number, or credential.

Voice integration tests use mocked provider responses. A live test needs
real credentials, an approver phone, and a public HTTPS callback.
