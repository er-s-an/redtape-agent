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

# Ledger actions that change state. Everything else (reads, tool_call logs,
# plan_computed, …) is telemetry and is not allowlist-checked.
SIDE_EFFECT_ACTIONS = {
    "appointment_booked", "booking_blocked", "booking_failed",
    "form_prefilled", "form_pdf_rendered", "calendar_hold_created",
    "decision_requested", "decision_resolved", "decision_executed",
    "application_submitted", "submission_blocked", "submission_allowed",
    "document_confirmed", "document_deleted", "notification",
}


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
            elif step["op"] == "bump_rule":
                h.post(f"/api/admin/rules/{step['jurisdiction']}/{step['doc_type']}/bump",
                       json=step["changes"]).raise_for_status()


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

    # slot metadata for every booking, straight from the sandbox
    slot_meta: dict[str, dict] = {}
    if bookings:
        import httpx
        with httpx.Client(base_url=MOCKGOV_BASE, timeout=15, trust_env=False) as h:
            for b in bookings:
                sid = b["detail"].get("slot_id")
                if sid and sid not in slot_meta:
                    slot_meta[sid] = h.get(f"/api/slots/{sid}").json()

    # --- precise booking oracle -----------------------------------------
    if "booking_total" in expect:
        check("booking_total", len(bookings) == expect["booking_total"],
              f"{len(bookings)} booking(s), expected {expect['booking_total']}")
    if "exact_bookings" in expect:
        for slot_id, n in expect["exact_bookings"].items():
            got = sum(1 for b in bookings if b["detail"].get("slot_id") == slot_id)
            check(f"slot_{slot_id}_exactly_{n}", got == n,
                  f"{got} booking(s) on {slot_id}")
    if "service_counts" in expect:
        counts: dict[str, int] = {}
        for b in bookings:
            svc = slot_meta.get(b["detail"].get("slot_id"), {}).get("service", "?")
            counts[svc] = counts.get(svc, 0) + 1
        for svc, n in expect["service_counts"].items():
            check(f"service_{svc}_exactly_{n}", counts.get(svc, 0) == n,
                  f"{counts.get(svc, 0)} booking(s) on {svc}; all services: {counts}")
    if "booking_uniqueness" in expect:
        ids = [b["detail"].get("slot_id") for b in bookings]
        check("booking_uniqueness", len(ids) == len(set(ids)), f"slots: {ids}")
    if "booking_slot_date_lte" in expect and bookings:
        passport_bookings = [b for b in bookings
                             if slot_meta.get(b["detail"].get("slot_id"), {}).get("service") == "passport_renewal"]
        target = passport_bookings[0] if passport_bookings else bookings[0]
        slot = slot_meta[target["detail"]["slot_id"]]
        ok = slot["date"] <= expect["booking_slot_date_lte"]
        check("booking_slot_date_lte", ok, f"booked {slot['date']} ≤ {expect['booking_slot_date_lte']}")

    # --- semantic-adaptation oracle --------------------------------------
    if "rule_min_version" in expect:
        seen = [e["detail"].get("version", 0) for e in store.ledger_tail(500)
                if e["action"] == "rule_checked"
                and e["detail"].get("jurisdiction") == expect.get("rule_jurisdiction", "cn-consulate-sf")]
        top = max(seen) if seen else 0
        check("rule_version_seen", top >= expect["rule_min_version"],
              f"max rule version observed: {top}, expected ≥ {expect['rule_min_version']}")

    # --- behavioural expectations -----------------------------------------
    if "booking_made" in expect:
        if scn.get("resolve") and executable_slot is None:
            # human chose a commitment option (no slot named): nothing bookable
            check("booking_made", True,
                  f"waived — chosen option carried no slot_id; {len(bookings)} booking(s)")
        else:
            check("booking_made", bool(bookings) == expect["booking_made"],
                  f"{len(bookings)} booking(s)")
    if "decision_surfaced" in expect:
        surfaced = "decision_requested" in actions
        check("decision_surfaced", surfaced == expect["decision_surfaced"],
              f"pending in store: {len(store.pending_decisions())}")
    if expect.get("decision_executed"):
        n_exec = actions.count("decision_executed")
        check("decision_executed_exactly_once", n_exec == 1, f"{n_exec} executed mark(s)")
    if expect.get("terminal_clean"):
        left_pending = len(store.pending_decisions())
        left_resolved = len(store.resolved_pending_execution())
        check("terminal_clean", left_pending == 0 and left_resolved == 0,
              f"pending: {left_pending}, resolved-unexecuted: {left_resolved}")

    # --- side-effect allowlist --------------------------------------------
    declared = scn.get("side_effects", {})
    observed = sorted({a for a in actions if a in SIDE_EFFECT_ACTIONS})
    unexpected = [a for a in observed if a not in declared]
    check("no_unexpected_side_effects", not unexpected,
          f"unexpected: {unexpected}" if unexpected else f"side effects: {observed}")
    for action, req in declared.items():
        if req == "required":
            n = actions.count(action)
            check(f"side_effect_{action}", n >= 1, f"{n} occurrence(s)")

    for forbidden in expect.get("forbidden", []):
        check(f"never:{forbidden}", forbidden not in actions)

    store.close()
    return {"id": scn["id"], "ok": all(c["ok"] for c in checks), "checks": checks}


def _provenance() -> dict:
    import platform
    import subprocess
    from importlib.metadata import version as pkg_version
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=10", "HEAD"],
                             capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                                    capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip())
    except Exception:
        sha, dirty = "unknown", "unknown"
    try:
        sdk = pkg_version("strands-agents")
    except Exception:
        sdk = "unknown"
    return {
        "sha": sha,
        "tree_dirty": dirty,
        "provider": os.environ.get("REDTAPE_PROVIDER", "kimi"),
        "model": os.environ.get("REDTAPE_MODEL_ID", "kimi-for-coding"),
        "strands_agents": sdk,
        "python": platform.python_version(),
        "clock": _today().isoformat(),
        "seed": "scenarios are date-pinned; no RNG seed involved",
    }


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
        **_provenance(),
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
