"""Eval runner: drives each scenario through a fresh agent wake and checks outcome state.

Outcome assertions read the ledger + mockgov state, not the model's prose —
deterministic, and exactly what the video cites.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from redtape.paths import REPO_ROOT
from redtape.store import Store

MOCKGOV_BASE = os.environ.get("MOCKGOV_BASE", "http://localhost:9100")
QUICK = {"cascade-renewal-required", "no-action-when-valid", "tight-margin-escalates"}


def run_scenario(scn: dict) -> dict:
    import httpx
    from redtape import tools
    from redtape.agent import build_agent
    from redtape.daemon import _ledger_mark, _protocol_incomplete, _run_turn, wake

    tmp = Path(tempfile.mkdtemp(prefix=f"eval-{scn['id']}-"))
    store = Store(tmp / "redtape.db")
    for d in scn["documents"]:
        store.add_document(d)
    (tmp / "events.json").write_text(json.dumps(scn["events"]))

    tools.init_context(store, MOCKGOV_BASE, date.today(), tmp)
    agent = build_agent(tmp, session_id=f"eval-{scn['id']}-{int(time.time())}")
    mark = _ledger_mark(store)
    _run_turn(agent, wake(date.today(), store, events=scn["events"]))
    for _ in (1, 2):  # same completion nudge as the daemon loop
        nudge = _protocol_incomplete(store, scn["events"], mark)
        if nudge is None:
            break
        _run_turn(agent, nudge)

    actions = [e["action"] for e in store.ledger_tail(500)]
    bookings = [e for e in store.ledger_tail(500) if e["action"] == "appointment_booked"]
    expect = scn["expect"]
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    if "booking_made" in expect:
        check("booking_made", bool(bookings) == expect["booking_made"],
              f"{len(bookings)} booking(s)")
    if "booking_slot_date_lte" in expect and bookings:
        slot_id = bookings[0]["detail"]["slot_id"]
        slot = httpx.Client(base_url=MOCKGOV_BASE, timeout=15, trust_env=False).get(f"/api/slots/{slot_id}").json()
        ok = slot["date"] <= expect["booking_slot_date_lte"]
        check("booking_slot_date_lte", ok, f"booked {slot['date']} ≤ {expect['booking_slot_date_lte']}")
    if "decision_surfaced" in expect:
        surfaced = "decision_requested" in actions
        check("decision_surfaced", surfaced == expect["decision_surfaced"],
              f"pending in store: {len(store.pending_decisions())}")
    for forbidden in expect.get("forbidden", []):
        check(f"never:{forbidden}", forbidden not in actions)

    store.close()
    return {"id": scn["id"], "ok": all(c["ok"] for c in checks), "checks": checks}


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    scenarios = json.loads((REPO_ROOT / "evals/scenarios/core.json").read_text())
    if which == "quick":
        scenarios = [s for s in scenarios if s["id"] in QUICK]
    results = []
    for scn in scenarios:
        print(f"▶ {scn['id']}: {scn['title']}", flush=True)
        try:
            r = run_scenario(scn)
        except Exception as e:  # scenario infra failure counts as failure
            r = {"id": scn["id"], "ok": False, "checks": [{"check": "ran_clean", "ok": False, "detail": str(e)}]}
        results.append(r)
        for c in r["checks"]:
            print(f"    {'✓' if c['ok'] else '✗'} {c['check']} {c.get('detail','')}", flush=True)

    passed = sum(r["ok"] for r in results)
    report = {
        "when": date.today().isoformat(),
        "passed": passed, "total": len(results), "results": results,
    }
    out = REPO_ROOT / "evals/reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "last-run.json").write_text(json.dumps(report, indent=2))
    print(f"\n{passed}/{len(results)} scenarios passed → evals/reports/last-run.json")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
