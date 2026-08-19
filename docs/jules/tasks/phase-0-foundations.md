# Phase 0 — autonomous-development and correctness foundations

Run tasks in order J00 → J01/J02 → J03 → J04 → J05. J01 and J02 may run in parallel only from branches that both contain J00; their PRs must be merged before J03.

## J00 — Establish deterministic test and CI baseline

### Metadata

- risk: medium
- depends_on: none
- references: AGENTS.md, tests/pytest.ini, pyproject.toml, frontend/package.json
- allowed_paths: pyproject.toml, tests/, scripts/jules/, .github/workflows/, docs/jules/
- forbidden_paths: app/, tradingagents/, frontend/src/, production configuration

### Objective

Make the repository's supported fast validation commands explicit and runnable in Jules without real services or credentials.

### Required implementation

1. Add a dev/test optional dependency group containing pytest and pytest-asyncio. Do not use requirements-lock.txt on Linux because it contains pywin32.
2. Add a GitHub quality workflow for pull requests that runs import validation, a curated deterministic Python test set, frontend type-check, and frontend build.
3. Identify tests that require live APIs, MongoDB, Redis, credentials, or manual observation; mark them integration/external rather than weakening assertions.
4. Create or update a deterministic smoke-test list in scripts/jules/verify.sh. Keep total fast-gate runtime suitable for each PR.
5. Record any pre-existing unrelated failures in docs/jules/BASELINE.md with exact commands and error summaries.

### Tests and validation

    bash scripts/jules/setup.sh
    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh frontend
    source .venv/bin/activate
    python -m pytest -c tests/pytest.ini <curated-fast-test-paths> -q

### Out of scope

Do not fix product bugs, add feature models, or rewrite all historical tests.

### Stop conditions

Use DECISION_REQUIRED if there is no deterministic subset that can pass without changing production behavior.

## J01 — Fix authenticated identity and cross-user realtime isolation

### Metadata

- risk: high
- depends_on: J00
- references: AGENTS.md, docs/01-features/功能增强-开发总纲与实施清单.md sections 4 and Phase 0
- allowed_paths: app/services/auth_service.py, app/routers/websocket_notifications.py, app/middleware/, app/core/, app/models/notification.py, tests/
- forbidden_paths: factor, strategy, backtest, automation feature code

### Objective

Remove hard-coded admin identity from WebSocket notifications, task progress, and operation logging; prove messages and audit entries are scoped to the authenticated user.

### Required implementation

1. Define one tested helper that converts the verified JWT payload into the canonical user identity used by HTTP dependencies.
2. Reject missing, expired, malformed, or identity-less tokens before accepting a WebSocket.
3. Use the real user ID in the notification connection manager.
4. Verify task ownership before opening a task-progress channel.
5. Remove global task-progress broadcast. Send only to connections owned by the task user.
6. Make operation logs use the real identity rather than an admin placeholder.
7. Redact token query parameters and authorization data from logs.
8. Preserve existing HTTP authentication compatibility.

### Tests to add

- Valid user A receives user A notification.
- User B never receives user A notification or task progress.
- User B cannot subscribe to user A task.
- Invalid/expired token closes with an authorization code.
- Audit record contains the real user.
- Logs do not contain the complete token.

### Required validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/test_websocket_identity.py tests/unit/test_operation_log_identity.py

### Stop conditions

Use DECISION_REQUIRED if existing JWT payloads do not contain a stable user identifier and changing token issuance is required.

## J02 — Introduce canonical market and symbol normalization

### Metadata

- risk: medium
- depends_on: J00
- references: AGENTS.md, docs/01-features/功能增强-实现级开发规格.md sections 1.2 and 2.3
- allowed_paths: app/models/, app/services/symbols/, app/utils/, tradingagents/utils/, tests/
- forbidden_paths: analysis execution, paper trading, routers except a narrowly required shared model import

### Objective

Create a single pure SymbolNormalizer contract that converts supported legacy inputs into canonical market + symbol without changing current business flows yet.

### Required implementation

1. Define CanonicalSymbol with market CN/HK/US, symbol, currency, display_symbol, and original_input.
2. Support six-digit A shares, four/five-digit Hong Kong codes with optional .HK, and valid US tickers.
3. Reject ambiguous or invalid input instead of silently padding arbitrary text.
4. Define compatibility adapters for symbol, code, stock_code, and stock_symbol.
5. Make normalization deterministic and side-effect free; no database or network lookup.
6. Document market-detection limitations in the model.

### Tests to add

