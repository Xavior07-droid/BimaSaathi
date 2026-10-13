#!/usr/bin/env bash
# One-shot dev setup for backend (Linux/macOS/Git-Bash). Needs Python 3.12.
set -e
cd "$(dirname "$0")"
python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate
python -c "import sys; assert sys.version_info[:2]==(3,12), f'Need Python 3.12, got {sys.version}'"
pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp ../.env.example .env 2>/dev/null || true
pytest -q
echo "A1 OK. Activate with: source .venv/bin/activate  (Windows: .venv\\Scripts\\activate)"
