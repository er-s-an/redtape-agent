import sqlite3
from datetime import date

import pytest

from redtape.domain import (Document, RenewalRule, TravelEvent,
                            plan_for_travel, plan_license_renewal)
from redtape.store import Store

TODAY = date(2026, 9, 11)
PASSPORT = Document("passport", "cn-consulate-sf", expiry=date(2027, 4, 15), number="E12345678", holder_name="Xiao Demo")
LICENSE = Document("driver_license", "wa-dol", expiry=date(2027, 3, 1), number="WDL123", holder_name="Xiao Demo")
PASSPORT_RULE = RenewalRule("cn-consulate-sf", "passport", processing_weeks_max=8,
                            appointment_lead_days=7, requires_appointment=True, surrenders_current=True)
LICENSE_RULE = RenewalRule("wa-dol", "driver_license", renewal_window_days_before_expiry=365,
                           requires_appointment=False)
TRAVEL = TravelEvent(date(2026, 12, 20), "fly home for New Year")


def test_travel_triggers_passport_renewal_with_backward_dates():
    plan = plan_for_travel(TRAVEL, PASSPORT, PASSPORT_RULE, TODAY)
    assert plan.needs_action
    renew = plan.steps[0]
    assert renew.action == "renew"
    # in-hand by 2026-12-13 (7d buffer), minus 8 weeks processing
    assert renew.latest_date == date(2026, 10, 18)
    book = plan.steps[1]
    assert book.action == "book_appointment"
    assert book.latest_date == date(2026, 10, 11)


def test_no_action_when_passport_validity_sufficient():
    fresh = Document("passport", "cn-consulate-sf", expiry=date(2028, 1, 1))
    plan = plan_for_travel(TRAVEL, fresh, PASSPORT_RULE, TODAY)
    assert not plan.needs_action


def test_license_window_open_and_surrender_conflict():
    plan = plan_license_renewal(LICENSE, LICENSE_RULE, PASSPORT, PASSPORT_RULE, TODAY)
    assert plan.steps[0].action == "renew"  # window opened 2026-03-01
    assert plan.steps[0].latest_date == date(2027, 3, 1)
    assert plan.conflicts and "surrendering" in plan.conflicts[0]


def test_license_window_not_open_yet():
    later = Document("driver_license", "wa-dol", expiry=date(2027, 12, 1))
    plan = plan_license_renewal(later, LICENSE_RULE, PASSPORT, PASSPORT_RULE, TODAY)
    assert plan.steps[0].action == "prepare"


def test_plan_steps_json_serializable():
    import json
    from redtape.tools import _step_dict
    plan = plan_for_travel(TRAVEL, PASSPORT, PASSPORT_RULE, TODAY)
    json.dumps([_step_dict(s) for s in plan.steps])


def test_store_decision_flow_and_ledger_integrity(tmp_path):
    store = Store(tmp_path / "t.db")
    doc_id = store.add_document({"doc_type": "passport", "jurisdiction": "cn-consulate-sf",
                                 "number": "E12345678", "expiry_date": "2027-04-15",
                                 "holder_name": "Xiao Demo", "confirmed": True})
    doc = store.get_document_by_type("passport")
    assert doc is not None and doc["id"] == doc_id
    did = store.create_decision("pick_slot", {"why": "test"}, [{"slot": "S-1003"}, {"slot": "S-1017"}])
    assert len(store.pending_decisions()) == 1
    store.resolve_decision(did, "S-1003")
    assert store.pending_decisions() == []
    assert store.verify_ledger() is True
    store.conn.execute("UPDATE ledger SET action = 'tampered' WHERE id = 1")
    assert store.verify_ledger() is False
    store.close()


def test_submit_resolution_requires_displayed_exact_draft_binding():
    from fastapi import HTTPException
    from redtape.server import validate_resolution_choice

    hashless = {"approve": True, "doc_type": "passport", "jurisdiction": "cn-consulate-sf"}
    with pytest.raises(HTTPException, match="draft_path, draft_sha256"):
        validate_resolution_choice(
            {"kind": "submit_application", "options": [hashless]}, hashless
        )

    exact = {
        "approve": True,
        "doc_type": "passport",
        "jurisdiction": "cn-consulate-sf",
        "draft_path": "/tmp/passport-draft.json",
        "draft_sha256": "a" * 64,
    }
    validate_resolution_choice(
        {"kind": "submit_application", "options": [exact]}, exact
    )
    with pytest.raises(HTTPException, match="exactly match"):
        validate_resolution_choice(
            {"kind": "submit_application", "options": [exact]},
            {**exact, "draft_sha256": "b" * 64},
        )
    with pytest.raises(HTTPException, match="exactly match"):
        validate_resolution_choice(
            {"kind": "submit_application", "options": [exact]},
            {**exact, "approve": 1},
        )
