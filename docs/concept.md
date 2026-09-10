# RedTape — Concept (working document)

> Agents for Humans Hackathon · Track: **Everyday Agents**
> One-line pitch: **An autonomous agent that watches the dependency chain of your cross-border documents — passport, visa, permit, license — and quietly handles renewals end to end, surfacing only when a real decision needs you.**

## The problem

For people who live across borders — immigrants, expats, international students, digital nomads — life admin is not a list of reminders. It is a **dependency graph**:

- Renewing a driver's license requires a valid passport *and* lawful status.
- A visa stamp requires a passport valid 6+ months beyond the stay.
- Re-entering the country requires the visa, which requires the passport, which takes 4–8 weeks at a consulate that releases appointment slots at unpredictable times.

One missed window cascades. A passport expiring in 8 months is "fine" — until you realize the consulate backlog pushes your renewal past the visa window, which pushes past the license renewal, which means you can't legally drive to work. The cost of a miss is not a late fee; it is **loss of status, fines, or being unable to travel home for a family emergency**.

Existing tools are reminder-tier: they tell you a date is coming. None of them maintain the dependency structure, track jurisdiction rule changes, pre-fill the actual forms, or book the appointment. (Prior-art scan: `../research/02-prior-art.md` — consumer-side execution is open; the only adjacent hackathon winner, Province 2025, owns *tax filing*, a different paperwork domain.)

## Who it is for

Primary persona for the demo: **a Chinese engineer on a US work visa in Seattle** whose documents form a real chain: passport (expiring in 7 months), visa stamp, I-94, driver's license. The agent works for anyone whose life spans jurisdictions, but the demo tells one person's story precisely.

## What the agent does (the loop)

RedTape runs **in the background** (a daemon on a schedule, woken by time and events — not a chat window):

1. **Watches** — polls the document ledger, renewal windows, consulate appointment availability, and jurisdiction rule sources.
2. **Reasons over the dependency graph** — computes cascading deadlines ("passport must be *filed* by Oct 20 or the license renewal misses its window").
3. **Does the safe work autonomously** — pre-fills official PDF forms from the verified document store, drafts the cover email, books the earliest compatible appointment slot, puts holds on the calendar. Every action is written to an immutable **action ledger**.
4. **Surfaces only real decisions** — when a choice has irreversible or preference-dependent consequences, the agent stops and asks, with full context: *"Slot A (Oct 3) blocks international travel Oct 1–Nov 15; Slot B (Nov 14) leaves a 9-day buffer before the license window. Which do you want?"*
5. **Executes the confirmed decision** and keeps watching until the renewal is confirmed complete.

The human never opens an app to "manage" the agent. The agent works; the human decides.

## The mechanism that makes it non-obvious (Creativity)

The core data structure is a **document dependency graph** with dated edges: *document X renewal requires document Y valid with margin M under jurisdiction rule R*. Rules are versioned per jurisdiction and re-checked against official sources. Deadlines are computed *backwards* from the constraint, not forwards from the expiry date — that inversion is what no reminder app does, and it is what makes "watching" actually prevent cascades.

## Why this maps to the judging criteria

| Criterion | How RedTape answers it |
|---|---|
| Technical Implementation | Strands hooks = deterministic guardrails (dependency validator cancels unsafe submits); `LLMSteeringHandler` buddy agent double-checks irreversible actions; `SnapshotSessionManager` survives restarts; AgentCore deploy as stretch |
| Design | Thin but complete product: background daemon + Decision Inbox UI + timeline/graph dashboard + action ledger. Not a chatbot. |
| Potential Impact | Named audience (cross-border workers/students), quantified stakes (status loss, fines), credible execution path |
| Creativity | Dependency-graph deadline inversion + real form execution; not a reminder wrapper |
| Presentation | Video shows the full background loop: wake → detect cascade risk → pre-fill + book → one decision surfaced → confirmed → done, plus one eval number |

## Determinism & trust story

Judges were told (official announcement, Sep 9): *"prioritize making your agent more deterministic — that's what the judging criteria actually reward."* RedTape answers with:

- **Hooks** that validate every action against the dependency graph and hard rules (never submit without human-confirmed data; never book overlapping holds; fee amounts must match the fetched official schedule).
- **Steering** (`LLMSteeringHandler`) as a buddy agent reviewing each tool call against natural-language operating rules, citing the SDK's published result: 100% pass over 600 eval runs vs 82.5% prompt-only.
- An **eval suite** (`evals/`) of scripted renewal scenarios run headless; the video reports the number (e.g. windows caught, correct escalations, zero unauthorized submissions).

## Demo environment honesty

The agent's logic, document parsing, form pre-fill, and decision flow are real. The consulate/DMV **booking portal is a shipped sandbox** (`mockgov/`) that simulates slot availability and confirmation, so the full loop runs offline and deterministically in the demo. The booking tool's interface is written against the real portal's flow; swapping the sandbox for production is a client change, not a redesign.
