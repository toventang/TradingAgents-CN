#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"

mode="quick"
if [[ "$#" -gt 0 ]]; then
  mode="$1"
  shift
fi

fast_tests=(
  tests/test_external_test_inventory.py
  tests/test_jules_validation_contract.py
  tests/unit/tools/analysis/test_indicators_uil.py
)

activate_backend() {
  if [[ -f .venv/bin/activate ]]; then
    # Jules snapshots use this path. CI may instead provide an already-active Python.
    source .venv/bin/activate
  elif ! command -v python >/dev/null 2>&1; then
    echo "Python is unavailable. Run: bash scripts/jules/setup.sh" >&2
    exit 2
  fi
}

case "$mode" in
  imports)
    activate_backend
    python scripts/validation/check_imports.py
    ;;
  backend)
    if [[ "$#" -eq 0 ]]; then
      echo "backend mode requires one or more explicit test paths" >&2
      exit 2
    fi
    activate_backend
    python -m pytest -c tests/pytest.ini "$@" -q
    ;;
  fast)
    activate_backend
    python -m pytest -c tests/pytest.ini "${fast_tests[@]}" -q
    ;;
  frontend)
    yarn --cwd frontend type-check
    yarn --cwd frontend build
    ;;
  quick)
    activate_backend
    python scripts/validation/check_imports.py
    python scripts/jules/validate_manifest.py
    python -m pytest -c tests/pytest.ini "${fast_tests[@]}" -q
    ;;
  *)
    echo "Usage: $0 {quick|imports|fast|backend <test-paths...>|frontend}" >&2
    exit 2
    ;;
esac
