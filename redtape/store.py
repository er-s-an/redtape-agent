"""Durable state for RedTape: documents, decisions, and a hash-chained action ledger.

Every autonomous action the agent takes lands in the ledger as an append-only,
hash-chained entry — the project's determinism/trust story made concrete.

Thread safety: the Strands runtime may execute independent tool calls on
parallel threads, and every tool writes through this one Store. sqlite3
connections tolerate cross-thread use only when serialized, so all access is
guarded by a reentrant lock (reentrant because higher-level operations call
log() while already holding it).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    number TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    holder_name TEXT NOT NULL,
    fields TEXT NOT NULL DEFAULT '{}',
    confirmed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    context TEXT NOT NULL,
    options TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT,
    resolution TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""

GENESIS = "0" * 64


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "redtape_data/redtape.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # WAL: the server, daemon, and CLI checks hit this file concurrently;
        # rollback-journal mode lets one writer starve the others mid-cycle.
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # --- documents -------------------------------------------------------

    def add_document(self, doc: dict[str, Any]) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO documents (doc_type, jurisdiction, number, expiry_date, holder_name, fields, confirmed)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    doc["doc_type"], doc["jurisdiction"], doc["number"], doc["expiry_date"],
                    doc["holder_name"], json.dumps(doc.get("fields", {})), int(doc.get("confirmed", False)),
                ),
            )
            self.conn.commit()
            self.log("human" if doc.get("confirmed") else "agent", "document_added",
                     {"doc_id": cur.lastrowid, "doc_type": doc["doc_type"]})
            return cur.lastrowid

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM documents ORDER BY expiry_date").fetchall()
            return [self._row(r, json_cols=("fields",)) for r in rows]

    def get_document_by_type(self, doc_type: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM documents WHERE doc_type = ? ORDER BY expiry_date DESC LIMIT 1", (doc_type,)
            ).fetchone()
            return self._row(row, json_cols=("fields",)) if row else None

    # --- decisions -------------------------------------------------------

    def create_decision(self, kind: str, context: dict[str, Any], options: list[dict[str, Any]]) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO decisions (created_at, kind, context, options) VALUES (?, ?, ?, ?)",
                (_utcnow(), kind, json.dumps(context), json.dumps(options)),
            )
            self.conn.commit()
            self.log("agent", "decision_requested", {"decision_id": cur.lastrowid, "kind": kind})
            return cur.lastrowid

    def pending_decisions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM decisions WHERE status = 'pending' ORDER BY created_at"
            ).fetchall()
            return [self._row(r, json_cols=("context", "options")) for r in rows]

    def resolve_decision(self, decision_id: int, choice: Any, by: str = "human") -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE decisions SET status = 'resolved', resolved_at = ?, resolution = ? WHERE id = ?",
                (_utcnow(), json.dumps({"choice": choice, "by": by}), decision_id),
            )
            self.conn.commit()
            self.log(by, "decision_resolved", {"decision_id": decision_id, "choice": choice})

    def resolved_pending_execution(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM decisions WHERE status = 'resolved' ORDER BY resolved_at"
            ).fetchall()
            return [self._row(r, json_cols=("context", "options", "resolution")) for r in rows]

    def mark_decision_executed(self, decision_id: int) -> None:
        with self._lock:
            self.conn.execute("UPDATE decisions SET status = 'executed' WHERE id = ?", (decision_id,))
            self.conn.commit()
            self.log("agent", "decision_executed", {"decision_id": decision_id})

    # --- ledger ----------------------------------------------------------

    def log(self, actor: str, action: str, detail: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            prev = self.conn.execute("SELECT hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else GENESIS
            ts = _utcnow()
            body = json.dumps({"ts": ts, "actor": actor, "action": action, "detail": detail},
                              sort_keys=True, ensure_ascii=False)
            digest = hashlib.sha256((prev_hash + body).encode()).hexdigest()
            self.conn.execute(
                "INSERT INTO ledger (ts, actor, action, detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, actor, action, json.dumps(detail, ensure_ascii=False), prev_hash, digest),
            )
            self.conn.commit()
            return {"ts": ts, "actor": actor, "action": action, "hash": digest}

    def ledger_tail(self, n: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (n,)).fetchall()
            return [self._row(r, json_cols=("detail",)) for r in reversed(rows)]

    def verify_ledger(self) -> bool:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM ledger ORDER BY id").fetchall()
            prev_hash = GENESIS
            for r in rows:
                body = json.dumps({"ts": r["ts"], "actor": r["actor"], "action": r["action"],
                                   "detail": json.loads(r["detail"])}, sort_keys=True, ensure_ascii=False)
                if r["prev_hash"] != prev_hash:
                    return False
                prev_hash = hashlib.sha256((prev_hash + body).encode()).hexdigest()
                if r["hash"] != prev_hash:
                    return False
            return True

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _row(row: sqlite3.Row, json_cols: tuple[str, ...]) -> dict[str, Any]:
        out = dict(row)
        for col in json_cols:
            if col in out and isinstance(out[col], str):
                out[col] = json.loads(out[col])
        return out
