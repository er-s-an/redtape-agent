# RedTape

**An autonomous agent that guards the dependency chain of your cross-border documents — passport, visa, permit, license — and handles renewals end to end in the background, surfacing only when a real decision needs you.**

Built with the [Strands Agents SDK](https://strandsagents.com/) · Agents for Humans Hackathon, **Everyday Agents** track.

## The problem

**November 20, a flight home.** The passport looks fine — seven months left. But the trip needs six months of validity *beyond* the stay, the consulate takes up to eight weeks to process, and appointments book out weeks ahead. Run the chain backwards and "seven months left" is an emergency with a six-week fuse.

For people who live across borders, life admin is not a reminder list — it is a dependency graph. A driver's-license renewal needs a valid passport and lawful status. A visa stamp needs six months of passport validity. And the renewal itself takes 4–8 weeks during which **you don't have your passport**. Miss one window and the chain cascades: lost status, fines, or no way to fly home for an emergency.

Reminder apps tell you a date is coming. RedTape computes your deadlines *backwards* from the constraints, does the safe work itself — checks the rules, books the appointment, pre-fills the forms, holds the calendar — and only interrupts you when a decision is genuinely yours.

## See it run

```bash
git clone https://github.com/er-s-an/redtape-agent.git && cd redtape-agent
uv venv && uv pip install -e ".[dev]"        # or: python -m venv .venv && pip install -e ".[dev]"
export KIMI_CODE_API_KEY=...                  # any Strands-supported model key; see Configuration

bash scripts/demo.sh                          # one command: sandbox + web app + demo persona, opens the UI
```

Or step by step:

```bash
# terminal 1 — the sandboxed government portal (deterministic demo environment)
uvicorn mockgov.app:app --port 9100

# terminal 2 — the product
python scripts/seed_persona.py                # synthetic demo persona, no real data
uvicorn redtape.server:app --port 9200        # open http://localhost:9200
```

Press **Run a check** in the UI. RedTape scans the document ledger, re-reads the sandbox portal's versioned rules, computes the backward-chained plan, books a valid appointment, pre-fills the application (JSON + a reviewable PDF draft, watermarked **DRAFT — NOT SUBMITTED**), places calendar holds — and if a choice is irreversible or costs money, it stops and asks you in the **Decision Inbox**.

![The dashboard: document chain, backward-chained timeline, and a decision that needs you](assets/dashboard.png)

The demo environment (`mockgov/`) simulates the consulate/DMV portal so the whole loop runs offline and deterministically. The agent's reasoning, document parsing, form pre-fill, guardrails, and decision flow are real; the portal client is the only simulated piece, isolated behind one interface.

## What makes it an agent, not a reminder

- **Dependency-graph planning** — deadlines are computed backwards from *when the document must be in hand*, through processing time and appointment lead, not forwards from an expiry date. Cross-renewal conflicts (passport surrendered while the license renewal needs it) are detected explicitly.
- **Background by design** — a daemon wakes the agent on a schedule or on triggers; there is no chat to babysit. After each wake the daemon verifies the cycle reached a terminal state (a booking landed, or a decision is pending/executed, or the plan required nothing) and nudges the agent once if it ended early — an empty model finish can't silently stall the chain.
- **Deterministic guardrails** — Strands **hooks** cancel any booking that lands after the graph-computed safe date, and cancel any application submission not explicitly approved by you; an approved decision unlocks exactly the slots it names (even when the model buries the slot id in prose). Watch the hook fire in the Activity feed.
- **A steering buddy** — Strands' `LLMSteeringHandler` reviews each tool call against natural-language operating rules and guides the agent back when it drifts. RedTape subclasses it to degrade "interrupt for human" decisions into guidance: a background agent must never suspend mid-turn waiting for a human — the Decision Inbox is the only human-input channel.
- **Auditable everything** — every action lands in a hash-chained ledger you can verify (`verify_ledger()`); sessions persist across restarts via `SnapshotSessionManager`. The store runs in WAL mode with serialized access, so the web server, daemon, and CLI checks can share one database without starving each other's writes.
- **Photo intake** — point a camera at a document; the vision model extracts the fields, you confirm, the agent takes it from there. (The photo is sent to the configured vision provider — Kimi in the demo — and stored locally until you delete it; nothing is trusted until you confirm.)

## Architecture

![architecture](docs/architecture.png)

```
scheduler ── wakes ──▶ Strands agent ──▶ tools: documents · rules · plans · booking · forms · calendar
                           │  ▲                     guardrail hooks cancel unsafe calls before they run
                           │  └── steering buddy reviews every tool call
                           ▼
                    Decision Inbox (the only interruption)  ·  hash-chained action ledger
```

## Evaluation

`python -m evals.run` (with the sandbox portal running on :9100) drives **10 scripted scenarios** against a **fresh, isolated state per scenario** — a temp SQLite store, a reset sandbox (slots, bookings, and rules restored to shipped versions), and a pinned clock — and asserts on **outcome state**, not model prose: exact booking counts with office/service/slot binding, exactly-once execution after a human resolves a decision, no booking at all when the best slot is taken until a human approves a choice, no double-booking on a duplicate trigger, adaptation when a rule version changes mid-run, a strict side-effect allowlist per scenario, and zero unauthorized submissions. Latest report (with run provenance: commit SHA, provider/model, SDK version, clock): `evals/reports/last-run.json`.

A deterministic **attack matrix** (`tests/test_guardrails.py`) calls the guardrail hooks directly — no model in the loop — and cancels: wrong-office/service bookings, bookings with no plan authorization, submissions without an approved decision (asserting the block is *logged*, not just absent), and reused approvals. Safety claims come from these two layers together, not from the agent behaving during a demo.

```bash
python -m evals.run            # full suite → evals/reports/last-run.json
python -m evals.run quick      # the 3 fastest scenarios
```

Set `EVAL_CLOCK=2026-09-11` to pin the planning date regardless of the host date (by default the suite uses the sandbox's own `TODAY`).

## Current status

| Claim | Status |
|---|---|
| Background wake → plan → safe work → one human decision → execute | **Implemented** (sandbox) |
| Guardrail hooks: date bound, action binding (office/service/doc), submission approval with one-time nonce | **Implemented** — attack matrix in `tests/test_guardrails.py` |
| Eval suite (10 scenarios) + attack matrix (5 direct attacks) | **Implemented** — latest numbers in `evals/reports/last-run.json`, bound to the run's commit SHA |
| Government portal | **Simulated** — `mockgov/` ships with the repo; rule payloads carry the real source URLs they were modeled on |
| Real consulate/DMV integration, real submissions | **Planned** — portal client is isolated behind one interface |
| AgentCore deployment / live demo | **Planned** — provider path wired (`REDTAPE_PROVIDER=bedrock`), not deployed |
| Photo intake privacy (retention/redaction policy) | **Partially implemented** — raw file removed on document delete; vision extraction disclosed in the upload endpoint |
| Real-user impact evidence | **NOT_RUN** |
| Eligibility self-declaration, public video upload, Devpost submission | **PAUSED-HUMAN** |

## Configuration

| env var | default | purpose |
|---|---|---|
| `KIMI_CODE_API_KEY` | — | model key (dev/demo default: Kimi K2.7) |
| `REDTAPE_PROVIDER` | `kimi` | `kimi` or `bedrock` (AgentCore path) |
| `REDTAPE_MODEL_ID` | `kimi-for-coding` | model override |
| `MOCKGOV_TODAY` | `2026-09-11` | the sandbox's "today" — pin it to keep demo dates stable |
| `REDTAPE_TODAY` | host date | the web app's and daemon's "today" — set it to match `MOCKGOV_TODAY` so every surface plans against the same day |
| `EVAL_CLOCK` | sandbox `TODAY` | the eval suite's planning date |

Note on providers: the agent loop works with any Strands-supported text model (the provider is one env var away), but **photo intake currently calls Kimi's vision endpoint directly** — with another provider, document entry falls back to manual form entry. The `bedrock` provider path is wired but the AgentCore deployment is optional and not part of this repo's local demo. `requirements-lock.txt` records the exact dependency set the tests and evals were last verified against.

## License

MIT — see [LICENSE](LICENSE).
