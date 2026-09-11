"""The background runtime: RedTape is woken by time, not by a chat message.

Usage:
    python -m redtape.daemon --once            # single wake-scan-act cycle
    python -m redtape.daemon --interval 3600   # loop forever
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

from .agent import build_agent
from .paths import DATA_DIR
from .store import Store
from .tools import init_context

MOCKGOV_BASE = "http://localhost:9100"


def wake(today: date, store: Store | None = None) -> str:
    events_path = DATA_DIR / "events.json"
    events = json.loads(events_path.read_text()) if events_path.exists() else []
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--today", default=None, help="ISO date override for demos")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    store = Store(DATA_DIR / "redtape.db")
    init_context(store, MOCKGOV_BASE, today, DATA_DIR)
    agent = build_agent(DATA_DIR)

    if args.once:
        agent(wake(today, store))
        return
    while True:
        agent(wake(today, store))
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
