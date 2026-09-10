"""Deterministic guardrails: hook plugins that validate or cancel tool calls
before they execute — the deterministic layer the organizers explicitly reward.

Two hard rules:
1. book_appointment is cancelled when the slot lands after the latest safe
   booking date computed from the dependency graph (or when no renewal plan
   exists at all).
2. submit_application is cancelled unless a human-approved decision covering
   that exact document exists. Submission is human-only by design.

Every tool call (and every cancellation) is written to the hash-chained ledger.
"""
from __future__ import annotations

from datetime import date

import httpx

from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent
from strands.hooks.registry import HookProvider, HookRegistry

from ..domain import TravelEvent, plan_for_travel
from ..tools import _doc_to_domain, _rule_to_domain, ctx


class Guardrails(HookProvider):
    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use.get("name", "")
        tool_input = event.tool_use.get("input", {}) or {}
        c = ctx()
        c.store.log("agent", "tool_call", {"tool": name, "input": tool_input})
        if name == "book_appointment":
            self._guard_booking(event, tool_input)
        elif name == "submit_application":
            self._guard_submission(event, tool_input)

    def after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use.get("name", "")
        ctx().store.log("agent", "tool_result", {"tool": name,
                                                 "cancelled": bool(getattr(event, "cancel_tool", False))})

    # --- guards ----------------------------------------------------------

    def _guard_booking(self, event: BeforeToolCallEvent, tool_input: dict) -> None:
        c = ctx()
        slot_id = tool_input.get("slot_id", "")
        with httpx.Client(base_url=c.mockgov_base, timeout=15, trust_env=False) as h:
            slot = h.get(f"/api/slots/{slot_id}")
            if slot.status_code == 404:
                event.cancel_tool = f"unknown slot {slot_id}"
                c.store.log("hook", "booking_blocked", {"slot_id": slot_id, "why": "unknown slot"})
                return
            slot_date = date.fromisoformat(slot.json()["date"])
        passport = c.store.get_document_by_type("passport")
        if passport is None:
            event.cancel_tool = "no passport on file — nothing to renew"
            c.store.log("hook", "booking_blocked", {"slot_id": slot_id, "why": "no passport"})
            return
        with httpx.Client(base_url=c.mockgov_base, timeout=15, trust_env=False) as h:
            rule = h.get(f"/api/rules/{passport['jurisdiction']}/passport").json()
        events = _load_events(c)
        travel = next((e for e in events if e.get("needs", {}).get("passport")), None)
        if travel is None:
            event.cancel_tool = "no active travel/renewal pressure — booking an appointment now is pointless"
            c.store.log("hook", "booking_blocked", {"slot_id": slot_id, "why": "no active plan"})
            return
        plan = plan_for_travel(
            TravelEvent(date.fromisoformat(travel["date"]), travel["description"]),
            _doc_to_domain(passport), _rule_to_domain(rule), c.today,
        )
        book_steps = [s for s in plan.steps if s.action == "book_appointment"]
        if not book_steps:
            event.cancel_tool = "dependency graph says no passport renewal is needed"
            c.store.log("hook", "booking_blocked", {"slot_id": slot_id, "why": "no renewal needed"})
            return
        latest = book_steps[0].latest_date
        if slot_date > latest:
            event.cancel_tool = (
                f"slot {slot_id} is on {slot_date.isoformat()}, after the latest safe booking date "
                f"{latest.isoformat()} computed from the dependency graph — pick an earlier slot"
            )
            c.store.log("hook", "booking_blocked",
                        {"slot_id": slot_id, "slot_date": slot_date.isoformat(),
                         "latest_safe": latest.isoformat()})
            return
        c.store.log("hook", "booking_allowed",
                    {"slot_id": slot_id, "slot_date": slot_date.isoformat(),
                     "latest_safe": latest.isoformat()})

    def _guard_submission(self, event: BeforeToolCallEvent, tool_input: dict) -> None:
        c = ctx()
        doc_type = tool_input.get("doc_type", "")
        approved = c.store.conn.execute(
            "SELECT id, resolution FROM decisions WHERE status = 'resolved' AND kind = 'submit_application'"
        ).fetchall()
        import json
        for row in approved:
            resolution = json.loads(row["resolution"])
            choice = resolution.get("choice", {})
            if choice.get("approve") is True and choice.get("doc_type") == doc_type:
                c.store.log("hook", "submission_allowed", {"doc_type": doc_type,
                                                           "decision_id": row["id"]})
                return
        event.cancel_tool = (
            "submission is human-only: no approved decision covers "
            f"{doc_type}. Use request_human_decision first."
        )
        c.store.log("hook", "submission_blocked", {"doc_type": doc_type})


def _load_events(c) -> list[dict]:
    import json
    path = c.data_dir / "events.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())
