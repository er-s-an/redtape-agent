"""The agent's toolset. Each tool is a thin, testable action over the local
store or the (sandboxed) government portal — and each writes to the
hash-chained ledger so every autonomous action is auditable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from dateutil.relativedelta import relativedelta
from strands import tool

from .domain import (Document, RenewalRule, TravelEvent, plan_for_travel,
                     plan_license_renewal)
from .store import Store


def _step_dict(step) -> dict:
    return {
        "doc_type": step.doc_type,
        "action": step.action,
        "latest_date": step.latest_date.isoformat(),
        "reasons": step.reasons,
    }


@dataclass
class RedTapeContext:
    store: Store
    mockgov_base: str
    today: date
    data_dir: Path


_ctx: RedTapeContext | None = None


def init_context(store: Store, mockgov_base: str, today: date, data_dir: str | Path) -> None:
    global _ctx
    _ctx = RedTapeContext(store=store, mockgov_base=mockgov_base.rstrip("/"),
                          today=today, data_dir=Path(data_dir))


def ctx() -> RedTapeContext:
    if _ctx is None:
        raise RuntimeError("redtape tools not initialised — call init_context() first")
    return _ctx


def _http() -> httpx.Client:
    # trust_env=False: never route localhost sandbox traffic through a system proxy
    return httpx.Client(base_url=ctx().mockgov_base, timeout=15, trust_env=False)


def _doc_to_domain(d: dict[str, Any]) -> Document:
    return Document(doc_type=d["doc_type"], jurisdiction=d["jurisdiction"],
                    expiry=date.fromisoformat(d["expiry_date"]), number=d["number"],
                    holder_name=d["holder_name"])


def _rule_to_domain(r: dict[str, Any]) -> RenewalRule:
    p = r["payload"]
    return RenewalRule(
        jurisdiction=r["jurisdiction"], doc_type=r["doc_type"],
        processing_weeks_max=p.get("processing_weeks_max", 0),
        requires_appointment=p.get("requires_appointment", False),
        surrenders_current=p.get("surrenders_current_passport", False),
        renewal_window_days_before_expiry=p.get("renewal_window_days_before_expiry"),
    )


@tool
def list_documents() -> list[dict]:
    """List all tracked documents with expiry dates and days remaining."""
    c = ctx()
    docs = []
    for d in c.store.list_documents():
        expiry = date.fromisoformat(d["expiry_date"])
        docs.append({**d, "days_until_expiry": (expiry - c.today).days})
    c.store.log("agent", "documents_scanned", {"count": len(docs)})
    return docs


@tool
def check_rule(jurisdiction: str, doc_type: str) -> dict:
    """Fetch the current renewal rule for a jurisdiction/document from the portal.

    Returns the rule including its version — re-check to detect rule changes.
    """
    c = ctx()
    with _http() as h:
        resp = h.get(f"/api/rules/{jurisdiction}/{doc_type}")
        resp.raise_for_status()
        rule = resp.json()
    c.store.log("agent", "rule_checked",
                {"jurisdiction": jurisdiction, "doc_type": doc_type, "version": rule["version"]})
    return rule


@tool
def compute_renewal_plan(travel_date: str, travel_description: str,
                         min_passport_valid_months: int = 6) -> dict:
    """Compute backwards-chained renewal deadlines for a planned trip.

    Walks the dependency graph: travel date + validity rule → in-hand-by →
    submit-by (processing time) → book-by (appointment lead). Also checks the
    driver-license renewal and reports cross-renewal conflicts.
    """
    c = ctx()
    passport = c.store.get_document_by_type("passport")
    license_doc = c.store.get_document_by_type("driver_license")
    if passport is None:
        return {"error": "no passport on file"}
    with _http() as h:
        pr = h.get(f"/api/rules/{passport['jurisdiction']}/passport").json()
    passport_rule = _rule_to_domain(pr)
    event = TravelEvent(date.fromisoformat(travel_date), travel_description,
                        min_passport_valid_months)
    travel_plan = plan_for_travel(event, _doc_to_domain(passport), passport_rule, c.today)
    result: dict[str, Any] = {
        "travel": {"steps": [_step_dict(s) for s in travel_plan.steps], "conflicts": travel_plan.conflicts},
    }
    if license_doc is not None:
        with _http() as h:
            lr = h.get(f"/api/rules/{license_doc['jurisdiction']}/driver_license").json()
        license_plan = plan_license_renewal(_doc_to_domain(license_doc), _rule_to_domain(lr),
                                            _doc_to_domain(passport), passport_rule, c.today)
        result["driver_license"] = {"steps": [_step_dict(s) for s in license_plan.steps],
                                    "conflicts": license_plan.conflicts}
    c.store.log("agent", "plan_computed", {"travel_date": travel_date,
                                           "steps": len(travel_plan.steps),
                                           "conflicts": len(travel_plan.conflicts)})
    return result


@tool
def check_appointment_slots(office: str, service: str) -> list[dict]:
    """List currently available appointment slots for a service (earliest first)."""
    c = ctx()
    with _http() as h:
        slots = h.get("/api/slots", params={"office": office, "service": service}).json()
    c.store.log("agent", "slots_checked", {"office": office, "service": service,
                                           "available": len(slots)})
    return slots


@tool
def book_appointment(slot_id: str, reason: str) -> dict:
    """Book an appointment slot. Guardrail hooks validate the slot against
    computed deadlines before this executes — an unsafe slot is cancelled."""
    c = ctx()
    with _http() as h:
        resp = h.post("/api/bookings", json={
            "slot_id": slot_id,
            "applicant_name": (c.store.get_document_by_type("passport") or {}).get("holder_name", ""),
            "document_number": (c.store.get_document_by_type("passport") or {}).get("number", ""),
        })
        if resp.status_code == 409:
            c.store.log("agent", "booking_failed", {"slot_id": slot_id, "reason": "slot taken"})
            return {"error": "slot already taken", "slot_id": slot_id}
        resp.raise_for_status()
        booking = resp.json()
    c.store.log("agent", "appointment_booked", {"slot_id": slot_id, "reason": reason,
                                                "confirmation": booking["confirmation_code"]})
    return booking


@tool
def create_calendar_hold(day: str, title: str, note: str) -> str:
    """Create a calendar hold (.ics) for an appointment or deadline."""
    c = ctx()
    cal_dir = c.data_dir / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    day_iso = date.fromisoformat(day)
    path = cal_dir / f"{day_iso.isoformat()}-{title.lower().replace(' ', '-')}.ics"
    path.write_text(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        f"UID:{day_iso.isoformat()}-{abs(hash(title))}@redtape\r\n"
        f"DTSTART;VALUE=DATE:{day_iso.strftime('%Y%m%d')}\r\n"
        f"SUMMARY:{title}\r\nDESCRIPTION:{note}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    c.store.log("agent", "calendar_hold_created", {"day": day, "title": title})
    return str(path)


@tool
def draft_form_prefill(jurisdiction: str, doc_type: str) -> dict:
    """Prepare a renewal application draft from the verified document store.
    Produces a structured draft artifact; final submission is always human."""
    c = ctx()
    doc = c.store.get_document_by_type(doc_type)
    if doc is None:
        return {"error": f"no {doc_type} on file"}
    with _http() as h:
        rule = h.get(f"/api/rules/{jurisdiction}/{doc_type}").json()
    forms_dir = c.data_dir / "forms"
    forms_dir.mkdir(parents=True, exist_ok=True)
    draft = {
        "jurisdiction": jurisdiction, "doc_type": doc_type,
        "rule_version": rule["version"],
        "applicant": {"name": doc["holder_name"], "document_number": doc["number"],
                      "current_expiry": doc["expiry_date"]},
        "required_items": rule["payload"].get("required_items", []),
        "fee_usd": rule["payload"].get("fee_usd"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "DRAFT — not submitted",
    }
    path = forms_dir / f"{jurisdiction}-{doc_type}-draft.json"
    path.write_text(json.dumps(draft, indent=2, ensure_ascii=False))
    c.store.log("agent", "form_prefilled", {"jurisdiction": jurisdiction, "doc_type": doc_type,
                                            "rule_version": rule["version"], "path": str(path)})
    from .pdf import render_application_pdf
    pdf_path = render_application_pdf(
        forms_dir / f"{jurisdiction}-{doc_type}-draft.pdf",
        jurisdiction=jurisdiction, doc_type=doc_type, applicant=draft["applicant"], rule=rule,
    )
    c.store.log("agent", "form_pdf_rendered", {"path": pdf_path})
    return {"draft_path": str(path), "pdf_path": pdf_path,
            "fee_usd": draft["fee_usd"], "status": draft["status"]}


@tool
def submit_application(jurisdiction: str, doc_type: str, draft_path: str) -> dict:
    """Submit a prepared application to the portal. IRREVERSIBLE — a guardrail
    hook cancels this unless a human-approved decision covers it."""
    c = ctx()
    with _http() as h:
        resp = h.post("/api/submissions", json={
            "jurisdiction": jurisdiction, "form_type": doc_type,
            "fields": {"draft_path": draft_path},
        })
        resp.raise_for_status()
        case = resp.json()
    c.store.log("agent", "application_submitted", {"case_id": case["case_id"]})
    return case


@tool
def request_human_decision(kind: str, context: str, options: list[dict]) -> dict:
    """Surface a decision to the human. Use ONLY when the choice is genuinely
    theirs: irreversible actions, preference tradeoffs, anything costing money.
    Options carry concrete dates/margins so the human can decide in one look."""
    c = ctx()
    decision_id = c.store.create_decision(
        kind,
        {"context": context, "date": c.today.isoformat()},
        options,
    )
    return {"decision_id": decision_id, "status": "pending",
            "message": "Surfaced to the Decision Inbox. Stop and wait — do not act on this until resolved."}


@tool
def mark_decision_executed(decision_id: int) -> dict:
    """Mark a human-resolved decision as fully executed after you have carried
    out its chosen option (booking made, drafts prepared, holds placed)."""
    ctx().store.mark_decision_executed(decision_id)
    return {"decision_id": decision_id, "status": "executed"}


@tool
def notify_user(message: str) -> dict:
    """Send a low-priority FYI notification (logged; no decision needed)."""
    ctx().store.log("agent", "notification", {"message": message})
    return {"sent": True, "message": message}
