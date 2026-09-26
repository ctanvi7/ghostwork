# GhostWork

**Discover hidden work. Automate it safely.**

GhostWork is an AI-powered enterprise workflow discovery and governed
automation platform that identifies recurring, undocumented work across
business systems and converts suitable workflows into safe, verifiable
agentic automation.

## What it is

Organizations perform repetitive workflows that are never formally
documented. These workflows often span multiple systems, policies,
approvals, and manual actions.

GhostWork analyzes **privacy-safe workflow telemetry** to identify
recurring patterns, reconstruct workflows, and surface high-value
automation opportunities.

**Discover → Prioritize → Understand → Execute → Approve → Verify**

GhostWork uses AI where interpretation and reasoning are valuable, while
deterministic controls govern sensitive actions.

## What it does (Business Objective)

-   Identifies recurring workflows from operational activity metadata
-   Reconstructs cross-system workflows
-   Prioritizes automation opportunities using **GhostScore**
-   Uses specialized AI agents to execute workflow steps
-   Enforces deterministic **Autonomy Boundaries**
-   Pauses high-risk actions for human approval
-   Performs approved actions through enterprise integrations such as
    Freshdesk
-   Independently verifies external actions before declaring completion
-   Maintains execution and approval history for traceability

### Example: Refund Verification

**Freshdesk Ticket → Customer Context → Billing → Policy → Risk →
Approval → Freshdesk Update → Verification**

Demo scenario:

-   **Refund requested:** ₹32,000
-   **Autonomous approval limit:** ₹25,000

GhostWork can understand and process the request, but deterministic
policy prevents it from autonomously proceeding beyond the ₹25,000
boundary. The workflow pauses for human approval. Only after approval
does GhostWork perform the Freshdesk action and independently read
Freshdesk again to verify the result.

> **AI interprets. Code governs.**

## What it doesn't do (Out of Scope)

GhostWork is not intended to:

-   Monitor employee keystrokes, screenshots, or private conversations
-   Replace humans in high-risk decisions without defined authorization
-   Allow an LLM to override deterministic enterprise policies
-   Treat an API success response alone as proof that a workflow
    succeeded
-   Automatically execute every discovered workflow
-   Replace Freshdesk or other enterprise systems of record
-   Provide unrestricted autonomous access to enterprise applications

The hackathon MVP is not positioned as production-ready enterprise
infrastructure. Production deployment would require additional
capabilities such as enterprise RBAC, multi-tenancy, expanded
observability, security hardening, compliance controls, scalability, and
additional production connectors.

## Product Integrations

  -----------------------------------------------------------------------
  Product                             How GhostWork uses it
  ----------------------------------- -----------------------------------
  **Freshdesk / Freshworks**          Enterprise support system and
                                      real-world workflow action surface

  **Freshdesk MCP**                   Reads real ticket context, performs
                                      approved actions, and independently
                                      verifies results

  **Anthropic Claude**                Semantic reasoning and
                                      interpretation of unstructured
                                      workflow context

  **Sarvam AI**                       Speech capabilities for
                                      human-in-the-loop approval
                                      experiences

  **Vobiz**                           Telephony channel for contacting
                                      human approvers

  **Supabase**                        PostgreSQL-backed persistence for
                                      workflows, executions, steps,
                                      approvals, and audit data

  **Flask**                           Backend application and API layer
  -----------------------------------------------------------------------

## System Interaction Diagram

``` text
Freshdesk MCP ───────┐
                     │
Claude ──────────────┼──► GhostWork Orchestrator
                     │       │
Supabase ────────────┘       ├──► Deterministic Governance
                             │         │
                             │         └──► Human Approval
                             │               ├── Web
                             │               └── Vobiz + Sarvam
                             │
                             └──► Freshdesk Action
                                      │
                                      ▼
                              MCP Readback Verification
```

## Core Agentic Workflow

``` text
Freshdesk Ticket
       ↓
Context Agent
       ↓
Billing Agent
       ↓
Policy Agent
       ↓
Risk Agent
       ↓
Autonomy Boundary
       ↓
Human Approval (when required)
       ↓
Communication Agent
       ↓
Freshdesk MCP
       ↓
Verification Agent
       ↓
VERIFIED COMPLETE
```

## Design Principle

> **LLMs reason. Deterministic code controls authority. External actions
> are independently verified.**

GhostWork separates reasoning, authority, action, and verification so
that understanding a request does not automatically grant an AI system
permission to execute it.
