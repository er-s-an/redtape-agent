"""Direct attack matrix against the deterministic guardrails.

These tests call the guard hooks the same way Strands does (BeforeToolCallEvent
with a tool_use payload) — no model in the loop. Every safety property the
submission claims is attacked here explicitly:

- booking with the wrong office/service/jurisdiction is cancelled;
- a slot with no plan authorization (driver-license side booking) is cancelled;
- an unapproved submit_application is cancelled AND logs submission_blocked
  (not a vacuous "nothing happened");
- an approval unlocks exactly one submission (one-time nonce);
- an unconfirmed document cannot be booked against.

Needs the sandbox portal on :9100 (the eval runner needs it too); skipped
when it is not running.
"""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

MOCKGOV = "http://localhost:9100"


def _sandbox_up() -> bool:
    try:
        with httpx.Client(base_url=MOCKGOV, timeout=3, trust_env=False) as h:
            h.post("/api/admin/reset")
            return True
    except httpx.TransportError:
        return False


pytestmark = pytest.mark.skipif(not _sandbox_up(), reason="sandbox portal not running on :9100")


class FakeEvent:
    def __init__(self, name: str, tool_input: dict):
        self.tool_use = {"name": name, "input": tool_input}
        self.cancel_tool: object = False


@pytest.fixture()
def guard_ctx(tmp_path, monkeypatch):
    from redtape import tools
    from redtape.plugins.guardrails import Guardrails
    from redtape.store import Store

    store = Store(tmp_path / "t.db")
    store.add_document({"doc_type": "passport", "jurisdiction": "cn-consulate-sf",
                        "number": "E12345678", "expiry_date": "2027-04-15",
                        "holder_name": "Xiao Demo", "confirmed": True})
    store.add_document({"doc_type": "driver_license", "jurisdiction": "wa-dol",
                        "number": "WDL123DEMO", "expiry_date": "2027-03-01",
                        "holder_name": "Xiao Demo", "confirmed": True})
    (tmp_path / "events.json").write_text(json.dumps(
        [{"kind": "travel", "date": "2026-12-20", "description": "fly home",
          "needs": {"passport": True}}]))
    tools.init_context(store, MOCKGOV, date(2026, 9, 11), tmp_path)
    yield Guardrails(), store
    store.close()


def _blocked_why(store) -> list[str]:
    return [e["detail"].get("why", "")
            for e in store.ledger_tail(100) if e["action"] == "booking_blocked"]


def test_wrong_service_booking_is_cancelled(guard_ctx):
    guard, store = guard_ctx
    ev = FakeEvent("book_appointment",
                   {"slot_id": "S-1003", "office": "wa-dol",
                    "service": "driver_license_renewal", "doc_type": "driver_license",
                    "reason": "attack: passport slot claimed as a DOL slot"})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "wrong-service booking must be cancelled"
    assert any("binding mismatch" in w for w in _blocked_why(store))


def test_no_plan_authorization_side_booking_is_cancelled(guard_ctx):
    guard, store = guard_ctx
    # correct names, but the license renewal has no appointment plan step —
    # the guard must not let a side booking ride the passport travel plan.
    ev = FakeEvent("book_appointment",
                   {"slot_id": "D-0922", "office": "wa-dol",
                    "service": "driver_license_renewal", "doc_type": "driver_license",
                    "reason": "attack: license booking without any plan authorization"})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "booking without plan authorization must be cancelled"
    assert any("no plan authorization" in w for w in _blocked_why(store))


