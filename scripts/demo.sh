#!/bin/bash
# RedTape — one-command demo. Starts the sandbox portal + web app, seeds the
# synthetic persona, and opens the UI.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

lsof -ti:9100 | xargs kill 2>/dev/null || true
lsof -ti:9200 | xargs kill 2>/dev/null || true

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
