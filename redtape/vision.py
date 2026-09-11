"""Vision intake: read a photo of a document, extract structured fields.
Uses the configured model's image input (K2.7 supports image_in).
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import httpx

_PROMPT = """Read this photo of an identity document. Extract ONLY JSON, no prose:
{"doc_type": one of "passport"|"driver_license"|"lawful_status"|"other",
 "jurisdiction": issuing authority or country code,
 "number": document number,
 "expiry_date": ISO date YYYY-MM-DD,
 "holder_name": full name,
 "fields": {any other visible fields like birth date, issuing city}}
If a field is unreadable, use null. If this is not a document, return {"error": "not a document"}."""


def extract_document_fields(image_path: str | Path) -> dict:
    import os
    raw = Path(image_path).read_bytes()
    b64 = base64.b64encode(raw).decode()
    mime = "image/png" if str(image_path).lower().endswith(".png") else "image/jpeg"
    resp = httpx.post(
        "https://api.kimi.com/coding/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['KIMI_CODE_API_KEY']}"},
        json={
            "model": os.environ.get("REDTAPE_MODEL_ID", "kimi-for-coding"),
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"vision extraction returned no JSON: {text[:200]}")
    fields = json.loads(match.group(0))
    if "error" in fields:
        raise ValueError(fields["error"])
    return fields
