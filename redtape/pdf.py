"""Render a real filled application PDF from the verified document store.

The artifact is visibly marked DRAFT — RedTape prepares, humans submit.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def render_application_pdf(out_path: str | Path, *, jurisdiction: str, doc_type: str,
                           applicant: dict, rule: dict) -> str:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    w, h = LETTER

    c.setFillColor(HexColor("#b3331d"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, h - 80, f"{doc_type.replace('_', ' ').title()} Renewal Application")
    c.setFillColor(HexColor("#78716c"))
    c.setFont("Helvetica", 11)
    c.drawString(72, h - 100, f"{jurisdiction} · prepared by RedTape · {datetime.now():%Y-%m-%d %H:%M}")

    c.setStrokeColor(HexColor("#b3331d"))
    c.setLineWidth(2)
    c.line(72, h - 112, w - 72, h - 112)

    c.setFillColor(HexColor("#1c1917"))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(72, h - 150, "Applicant")
    c.setFont("Helvetica", 12)
    rows = [
        ("Full name", applicant.get("name", "")),
        ("Document number", applicant.get("document_number", "")),
        ("Current document expiry", applicant.get("current_expiry", "")),
    ]
    y = h - 174
    for label, value in rows:
        c.setFont("Helvetica-Oblique", 11)
        c.setFillColor(HexColor("#78716c"))
        c.drawString(72, y, label)
        c.setFont("Helvetica", 12)
        c.setFillColor(HexColor("#1c1917"))
        c.drawString(260, y, str(value))
        y -= 22

    p = rule.get("payload", {})
    c.setFont("Helvetica-Bold", 13)
    c.drawString(72, y - 12, "Filing details (per rules v%s, effective %s)" % (rule["version"], rule["effective_from"]))
    y -= 36
    c.setFont("Helvetica", 12)
    for label, value in [
        ("Fee", f"${p.get('fee_usd', '—')}"),
        ("Processing", f"{p.get('processing_weeks_min', '?')}–{p.get('processing_weeks_max', '?')} weeks"),
        ("Required items", ", ".join(p.get("required_items", []))),
    ]:
        c.setFont("Helvetica-Oblique", 11)
        c.setFillColor(HexColor("#78716c"))
        c.drawString(72, y, label)
        c.setFont("Helvetica", 12)
        c.setFillColor(HexColor("#1c1917"))
        c.drawString(260, y, str(value))
        y -= 22

    c.saveState()
    c.setFillColor(HexColor("#b3331d"))
    c.setFillAlpha(0.12)
    c.setFont("Helvetica-Bold", 64)
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "DRAFT — NOT SUBMITTED")
    c.restoreState()

    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#78716c"))
    c.drawString(72, 60, "RedTape prepares drafts only. A human reviews and submits. Rule source: " + rule.get("source_url", ""))
    c.showPage()
    c.save()
    return str(path)
