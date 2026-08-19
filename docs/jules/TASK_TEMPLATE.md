# Jules atomic task template

Use this full form when adding or splitting a task. The 57 program packets may omit a repeated section only when the same requirement is inherited explicitly from AGENTS.md: depends_on is the precondition, allowed/forbidden paths define scope, the referenced domain specification defines public and edge contracts, and the AGENTS.md completion/stop rules apply to every task.

## Metadata

- task_id:
- title:
- risk: low | medium | high
- depends_on:
- parallel_with:
- references:
- allowed_paths:
- forbidden_paths:

## Objective

One observable outcome. Do not combine multiple independent outcomes.

## Preconditions

Concrete code, schema, migration, or test artifacts that must already exist in the starting branch.

## Required implementation

Numbered, exhaustive behavior for this task only.

## Public contracts

API, Pydantic, TypeScript, database, event, or state contracts created or changed.

## Failure and edge cases

Explicit negative behavior, retry rules, idempotency, permissions, and invalid states.

## Tests to add

Exact test modules and cases.

## Required validation

Commands that must pass. Commands must be runnable without real secrets or network services unless the task explicitly provisions containers.

## Out of scope

Named adjacent work Jules must not start.

## Completion evidence

Files, commands, and compatibility statements required in the final summary.

## Stop conditions

Conditions requiring BLOCKED_DEPENDENCY or DECISION_REQUIRED.