- Representative Shanghai, Shenzhen, Beijing, Hong Kong, and US inputs.
- Case and whitespace normalization.
- Conflicting explicit market and inferred market.
- Empty, malformed, overlong, and mixed inputs.
- Serialization round trip.

### Required validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/symbols/

### Out of scope

Do not migrate collections or replace every legacy field in this task.

## J03 — Add durable domain-task repository and state machine

### Metadata

- risk: high
- depends_on: J01, J02
- references: docs/01-features/功能增强-实现级开发规格.md section 3
- allowed_paths: app/models/domain_task.py, app/repositories/, app/services/domain_tasks/, app/core/database.py, tests/
- forbidden_paths: app/routers/analysis.py, app/services/simple_analysis_service.py, feature workers

### Objective

Implement the persistent task model, legal transitions, ownership, idempotency, lease, heartbeat, retry, and cancellation repository without adding feature handlers.

### Required implementation

1. Implement every domain_tasks field and index from the specification.
2. Model legal transitions as a single tested state machine.
3. Create idempotently with user_id + task_type + idempotency_key and verify request_hash.
4. Atomically claim queued tasks by priority and creation time.
5. Add heartbeat and lease extension requiring matching worker_id.
6. Recover expired running leases into retry_wait or failed according to attempt count.
7. Implement cooperative cancel requests and queued direct cancellation.
8. Persist append-only task events and paginate them.
9. Require user_id on all user-facing repository reads.
10. Use fakes or an integration fixture; no live production database.

### Tests to add

- Every legal and illegal transition.
- Two workers racing to claim the same task.
- Same idempotency key/same request and same key/different request.
- Lease ownership and expiration.
- Retry exhaustion.
- Cancellation at queued and running states.
- Cross-user reads.

### Required validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/domain_tasks/ tests/integration/test_domain_task_repository.py

## J04 — Add domain worker, handler registry, and task API

### Metadata

- risk: high
- depends_on: J03
- references: docs/01-features/功能增强-实现级开发规格.md section 3
- allowed_paths: app/workers/, app/services/domain_tasks/, app/routers/domain_tasks.py, app/main.py, tests/
- forbidden_paths: factor/backtest/alert/automation handlers, existing analysis behavior

### Objective

Provide a process entry point that executes registered domain handlers with heartbeat, cancellation, retries, graceful shutdown, and owner-scoped task APIs.

### Required implementation

1. Define a handler protocol taking validated payload, task context, progress callback, and cancellation checker.
2. Add an explicit registry; unknown task_type fails without dynamic import.
3. Implement worker polling, claim, heartbeat, retryable/non-retryable classification, and graceful SIGTERM handling.
4. Persist deterministic progress and result references, never large embedded results.
5. Add GET task, GET task events, list tasks, and cancel routes.
6. Register the router in app/main.py.
7. Do not register actual feature handlers in this task.

### Tests to add

- Success, retryable failure, terminal failure, cancellation, unknown handler, worker shutdown, and user ownership.
- API response codes 202/404/409 where applicable.

### Required validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/domain_tasks/ tests/integration/test_domain_task_api.py tests/integration/test_domain_worker.py

## J05 — Extract paper-trading domain services without behavior change

### Metadata

- risk: high
- depends_on: J04
- references: docs/01-features/功能增强-智能选股自动模拟与学习实现规格.md section 2
- allowed_paths: app/routers/paper.py, app/services/paper/, app/models/paper.py, tests/unit/paper/, tests/integration/test_paper_api.py
- forbidden_paths: automation campaigns, backtest engine, frontend

### Objective

Move current manual paper-trading logic from the router into focused services while preserving existing API responses and MongoDB collection compatibility.

### Required implementation

1. Extract SymbolNormalizer use, market rules, price snapshots, account, order, execution, position, and performance responsibilities.
2. Keep router functions limited to authentication, input validation, service calls, and response mapping.
3. Preserve current multi-currency behavior and legacy account migration.
4. Preserve A-share T+1 and existing commission behavior exactly; characterize questionable behavior with tests rather than changing it.
5. Add service-level interfaces that later backtest and automation tasks can reuse.
6. Prevent partial multi-collection updates from producing silent success; add a documented consistency boundary.

### Tests to add

- Existing buy, sell, insufficient cash, insufficient position, T+1, commission, account, position, orders, and reset behavior.
- CN/HK/US normalization through the service.
- Failure between account and position updates produces an explicit error/recovery record.

### Required validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/paper/ tests/integration/test_paper_api.py

### Out of scope

Do not add portfolios, lots, campaign fields, stop orders, or new UI.
