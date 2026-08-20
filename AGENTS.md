# Repository instructions for autonomous coding agents

## Purpose

This repository is TradingAgents-CN. The primary product is:

- FastAPI backend in app/
- LangGraph trading-analysis kernel in tradingagents/
- Vue 3 frontend in frontend/
- MongoDB and Redis persistence

cli/ and web/ are legacy-compatible interfaces. Do not extend them unless the active task explicitly requires it.

## Read before changing code

For the feature-enhancement program, read in this order:

1. docs/jules/README.md
2. The single task section named by the task prompt under docs/jules/tasks/
3. Only the domain specification files listed in that task's references
4. Existing source and tests in the task's declared scope

The long files under docs/01-features/ are domain specifications, not a request to implement everything in one session.

## Task boundary

- Implement exactly one Jules task ID per session.
- Do not begin dependent or neighboring tasks.
- Respect allowed_paths and forbidden_paths in the task packet.
- If required dependencies are not present in the starting branch, stop and report BLOCKED_DEPENDENCY.
- If the specification is internally inconsistent in a way that changes financial behavior, permissions, data retention, or public API contracts, stop and report DECISION_REQUIRED.
- Do not silently simplify a required behavior.

## Preserve user and upstream work

- Inspect git status before editing.
- Existing changes are not yours. Do not reset, discard, overwrite, or reformat unrelated files.
- Never use git reset --hard, destructive checkout, broad deletion, or repository-wide formatting.
- Keep diffs focused. No opportunistic refactors.

## Environment

Jules runs in Ubuntu. Initialize the repository with:

    bash scripts/jules/setup.sh

The setup script intentionally does not create .env, start external services, or require API keys.

Never depend on real LLM, market-data, email, MongoDB cloud, or broker credentials in unit tests. Use deterministic fixtures and fakes.

## Validation commands

Activate Python first:

    source .venv/bin/activate

Run import validation:

    bash scripts/jules/verify.sh imports

Run targeted backend tests:

    python -m pytest -c tests/pytest.ini <test-paths> -q

Run frontend type and build validation:

    bash scripts/jules/verify.sh frontend

Run the exact commands in the active task packet. A task is not complete when required checks are skipped.

Do not use yarn lint as a check: the current script includes --fix and can mutate unrelated files.

## Architecture rules

- Routers validate/authenticate and delegate. Do not place new domain logic directly in routers.
- New large features go in focused packages under app/services/, not in simple_analysis_service.py, config_service.py, or app/routers/paper.py.
- Every private resource must be scoped by the authenticated user_id.
- New stock identity uses the pair market + symbol. Legacy code, stock_code, and stock_symbol are compatibility inputs only.
- Long-running work must use the durable domain-task infrastructure once it exists. Do not add new FastAPI in-process background jobs.
- Published factor, strategy, Skill, and ruleset versions are immutable.
- LLMs explain structured facts. They do not compute ledger balances, factor values, fills, fees, returns, or backtest metrics.
- Do not use eval, exec, arbitrary user code, dynamic imports from user input, or unrestricted external tools.

## Financial correctness

- Prevent look-ahead and survivorship bias.
- Financial data becomes visible from its publication timestamp, not its report period.
- Signals created from a daily close execute no earlier than the next legal execution point.
- Backtest and paper-trading cash, orders, lots, positions, and fees must reconcile.
- Stale, invalid, or unavailable data cannot trigger automated buying.
- A-share T+1, lot size, suspension, price limits, and date-versioned fees must be enforced where required.
- Persist data versions, timestamps, rule versions, and evidence references for reproducibility.

## Security and privacy

- Resolve the real user from authentication. Never use a hard-coded admin.
- Do not log JWTs, API keys, complete authorization headers, or secret prefixes.
- Never add a real secret or credential to the repository.
- Tests must verify cross-user isolation for every new private resource.
- Automated simulation must never connect to a real broker.

## Database changes

- Add explicit indexes for ownership, state scans, and resource/date queries.
- Migrations must be idempotent, batchable, resumable, and have a verification step.
- Do not physically remove legacy fields during this program.
- Never put TTL indexes on ledgers, trades, backtests, audit records, or published definitions.

## Tests

For every behavior:

- Add deterministic unit tests.
- Add repository/API integration tests when persistence, ownership, state transitions, or idempotency changes.
- Use hand-calculated fixtures for financial formulas and ledgers.
- Add negative tests for permission boundaries and invalid state transitions.
- Do not weaken, delete, skip, or rewrite an existing failing test merely to make a task pass.

If an unrelated baseline test fails, document the exact command and failure separately. The task's new and directly related tests must pass.

## Frontend

- Use existing Vue 3, Element Plus, Pinia, Axios, and routing conventions.
- Add matching TypeScript types and API clients before page integration.
- Use server pagination for large factor, trade, event, and snapshot datasets.
- Do not expose secrets or full sensitive payloads in browser logs.
- Every new protected page must use route authentication and be reachable from the intended navigation.

## Completion report

The final Jules summary must include:

1. Task ID and outcome
2. Files changed
3. Database/API compatibility notes
4. Tests run with exact commands and results
5. Checks not run and why
6. Remaining risks or blockers
7. Confirmation that no later task was started

Never claim the entire enhancement program is complete after finishing one task.
