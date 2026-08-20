# Phase 8 — security, capacity, rollout, and operations

## J80 — Run cross-domain security and failure hardening

### Metadata

- risk: high
- depends_on: J75
- references: AGENTS.md security rules and development total plan sections 8 and 10
- allowed_paths: app/, tradingagents/, frontend/src/, tests/security/, docs/security/
- forbidden_paths: new product features

### Objective

Audit and fix ownership, JWT type handling, secret/token logging, CORS, WebSocket authorization, export authorization, arbitrary execution, stale automated actions, ledger freezing, and feature-flag shutdown across the completed program.

### Required implementation

Keep fixes individually test-backed and scoped. Do not introduce new features or weaken financial controls.

### Validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/security/
    bash scripts/jules/verify.sh frontend

## J81 — Establish capacity and performance budgets

### Metadata

- risk: medium
- depends_on: J80
- references: development total plan sections 8.2 and 9
- allowed_paths: app/services/, tradingagents/, tests/performance/, scripts/benchmarks/, docs/performance/
- forbidden_paths: public behavior changes without a separate decision

### Objective

Benchmark factor chunks, concurrent backtests, alert grouping, Campaign pagination, task queues, and Skill budgets; enforce configured limits and document target-environment results.

### Validation

Run deterministic benchmark commands added by the task and the directly affected unit tests. Do not claim universal capacity from one machine.

## J82 — Finalize deployment, migration, rollback, and feature rollout

### Metadata

- risk: high
- depends_on: J81
- references: development total plan sections 5, 6, 7 Phase 8, and 13
- allowed_paths: docs/deployment/, docs/jules/, scripts/migrations/, docker-compose.yml, Dockerfile.backend, Dockerfile.frontend, .github/workflows/, tests/
- forbidden_paths: new domain features, destructive production migration

### Objective

Document and verify setup, indexes, idempotent migration dry-run/verify, worker deployment, monitoring, backup, rollback, feature-flag progression, incident handling, and final Definition of Done.

### Required implementation

1. Provide exact staging and production runbooks.
2. Verify feature flags default off.
3. Provide non-destructive migration dry run and verification.
4. Provide rollback that disables behavior without deleting data.
5. Run the complete deterministic gate and record results.
6. Mark the program complete only if every Definition of Done item has evidence.

### Validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh frontend
    bash scripts/jules/verify.sh backend tests/e2e/test_enhancement_program.py tests/security/