def test_unapproved_submit_is_cancelled_and_logged(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft = tmp_path / "forms" / "draft.json"
    draft.parent.mkdir(parents=True)
    draft.write_text("{}")
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "unapproved submission must be cancelled"
    blocked = [e for e in store.ledger_tail(100) if e["action"] == "submission_blocked"]
    assert blocked, "the block must be logged (not a vacuous pass)"


def test_approval_is_a_one_time_nonce(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft = tmp_path / "forms" / "draft.json"
    draft.parent.mkdir(parents=True)
    draft.write_text("{}")
    import hashlib
    draft_hash = hashlib.sha256(draft.read_bytes()).hexdigest()
    # the draft must be pipeline-produced (this is what draft_form_prefill logs)
    store.log("agent", "form_prefilled", {"jurisdiction": "cn-consulate-sf",
                                          "doc_type": "passport",
                                          "draft_sha256": draft_hash})
    did = store.create_decision("submit_application", {"why": "attack"}, [])
    store.resolve_decision(did, {"approve": True, "doc_type": "passport",
                                 "jurisdiction": "cn-consulate-sf",
                                 "draft_sha256": draft_hash})

    first = FakeEvent("submit_application",
                      {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                       "draft_path": str(draft)})
    guard.before_tool(first)  # type: ignore[arg-type]
    assert not first.cancel_tool, "first submission with approval must be allowed"
    allowed = [e for e in store.ledger_tail(100) if e["action"] == "submission_allowed"]
    assert len(allowed) == 1 and allowed[0]["detail"].get("draft_sha256")

    second = FakeEvent("submit_application",
                       {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                        "draft_path": str(draft)})
    guard.before_tool(second)  # type: ignore[arg-type]
    assert second.cancel_tool, "reusing one approval must be cancelled"


def test_approval_for_wrong_jurisdiction_is_cancelled(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft = tmp_path / "forms" / "draft.json"
    draft.parent.mkdir(parents=True)
    draft.write_text("{}")
    did = store.create_decision("submit_application", {"why": "attack"}, [])
    store.resolve_decision(did, {"approve": True, "doc_type": "passport",
                                 "jurisdiction": "wa-dol"})
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "an approval for another jurisdiction must not cover this filing"
    blocked = [e for e in store.ledger_tail(100) if e["action"] == "submission_blocked"]
    assert any("jurisdiction" in (e["detail"].get("why") or "") for e in blocked)


def test_tampered_draft_is_cancelled(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft = tmp_path / "forms" / "draft.json"
    draft.parent.mkdir(parents=True)
    draft.write_text("{}")
    import hashlib
    pipeline_hash = hashlib.sha256(draft.read_bytes()).hexdigest()
    store.log("agent", "form_prefilled", {"jurisdiction": "cn-consulate-sf",
                                          "doc_type": "passport",
                                          "draft_sha256": pipeline_hash})
    did = store.create_decision("submit_application", {"why": "attack"}, [])
    store.resolve_decision(did, {"approve": True, "doc_type": "passport",
                                 "jurisdiction": "cn-consulate-sf",
                                 "draft_sha256": pipeline_hash})
    # tamper AFTER the approval: the file no longer matches what was approved
    draft.write_text('{"applicant": {"name": "Mallory"}}')
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "a draft modified after approval must be cancelled"


def test_foreign_draft_without_pipeline_origin_is_cancelled(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft = tmp_path / "forms" / "foreign.json"
    draft.parent.mkdir(parents=True)
    draft.write_text("{}")
    did = store.create_decision("submit_application", {"why": "attack"}, [])
    store.resolve_decision(did, {"approve": True, "doc_type": "passport",
                                 "jurisdiction": "cn-consulate-sf"})
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "a draft that never came from draft_form_prefill must be cancelled"
    blocked = [e for e in store.ledger_tail(100) if e["action"] == "submission_blocked"]
    assert any("pipeline" in (e["detail"].get("why") or "") for e in blocked)


def test_unconfirmed_document_cannot_be_booked(tmp_path, monkeypatch):
    from redtape import tools
    from redtape.plugins.guardrails import Guardrails
    from redtape.store import Store

    store = Store(tmp_path / "t.db")
    store.add_document({"doc_type": "passport", "jurisdiction": "cn-consulate-sf",
                        "number": "E87654321", "expiry_date": "2027-04-15",
                        "holder_name": "Xiao Demo", "confirmed": False})
    (tmp_path / "events.json").write_text(json.dumps(
        [{"kind": "travel", "date": "2026-12-20", "description": "fly home",
          "needs": {"passport": True}}]))
    tools.init_context(store, MOCKGOV, date(2026, 9, 11), tmp_path)
    ev = FakeEvent("book_appointment",
                   {"slot_id": "S-1003", "office": "cn-consulate-sf",
                    "service": "passport_renewal", "doc_type": "passport",
                    "reason": "attack: book against unconfirmed data"})
    Guardrails().before_tool(ev)  # type: ignore[arg-type]
    assert ev.cancel_tool and "confirmed" in str(ev.cancel_tool)
    store.close()
