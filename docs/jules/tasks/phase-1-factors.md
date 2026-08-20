# Phase 1 — factor platform

J10 and J11 may run in parallel after Phase 0. J12–J15 must then merge sequentially in numeric order because they reuse common calculator helpers. Merge all four calculation groups before J16.

## J10 — Define market data, point-in-time, calendar, and quality contracts

### Metadata

- risk: high
- depends_on: J02, J04
- references: docs/01-features/功能增强-实现级开发规格.md sections 2.3 and 4.4
- allowed_paths: app/models/market_data.py, app/services/market_data/, app/services/calendars/, app/services/data_quality/, tests/
- forbidden_paths: factor formulas, strategies, backtests, existing provider implementations except adapters

### Objective

Create normalized read contracts for OHLCV, point-in-time financial facts, news timestamps, market sessions, benchmark identity, and quality status.

### Required implementation

1. Define normalized daily-bar fields and percent semantics.
2. Define financial availability by publish_at, never report_period alone.
3. Define published_at and ingested_at visibility for news/social inputs.
4. Implement market calendar interface for trade day, sessions, next/previous legal point, and timezone.
5. Define quality states valid/partial/stale/suspended/invalid/unavailable with reason codes.
6. Add read-only adapters around current Mongo/data-source paths; do not rewrite providers.
7. Return source version and as_of on every batch.

### Tests and validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/market_data/ tests/unit/calendars/ tests/unit/data_quality/

Test publication boundaries, timezone/DST, duplicate bars, invalid OHLC, NaN/Infinity, stale data, and missing fields.

## J11 — Implement FactorDefinition and static registry metadata

### Metadata

- risk: medium
- depends_on: J03
- references: docs/01-features/功能增强-实现级开发规格.md sections 4.2 and 4.3
- allowed_paths: app/models/factor.py, app/services/factors/registry.py, app/services/factors/definitions/, app/repositories/factor_repository.py, tests/unit/factors/
- forbidden_paths: formula implementations, routers, frontend

### Objective

Register the exact 171-factor catalog with versioned metadata, parameter schemas, dependencies, market support, minimum history, direction, and missing-value policies.

### Required implementation

1. Implement FactorDefinition and FactorSpec validation.
2. Register 18 return/price, 23 trend, 18 momentum, 20 volatility/risk, 19 liquidity, 15 valuation, 20 quality, 16 growth, 12 sentiment/event, and 10 cross/composite factors.
3. Reject duplicate IDs, invalid versions, unknown dependencies, dependency cycles, output collisions, and illegal defaults at startup/test time.
4. Mirror active definitions to factor_definitions idempotently using checksum; never store executable code.
5. Expose registry query methods by ID, category, market, and status.

### Tests and validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/factors/test_registry.py tests/unit/factors/test_definition_catalog.py

The catalog-count test must assert every group and total 171.

## J12 — Implement price, trend, and momentum factors

### Metadata

- risk: high
- depends_on: J10, J11
- references: factor specification sections 4.3.1–4.3.3
- allowed_paths: app/services/factors/calculators/price.py, trend.py, momentum.py, common.py, tests/unit/factors/calculators/
- forbidden_paths: registry metadata changes except correcting a proven mismatch, APIs, other factor groups

### Objective

Implement the 59 registered return/price, trend, and momentum factor outputs using shared rolling intermediates.

### Required implementation

1. Match every formula and default parameter in the specification.
2. Keep MACD factor histogram unmultiplied; preserve old UI compatibility in an adapter, not the factor value.
3. Make RSI method explicit in provenance.
4. Use ordered per-symbol data and preserve the input index.
5. Convert non-finite outputs to missing with quality reasons.
6. Enforce minimum history and zero-denominator behavior.

### Tests and validation

Use hand-calculated constant, monotonic, oscillating, gap, zero-range, and short-history fixtures.

    bash scripts/jules/verify.sh backend tests/unit/factors/calculators/test_price.py tests/unit/factors/calculators/test_trend.py tests/unit/factors/calculators/test_momentum.py

## J13 — Implement volatility, tail-risk, and liquidity factors

### Metadata

