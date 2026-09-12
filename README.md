# RedTape

**Life moves forward. RedTape works backward.**

A background agent for cross-border paperwork. Built with the [Strands Agents SDK](https://strandsagents.com/), RedTape turns a distant travel date into an executable renewal plan, prepares reversible work, and asks before the choice becomes costly or irreversible.

## One trip, one hidden deadline

Xiao's family trip is on November 20. Her passport expires the following April: it looks valid, but the demo's six-month rule requires validity through May 20. Working backward gives a November 13 in-hand target, September 18 latest regular filing, and September 11 book-by date. The first available appointment is October 3.

The Strands agent checks confirmed documents, reads versioned sandbox rules, computes the plan and searches appointment availability. A deterministic hook blocks the late booking. RedTape prepares a draft and calendar holds, then puts the real tradeoff in the Decision Inbox:

> S-1003 · $83 expedited · projected return October 31 · 20 days before the flight.

After that exact option is approved, the agent books the sandbox appointment and returns a matching confirmation. Xiao retains the decision; RedTape carries out the approved work.

![Architecture](docs/architecture.png)

## Run locally

Tested with Python 3.13 and Strands Agents 1.55.1. A Kimi API credential is required for the default model loop; deterministic tests do not call a model.

```bash
git clone https://github.com/er-s-an/redtape-agent.git
cd redtape-agent
uv venv --python 3.13
uv pip install -r requirements-lock.txt -e '.[dev]'
export KIMI_CODE_API_KEY='<your key>'
bash scripts/demo.sh
```

Open http://localhost:9200 and press **Run agent check**. Inspect the generated decision and approve the exact displayed option. The local sandbox is at http://localhost:9100/docs. The script pins product and sandbox clocks to September 11, 2026; persona data is synthetic. It preserves existing local data, so use a fresh clone for the initial judge scenario. Close the two demo servers when finished.

Model calls use the configured external provider and can take several minutes. The recorded run required a resumed follow-through; it is not an instant-response claim. See [recorded demonstration](docs/recorded-demo.md) and [testing instructions](docs/testing.md).

## What is real

| Component | Status |
| --- | --- |
| Strands agent, tool selection, LLM steering and session persistence | Implemented; genuine hosted model exercised in the recorded case |
| Backward date planner, deterministic booking/submission guards, Decision Inbox and hash-chained SQLite ledger | Implemented and tested locally |
| Draft JSON/PDF and calendar holds | Real local artifacts; no government submission |
| Xiao's documents, rules, appointments and government portal | Synthetic shipped mockgov sandbox |
| Default model | Configured Kimi endpoint; requested and returned ID kimi-for-coding |
| Bedrock provider and AgentCore entry point | Code paths present; deployment not demonstrated |
| Live agency connectors, real-user outcomes and public hosted app | Not demonstrated |

On September 12, a real Strands run completed the same-case chain: model-selected work → blocked late slot → concrete decision → exact synthetic operator approval → matching sandbox receipt CNF-B1000. All nine outcome checks passed after a persisted-session continuation. This is one scenario, not a claim that every model call or the entire scenario suite passed. [Sanitized proof and source hashes](docs/demo-proof.json).

The 128-second English submission film reflects this genuine run. [Current transcript and shot plan](video/script.md). Public video hosting and the Devpost entry are managed separately; this repository does not claim an uploaded URL before it exists.

## Permission boundaries

The model proposes actions. Deterministic code owns date calculations and hard permissions.

Booking binds slot, office, service, document, jurisdiction and confirmation state. A slot outside the plan's safe date requires approval covering that exact slot. The UI displays actual generated alternatives and derives receipt values from the matching approval and booking.

Application submission requires an exact displayed approval: approve=true, document, jurisdiction, canonical pipeline draft path, mandatory SHA256 and matching draft provenance. SQLite atomically consumes one approval for at most one dispatch attempt. A failed request does not silently re-authorize it; this is not exactly-once delivery by a government agency. No application was filed in the recorded demo.

## Verify without a hosted model

```bash
# Terminal 1
MOCKGOV_TODAY=2026-09-11 .venv/bin/python -m uvicorn mockgov.app:app --host 127.0.0.1 --port 9100

# Terminal 2
MOCKGOV_BASE=http://127.0.0.1:9100 REDTAPE_TODAY=2026-09-11 \
  .venv/bin/python -m pytest tests/ -q
node tests/ui-display.test.mjs
```

The Python tests cover dates, concurrent ledger writes, sandbox isolation, exact displayed options, draft/hash provenance and atomic approval consumption. The JavaScript test guards against index-based fabricated alternative labels and mismatched receipt fields.

`python -m evals.run quick` and `python -m evals.run` are separate hosted-model evaluations and require credentials. The tracked evals/reports/last-run.json is a historical nine-scenario artifact, not current-release certification. No new full hosted matrix is claimed.

## Configuration and privacy

- KIMI_CODE_API_KEY: default text model and optional photo-intake credential.
- REDTAPE_PROVIDER: kimi by default; bedrock is a compatible alternate path.
- REDTAPE_MODEL_ID: kimi-for-coding by default for the Kimi provider.
- MOCKGOV_BASE: localhost:9100 by default.
- MOCKGOV_TODAY / REDTAPE_TODAY: both pinned by the demo script.

Photo intake sends the selected image to Kimi's vision endpoint and retains a local raw upload until its document is deleted. Use the shipped synthetic persona or manual entry for judging. A different text provider does not automatically change photo intake. Keep credentials and personal documents out of Git; generated state is ignored.

## Source map

- redtape/agent.py — Strands assembly, operating prompt and LLM steering.
- redtape/domain.py — deterministic backward planning.
- redtape/plugins/guardrails.py — action-bound permission hooks.
- redtape/store.py — documents, decisions, atomic approval use and ledger.
- redtape/server.py and static/index.html — product surface.
- mockgov/ — versioned rules and local government sandbox.
- docs/architecture.svg — editable architecture source.

MIT licensed. See [LICENSE](LICENSE).
