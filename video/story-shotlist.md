# Final-video shot list — story skeleton (VIDEO_STATUS = DEFERRED-BY-DESIGN)

One person, one cascade, one decision. 90–120s. Freeze gate before recording:
core loop stable · P0 + attack matrix green · evidence bound to release SHA ·
README/submission/script aligned.

| # | Time | Shot | Source | Real/Simulated | On-screen text |
|---|---|---|---|---|---|
| 1 | 0–12s | Xiao, passport page, trip date Nov 20 | card + still | Simulated persona (synthetic) | "7 months left — and already too late" |
| 2 | 12–28s | Background wake: ledger scan, rule reread | recorded UI, 8x | Real (sandbox) | "no app open. no instructions." |
| 3 | 28–48s | Dependency graph + backward dates tighten | recorded UI + card | Real (deterministic plan) | "in hand 11/13 ← submit 9/18 ← book 9/11" |
| 4 | 48–68s | Safe work auto-completed; unsafe booking blocked | recorded UI, 6x | Real (hook cancel visible in Activity) | "draft ready · late slot CANCELLED by guardrail" |
| 5 | 68–88s | Decision Inbox: one choice, cost vs margin | recorded UI, real-time | Real | "$83 expedited · in hand 10/31 · approve?" |
| 6 | 88–105s | Approval → booking confirmation + ledger entry | recorded UI, real-time | Real | "CNF-… booked · ledger verified" |
| 7 | 105–120s | Sandbox disclosure + Strands close | card | Real claims only | "demo runs on the repo's government sandbox · Strands Agents SDK" |

Numbers allowed on screen (bind to SHA at recording time):
- scenario count / pass count from `evals/reports/last-run.json`
- attack matrix count from the pytest suite
- commit short SHA

Numbers NOT allowed: any real-user count, real agency integration claim,
unsourced impact multipliers, "zero unauthorized submissions" without the
attack-matrix qualifier.
