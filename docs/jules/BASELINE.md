# Jules validation baseline

Status: must be refreshed by task J00 on its starting commit.

## Known repository facts before J00

- Python requires 3.10 or newer.
- pytest and pytest-asyncio exist in requirements-lock.txt but are not declared in pyproject.toml development extras.
- requirements-lock.txt contains pywin32 and is not a portable Jules Ubuntu installation source.
- frontend uses Yarn classic lockfile v1.
- frontend validation commands are yarn type-check and yarn build.
- yarn lint currently includes --fix and is not a non-mutating gate.
- tests/pytest.ini excludes integration-marked tests by default.
- existing GitHub workflows publish Docker images and check upstream synchronization; they do not provide a complete pull-request unit/type/build gate.
- scripts/validation/check_imports.py is a deterministic static import validator.

## Required J00 update

J00 must record:

- Starting commit.
- Python/Node/Yarn versions in the Jules snapshot.
- Exact curated fast-test paths.
- Pass/fail result for import validation.
- Pass/fail result for frontend type-check/build.
- Any unrelated failing test with exact command and error.
- Final CI workflow names required for later PRs.

Do not treat this pre-J00 note as proof that current tests pass.

