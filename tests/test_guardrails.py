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
import os
from datetime import date
from pathlib import Path

import httpx
import pytest

MOCKGOV = os.environ.get("MOCKGOV_BASE", "http://localhost:9100")


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


def _pipeline_draft(store, path: Path, *, content: str = "{}") -> tuple[Path, str]:
    import hashlib
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path = path.resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store.log("agent", "form_prefilled", {
        "jurisdiction": "cn-consulate-sf",
        "doc_type": "passport",
        "path": str(path),
        "draft_sha256": digest,
    })
    return path, digest


def _submission_approval(store, path: Path, digest: str, **overrides) -> int:
    choice = {
        "approve": True,
        "doc_type": "passport",
        "jurisdiction": "cn-consulate-sf",
        "draft_path": str(path),
        "draft_sha256": digest,
    }
    choice.update(overrides)
    did = store.create_decision("submit_application", {"why": "test"}, [choice])
    store.resolve_decision(did, choice)
    return did


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
    draft, draft_hash = _pipeline_draft(store, tmp_path / "forms" / "draft.json")
    did = _submission_approval(store, draft, draft_hash)

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
    draft, digest = _pipeline_draft(store, tmp_path / "forms" / "draft.json")
    _submission_approval(store, draft, digest, jurisdiction="wa-dol")
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "an approval for another jurisdiction must not cover this filing"
    blocked = [e for e in store.ledger_tail(100) if e["action"] == "submission_blocked"]
    assert any("jurisdiction" in (e["detail"].get("why") or "") for e in blocked)


def test_tampered_draft_is_cancelled(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft, pipeline_hash = _pipeline_draft(store, tmp_path / "forms" / "draft.json")
    _submission_approval(store, draft, pipeline_hash)
    # tamper AFTER the approval: the file no longer matches what was approved
    draft.write_text('{"applicant": {"name": "Mallory"}}')
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "a draft modified after approval must be cancelled"


def test_foreign_draft_without_pipeline_origin_is_cancelled(guard_ctx, tmp_path):
    guard, store = guard_ctx
    # A historical pipeline draft has the same bytes/hash but a different path.
    # Hash-only provenance must not bless this foreign path.
    _pipeline_draft(store, tmp_path / "forms" / "pipeline.json")
    draft = (tmp_path / "forms" / "foreign.json").resolve()
    draft.write_text("{}")
    import hashlib
    digest = hashlib.sha256(draft.read_bytes()).hexdigest()
    _submission_approval(store, draft, digest)
    ev = FakeEvent("submit_application",
                   {"jurisdiction": "cn-consulate-sf", "doc_type": "passport",
                    "draft_path": str(draft)})
    guard.before_tool(ev)  # type: ignore[arg-type] — structural test fake
    assert ev.cancel_tool, "a draft that never came from draft_form_prefill must be cancelled"
    blocked = [e for e in store.ledger_tail(100) if e["action"] == "submission_blocked"]
    assert any("provenance" in (e["detail"].get("why") or "") for e in blocked)

    # A path alias is not the exact dispatch path even if it resolves to the
    # approved file. The guard must not normalize one request for comparison
    # and then send a different string to the portal.
    alias = draft.parent / ".." / "forms" / draft.name
    alias_ev = FakeEvent("submit_application", {
        "jurisdiction": "cn-consulate-sf", "doc_type": "passport", "draft_path": str(alias),
    })
    guard.before_tool(alias_ev)  # type: ignore[arg-type]
    assert alias_ev.cancel_tool and "canonical" in str(alias_ev.cancel_tool)


def test_approval_without_draft_sha256_cannot_authorize_historical_draft(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft, digest = _pipeline_draft(store, tmp_path / "forms" / "draft.json")
    _submission_approval(store, draft, digest, draft_sha256=None)
    ev = FakeEvent("submit_application", {
        "jurisdiction": "cn-consulate-sf",
        "doc_type": "passport",
        "draft_path": str(draft),
    })
    guard.before_tool(ev)  # type: ignore[arg-type]
    assert ev.cancel_tool, "a hashless approval must never authorize a historical pipeline draft"
    blocked = [e for e in store.ledger_tail(100) if e["action"] == "submission_blocked"]
    assert any("draft_sha256" in (e["detail"].get("why") or "") for e in blocked)

    # A legacy/internal forged resolution cannot bypass the displayed options
    # invariant at consumption time, even with otherwise exact provenance.
    forged = {"approve": True, "doc_type": "passport", "jurisdiction": "cn-consulate-sf",
              "draft_path": str(draft), "draft_sha256": digest}
    rejection = {"approve": False, "doc_type": "passport", "jurisdiction": "cn-consulate-sf"}
    did = store.create_decision("submit_application", {"why": "legacy"}, [rejection])
    store.resolve_decision(did, forged)
    forged_ev = FakeEvent("submit_application", {
        "jurisdiction": "cn-consulate-sf", "doc_type": "passport", "draft_path": str(draft),
    })
    guard.before_tool(forged_ev)  # type: ignore[arg-type]
    assert forged_ev.cancel_tool


def test_consumed_approval_does_not_hide_newer_valid_approval(guard_ctx, tmp_path):
    guard, store = guard_ctx
    draft, digest = _pipeline_draft(store, tmp_path / "forms" / "draft.json")
    first_id = _submission_approval(store, draft, digest)
    first = FakeEvent("submit_application", {
        "jurisdiction": "cn-consulate-sf", "doc_type": "passport", "draft_path": str(draft),
    })
    guard.before_tool(first)  # type: ignore[arg-type]
    assert not first.cancel_tool

    second_id = _submission_approval(store, draft, digest)
    second = FakeEvent("submit_application", {
        "jurisdiction": "cn-consulate-sf", "doc_type": "passport", "draft_path": str(draft),
    })
    guard.before_tool(second)  # type: ignore[arg-type]
    assert not second.cancel_tool
    allowed_ids = [e["detail"]["decision_id"] for e in store.ledger_tail(100)
                   if e["action"] == "submission_allowed"]
    assert allowed_ids == [first_id, second_id]


def test_submission_approval_consumption_is_atomic_across_store_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from redtape.store import Store

    db = tmp_path / "atomic.db"
    owner = Store(db)
    draft, digest = _pipeline_draft(owner, tmp_path / "forms" / "draft.json")
    decision_id = _submission_approval(owner, draft, digest)
    gate = Barrier(2)

    contenders = [Store(db), Store(db)]

    def claim(contender: Store) -> int | None:
        try:
            gate.wait()
            claimed, _ = contender.consume_submission_approval(
                doc_type="passport",
                jurisdiction="cn-consulate-sf",
                draft_path=str(draft),
                draft_sha256=digest,
            )
            return claimed
        finally:
            contender.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, contenders))
    assert claims.count(decision_id) == 1 and claims.count(None) == 1
    assert owner.conn.execute("SELECT COUNT(*) FROM submission_approval_uses").fetchone()[0] == 1
    assert len([e for e in owner.ledger_tail(100) if e["action"] == "submission_allowed"]) == 1
    assert owner.verify_ledger() is True
    owner.close()


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
