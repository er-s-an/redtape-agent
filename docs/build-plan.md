# RedTape — Build plan (Sep 11 → Sep 14 5:00pm PT)

Deadline math: submission closes **Sep 14, 2026 5:00pm PT = Sep 15 08:00 Beijing**. All dates below are Beijing.

## Priority legend

- **P0** — required for a valid, competitive submission
- **P1** — materially raises scores (per research: AgentCore, eval numbers, UI polish)
- **P2** — stretch, only if P0+P1 are green

## Workstreams & milestones

### Day 1 — Fri Sep 11: skeleton + the loop walks
- [x] Repo scaffold, docs, license (Apache-2.0→MIT), git init
- [x] **P0** `mockgov/`: FastAPI sandbox — appointment slots, booking, form submission endpoint; deterministic seed data
- [x] **P0** Core domain model: document records, dependency graph (SQLite), backward deadline computation
- [x] **P0** Agent core: `Agent` + system prompt + tools (`list_documents`, `check_rule`, `compute_renewal_plan`, `check_appointment_slots`, `book_appointment`, `create_calendar_hold`, `draft_form_prefill`, `request_human_decision`, `notify_user`, `submit_application`)
- [x] **P0** Background daemon loop: wake → scan → act → sleep; ledger writes every action
- [x] **P0** Hooks plugin: booking guard (slot ≤ graph-computed deadline) + submission guard (human-approved decisions only)
- [x] **P1** `SnapshotSessionManager` wired in
- [x] **P1** Steering: `LLMSteeringHandler` buddy with operating rules
- [x] First full end-to-end wake verified (book S-1003, prefill draft, 3 calendar holds, valid hash chain)

### Day 2 — Sat Sep 12: real documents + guardrails + product surface
- [x] **P0** Document intake: photo → vision-model field extraction → human confirm (unconfirmed docs are hook-blocked from use)
- [x] **P0** `prefill_form`: structured JSON draft + real rendered PDF (DRAFT watermarked)
- [x] **P0** Hooks plugin: booking guard (slot ≤ graph-computed deadline; unconfirmed data blocked) + submission guard (approved decisions only) + approved-decision unlock path
- [x] **P0** Steering: `LLMSteeringHandler` with operating rules
- [x] **P0** Decision Inbox UI + documents/countdowns + dependency graph + timeline + plain-language activity feed
- [x] **P0** Decision→execution loop: resolving in the inbox wakes the agent to execute
- [x] Demo scenario tuned: tight travel date (Nov 20) makes regular processing geometrically impossible → mandatory expedite decision
- [ ] **P0** Eval suite run + numbers in hand
- [ ] **P1** AgentCore deploy (`agentcore create/deploy`), keep local mode as primary demo
- [ ] **P1** Demo video recorded + assembled

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
