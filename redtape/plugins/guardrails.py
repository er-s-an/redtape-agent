"""Deterministic guardrails: hook plugins that validate or cancel tool calls
before they execute — the deterministic layer the organizers explicitly reward.

Two hard rules:
1. book_appointment is cancelled unless the request binds to the plan: the
   slot's office/service must match the arguments, the named document must
   exist, be human-confirmed and belong to that office, and the date must sit
   inside the dependency-graph window — or the exact slot must be named by an
   approved decision. Autonomous bookings exist only for the travel-triggered
   passport renewal.
2. submit_application is cancelled unless a human-approved decision covers
   that exact jurisdiction + document + pipeline draft path + mandatory hash.
   The approval is atomically consumed before the submission attempt, so one
   approval can authorize at most one dispatch. Submission is human-only by
   design.

Every tool call (and every cancellation) is written to the hash-chained ledger.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent
from strands.hooks.registry import HookProvider, HookRegistry

from ..domain import TravelEvent, plan_for_travel
from ..tools import _doc_to_domain, _rule_to_domain, ctx


class Guardrails(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
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
            slot = slot.json()
        slot_date = date.fromisoformat(slot["date"])

        # 1. action binding: the request must name the slot's real office,
        #    service and the document it is for — a wrong-service request is
        #    rejected before any date check can pass it.
        office = tool_input.get("office", "")
        service = tool_input.get("service", "")
        doc_type = tool_input.get("doc_type", "")
        if office != slot["office"] or service != slot["service"]:
            event.cancel_tool = (
                f"action binding failed: slot {slot_id} is {slot['office']}/{slot['service']}, "
                f"not {office}/{service} — take office and service from the rule payload, "
                "and only book slots the plan actually names"
            )
            c.store.log("hook", "booking_blocked",
                        {"slot_id": slot_id, "why": "office/service binding mismatch",
                         "claimed": f"{office}/{service}",
                         "actual": f"{slot['office']}/{slot['service']}"})
            return

        # 2. document binding: the named document must exist, be confirmed,
        #    and belong to the slot's office/jurisdiction.
        doc = c.store.get_document_by_type(doc_type) if doc_type else None
        if doc is None:
            event.cancel_tool = f"no confirmed {doc_type or 'document'} on file to bind this booking to"
            c.store.log("hook", "booking_blocked",
                        {"slot_id": slot_id, "why": "no document to bind", "doc_type": doc_type})
            return
        if doc["jurisdiction"] != slot["office"]:
            event.cancel_tool = (
                f"document binding failed: {doc_type} belongs to {doc['jurisdiction']}, "
                f"not {slot['office']} — wrong-office bookings are never allowed"
            )
            c.store.log("hook", "booking_blocked",
                        {"slot_id": slot_id, "why": "jurisdiction binding mismatch",
                         "doc_jurisdiction": doc["jurisdiction"], "slot_office": slot["office"]})
            return
        if not doc.get("confirmed"):
            event.cancel_tool = ("passport data is not confirmed by the human yet — "
                                 "request confirmation (decision kind confirm_document) before acting on it")
            c.store.log("hook", "booking_blocked", {"slot_id": slot_id, "why": "passport unconfirmed"})
            return

        # 3. plan binding: only the travel-triggered passport renewal may be
        #    booked autonomously; any other appointment requires an approved
        #    human decision covering the exact slot.
        with httpx.Client(base_url=c.mockgov_base, timeout=15, trust_env=False) as h:
            rule = h.get(f"/api/rules/{doc['jurisdiction']}/{doc['doc_type']}").json()
        events = _load_events(c)
        travel = next((e for e in events if e.get("needs", {}).get("passport")), None)
        if doc_type != "passport" or travel is None:
            if self._approved_decision_covers(slot_id):
                c.store.log("hook", "booking_allowed",
                            {"slot_id": slot_id, "via": "approved decision",
                             "why": "non-plan booking with human approval"})
                return
            event.cancel_tool = (
                "only the travel-triggered passport renewal may be booked autonomously; "
                "this appointment has no plan authorization — surface it as a decision first"
            )
            c.store.log("hook", "booking_blocked",
                        {"slot_id": slot_id, "why": "no plan authorization for this document/service"})
            return
        plan = plan_for_travel(
            TravelEvent(date.fromisoformat(travel["date"]), travel["description"]),
            _doc_to_domain(doc), _rule_to_domain(rule), c.today,
        )
        book_steps = [s for s in plan.steps if s.action == "book_appointment"]
        if not book_steps:
            event.cancel_tool = "dependency graph says no passport renewal is needed"
            c.store.log("hook", "booking_blocked", {"slot_id": slot_id, "why": "no renewal needed"})
            return
        latest = book_steps[0].latest_date
        if slot_date > latest:
            if self._approved_decision_covers(slot_id):
                c.store.log("hook", "booking_allowed",
                            {"slot_id": slot_id, "via": "approved decision"})
                return
            event.cancel_tool = (
                f"slot {slot_id} is on {slot_date.isoformat()}, after the latest safe booking date "
                f"{latest.isoformat()} computed from the dependency graph — pick an earlier slot, "
                f"or surface a decision if a later slot plus expedited processing is the right tradeoff"
            )
            c.store.log("hook", "booking_blocked",
                        {"slot_id": slot_id, "slot_date": slot_date.isoformat(),
                         "latest_safe": latest.isoformat()})
            return
        c.store.log("hook", "booking_allowed",
                    {"slot_id": slot_id, "slot_date": slot_date.isoformat(),
                     "latest_safe": latest.isoformat()})

    def _approved_decision_covers(self, slot_id: str) -> bool:
        import json
        import re
        c = ctx()
        rows = c.store.conn.execute(
            "SELECT resolution FROM decisions WHERE status IN ('resolved', 'executed')"
        ).fetchall()
        slot_re = re.compile(r"\b[A-Z]-\d{3,4}\b")
        for row in rows:
            choice = json.loads(row["resolution"]).get("choice", {})
            covered = choice.get("slot_ids") or (
                [choice["slot_id"]] if choice.get("slot_id") else []
            )
            if not covered:  # models sometimes bury the slot id in prose — dig it out
                for value in choice.values():
                    covered.extend(slot_re.findall(value) if isinstance(value, str) else [])
            if slot_id in covered:
                return True
        return False

    def _guard_submission(self, event: BeforeToolCallEvent, tool_input: dict) -> None:
        import hashlib
        from pathlib import Path
        c = ctx()
        doc_type = tool_input.get("doc_type", "")
        jurisdiction = tool_input.get("jurisdiction", "")
        raw_path = tool_input.get("draft_path", "")
        try:
            path = Path(raw_path).resolve(strict=True)
            draft_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, TypeError):
            event.cancel_tool = f"draft not found at {raw_path!r} — re-run draft_form_prefill"
            c.store.log(
                "hook", "submission_blocked",
                {"doc_type": doc_type, "jurisdiction": jurisdiction, "why": "draft missing"},
            )
            return

        # The path string sent downstream must be the exact canonical path that
        # the pipeline produced and the human approved. An alias (relative path,
        # ``..`` segment, or symlink) is a different dispatch request even when
        # it happened to resolve to the same bytes during this check.
        if raw_path != str(path):
            reason = "draft_path is not the canonical pipeline path"
            event.cancel_tool = (
                "submission is human-only: draft_path must exactly match the "
                "canonical path returned by draft_form_prefill"
            )
            c.store.log(
                "hook", "submission_blocked",
                {"doc_type": doc_type, "jurisdiction": jurisdiction, "why": reason},
            )
            return

        decision_id, reason = c.store.consume_submission_approval(
            doc_type=doc_type,
            jurisdiction=jurisdiction,
            draft_path=str(path),
            draft_sha256=draft_hash,
        )
        if decision_id is not None:
            return
        event.cancel_tool = (
            "submission is human-only: no unused approval exactly covers this "
            f"jurisdiction, document, draft path and draft_sha256 ({reason}). "
            "Request a new decision for this exact draft."
        )
        c.store.log(
            "hook", "submission_blocked",
            {"doc_type": doc_type, "jurisdiction": jurisdiction, "why": reason},
        )


def _load_events(c) -> list[dict]:
    import json
    path = c.data_dir / "events.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())
