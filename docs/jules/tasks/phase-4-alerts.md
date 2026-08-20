# Phase 4 — realtime monitoring and alerts

## J40 — Add versioned alert rules and state semantics

### Metadata

- risk: high
- depends_on: J01, J17
- references: docs/01-features/功能增强-预警与AI-Skill实现规格.md sections 1.1–1.6
- allowed_paths: app/models/alert.py, app/repositories/alert_repository.py, app/services/alerts/rule_validator.py, state_machine.py, tests/unit/alerts/
- forbidden_paths: scheduler, notification transport, frontend

### Objective

Implement owner-scoped rule/state/event models and exact edge/level/once, true/false/unknown, cooldown, recovery, daily quota, version, and scope validation.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/alerts/test_rule_validator.py tests/unit/alerts/test_state_machine.py

## J41 — Implement grouped realtime evaluation planner

### Metadata

- risk: high
- depends_on: J40, J16
- references: alert specification sections 1.7–1.8
- allowed_paths: app/services/alerts/planner.py, evaluator.py, state_repository.py, app/workers/handlers/alert_evaluation.py, app/services/scheduler_service.py, tests/
- forbidden_paths: UI, email/webhook channels, automated trade actions

### Objective

Group rules by market/frequency/dependency, load shared snapshots once, enforce market sessions/staleness, use a distributed time-bucket lock, atomically update state, and idempotently write events.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/alerts/test_evaluator.py tests/integration/test_alert_planner.py

Two concurrent evaluators must create one event.

## J42 — Make notification delivery multi-user/multi-instance and migrate favorite thresholds

### Metadata

- risk: high
- depends_on: J41
- references: alert specification sections 1.9 and 1.12
- allowed_paths: app/services/notifications_service.py, app/routers/websocket_notifications.py, app/services/alerts/event_service.py, app/services/favorites_service.py, app/migrations/, tests/
- forbidden_paths: external notification providers, alert UI

### Objective

Publish structured alert metadata to the correct user across API instances, retain Mongo fallback, and idempotently convert legacy favorite high/low thresholds into rules.

### Validation

    bash scripts/jules/verify.sh backend tests/integration/test_alert_delivery.py tests/integration/test_favorite_alert_migration.py

## J43 — Add alert APIs and health

### Metadata

- risk: medium
- depends_on: J42
- references: alert specification section 1.11
- allowed_paths: app/routers/alerts.py, app/main.py, app/services/alerts/, tests/integration/test_alert_api.py
- forbidden_paths: frontend, automated paper actions

### Objective

Implement rule CRUD/enable/disable/validate/preview/test-notification, event query/ack, and health APIs with ownership, optimistic version conflicts, quotas, and stable errors.

### Validation

    bash scripts/jules/verify.sh backend tests/integration/test_alert_api.py

## J44 — Add monitoring center, rule wizard, and event UI

### Metadata

- risk: medium
- depends_on: J43
- references: alert specification section 1.13
- allowed_paths: frontend/src/api/alerts.ts, frontend/src/types/alert.ts, frontend/src/views/Alerts/, frontend/src/views/Favorites/, frontend/src/router/, frontend/src/components/Layout/
- forbidden_paths: backend, external channels

### Objective

Add authenticated monitoring health, rule wizard/list, realtime event center, acknowledgement, structured values/timestamps/latency, favorite compatibility, and deduplicated critical presentation.

### Validation

    bash scripts/jules/verify.sh frontend
