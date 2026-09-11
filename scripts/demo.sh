#!/bin/bash
# RedTape — one-command demo. Starts the sandbox portal + web app, seeds the
# synthetic persona, and opens the UI.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

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
