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
- [x] Verify Freshdesk final state when a live write occurs
- [x] Verify required approval record
- [x] Record verification result and mark execution COMPLETED/FAILED

## P1 — Voice Approval
- [ ] Sarvam STT local test
- [ ] Sarvam TTS local test
- [ ] Vobiz outbound-call test
- [x] Vobiz webhook test (mocked provider callback)
- [x] Connect TTS audio to call
- [x] Capture/forward spoken response
- [x] STT transcript (mocked provider response)
- [x] Parse approve/reject intent
- [x] Require confirmation
- [x] DTMF fallback
- [x] Web fallback

## P2 — Polish
- [x] Dashboard
- [x] Integrations status page
- [x] Loading states
- [x] Error states
- [x] Impact screen with labeled demo estimates
- [ ] README screenshots
- [x] Clean synthetic, metadata-only demo dataset

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
