#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run: bash scripts/jules/setup.sh" >&2
  exit 2
fi

source .venv/bin/activate

mode="quick"
if [[ "$#" -gt 0 ]]; then
  mode="$1"
  shift
fi

case "$mode" in
  imports)
    python scripts/validation/check_imports.py
    ;;
  backend)
    if [[ "$#" -eq 0 ]]; then
      python -m pytest -c tests/pytest.ini tests/unit/ -q
    else
      python -m pytest -c tests/pytest.ini "$@" -q
    fi
    ;;
  frontend)
    yarn --cwd frontend type-check
    yarn --cwd frontend build
    ;;
  quick)
    python scripts/validation/check_imports.py
    ;;
  *)
    echo "Usage: $0 {quick|imports|backend [test-paths...]|frontend}" >&2
    exit 2
    ;;
esac