- risk: high
- depends_on: J10, J11, J12
- references: factor specification sections 4.3.4–4.3.5
- allowed_paths: app/services/factors/calculators/volatility.py, liquidity.py, common.py, tests/unit/factors/calculators/
- forbidden_paths: APIs, backtest performance code, other factor groups

### Objective

Implement the 39 volatility/risk and volume/liquidity factors with explicit annualization, benchmark alignment, currency-unit, and zero-volume behavior.

### Required implementation

1. Parameterize market annual trading days.
2. Align benchmark and symbol returns by trade date before beta/alpha.
3. Define positive loss values for VaR/CVaR.
4. Calculate drawdown from a normalized window wealth path.
5. Normalize amount units before Amihud.
6. Treat suspension and zero volume distinctly.

### Tests and validation

    bash scripts/jules/verify.sh backend tests/unit/factors/calculators/test_volatility.py tests/unit/factors/calculators/test_liquidity.py

Include hand-calculated beta, drawdown, VaR, ATR, MFI, CMF, VWAP, and illiquidity cases.

## J14 — Implement valuation, quality, and growth factors

### Metadata

- risk: high
- depends_on: J10, J11, J13
- references: factor specification sections 4.3.6–4.3.8
- allowed_paths: app/services/factors/calculators/fundamental.py, app/services/factors/point_in_time.py, tests/unit/factors/
- forbidden_paths: provider rewrites, LLM fundamental analyst, APIs

### Objective

Implement the 51 valuation, quality, profitability, solvency, growth, and stability factors using point-in-time financial observations.

### Required implementation

1. Make observations visible only on/after publish_at.
2. Forward-fill a known observation only until the next publication.
3. Preserve report period and publication evidence.
4. Apply non-positive denominator rules exactly.
5. Return missing rather than invented estimates when inputs are absent.
6. Keep percentage storage in decimal form.
7. Support TTM/quarterly transformations explicitly and deterministically.

### Tests and validation

    bash scripts/jules/verify.sh backend tests/unit/factors/test_point_in_time.py tests/unit/factors/calculators/test_fundamental.py

Include restatement, late publication, negative earnings, missing quarters, zero denominator, and three-year CAGR cases.

## J15 — Implement sentiment, event, cross-sectional, and base composite factors

### Metadata

- risk: high
- depends_on: J10, J11, J14
- references: factor specification sections 4.3.9–4.3.10
- allowed_paths: app/services/factors/calculators/sentiment.py, event.py, cross_section.py, tests/unit/factors/
- forbidden_paths: LLM calls, arbitrary text classification, user composite DSL

### Objective

Implement the 12 sentiment/event and 10 fixed cross-sectional/composite factors from already structured, timestamped inputs.

### Required implementation

1. Use structured sentiment values and source/time-decay weights; do not call an LLM in factor calculation.
2. Enforce publication/ingestion visibility.
3. Use market/board/date-specific price-limit inputs for limit counts.
4. Rank within a fixed universe snapshot.
5. Return no z-score/rank if fewer than 20 valid symbols.
6. Save component contributions for fixed composites.

### Tests and validation

    bash scripts/jules/verify.sh backend tests/unit/factors/calculators/test_sentiment.py tests/unit/factors/calculators/test_cross_section.py

## J16 — Build parallel factor computation and immutable snapshots

### Metadata

- risk: high
- depends_on: J12, J13, J14, J15
- references: factor specification sections 4.4 and 4.7
- allowed_paths: app/services/factors/engine.py, dag.py, snapshot_service.py, app/workers/handlers/factor_compute.py, app/repositories/factor_repository.py, app/models/factor.py, tests/
- forbidden_paths: factor UI, strategy signals

### Objective

Compute requested factors over fixed universes in bounded symbol chunks, reuse intermediates, publish only complete immutable snapshots, and integrate with domain tasks.

### Required implementation

1. Plan DAG and common intermediates once per task.
2. Default to 100-symbol chunks and bounded process workers.
3. Batch asynchronous reads/writes.
4. Support progress by completed symbols, cancellation, retry, and deterministic checksum.
5. Write building chunks and atomically mark ready only after row/factor completeness checks.
6. Mark failed/superseded without exposing partial values as ready.
7. Deduplicate identical compute requests where allowed.

