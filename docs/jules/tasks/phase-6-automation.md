# Phase 6 — intelligent selection and automatic paper simulation

## J60 — Add paper portfolios, lots, ledger, and migration

### Metadata

- risk: high
- depends_on: J05, J31
- references: docs/01-features/功能增强-智能选股自动模拟与学习实现规格.md sections 2, 3, 7.2–7.4
- allowed_paths: app/models/paper.py, app/services/paper/, app/repositories/, app/migrations/, app/routers/paper.py, tests/
- forbidden_paths: campaigns, attribution, learning, real broker integration

### Objective

Add isolated manual/automation portfolios, position lots, order events, ledger entries, reconciliation, optimistic concurrency, and idempotent migration of legacy paper data.

### Required implementation

Preserve old API defaults through a manual default portfolio. Atomic fills must reconcile order/trades/cash/lots/positions. A mismatch freezes automated writes and emits a domain error.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/paper/ tests/integration/test_paper_portfolio_migration.py tests/integration/test_paper_reconciliation.py

## J61 — Implement Campaign lifecycle and validation

### Metadata

- risk: high
- depends_on: J60, J24
- references: automation specification sections 4 and 5
- allowed_paths: app/models/automation.py, app/repositories/automation_repository.py, app/services/automation/campaign_service.py, app/migrations/, tests/unit/automation/
- forbidden_paths: cycle execution, risk exits, UI

### Objective

Implement draft/validating/ready/active/paused/stopping/completed/failed transitions, activation validation, frozen fields, revisions, portfolio allocation, and non-retroactive start semantics.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/automation/test_campaign_state.py tests/unit/automation/test_campaign_validation.py

## J62 — Implement idempotent Campaign cycles, candidates, and orders

### Metadata

- risk: high
- depends_on: J61, J41
- references: automation specification section 6 and 7.1
- allowed_paths: app/services/automation/cycle_runner.py, allocation.py, app/workers/handlers/campaign_cycle.py, app/repositories/automation_repository.py, tests/
- forbidden_paths: exit rules, attribution, UI

### Objective

Run post-activation strategy cycles over fixed universe/factor snapshots, save all selected and rejected candidates, allocate deterministically, and create one idempotent order set per campaign/time bucket.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/automation/test_cycle_runner.py tests/integration/test_campaign_cycle_worker.py

Two workers and task retries must not duplicate candidates or orders.

## J63 — Implement position and portfolio risk exits

### Metadata

- risk: high
- depends_on: J62
- references: automation specification section 8
- allowed_paths: app/services/automation/risk_engine.py, app/services/paper/, app/workers/handlers/campaign_cycle.py, tests/unit/automation/
- forbidden_paths: attribution, learning, UI

### Objective

Implement fixed/ATR/trailing stops, take profit, strategy/time exit, conflict priority, portfolio drawdown/daily loss pause, T+1/limit blocking, stale-data behavior, cooldown, and user-confirmed resume.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/automation/test_risk_engine.py tests/integration/test_automation_exits.py

## J64 — Add Campaign equity, completion, performance, APIs, and notifications

### Metadata

- risk: high
- depends_on: J63, J33
- references: automation specification sections 9, 13, 14, and 16
- allowed_paths: app/services/automation/performance_service.py, app/routers/automations.py, app/main.py, app/services/notifications_service.py, app/workers/handlers/, tests/
- forbidden_paths: frontend, attribution, learning

### Objective

Persist daily equity, complete mark-to-market/liquidate policies, deterministic performance/opportunity-cost results, owner-scoped Campaign APIs, and only the specified notifications.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/automation/test_performance.py tests/integration/test_automation_api.py tests/integration/test_automation_notifications.py

## J65 — Add automatic simulation Campaign UI

### Metadata

- risk: medium
- depends_on: J64
- references: automation specification sections 15.1–15.2
- allowed_paths: frontend/src/api/automations.ts, frontend/src/types/automation.ts, frontend/src/views/Automation/, frontend/src/views/PaperTrading/, frontend/src/router/, frontend/src/components/Layout/
- forbidden_paths: backend, attribution/learning UI

### Objective

Add the guarded creation wizard, validation/dry-run, activation confirmation, status/health/equity, candidates, positions/lots, orders, events, pause/resume/stop, and risk-blocked UX.

### Validation

    bash scripts/jules/verify.sh frontend

