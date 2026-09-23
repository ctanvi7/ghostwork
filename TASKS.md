# GhostWork — Build Checklist

## P0 — Core Spine
- [ ] Create repo and project structure
- [ ] Flask `/api/health`
- [ ] Configure `.env`
- [ ] Create Supabase schema
- [ ] Implement execution state model
- [ ] Implement deterministic Risk Agent
- [ ] Implement web Approve / Reject
- [ ] Implement pause/resume orchestrator
- [ ] Build minimal execution UI

## P0 — Freshworks
- [ ] Connect Freshdesk sandbox
- [ ] Fetch ticket
- [ ] Normalize ticket into GhostWork model
- [ ] Update ticket
- [ ] Add note/reply
- [ ] Re-fetch and verify update

## P0 — Claude
- [ ] Context extraction
- [ ] Policy interpretation
- [ ] Structured JSON validation
- [ ] Customer-response generation
- [ ] Fallback for model/API failure

## P1 — Discovery
- [ ] Seed event dataset
- [ ] Group events by case
- [ ] Detect repeated sequence
- [ ] Compute GhostScore
- [ ] Render GhostGraph
- [ ] Generate GhostSkill JSON

## P1 — Verification
- [ ] Verify Freshdesk final state
- [ ] Verify approval record
- [ ] Mark execution VERIFIED/FAILED

## P1 — Voice Approval
- [ ] Sarvam STT local test
- [ ] Sarvam TTS local test
- [ ] Vobiz outbound-call test
- [ ] Vobiz webhook test
- [ ] Connect TTS audio to call
- [ ] Capture/forward spoken response
- [ ] STT transcript
- [ ] Parse approve/reject intent
- [ ] Require confirmation
- [ ] DTMF fallback
- [ ] Web fallback

## P2 — Polish
- [ ] Dashboard
- [ ] Integrations status page
- [ ] Loading states
- [ ] Error states
- [ ] Impact screen
- [ ] README screenshots
- [ ] Clean demo dataset

## Pre-Demo Validation
- [ ] ₹10,000 refund proceeds automatically
- [ ] ₹32,000 refund pauses
- [ ] Web approval resumes
- [ ] Rejection stops
- [ ] Vobiz approval resumes
- [ ] Freshdesk shows final update
- [ ] Verification succeeds
- [ ] Demo completes with Claude unavailable
- [ ] Demo completes with voice unavailable
