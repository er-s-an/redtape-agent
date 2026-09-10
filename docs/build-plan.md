# RedTape — Build plan (Sep 11 → Sep 14 5:00pm PT)

Deadline math: submission closes **Sep 14, 2026 5:00pm PT = Sep 15 08:00 Beijing**. All dates below are Beijing.

## Priority legend

- **P0** — required for a valid, competitive submission
- **P1** — materially raises scores (per research: AgentCore, eval numbers, UI polish)
- **P2** — stretch, only if P0+P1 are green

## Workstreams & milestones

### Day 1 — Fri Sep 11: skeleton + the loop walks
- [x] Repo scaffold, docs, license (Apache-2.0), git init
- [ ] **P0** `mockgov/`: FastAPI sandbox — appointment slots, booking, form submission endpoint; deterministic seed data
- [ ] **P0** Core domain model: document records, dependency graph (SQLite), backward deadline computation
- [ ] **P0** Agent core: `Agent` + system prompt + first tools (`graph_query`, `graph_update`, `book_appointment`, `calendar_hold`, `request_decision`, `log_action`)
- [ ] **P0** Background daemon loop: wake → scan → act → sleep; ledger writes every action
- [ ] **P1** `SnapshotSessionManager` wired in

### Day 2 — Sat Sep 12: real documents + guardrails
- [ ] **P0** Document intake: extract expiry/fields from uploaded PDF/image (vision call) → verified document store
- [ ] **P0** `prefill_form`: fill real fillable PDFs (e.g. passport renewal form) from the document store → draft artifact
- [ ] **P0** Hooks plugin: `BeforeToolCallEvent` validators (dependency check, date sanity, no-submit-without-confirmation, fee cross-check)
- [ ] **P0** Steering: `LLMSteeringHandler` with operating rules (natural-language SOP)
- [ ] **P0** Decision Inbox UI (FastAPI + server-rendered): pending decisions with context, approve/reject; action ledger view
- [ ] **P1** Timeline + dependency-graph dashboard view

### Day 3 — Sun Sep 13: proof + polish
- [ ] **P0** Eval suite: ≥20 scripted scenarios across jurisdictions/doc types; headless runner; report (windows caught / correct escalations / unauthorized submits = 0)
- [ ] **P0** Architecture diagram (Mermaid → PNG) + README full write-up with setup-from-cold instructions
- [ ] **P1** AgentCore deploy (`agentcore create/deploy`), keep local mode as primary demo
- [ ] **P1** Demo data story rehearsed end-to-end (the persona's cascade scenario)
- [ ] **P2** Notification channel beyond inbox (email/desktop)

### Day 4 — Mon Sep 14 (deadline = Tue 08:00 Beijing): package
- [ ] **P0** Video ≤5 min: script first (problem → who → why → working loop → eval number); screen record + voiceover; upload to YouTube early; NOT "made for kids"
- [ ] **P0** Devpost submission form: every required field, Built-With names Strands Agents, repo URL, Builder ID, architecture diagram, live demo link if AgentCore is up
- [ ] **P1** builder.aws bonus posts (up to 3 × +0.2, "Agents for Humans" in title)
- [ ] **P0** Freeze everything after submit — no edits, not even typos

## User-action checklist (only the user can do these)

1. **TONIGHT before 03:00 Beijing (Sep 12)** — request the $50 AWS credits: register for the hackathon on Devpost first, then submit https://forms.gle/6sjzKiX6bKUMA5NEA
2. Register on https://agentsforhumans.devpost.com ("Join Hackathon")
3. AWS account + enable Bedrock model access (Claude Sonnet class) in the console; create **AWS Builder ID**
4. Verify eligibility (residence not in excluded list — mainland China is not excluded; HK/SG/AU/IT/… are)
5. Later: make the GitHub repo public, add license in About section; upload video; submit
