# Phase 5 — application runtime AI Skills

These are TradingAgents-CN runtime Skills, not Jules or Codex instruction files.

## J50 — Add Skill manifest, registry, assignment, and tool permissions

### Metadata

- risk: high
- depends_on: J23
- references: docs/01-features/功能增强-预警与AI-Skill实现规格.md sections 2.1–2.5 and 2.9–2.10
- allowed_paths: app/models/skill.py, app/repositories/skill_repository.py, app/services/skills/, tradingagents/skills/registry.py, tradingagents/skills/tool_registry.py, tests/unit/skills/
- forbidden_paths: built-in Skill prompts, LangGraph integration, UI, arbitrary plugin loading

### Objective

Implement immutable Skill manifests, dependency validation, assignment precedence, budgets, cache policy, and a closed tool-permission registry without executing Skills yet.

### Required implementation

Reject dynamic code, unknown URLs/tools, dependency cycles, privilege escalation, illegal budgets, and mutation of published versions. Resolve system-disabled → strategy-required → AnalysisProfile → user-default → system-default precedence.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/skills/test_manifest.py tests/unit/skills/test_registry.py tests/unit/skills/test_assignments.py

## J51 — Implement deterministic built-in Skills

### Metadata

- risk: high
- depends_on: J50, J19
- references: Skill specification section 2.6
- allowed_paths: tradingagents/skills/builtins/, tradingagents/skills/models/, tests/unit/skills/builtins/
- forbidden_paths: LLM calls, graph integration, write tools

### Objective

Implement schema-first deterministic Skills for factor_snapshot_summary, technical_regime, valuation_assessment, financial_quality, growth_sustainability, sentiment_aggregation, portfolio_risk_plan, and strategy_explainer where their output is deterministic.

### Required implementation

Each Skill needs input/output models, evidence refs, warnings, budgets, golden fixtures, invalid-input tests, and no side effects.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/skills/builtins/

## J52 — Implement LLM and composite Skill executor plus remaining built-ins

### Metadata

- risk: high
- depends_on: J50, J51
- references: Skill specification sections 2.4, 2.6, and 2.7
- allowed_paths: tradingagents/skills/executor.py, composer.py, builtins/, app/services/skills/execution_service.py, tests/unit/skills/
- forbidden_paths: LangGraph nodes, API, UI, paper trading

### Objective

Execute llm_reasoning and composite Skills with validated structured inputs/outputs, read-only tool whitelist, timeout/call/token budgets, one schema-repair attempt, caching, evidence, and failure policies.

### Required implementation

Implement news_event_classifier, bull_case_builder, bear_case_builder, backtest_interpreter, trade_loss_attribution, missed_upside_attribution, and learning_proposal_generator schemas/prompts. Test with fake LLMs only.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/skills/test_executor.py tests/unit/skills/test_composite.py tests/unit/skills/test_builtin_schemas.py

## J53 — Integrate resolved Skills into LangGraph

### Metadata

- risk: high
- depends_on: J52, J23
- references: Skill specification section 2.8
- allowed_paths: tradingagents/graph/, tradingagents/agents/, tradingagents/skills/, app/services/simple_analysis_service.py, app/models/analysis.py, tests/
- forbidden_paths: paper/backtest execution, Skill UI, unrelated provider rewrites

### Objective

Resolve the AnalysisProfile at graph construction, execute declared Skills per role, store skill_results and execution IDs, inject bounded structured summaries, and preserve legacy behavior when runtime Skills are disabled.

### Validation

    bash scripts/jules/verify.sh imports
    bash scripts/jules/verify.sh backend tests/unit/skills/test_graph_integration.py tests/test_tradingagents_runtime_settings.py

Test schema failure isolation, disabled dependency, exact version trace, and legacy-disabled compatibility.

## J54 — Add Skill catalog, version, test, assignment, and execution APIs

### Metadata

- risk: medium
- depends_on: J53
- references: Skill specification section 2.11
- allowed_paths: app/routers/skills.py, app/main.py, app/services/skills/, tests/integration/test_skill_api.py
- forbidden_paths: frontend, arbitrary code upload

### Objective

Expose owner-scoped catalog/detail/draft/validate/test/publish/clone, assignment, and execution-history APIs with redaction and quotas.

### Validation

    bash scripts/jules/verify.sh backend tests/integration/test_skill_api.py

## J55 — Add Skill catalog and configuration UI

### Metadata

- risk: medium
- depends_on: J54
- references: Skill specification section 2.12
- allowed_paths: frontend/src/api/skills.ts, frontend/src/types/skill.ts, frontend/src/views/Skills/, frontend/src/views/Settings/, frontend/src/router/, frontend/src/components/Layout/
- forbidden_paths: backend, code upload/editor

### Objective

Add authenticated catalog, dependency/tool/budget display, clone/configure/test/publish, scope assignments with effective-source explanation, and redacted execution history.

### Validation

    bash scripts/jules/verify.sh frontend

