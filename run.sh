#!/usr/bin/env bash
# Smart Queue Bot — one-command launcher (macOS / Linux / Git Bash)
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python -m venv "$VENV"
fi

# venv python (Windows Git Bash uses Scripts/, *nix uses bin/)
if [ -f "$VENV/Scripts/python.exe" ]; then
  PY="$VENV/Scripts/python.exe"
else
  PY="$VENV/bin/python"
fi

echo "Installing dependencies..."
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r "$ROOT/backend/requirements.txt" --quiet

echo ""
echo "Smart Queue Bot starting at http://127.0.0.1:8000"
echo "  Home / sign up: http://127.0.0.1:8000/"
echo "  Dashboard:      http://127.0.0.1:8000/dashboard.html (after login)"
echo "  Customer link:  http://127.0.0.1:8000/q/<your-slug> (shown on your dashboard)"
echo ""

cd "$ROOT/backend"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
