#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"

python3 - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ is required, found {sys.version}")
print(f"Using Python {sys.version.split()[0]}")
PY

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
python -m pip install pytest==8.4.2 pytest-asyncio==1.2.0

if command -v corepack >/dev/null 2>&1; then
  corepack enable
fi

if ! command -v yarn >/dev/null 2>&1; then
  npm install --global yarn@1.22.22
fi

yarn --cwd frontend install --frozen-lockfile --non-interactive

python - <<'PY'
import fastapi
import pandas
import pydantic

print("Backend dependency smoke check: OK")
PY

python scripts/validation/check_imports.py
python scripts/jules/validate_manifest.py
yarn --cwd frontend --version

echo "Jules environment setup complete."
