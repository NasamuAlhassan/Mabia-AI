#!/usr/bin/env bash
# Both halves. The frontend suite is small and covers exactly one thing -- the
# offline outbox -- because that is the piece whose failure loses a household's
# record permanently, and it is not reachable from the Python tests.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

cd "$root/backend"
[ -d .venv ] || { python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt; }
.venv/bin/python -m pytest tests/ -q

cd "$root/frontend"
if command -v node >/dev/null 2>&1; then
  node --test test/*.test.mjs
else
  echo "node not found — skipping the offline outbox tests" >&2
fi
