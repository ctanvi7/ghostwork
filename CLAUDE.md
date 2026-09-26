# CLAUDE.md — Persistent Instructions for Claude Code

## Project
**GhostWork** — discovers undocumented repetitive enterprise workflows and converts them into governed AI-agent automations.

## Core Demo
Refund Verification:
- Freshdesk Ticket: 2048
- Customer: Aditi Rao
- Invoice: INV-88421
- Refund: ₹32,000
- Autonomous approval threshold: ₹25,000

The workflow must pause at the Risk Agent, obtain human approval, resume, update Freshdesk, and verify the final state.

## Read First
Before making non-trivial changes, read:
1. `PRD.md`
2. `SPEC.md`
3. `AGENTS.md`
4. `TASKS.md` if present

## Stack
- Python + Flask
- HTML/CSS/JavaScript
- Supabase PostgreSQL + Auth
- Freshdesk REST v2
- Anthropic Claude API
- Vobiz telephony
- Sarvam TTS
- pytest

## Hard Constraints
- Do not add a new major framework unless explicitly requested.
- Do not replace Flask with FastAPI/Django.
- Do not replace vanilla frontend with React/Next.js.
- Do not add LangChain/LangGraph by default.
- Do not add microservices, queues, or infrastructure unless required.
- Do not hard-code secrets.
- Do not bypass the approval state machine.
- Do not let LLM output override deterministic policy rules.

## Design Principle
**LLM for interpretation; code for enforcement.**

Examples:
- Claude may determine that a ticket is a refund request.
- Claude may interpret the textual refund policy.
- Python must enforce `refund_amount > 25000 => approval required`.

## Implementation Order
When building from scratch or repairing the app, prioritize:
1. Flask health route
2. Execution state model
3. Risk Agent
4. Web approval pause/resume
5. Basic execution UI
6. Claude policy reasoning
7. Freshdesk read
8. Freshdesk write-back
9. Verification Agent
10. Workflow discovery / GhostScore / GhostGraph
11. Vobiz call
12. Sarvam TTS
13. Polish

## External API Behavior
For Freshdesk, Claude, Vobiz, and Sarvam:
- use timeouts
- validate responses
- catch errors
- log failures
- return explicit error states
- keep a demo fallback path

## Response Format When Helping Us Code
When asked to implement a feature:
1. Briefly state what will change.
2. Name the files to create/modify.
3. Make the smallest working change.
4. Add a focused test when applicable.
5. Give the exact command to run.
6. Explain expected output.
7. Do not rewrite unrelated files.

## Beginner-Friendly Requirement
The team must be able to explain the code to judges.
Prefer clear code and short explanations over advanced patterns.

## Demo Safety
Never make the demo dependent on:
- live LLM availability
- voice recognition
- telephony
- external deployment

The safe fallback is:
**cached/real ticket → deterministic agent flow → web approval → Freshdesk/mock write → verification.**
