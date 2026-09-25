# GhostWork — Demo Runbook

## Golden Scenario
- Ticket: 2048
- Customer: Aditi Rao
- Invoice: INV-88421
- Refund: ₹32,000
- Auto-approval threshold: ₹25,000

## Demo Sequence
1. Open Freshdesk ticket.
2. Show GhostWork receiving/reading the ticket.
3. Open Refund Verification workflow.
4. Show:
   - 37 occurrences
   - GhostScore 87
   - 78% automatable
   - 11m 07s manual time
5. Show GhostGraph.
6. Generate/run GhostSkill.
7. Show agents completing sequentially.
8. Risk Agent pauses at ₹32,000.
9. Say: **"GhostWork doesn't just know how to act. It knows when not to act."**
10. Click `Call Approver`.
11. Vobiz calls the manager.
12. Sarvam speaks the approval request.
13. Manager says "approve" or presses 1, then presses 1 again to confirm. Pressing 2 rejects.
14. Execution resumes.
15. Freshdesk is updated.
16. Verification Agent checks the final state.
17. Show impact: 11m 07s → 1m 48s; 6 human touches → 1.
18. Close: **"Most automation platforms automate workflows companies already know. GhostWork discovers the ones they don't."**

## Fallbacks
### If Sarvam speech recognition fails
Press 1 to request approval, then 1 again to confirm. Press 2 to reject.

### If Vobiz fails
Use web approval.

### Voice prerequisites
Set `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, `VOBIZ_FROM_NUMBER`,
`APPROVER_PHONE`, and an HTTPS `PUBLIC_BASE_URL` reachable by Vobiz.
Set `SARVAM_API_KEY` for generated prompts and spoken responses. A local
`http://localhost:5000` URL cannot receive provider callbacks.

### If Claude fails
Use cached/deterministic policy result and continue.

### If Freshdesk fails
Use cached ticket data and explicitly state the sandbox connection is temporarily unavailable; do not fake a successful live API call.

## Before Judging
- Ensure API keys loaded
- Verify Freshdesk sandbox access
- Place test call
- Verify approver phone available
- Run golden scenario once
- Reset ticket state
- Reset execution state
- Disable debug noise in UI
- Keep backup screen recording ready
