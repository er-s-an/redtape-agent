# RedTape demo video — narration script + story skeleton

VIDEO_STATUS = DEFERRED-BY-DESIGN. Engineering is still moving; this script is the
frozen story skeleton for the final recording. Do not re-record until the
engineering freeze gate passes (core loop stable, P0 + attack matrix green,
evidence bound to the release SHA, README/submission aligned). When recording,
bind every on-screen number to the SHA in `evals/reports/last-run.json`.

Segments drive the assembly: cards are HTML→PNG loops, demo footage is a real
recorded run (sped up where noted). Voice: macOS `say`, re-recordable by the human later.

Story: one person, one cascade, one decision.

## S1 · title (card, ~7s)
"RedTape — an agent for the paperwork of a life across borders."

## S2 · problem — one person (card, ~30s)
"Xiao has to fly home on November 20th. Her passport shows seven months left —
plenty, you'd think. But the visa rule needs six months of validity beyond the
trip, the consulate keeps your passport for four to eight weeks, and the license
renewal needs the passport in hand. One date is coming from four directions, and
no reminder app sees the chain. RedTape does."

## S3 · demo wake (footage, ~50s at 8x)
"RedTape runs in the background — no app to babysit. We're triggering one of its
scheduled checks. It scans the document ledger and re-reads the versioned rules
from the government sandbox that ships with the repo — and catches what a human
would miss: the November 20th trip requires six months of passport validity, and
this passport expires in April."

## S4 · plan (card, ~16s)
"It computes deadlines backwards: in hand by November 13th, minus eight weeks of
processing — regular handling means submitting by mid-September. The earliest
consulate slot is October 3rd. Regular processing cannot make it."

## S5 · autonomous work (footage, ~30s at 6x)
"It still does the safe work: the renewal plan computed, the application
pre-filled as a draft, calendar holds placed. It books nothing — no slot can make
the regular deadline, and its guardrails will not let it gamble on a late one."

## S6 · decision (card, ~10s)
"When no regular path is safe, it doesn't gamble — it stops, and asks. Once."

## S7 · decision inbox (footage, ~28s, real-time)
"One viable path: expedited processing, the October 3rd slot, eighty-three
dollars — in hand around October 31st, twenty days before the trip. You approve
it. The guardrail verifies the approval — and RedTape books exactly that slot."

## S8 · trust (card + numbers, ~22s)
"Underneath: Strands agent hooks cancel unsafe actions before they run — a
wrong-service booking, an unapproved submission, a reused approval — a steering
buddy reviews every tool call, sessions survive restarts, and every action lands
in a hash-chained ledger. The scripted scenarios and the direct attack matrix
run green against the release SHA; the report is in the repo."

## S9 · close (card, ~10s)
"RedTape. Built with the Strands Agents SDK. For the 304 million people whose
lives span borders — one quiet chain of paperwork, watched end to end, in the
sandbox that ships with this repository."

## Truth labels for the editor

| Segment | Label | Note |
|---|---|---|
| S3/S5/S7 footage | Real (sandbox) | recorded against the repo's mockgov sandbox, not a live agency |
| S4 plan math | Real | deterministic domain layer, same code the agent runs |
| S7 approval → booking | Real | guardrail unlock path, recorded live |
| "government sandbox" mention | Required disclosure | never narrate as a live consulate/DMV integration |
| S8 numbers | Bind to SHA | on-screen: scenario count, pass count, commit short SHA from last-run.json |
