# Jules validation baseline

## J00 result

- Task: `J00 — Establish deterministic test and CI baseline`
- Outcome: implementation complete; Ubuntu-only setup/frontend checks remain for the first Jules snapshot or pull-request run.
- Starting commit: `94ced9b3b252cc4f60eb414c1b7f9885f2147aa1`
- Baseline captured: 2026-08-21
- Later task started: no

## Supported pull-request gate

The required workflow is `.github/workflows/jules-quality-gate.yml`, named `Jules quality gate`. It has two independent jobs:

1. `backend-fast-gate`: install `.[dev]`, run static import validation, then run the deterministic Python list below.
2. `frontend-type-and-build`: install the frozen Yarn classic lockfile, run `vue-tsc --noEmit`, then run the Vite production build.

The stable local/Jules entry points are:

```bash
bash scripts/jules/verify.sh imports
bash scripts/jules/verify.sh fast
bash scripts/jules/verify.sh frontend
bash scripts/jules/verify.sh quick
bash scripts/jules/verify.sh backend <explicit-test-paths...>
```

`quick` runs import validation, the Jules task-manifest validator, and the same fast test list as `fast`.

## Deterministic Python test list

The authoritative list is the `fast_tests` array in `scripts/jules/verify.sh`:

```text
tests/test_external_test_inventory.py
tests/test_jules_validation_contract.py
tests/unit/tools/analysis/test_indicators_uil.py
```

These tests use only repository files and deterministic in-memory data. They do not require an LLM, market-data provider, email, MongoDB, Redis, broker, credentials, or wall-clock-sensitive assertions.

Known live/manual tests are enumerated with reasons in `tests/external_test_inventory.py`. `tests/conftest.py` applies `integration` or `external` markers centrally and prevents their modules from being imported during the default test run. Assertions in those historical tests were not weakened or removed.

## Validation evidence from the J00 development environment

The local host is Windows without WSL. Its available runtimes were:

```text
Python 3.12.13 (Codex bundled runtime)
Node v24.19.0 (Codex bundled runtime)
Yarn unavailable
```

### Passed

Command:

```powershell
C:\Users\ttw13\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -c tests/pytest.ini tests/test_external_test_inventory.py tests/test_jules_validation_contract.py tests/unit/tools/analysis/test_indicators_uil.py -q
```

Result:

```text
8 passed in 86.65s
```

The network-share filesystem accounts for most of the local duration; the set is expected to be materially faster on the Jules Ubuntu VM.

After expanding the external-test inventory, the two directly affected files were rerun:

```powershell
C:\Users\ttw13\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -c tests/pytest.ini tests/test_external_test_inventory.py tests/test_jules_validation_contract.py -q
```

Result:

```text
6 passed in 11.57s
```

Import validation initially encountered the pre-existing Windows console encoding issue documented below. With UTF-8 mode enabled, the validator passed:

```powershell
$env:PYTHONUTF8='1'
C:\Users\ttw13\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts/validation/check_imports.py
```

Result:

```text
checked files: 310
checked imports: 2757
errors: 0
```

Manifest validation passed:

```powershell
C:\Users\ttw13\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts/jules/validate_manifest.py
```

Result:

```text
Jules manifest valid: 57 tasks, no missing sections or dependency cycles
```

Shell syntax validation passed:

```powershell
C:\Program Files\Git\bin\bash.exe -n Z:/Documents/opensource/AI/TradingAgents-CN/scripts/jules/setup.sh
C:\Program Files\Git\bin\bash.exe -n Z:/Documents/opensource/AI/TradingAgents-CN/scripts/jules/verify.sh
```

## Required checks not executable on this host

The following task-packet commands are intentionally still required in Jules/CI, but could not be completed on this Windows host:

```bash
bash scripts/jules/setup.sh
bash scripts/jules/verify.sh frontend
```

Reason: the setup contract intentionally targets Jules Ubuntu and creates `.venv/bin/activate`; this host has no WSL. Git Bash resolves `python`/`python3` to non-functional Windows Store aliases, and Yarn plus `frontend/node_modules` are absent. The implementation was not changed to accommodate this non-Jules environment because that would weaken the documented Ubuntu setup contract.

The first Jules snapshot or pull-request workflow must capture its actual Python, Node, and Yarn versions and confirm both commands. A failure there is a J00 blocker and must not be reclassified as a product-feature failure.

## Pre-existing unrelated failures and environment observations

### Windows GBK console failure in import validator

Exact command:

```powershell
C:\Users\ttw13\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts/validation/check_imports.py
```

Error summary:

```text
UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f4c2'
```

The failure occurs while printing an emoji before validation begins. `PYTHONUTF8=1` makes the unchanged validator pass. J00 did not modify `scripts/validation/check_imports.py` because that path is outside the task's `allowed_paths`, and Jules Ubuntu uses UTF-8 by default.

### Incomplete ad-hoc Python environment

Before the fast list was run, a broader candidate list failed collection because the bundled Python did not contain base project packages (`pydantic_settings`, `fastapi`, and `motor`). This was not treated as a repository test failure: the required Ubuntu setup command had not run in that interpreter. A subsequent attempt to download those base packages timed out against `files.pythonhosted.org`; the final deterministic list above passed without changing production behavior.

## Compatibility and scope notes

- `requirements-lock.txt` remains untouched and is not used by Jules Linux setup because it contains `pywin32`.
- Runtime dependencies and production configuration are unchanged. Only the `dev` optional dependency group was added.
- Existing external/manual assertions are unchanged; classification only controls default collection.
- No application, trading kernel, frontend source, database schema, public API, financial behavior, or later Jules task was changed.
