#!/bin/bash
# RedTape — one-command demo. Starts the sandbox portal + web app, seeds the
# synthetic persona, and opens the UI.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

# Keep the judge story stable across recording days: this pin makes the
# synthetic passport show 216 days remaining and keeps every backward date in
# the UI, sandbox and agent on the same clock. Override both deliberately when
# exercising another date.
export MOCKGOV_TODAY="${MOCKGOV_TODAY:-2026-09-11}"
export REDTAPE_TODAY="${REDTAPE_TODAY:-$MOCKGOV_TODAY}"

# free the two demo ports, but only kill OUR uvicorn processes — never
# whatever a developer happens to be running on those ports otherwise
pkill -f "uvicorn mockgov.app:app --port 9100" 2>/dev/null || true
pkill -f "uvicorn redtape.server:app --port 9200" 2>/dev/null || true
sleep 1

"$PY" -m uvicorn mockgov.app:app --port 9100 &>/tmp/redtape-mockgov.log &
"$PY" -m uvicorn redtape.server:app --port 9200 &>/tmp/redtape-server.log &
sleep 2

if [ ! -f redtape_data/redtape.db ]; then
  PYTHONPATH=. "$PY" scripts/seed_persona.py
fi

echo "RedTape is up:"
echo "  product  → http://localhost:9200"
echo "  sandbox  → http://localhost:9100/docs"
open http://localhost:9200 2>/dev/null || true
