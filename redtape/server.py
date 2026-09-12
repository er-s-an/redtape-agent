"""RedTape web app: the product surface.

Dashboard (documents, deadlines, dependency graph), Decision Inbox
(the only place the agent ever interrupts you), Activity (what the agent
did, in plain language), and the Wake button that runs one background
scan-and-act cycle live.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .paths import DATA_DIR, REPO_ROOT
from .store import Store, same_json_value
from .clock import today as clock_today

MOCKGOV_BASE = os.environ.get("MOCKGOV_BASE", "http://localhost:9100").rstrip("/")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="RedTape")
_store: Store | None = None
_wake_state: dict = {"running": False, "log": "", "started_at": None}


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(DATA_DIR / "redtape.db")
    return _store


# --- state ---------------------------------------------------------------

@app.get("/api/state")
def state() -> dict:
    s = store()
    today = clock_today()
    docs = []
    for d in s.list_documents():
        expiry = date.fromisoformat(d["expiry_date"])
        docs.append({**d, "days_until_expiry": (expiry - today).days})
    events_path = DATA_DIR / "events.json"
    events = json.loads(events_path.read_text()) if events_path.exists() else []
    activity = s.ledger_tail(80)
    return {
        "today": today.isoformat(),
        "documents": docs,
        "decisions": s.pending_decisions(),
        "activity": activity,
        "events": events,
        "timeline": compute_timeline(s, today, events),
        "wake": {k: v for k, v in _wake_state.items()},
        "ledger_verified": s.verify_ledger(),
    }


def compute_timeline(s: Store, today: date, events: list) -> list[dict]:
    """Deterministic view of the plan the agent would compute — drives the
    timeline strip so the deadlines are visible before/after the agent runs."""
    import httpx
    from .domain import TravelEvent, plan_for_travel
    from .tools import _doc_to_domain, _rule_to_domain
    marks: list[dict] = []
    passport = s.get_document_by_type("passport")
    if passport is None:
        return marks
    travel = next((e for e in events if e.get("needs", {}).get("passport")), None)
    if travel is None:
        return marks
    try:
        with httpx.Client(base_url=MOCKGOV_BASE, timeout=5, trust_env=False) as h:
            rule = h.get(f"/api/rules/{passport['jurisdiction']}/passport").json()
    except Exception:
        return marks
    plan = plan_for_travel(
        TravelEvent(date.fromisoformat(travel["date"]), travel["description"]),
        _doc_to_domain(passport), _rule_to_domain(rule), today,
    )
    label = {"book_appointment": "book appointment by", "renew": "submit renewal by"}
    for step in plan.steps:
        marks.append({"date": step.latest_date.isoformat(), "kind": step.action,
                      "label": label.get(step.action, step.action)})
    if plan.needs_action:
        marks.append({"date": travel["date"], "kind": "travel", "label": travel["description"]})
    return sorted(marks, key=lambda m: m["date"])


@app.get("/api/graph")
def graph() -> dict:
    s = store()
    docs = s.list_documents()
    nodes, edges = [], []
    for d in docs:
        nodes.append({"id": d["doc_type"], "label": d["doc_type"].replace("_", " "),
                      "expiry": d["expiry_date"]})
    known = {d["doc_type"] for d in docs}
    if {"passport", "driver_license"} <= known:
        edges.append({"from": "driver_license", "to": "passport",
                      "label": "renewal needs passport in hand"})
    if {"passport", "lawful_status"} <= known:
        edges.append({"from": "lawful_status", "to": "passport",
                      "label": "status renewal needs valid passport"})
    if "lawful_status" in known:
        edges.append({"from": "driver_license", "to": "lawful_status",
                      "label": "renewal needs lawful status"})
    return {"nodes": nodes, "edges": edges}


# --- decisions -----------------------------------------------------------

class ResolveRequest(BaseModel):
    choice: dict[str, object]


def validate_resolution_choice(decision: dict, choice: dict[str, object]) -> None:
    """Accept only a displayed option; submission approvals need exact binding."""
    if not any(same_json_value(choice, option) for option in decision.get("options", [])):
        raise HTTPException(422, "choice must exactly match one option shown in this decision")
    if decision.get("kind") != "submit_application":
        return
    approve = choice.get("approve")
    if type(approve) is not bool:
        raise HTTPException(422, "submission choices must explicitly set approve true or false")
    if approve is False:
        return
    required = ("doc_type", "jurisdiction", "draft_path", "draft_sha256")
    missing = [name for name in required if not isinstance(choice.get(name), str) or not choice.get(name)]
    if missing:
        raise HTTPException(422, f"submission approval is missing exact binding: {', '.join(missing)}")
    if re.fullmatch(r"[0-9a-f]{64}", str(choice["draft_sha256"])) is None:
        raise HTTPException(422, "submission approval draft_sha256 must be 64 lowercase hex characters")


@app.post("/api/decisions/{decision_id}/resolve")
def resolve(decision_id: int, req: ResolveRequest) -> dict:
    s = store()
    decision = s.get_decision(decision_id)
    if decision is None:
        raise HTTPException(404, "decision not found")
    if decision["status"] != "pending":
        raise HTTPException(409, "decision is no longer pending")
    validate_resolution_choice(decision, req.choice)
    try:
        s.resolve_decision(decision_id, req.choice, by="human")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    def _wake_when_free() -> None:
        import time
        while _wake_state["running"]:
            time.sleep(2)
        wake()

    threading.Thread(target=_wake_when_free, daemon=True).start()
    return {"ok": True, "decision_id": decision_id, "status": "resolved"}


# --- documents ------------------------------------------------------------

@app.post("/api/documents/{doc_id}/confirm")
def confirm_document(doc_id: int) -> dict:
    store().confirm_document(doc_id)
    return {"ok": True}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int) -> dict:
    store().delete_document(doc_id)
    return {"ok": True}


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile) -> dict:
    """Extract document fields from a photo via the vision model, then store
    unconfirmed — the human confirms before the agent trusts it. The raw file
    is kept locally (and removed when the document is deleted); it is sent to
    the configured vision provider for extraction."""
    from .vision import extract_document_fields
    data = await file.read()
    suffix = Path(file.filename or "doc.jpg").suffix or ".jpg"
    raw_dir = DATA_DIR / "uploads"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}{suffix}"
    raw_path.write_bytes(data)
    fields = extract_document_fields(raw_path)
    doc_id = store().add_document({**fields, "confirmed": False,
                                   "fields": {"raw_path": str(raw_path)}})
    return {"doc_id": doc_id, "extracted": fields}


# --- wake (run one agent cycle) -------------------------------------------

@app.post("/api/wake")
def wake() -> dict:
    if _wake_state["running"]:
        raise HTTPException(409, "a wake cycle is already running")

    def _run() -> None:
        _wake_state.update(running=True, log="", started_at=datetime.now().isoformat(timespec="seconds"))
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "redtape.daemon", "--once"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if "reasoningContent is not supported" in line:
                continue
            _wake_state["log"] += line
        proc.wait()
        _wake_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True}


@app.get("/api/wake/log")
def wake_log() -> dict:
    return _wake_state


# --- static UI -------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
