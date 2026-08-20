# Phase 2 — versioned strategies and analysis profiles

## J20 — Add immutable strategy and universe persistence

### Metadata

- risk: high
- depends_on: J1A
- references: docs/01-features/功能增强-策略与回测实现规格.md sections 1.1, 1.2, and 1.7
- allowed_paths: app/models/strategy.py, app/repositories/strategy_repository.py, app/services/strategies/version_service.py, tests/
- forbidden_paths: signal evaluation, templates, frontend

### Objective

Implement owner-scoped Strategy, immutable StrategyVersion, UniverseSnapshot, and StrategySignal persistence with indexes and lifecycle rules.

### Required implementation

Support draft creation, version increment, immutable published versions, clone provenance, soft archive, checksums, factor/Skill dependency freezing, and system-template read-only ownership.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/strategies/test_versions.py tests/integration/test_strategy_repository.py

Test concurrent version creation, cross-user isolation, immutable publish, and snapshot uniqueness.

## J21 — Implement strategy DSL validator and deterministic signal engine

### Metadata

- risk: high
- depends_on: J20, J19
- references: strategy specification sections 1.3 and 1.6
- allowed_paths: app/services/strategies/validator.py, condition_tree.py, signal_engine.py, app/models/strategy.py, tests/unit/strategies/
- forbidden_paths: templates, API, frontend, backtest

### Objective

Validate and execute the whitelisted universe, condition, rank, rebalance, portfolio, execution, and risk DSL over fixed factor/universe snapshots.

### Required implementation

Reject unknown factors/operators, trees deeper than 10 or larger than 200 nodes, impossible conflicts, illegal execution timing, missing exit, and future data. Produce deterministic tie-breaking, scores, ranks, reason codes, and contributions.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/strategies/test_validator.py tests/unit/strategies/test_signal_engine.py

## J22 — Deliver the 14 system strategy templates

### Metadata

- risk: high
- depends_on: J21
- references: strategy specification section 1.4
- allowed_paths: app/services/strategies/templates/, app/migrations/, tests/unit/strategies/templates/
- forbidden_paths: user strategies, APIs, frontend

### Objective

Implement and seed all 14 versioned, read-only system templates with exact dependencies, defaults, risk rules, applicability, and warnings.

### Required implementation

Each template needs one fixture producing signals, one producing none, parameter ranges, cost/slippage defaults, minimum history, benchmark, suitable/unsuitable markets, and an idempotent seed migration.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/strategies/templates/

Assert exactly 14 active template IDs from the specification.

## J23 — Add versioned AnalysisProfile compatibility layer

### Metadata

- risk: medium
- depends_on: J20
- references: strategy specification section 1.5
- allowed_paths: app/models/analysis.py, app/models/strategy.py, app/services/analysis_profiles/, app/repositories/strategy_repository.py, tests/
- forbidden_paths: LangGraph Skill execution, frontend, strategy signals

### Objective

Persist AnalysisProfile versions and resolve either profile_id or legacy analysis parameters into one validated runtime profile.

### Required implementation

Support analysts, depth, model refs without secrets, risk preference, horizon, future Skill references, factor context limits, strategy context, debate limits, and output schema version. Reject conflicting profile and inline parameters.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/analysis_profiles/ tests/integration/test_analysis_profile_compatibility.py

## J24 — Add strategy and AnalysisProfile APIs

### Metadata

- risk: medium
- depends_on: J22, J23
- references: strategy specification section 1.8
- allowed_paths: app/routers/strategies.py, app/routers/analysis_profiles.py, app/main.py, app/services/strategies/, tests/integration/
- forbidden_paths: frontend, backtest

### Objective

Expose template discovery, user strategy CRUD/version/clone/validate/publish, signal jobs, and AnalysisProfile APIs with stable ownership and errors.

### Validation

    bash scripts/jules/verify.sh backend tests/integration/test_strategy_api.py tests/integration/test_analysis_profile_api.py

## J25 — Add strategy center, wizard, versions, and profile UI

### Metadata

- risk: medium
- depends_on: J24
- references: strategy specification section 1.9
- allowed_paths: frontend/src/api/strategies.ts, frontend/src/api/analysisProfiles.ts, frontend/src/types/, frontend/src/views/Strategies/, frontend/src/views/Settings/, frontend/src/router/, frontend/src/components/Layout/
- forbidden_paths: backend, backtest pages

### Objective

Add authenticated system-template/my-strategy views, a structured strategy wizard, dependency/validation display, version diff, publish confirmation, signal list, and AnalysisProfile settings.

### Validation

    bash scripts/jules/verify.sh frontend

No free-form executable rule editor is allowed.

