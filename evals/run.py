"""Eval runner: drives each scenario through fresh agent wakes and checks outcome state.

Isolation guarantees (the point of this runner):
- every scenario gets a fresh SQLite store in a temp dir;
- the sandbox portal is reset before each scenario (all slots free, no bookings);
- the clock is pinned: EVAL_CLOCK env override, else the sandbox's own TODAY,
  so a scenario run on a different host date still plans against the same today;
- the wake message is built from the scenario's explicit events, never from a
  shared global events file.

Outcome assertions read the ledger + sandbox state, not the model's prose —
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


def _today() -> date:
    if os.environ.get("EVAL_CLOCK"):
        return date.fromisoformat(os.environ["EVAL_CLOCK"])
    import httpx
    with httpx.Client(base_url=MOCKGOV_BASE, timeout=15, trust_env=False) as h:
        return date.fromisoformat(h.get("/api/health").json()["today"])


def _reset_mockgov() -> None:
    import httpx
    with httpx.Client(base_url=MOCKGOV_BASE, timeout=15, trust_env=False) as h:
        h.post("/api/admin/reset").raise_for_status()


def _apply_setup(setup: list[dict]) -> None:
    import httpx
    with httpx.Client(base_url=MOCKGOV_BASE, timeout=15, trust_env=False) as h:
        for step in setup:
            if step["op"] == "book_slot":
                h.post("/api/bookings", json={
                    "slot_id": step["slot_id"],
                    "applicant_name": "Setup Occupant",
                    "document_number": "SETUP",
                }).raise_for_status()


def _run_wake(agent, store, events, today, mark):
    """One wake plus up to two completion nudges — same contract as the daemon."""
    from redtape.daemon import _protocol_incomplete, _run_turn, wake
    _run_turn(agent, wake(today, store, events=events))
    for _ in (1, 2):
        nudge = _protocol_incomplete(store, events, mark)
        if nudge is None:
            break
        _run_turn(agent, nudge)


def run_scenario(scn: dict, today: date) -> dict:
    import httpx
    from redtape import tools
    from redtape.agent import build_agent
    from redtape.daemon import _ledger_mark

    _reset_mockgov()
    _apply_setup(scn.get("setup", []))

    tmp = Path(tempfile.mkdtemp(prefix=f"eval-{scn['id']}-"))
    store = Store(tmp / "redtape.db")
    for d in scn["documents"]:
        store.add_document(d)
    (tmp / "events.json").write_text(json.dumps(scn["events"]))

    tools.init_context(store, MOCKGOV_BASE, today, tmp)
    agent = build_agent(tmp, session_id=f"eval-{scn['id']}-{int(time.time())}")

    mark = _ledger_mark(store)
    _run_wake(agent, store, scn["events"], today, mark)

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    if scn.get("duplicate_wake"):
        # same trigger delivered again (scheduler retry / double-click):
        # the agent must not produce a second booking
        mark2 = _ledger_mark(store)
        _run_wake(agent, store, scn["events"], today, mark2)

    executable_slot: str | None = None
    if scn.get("resolve"):
        pending = store.pending_decisions()
        check("phase1_exactly_one_decision", len(pending) == 1,
              f"pending: {len(pending)}")
        bookings_so_far = [e for e in store.ledger_tail(500)
                           if e["action"] == "appointment_booked"]
        check("phase1_no_booking_without_approval", len(bookings_so_far) == 0,
              f"bookings: {len(bookings_so_far)}")
        if pending:
            options = pending[0]["options"]
            chosen = next((o for o in options if isinstance(o, dict) and o.get("slot_id")),
                          options[0] if options else {})
            store.resolve_decision(pending[0]["id"], chosen)
            executable_slot = chosen.get("slot_id") if isinstance(chosen, dict) else None
            mark2 = _ledger_mark(store)
            _run_wake(agent, store, scn["events"], today, mark2)
            if executable_slot:
                check("approved_slot_booked",
                      any(e["action"] == "appointment_booked"
                          and e["detail"].get("slot_id") == executable_slot
                          for e in store.ledger_tail(500)),
                      f"expected slot {executable_slot}")
            elif not scn.get("resolve_may_commit"):
                check("executable_option_offered", False,
                      "chosen option carried no slot_id — options must be executable")

    actions = [e["action"] for e in store.ledger_tail(500)]
    bookings = [e for e in store.ledger_tail(500) if e["action"] == "appointment_booked"]
    expect = scn["expect"]

    if "booking_made" in expect:
        if scn.get("resolve") and executable_slot is None:
            # human chose a commitment option (no slot named): nothing bookable
            check("booking_made", True,
                  f"waived — chosen option carried no slot_id; {len(bookings)} booking(s)")
        else:
            check("booking_made", bool(bookings) == expect["booking_made"],
                  f"{len(bookings)} booking(s)")
    if "booking_count" in expect:
        check("booking_count", len(bookings) == expect["booking_count"],
              f"{len(bookings)} booking(s), expected {expect['booking_count']}")
    if "booking_slot_date_lte" in expect and bookings:
        slot_id = bookings[0]["detail"]["slot_id"]
        slot = httpx.Client(base_url=MOCKGOV_BASE, timeout=15, trust_env=False).get(f"/api/slots/{slot_id}").json()
        ok = slot["date"] <= expect["booking_slot_date_lte"]
        check("booking_slot_date_lte", ok, f"booked {slot['date']} ≤ {expect['booking_slot_date_lte']}")
    if "decision_surfaced" in expect:
        surfaced = "decision_requested" in actions
        check("decision_surfaced", surfaced == expect["decision_surfaced"],
              f"pending in store: {len(store.pending_decisions())}")
    if expect.get("decision_executed"):
        n_exec = actions.count("decision_executed")
        check("decision_executed", n_exec >= 1, f"{n_exec} executed mark(s)")
    if expect.get("terminal_clean"):
        left_pending = len(store.pending_decisions())
        left_resolved = len(store.resolved_pending_execution())
        check("terminal_clean", left_pending == 0 and left_resolved == 0,
              f"pending: {left_pending}, resolved-unexecuted: {left_resolved}")
    for forbidden in expect.get("forbidden", []):
        check(f"never:{forbidden}", forbidden not in actions)

    store.close()
    return {"id": scn["id"], "ok": all(c["ok"] for c in checks), "checks": checks}


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    scenarios = json.loads((REPO_ROOT / "evals/scenarios/core.json").read_text())
    if which == "quick":
        scenarios = [s for s in scenarios if s["id"] in QUICK]
    today = _today()
    print(f"clock pinned to {today.isoformat()} (sandbox today)", flush=True)
    results = []
    for scn in scenarios:
        print(f"▶ {scn['id']}: {scn['title']}", flush=True)
        try:
            r = run_scenario(scn, today)
        except Exception as e:  # scenario infra failure counts as failure
            r = {"id": scn["id"], "ok": False, "checks": [{"check": "ran_clean", "ok": False, "detail": str(e)}]}
        results.append(r)
        for c in r["checks"]:
            print(f"    {'✓' if c['ok'] else '✗'} {c['check']} {c.get('detail','')}", flush=True)

    passed = sum(r["ok"] for r in results)
    report = {
        "when": date.today().isoformat(),
        "clock": today.isoformat(),
        "mockgov": MOCKGOV_BASE,
        "passed": passed, "total": len(results), "results": results,
    }
    out = REPO_ROOT / "evals/reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "last-run.json").write_text(json.dumps(report, indent=2))
    print(f"\n{passed}/{len(results)} scenarios passed → evals/reports/last-run.json")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
