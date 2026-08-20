# Phase 7 — deterministic review, counterfactual analysis, and controlled learning

## J70 — Implement deterministic closed-trade attribution

### Metadata

- risk: high
- depends_on: J64
- references: automation specification section 10
- allowed_paths: app/models/automation.py, app/services/automation/attribution_engine.py, app/repositories/automation_repository.py, app/workers/handlers/trade_attribution.py, tests/unit/attribution/
- forbidden_paths: LLM calls, counterfactual future windows, learning proposals, UI

### Objective

Build TradeReviewInput, hand-calculated MAE/MFE, timing/execution/market/industry comparisons, evidence timeline, and deterministic standard cause candidates.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/attribution/test_metrics.py tests/unit/attribution/test_cause_candidates.py

Future events must never be represented as information known at entry.

## J71 — Implement missed-upside observation and legal counterfactuals

### Metadata

- risk: high
- depends_on: J70
- references: automation specification section 11
- allowed_paths: app/services/automation/counterfactual_engine.py, app/repositories/automation_repository.py, app/workers/handlers/, tests/unit/attribution/
- forbidden_paths: LLM explanations, learning, UI

### Objective

Track 5/10/20/60 trade-day post-exit paths, benchmark excess, tradeability, threshold/severity, window-end and legal alternative exits without treating the future high as realizable profit.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/attribution/test_counterfactual.py

## J72 — Add evidence-bound AI trade-review execution

### Metadata

- risk: high
- depends_on: J71, J53
- references: automation specification sections 10.3 and 11.4
- allowed_paths: app/services/automation/review_service.py, tradingagents/skills/builtins/, app/workers/handlers/trade_attribution.py, tests/
- forbidden_paths: strategy mutation, ledger mutation, learning application

### Objective

Use versioned review Skills to select standard cause codes, weights, confidence, evidence, counter-evidence, controllability, and insufficient-evidence warnings without altering deterministic facts.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/attribution/test_ai_review.py tests/integration/test_trade_review_worker.py

Use fake LLM output, schema attacks, unsupported claims, and post-exit event tests.

## J73 — Implement controlled learning proposals and validation flow

### Metadata

- risk: high
- depends_on: J72, J36
- references: automation specification section 12
- allowed_paths: app/services/automation/learning_service.py, app/models/automation.py, app/repositories/automation_repository.py, app/routers/learning_proposals.py, tests/
- forbidden_paths: automatic publish, mutation of active Campaigns, arbitrary parameter paths

### Objective

Aggregate reviews, enforce evidence/sample thresholds and tunable whitelist, create reviewable parameter diffs, generate validation backtests, and create a new strategy draft only after explicit approval.

### Validation

    bash scripts/jules/verify.sh backend tests/unit/learning/ tests/integration/test_learning_proposal_api.py

Test fewer than 30 trades, out-of-range changes, partial acceptance, failed validation, and unchanged published/active versions.

## J74 — Add review and learning UI

### Metadata

- risk: medium
- depends_on: J73
- references: automation specification sections 15.3–15.4
- allowed_paths: frontend/src/api/tradeReviews.ts, frontend/src/api/learningProposals.ts, frontend/src/types/, frontend/src/views/TradeReviews/, frontend/src/views/Learning/, frontend/src/router/, frontend/src/components/Layout/
- forbidden_paths: backend, automatic acceptance/publish

### Objective

Show selection→entry→exit→observation charts, evidence/counter-evidence, cause aggregation, legal counterfactuals, sample gates, proposal diffs/tradeoffs, per-change review, validation results, and separate create-draft/publish actions.

### Validation

    bash scripts/jules/verify.sh frontend

## J75 — Add deterministic full-program end-to-end fixture

### Metadata

- risk: high
- depends_on: J65, J74
- references: automation specification section 17.6 and docs/01-features/功能增强-开发总纲与实施清单.md Definition of Done
- allowed_paths: tests/e2e/, tests/fixtures/enhancement_program/, scripts/jules/verify.sh, docs/jules/BASELINE.md
- forbidden_paths: production behavior unless fixing a demonstrated program bug in a separate follow-up task

### Objective

Automate the fixed 20-stock/120-day path from factors through strategy, backtest, alert, Campaign, exits, attribution, observation, and learning draft with no external services.

### Validation

    bash scripts/jules/verify.sh backend tests/e2e/test_enhancement_program.py

The test must prove traceability, ledger reconciliation, no pre-activation fill, no cross-user data, and no automatic strategy publication.