### Tests and validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/factors/test_engine.py tests/integration/test_factor_snapshot_repository.py tests/integration/test_factor_worker.py

Test chunk failure, retry, cancellation, duplicate request, partial publication, and deterministic rerun.

## J17 — Add factor backend APIs

### Metadata

- risk: medium
- depends_on: J16
- references: factor specification section 4.8
- allowed_paths: app/routers/factors.py, app/models/factor.py, app/main.py, app/services/factors/, tests/integration/test_factor_api.py
- forbidden_paths: frontend, strategies, factor formulas

### Objective

Expose definition discovery, validation, compute jobs, snapshots, and paginated values with authentication and stable errors.

### Required implementation

Implement every endpoint in section 4.8 except factor analysis and user composites, which belong to J19/J1A. Return 202 for task creation. Enforce owner access, page limits, finite JSON values, and feature flag behavior.

### Required validation

    bash scripts/jules/verify.sh backend tests/integration/test_factor_api.py

## J18 — Add factor catalog, compute, job, and snapshot UI

### Metadata

- risk: medium
- depends_on: J17
- references: factor specification section 4.9 items 1, 2, and 5
- allowed_paths: frontend/src/api/factors.ts, frontend/src/types/factor.ts, frontend/src/views/Factors/, frontend/src/router/, frontend/src/components/Layout/, frontend/src/stores/
- forbidden_paths: backend, strategy UI, factor research/composite screens

### Objective

Add authenticated factor catalog, computation form, durable task progress, snapshot list, quality detail, and paginated values.

### Required implementation

Use server pagination, restore task progress after reload, show as_of/source/quality/version, and never load all market values at once. Add route authentication and navigation.

### Required validation

    bash scripts/jules/verify.sh frontend

Add focused component tests if the repository test harness supports them; otherwise document manual screenshot states using deterministic mocked API data.

## J19 — Implement factor research analytics and API

### Metadata

- risk: high
- depends_on: J16, J17
- references: factor specification sections 4.6 and 4.7
- allowed_paths: app/services/factors/analysis.py, app/workers/handlers/factor_analysis.py, app/models/factor.py, app/routers/factors.py, app/repositories/factor_repository.py, tests/
- forbidden_paths: frontend, user composite DSL

### Objective

Compute IC, Rank IC, quantile returns, monotonicity, turnover, correlation, exposure, and decay without label leakage.

### Required implementation

Evaluate 1/5/10/20-day future returns by explicit forward shift, record sample boundaries/counts, reject insufficient samples, integrate durable tasks, and expose analysis creation/result APIs.

### Required validation

    bash scripts/jules/verify.sh backend tests/unit/factors/test_analysis.py tests/integration/test_factor_analysis_api.py

Include a test that would fail if future labels leak into features.

## J1A — Implement safe user composite-factor DSL and API

### Metadata

- risk: high
- depends_on: J16, J17, J19
- references: factor specification section 4.5
- allowed_paths: app/models/factor.py, app/services/factors/composites.py, app/repositories/factor_repository.py, app/routers/factors.py, tests/
- forbidden_paths: eval, exec, arbitrary formulas, frontend

### Objective

Implement the exact structured transform, neutralize, arithmetic, missing, and filter whitelist for versioned user composite factors.

### Required implementation

Validate weight normalization, auto direction, minimum remaining coverage, contribution output, dependency versions, immutable publication, ownership, and no arbitrary executable expression.

### Required validation

    bash scripts/jules/verify.sh backend tests/unit/factors/test_composite_dsl.py tests/integration/test_factor_composite_api.py

## J1B — Add factor research and composite UI

### Metadata

- risk: medium
- depends_on: J18, J19, J1A
- references: factor specification section 4.9 items 3 and 4
- allowed_paths: frontend/src/api/factors.ts, frontend/src/types/factor.ts, frontend/src/views/Factors/, frontend/src/router/
- forbidden_paths: backend, strategies

### Objective

Add research visualizations and a structured composite editor with version, validation, contribution, exposure, sample, and warning displays.

### Required validation

    bash scripts/jules/verify.sh frontend

The editor must not provide a code or free-form formula execution box.
