"""Mock government portal used as RedTape's deterministic demo sandbox.

Simulates the three things the agent needs from the outside world:
appointment slots + booking, versioned machine-readable rules, and form
submission intake. All data is synthetic; rule payloads carry the real
source URLs they were modeled on.
"""
from __future__ import annotations

import itertools
import os
import threading
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

TODAY = date.fromisoformat(os.environ.get("MOCKGOV_TODAY", "2026-09-11"))

app = FastAPI(title="mockgov", version="0.1.0")
_lock = threading.Lock()
_booking_seq = itertools.count(1000)
_case_seq = itertools.count(5000)


class Rule(BaseModel):
    jurisdiction: str
    doc_type: str
    version: int
    effective_from: str
    source_url: str
    payload: dict


_RULES: dict[tuple[str, str], Rule] = {
    ("cn-consulate-sf", "passport"): Rule(
        jurisdiction="cn-consulate-sf",
        doc_type="passport",
        version=3,
        effective_from="2026-06-01",
        source_url="http://sanfrancisco.china-consulate.gov.cn/eng/lszj/hzlxz/",
        payload={
            "service": "passport_renewal",
            "requires_appointment": True,
            "processing_weeks_min": 4,
            "processing_weeks_max": 8,
            "fee_usd": 23,
            "surrenders_current_passport": True,
            "required_items": ["current passport", "photo", "application form", "fee"],
            "processing_options": [
                {"id": "regular", "weeks": 8, "fee_usd": 23},
                {"id": "expedited", "weeks": 4, "fee_usd": 83},
            ],
        },
    ),
    ("wa-dol", "driver_license"): Rule(
        jurisdiction="wa-dol",
        doc_type="driver_license",
        version=2,
        effective_from="2026-01-01",
        source_url="https://dol.wa.gov/driver-licensing-and-id/renew-your-driver-license",
        payload={
            "service": "driver_license_renewal",
            "renewal_window_days_before_expiry": 365,
            "requires": [
                {"doc_type": "passport", "min_valid_days_at_renewal": 0},
                {"doc_type": "lawful_status", "min_valid_days_at_renewal": 0},
            ],
            "fee_usd": 89,
            "online_eligible": False,
        },
    ),
    ("us-travel", "passport_validity"): Rule(
        jurisdiction="us-travel",
        doc_type="passport_validity",
        version=1,
        effective_from="2024-01-01",
        source_url="https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/all-visa-categories.html",
        payload={
            "min_valid_months_beyond_stay": 6,
            "note": "sandbox simplification of the 6-month validity rule",
        },
    ),
}

_SLOTS: dict[str, dict] = {
    "S-1003": {"office": "cn-consulate-sf", "service": "passport_renewal", "date": "2026-10-03", "time": "09:30", "taken": False},
    "S-1017": {"office": "cn-consulate-sf", "service": "passport_renewal", "date": "2026-10-17", "time": "13:00", "taken": False},
    "S-1031": {"office": "cn-consulate-sf", "service": "passport_renewal", "date": "2026-10-31", "time": "10:00", "taken": False},
    "S-1114": {"office": "cn-consulate-sf", "service": "passport_renewal", "date": "2026-11-14", "time": "15:30", "taken": False},
    "S-1128": {"office": "cn-consulate-sf", "service": "passport_renewal", "date": "2026-11-28", "time": "09:00", "taken": False},
    "D-0922": {"office": "wa-dol", "service": "driver_license_renewal", "date": "2026-09-22", "time": "10:30", "taken": False},
    "D-0929": {"office": "wa-dol", "service": "driver_license_renewal", "date": "2026-09-29", "time": "14:00", "taken": False},
    "D-1013": {"office": "wa-dol", "service": "driver_license_renewal", "date": "2026-10-13", "time": "09:30", "taken": False},
}

_BOOKINGS: dict[str, dict] = {}
_CASES: dict[str, dict] = {}


class BookingRequest(BaseModel):
    slot_id: str
    applicant_name: str
    document_number: str


class SubmissionRequest(BaseModel):
    jurisdiction: str
    form_type: str
    fields: dict


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "today": TODAY.isoformat()}


@app.get("/api/rules/{jurisdiction}/{doc_type}", response_model=Rule)
def get_rule(jurisdiction: str, doc_type: str) -> Rule:
    rule = _RULES.get((jurisdiction, doc_type))
    if rule is None:
        raise HTTPException(404, f"no rule for {jurisdiction}/{doc_type}")
    return rule


@app.get("/api/slots")
def list_slots(office: str, service: str, after: str | None = None) -> list[dict]:
    after_date = date.fromisoformat(after) if after else TODAY
    return [
        {"slot_id": sid, **s}
        for sid, s in sorted(_SLOTS.items(), key=lambda kv: kv[1]["date"])
        if s["office"] == office and s["service"] == service
        and date.fromisoformat(s["date"]) >= after_date and not s["taken"]
    ]


@app.get("/api/slots/{slot_id}")
def get_slot(slot_id: str) -> dict:
    slot = _SLOTS.get(slot_id)
    if slot is None:
        raise HTTPException(404, "unknown slot")
    return {"slot_id": slot_id, **slot}


@app.post("/api/bookings", status_code=201)
def book(req: BookingRequest) -> dict:
    with _lock:
        slot = _SLOTS.get(req.slot_id)
        if slot is None:
            raise HTTPException(404, "unknown slot")
        if slot["taken"]:
            raise HTTPException(409, "slot already taken")
        slot["taken"] = True
        booking_id = f"B{next(_booking_seq)}"
        record = {
            "booking_id": booking_id,
            "confirmation_code": f"CNF-{booking_id}",
            "slot_id": req.slot_id,
            "office": slot["office"],
            "service": slot["service"],
            "date": slot["date"],
            "time": slot["time"],
            "applicant_name": req.applicant_name,
            "document_number": req.document_number,
        }
        _BOOKINGS[booking_id] = record
        return record


@app.post("/api/submissions", status_code=201)
def submit(req: SubmissionRequest) -> dict:
    if (req.jurisdiction, req.form_type) not in [(r.jurisdiction, r.doc_type) for r in _RULES.values()]:
        raise HTTPException(400, f"no intake for {req.jurisdiction}/{req.form_type}")
    case_id = f"C{next(_case_seq)}"
    _CASES[case_id] = {"case_id": case_id, "status": "RECEIVED", **req.model_dump()}
    return _CASES[case_id]


@app.get("/api/submissions/{case_id}")
def submission_status(case_id: str) -> dict:
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(404, "unknown case")
    return case


@app.post("/api/admin/rules/{jurisdiction}/{doc_type}/bump")
def bump_rule(jurisdiction: str, doc_type: str, changes: dict) -> Rule:
    rule = _RULES.get((jurisdiction, doc_type))
    if rule is None:
        raise HTTPException(404, "no rule to bump")
    rule.version += 1
    rule.effective_from = TODAY.isoformat()
    rule.payload.update(changes)
    return rule
