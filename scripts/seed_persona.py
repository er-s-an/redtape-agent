"""Seed the synthetic demo persona (no real personal data — the repo is public).

Persona: Xiao Demo, a Chinese engineer in Seattle.
- passport expiring 2027-04-15 (7.5 months out — looks 'fine' to a human)
- WA driver license expiring 2027-03-01
- registered trigger: flight home 2026-12-20 (needs 6-month passport validity)
"""
import json
from datetime import date

from redtape.paths import DATA_DIR
from redtape.store import Store


def main() -> None:
    store = Store(DATA_DIR / "redtape.db")
    if store.list_documents():
        print("persona already seeded; leaving store untouched")
        return
    store.add_document({
        "doc_type": "passport", "jurisdiction": "cn-consulate-sf",
        "number": "E12345678", "expiry_date": "2027-04-15",
        "holder_name": "Xiao Demo", "confirmed": True,
        "fields": {"country": "CN", "type": "ordinary"},
    })
    store.add_document({
        "doc_type": "driver_license", "jurisdiction": "wa-dol",
        "number": "WDL123DEMO", "expiry_date": "2027-03-01",
        "holder_name": "Xiao Demo", "confirmed": True,
        "fields": {"state": "WA", "class": "D"},
    })
    store.add_document({
        "doc_type": "lawful_status", "jurisdiction": "us-uscis",
        "number": "I94-DEMO-001", "expiry_date": "2027-09-30",
        "holder_name": "Xiao Demo", "confirmed": True,
        "fields": {"basis": "H-1B"},
    })
    (DATA_DIR / "events.json").write_text(json.dumps([
        {"kind": "travel", "date": "2026-11-20",
         "description": "urgent family trip home", "needs": {"passport": True}},
    ], indent=2))
    print("seeded: passport, driver_license, lawful_status + travel event 2026-11-20")


if __name__ == "__main__":
    main()
