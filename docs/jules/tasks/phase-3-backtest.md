# Phase 3 — point-in-time backtesting

## J30 — Build point-in-time historical input and corporate-action layer

### Metadata

- risk: high
- depends_on: J22, J10
- references: docs/01-features/功能增强-策略与回测实现规格.md sections 2.1–2.3
- allowed_paths: app/services/backtest/data.py, corporate_actions.py, app/models/backtest.py, app/repositories/backtest_repository.py, tests/unit/backtest/
- forbidden_paths: broker, performance metrics, API, frontend

### Objective

Provide reproducible daily history, historical universe membership, publication-time financial visibility, corporate actions, benchmarks, and dated market-rule versions.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/backtest/test_point_in_time.py tests/unit/backtest/test_corporate_actions.py

Tests must catch future financial visibility and survivorship bias.

## J31 — Implement reusable simulated broker and execution rules

### Metadata

- risk: high
- depends_on: J30, J05
- references: backtest specification sections 2.4–2.6
- allowed_paths: app/services/backtest/broker.py, execution.py, app/services/paper/market_rules.py, app/models/backtest.py, tests/unit/backtest/
- forbidden_paths: daily strategy loop, performance metrics, API

### Objective

Implement next-open/VWAP-proxy/next-close execution, fixed and volume-impact slippage, fees, lots, T+1, suspension, price limits, participation, partial fills, expiry, and same-bar exit conflicts.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/backtest/test_broker.py tests/unit/backtest/test_market_rules.py

Use hand-calculated CN/HK/US fixtures and fixed random seeds.

## J32 — Implement daily backtest engine and ledgers

### Metadata

- risk: high
- depends_on: J31
- references: backtest specification sections 2.4 and 2.7
- allowed_paths: app/services/backtest/engine.py, portfolio.py, ledger.py, app/workers/handlers/backtest.py, app/repositories/backtest_repository.py, tests/
- forbidden_paths: metric interpretation, frontend

### Objective

Execute the exact 12-step trading-day order, persist orders/trades/positions/equity/events, support durable progress/cancel, and reconcile every day.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/backtest/test_engine.py tests/unit/backtest/test_ledger.py tests/integration/test_backtest_worker.py

Every fixture must satisfy cash + market value = equity within currency precision.

## J33 — Implement deterministic performance metrics

### Metadata

- risk: high
- depends_on: J32
- references: backtest specification section 2.8
- allowed_paths: app/services/backtest/performance.py, app/models/backtest.py, tests/unit/backtest/test_performance.py
- forbidden_paths: LLM interpretation, API, frontend

### Objective

Calculate every required absolute, risk-adjusted, benchmark-relative, trade, fee, turnover, concentration, monthly, yearly, and exit metric with documented formulas.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/backtest/test_performance.py

Cover zero trades, short sample, zero volatility, no drawdown, negative equity rejection, and FIFO closed lots.

## J34 — Add backtest APIs and exports

### Metadata

- risk: medium
- depends_on: J33
- references: backtest specification section 2.10
- allowed_paths: app/routers/backtests.py, app/main.py, app/services/backtest/, tests/integration/test_backtest_api.py
- forbidden_paths: frontend, parameter search

### Objective

Add owner-scoped create/list/detail/cancel/equity/trades/positions/events/metrics/compare/export APIs with 202 task creation and bounded pagination.

### Validation

    bash scripts/jules/verify.sh backend tests/integration/test_backtest_api.py

## J35 — Add backtest creation and result UI

### Metadata

- risk: medium
- depends_on: J34
- references: backtest specification section 2.11 except parameter laboratory
- allowed_paths: frontend/src/api/backtests.ts, frontend/src/types/backtest.ts, frontend/src/views/Backtests/, frontend/src/router/, frontend/src/components/Layout/
- forbidden_paths: backend, parameter laboratory

### Objective

Add authenticated creation, durable progress/cancel, result overview, equity/drawdown, monthly returns, trades, positions, events, warnings, export, and comparison.

### Validation

    bash scripts/jules/verify.sh frontend

## J36 — Add parameter search and walk-forward evaluation

### Metadata

- risk: high
- depends_on: J33, J34
- references: backtest specification section 2.9
- allowed_paths: app/services/backtest/parameter_search.py, app/workers/handlers/, app/routers/backtests.py, frontend/src/views/Backtests/, frontend/src/api/backtests.ts, tests/
- forbidden_paths: automatic strategy publication

### Objective

Implement one-to-three parameter grids, train/validation/test and walk-forward windows, combination limits, child runs, shared read-only inputs, stability results, and a parameter-lab UI.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/backtest/test_parameter_search.py tests/integration/test_parameter_search_api.py
    bash scripts/jules/verify.sh frontend

Never auto-publish the highest in-sample result.

