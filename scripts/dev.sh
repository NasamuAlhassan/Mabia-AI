#!/usr/bin/env bash
# One command to run the whole thing locally.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d backend/.venv ]; then
  echo "Creating the Python environment..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing web dependencies..."
  (cd frontend && npm install --silent)
fi

echo "API   → http://127.0.0.1:8000  (docs at /docs)"
echo "Web   → http://localhost:5173"
echo "Sign in with +233200000001 / 1234"
echo

trap 'kill 0' EXIT
(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000) &
(cd frontend && npm run dev) &
wait
