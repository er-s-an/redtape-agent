"""The background runtime: RedTape is woken by time, not by a chat message.

Usage:
    python -m redtape.daemon --once            # single wake-scan-act cycle
    python -m redtape.daemon --interval 3600   # loop forever
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date
from pathlib import Path

from .agent import build_agent
from .clock import today as clock_today
from .paths import DATA_DIR
from .store import Store
from .tools import init_context

MOCKGOV_BASE = os.environ.get("MOCKGOV_BASE", "http://localhost:9100").rstrip("/")

NUDGE = (
    "Protocol check: this wake had an active trigger, but the cycle ended with "
    "no appointment booked and no decision surfaced. Finish the protocol NOW — "
    "if no slot satisfies the book-by date under regular processing, call "
    "request_human_decision with the expedited option (and any real "
    "alternatives), each option carrying slot_id, cost, dates, and margin. "
    "Do not end your turn before that tool call."
)

NUDGE_EXEC = (
    "Protocol check: the human has resolved decisions that are not marked "
    "executed yet. Read the resolved decisions with check_decisions, finish "
    "the follow-through NOW: carry out each chosen option if not already done "
    "(book the exact slot named in the choice — the guardrail unlocks it), "
    "then call mark_decision_executed for every resolved decision. Do not end "
    "your turn before those tool calls."
)


def _load_events() -> list:
    events_path = DATA_DIR / "events.json"
    return json.loads(events_path.read_text()) if events_path.exists() else []


def _ledger_mark(store: Store) -> int:
    row = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM ledger").fetchone()
    return row[0]


def _protocol_incomplete(store: Store, events: list, mark: int) -> str | None:
    """A wake is complete when every trigger produced either a booking or a
    surfaced (and then executed) human decision. Returns the nudge to send if
    the model ended its turn early — e.g. an abrupt empty finish. Only fires
    when the dependency graph actually required action: valid documents
    produce an empty plan and must stay silent."""
    tail = [r for r in store.ledger_tail(300) if r["id"] > mark]
    if store.pending_decisions():
        return None
    if store.resolved_pending_execution():
        marked = any(
            r["action"] == "tool_call" and r["detail"].get("tool") == "mark_decision_executed"
            for r in tail
        )
        return None if marked else NUDGE_EXEC
    if not events:
        return None
    if any(r["action"] == "appointment_booked" for r in tail):
        return None
    if any(
        r["action"] == "plan_computed" and "book_appointment" in (r["detail"].get("actions") or [])
        for r in tail
    ):
        return NUDGE
    return None


def wake(today: date, store: Store | None = None, events: list | None = None) -> str:
    if events is None:
        events = _load_events()
    msg = (
        f"[WAKE] Today is {today.isoformat()}. "
        f"Registered triggers: {json.dumps(events, ensure_ascii=False)}. "
        "Run your standard scan-and-act protocol. If a trigger involves travel, "
        "compute the renewal plan first. End with a one-paragraph summary of "
        "actions taken and decisions surfaced."
    )
    if store is not None:
        resolved = store.resolved_pending_execution()
        if resolved:
            msg += (
                " The human has RESOLVED these decisions — execute the chosen option now, "
                "then mark_decision_executed for each: "
                + json.dumps([{"decision_id": d["id"], "kind": d["kind"],
                               "chosen": d["resolution"]["choice"]} for d in resolved],
                             ensure_ascii=False)
            )
    return msg


def _run_turn(agent, msg):
    """One agent turn, hardened against stray steering interrupts.

    The steering plugin can decide to pause the turn for human input. RedTape
    is a background agent — human input flows through the decision inbox, never
    through mid-turn suspension — so an interrupt is resumed with an explicit
    "proceed" response instead of crashing the next turn at resume time."""
    result = agent(msg)
    resumes = 0
    while getattr(result, "stop_reason", None) == "interrupt" and resumes < 3:
        unanswered = [i for i in (result.interrupts or []) if i.response is None]
        if not unanswered:
            break
        resumes += 1
        names = ", ".join(i.name for i in unanswered)
        print(f"[daemon] steering interrupt ({names}) — resuming with proceed")
        responses = [
            {"interruptResponse": {
                "interruptId": i.id,
                "response": ("Proceed. Apply any guidance and continue the wake "
                             "protocol; human input reaches you via the decision inbox."),
            }}
            for i in unanswered
        ]
        result = agent(responses)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--today", default=None, help="ISO date override for demos")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else clock_today()
    store = Store(DATA_DIR / "redtape.db")
    init_context(store, MOCKGOV_BASE, today, DATA_DIR)
    agent = build_agent(DATA_DIR)

    if args.once:
        mark = _ledger_mark(store)
        _run_turn(agent, wake(today, store))
        for attempt in (1, 2):
            nudge = _protocol_incomplete(store, _load_events(), mark)
            if nudge is None:
                break
            print(f"[daemon] wake ended early (nudge {attempt})")
            _run_turn(agent, nudge)
        return
    while True:
        _run_turn(agent, wake(today, store))
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
