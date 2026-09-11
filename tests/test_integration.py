"""Integration tests: the store under concurrent writes, and the sandbox API.

These guard the two failure modes that only appear outside unit-test
serialsation: Strands executing independent tool calls on parallel threads
through one shared Store (writes used to vanish), and eval scenarios leaking
state into each other through the sandbox portal.
"""
import threading

from fastapi.testclient import TestClient

from mockgov.app import app as mockgov_app
from redtape.store import Store


def test_store_survives_parallel_tool_call_writes(tmp_path):
    """4 threads x interleaved writes through ONE store, like Strands' parallel
    tool execution. Every write must land and the hash chain must stay valid."""
    store = Store(tmp_path / "t.db")
    errors: list[BaseException] = []

    def hammer(tid: int) -> None:
        try:
            for i in range(25):
                store.log("agent", "tool_call", {"thread": tid, "i": i})
                if i % 10 == 0:
                    store.add_document({
                        "doc_type": "passport", "jurisdiction": "cn-consulate-sf",
                        "number": f"T{tid}-{i}", "expiry_date": "2027-01-01",
                        "holder_name": "Concurrent Demo", "confirmed": True,
                    })
        except BaseException as e:  # noqa: BLE001 — surfaced via assertion below
            errors.append(e)

    threads = [threading.Thread(target=hammer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"writes raised: {errors}"
    n_logs = store.conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    n_docs = store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert n_logs == 4 * 25 + 12, f"expected every log to land, got {n_logs}"
    assert n_docs == 12
    assert store.verify_ledger() is True
    store.close()


def test_mockgov_reset_restores_pristine_state():
    """book the best slot, then reset: every slot free, no bookings/cases left.
    This is the per-scenario isolation hook the eval runner depends on."""
    with TestClient(mockgov_app) as h:
        h.post("/api/admin/reset").raise_for_status()
        before = h.get("/api/slots", params={"office": "cn-consulate-sf",
                                             "service": "passport_renewal"}).json()
        assert any(s["slot_id"] == "S-1003" for s in before)

        h.post("/api/bookings", json={
            "slot_id": "S-1003", "applicant_name": "Occupant", "document_number": "X",
        }).raise_for_status()
        taken = h.get("/api/slots", params={"office": "cn-consulate-sf",
                                            "service": "passport_renewal"}).json()
        assert all(s["slot_id"] != "S-1003" for s in taken)

        h.post("/api/admin/reset").raise_for_status()
        after = h.get("/api/slots", params={"office": "cn-consulate-sf",
                                            "service": "passport_renewal"}).json()
        assert any(s["slot_id"] == "S-1003" for s in after)
