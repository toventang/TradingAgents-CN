# Jules dispatch, PR, and recovery protocol

## 1. Operating model

Each Jules session is an isolated unit of work with its own VM and branch. The enhancement program therefore runs as a dependency-ordered sequence of atomic sessions, not as one long chat.

The machine-readable source is task-manifest.json. Detailed behavior is in the referenced phase file.

Default policy:

- One task per session.
- Starting branch contains every merged dependency.
- Maximum automatic concurrency is one.
- Jules creates a PR automatically.
- CI must pass before merge.
- The next dependent task is not dispatched before merge.

Concurrency one is deliberate: many tasks touch shared models, registries, and generated contracts. Increase concurrency only after proving allowed paths do not overlap and defining a merge/rebase order.

## 2. Preflight

Before the first session:

1. Connect the GitHub repository in Jules.
2. Configure Initial Setup as:

       bash scripts/jules/setup.sh

3. Run and Snapshot successfully.
4. Merge AGENTS.md, docs/jules/, scripts/jules/, and the domain specifications into the starting branch.
5. Run:

       python scripts/jules/validate_manifest.py

6. Confirm required branch protection and CI checks.
7. Ensure the GitHub label jules exists if Issue mode will be used.

## 3. Readiness algorithm

A task is ready when:

1. It has not already completed.
2. Every depends_on ID exists.
3. Every dependency PR is merged into the selected starting branch.
4. No open PR is already implementing the same task ID.
5. The environment snapshot is current for the dependency lockfiles.

Never infer readiness only from a Jules session saying “completed”; use the merged Git commit or merged PR.

## 4. Sessions API

Create one session using the official endpoint POST /v1alpha/sessions.

Low/medium-risk request shape:

    {
      "prompt": "<task prompt from task-manifest.json>",
      "title": "J17 Add factor backend APIs",
      "sourceContext": {
        "source": "<Jules connected source>",
        "githubRepoContext": {
          "startingBranch": "main"
        }
      },
      "requirePlanApproval": false,
      "automationMode": "AUTO_CREATE_PR"
    }

High-risk request shape changes only:

    "requirePlanApproval": true

High-risk includes authentication, durable task state, financial formulas, point-in-time behavior, ledgers, fills, automated exits, AI learning, migrations, and deployment.

Do not put JULES_API_KEY in this repository. Provide it only to the external dispatcher environment.

## 5. Plan approval

For requirePlanApproval tasks, verify the proposed plan:

- Names only the active task ID.
- Respects allowed/forbidden paths.
- Includes every required test.
- Does not silently weaken a security or financial rule.
- Does not begin a dependent task.
- Includes migration verification when required.

Reject or revise plans that say “implement a simplified version,” “mock the backend,” “skip tests,” or “handle later” for required behavior.

## 6. PR contract

PR title:

    [J17] Add factor backend APIs

PR description must contain:

- Task ID.
- Depends-on commits/PRs.
- Scope completed.
- Files changed.
- API/database compatibility.
- Exact commands and results.
- Skipped checks and reasons.
- Risks/blockers.
- Confirmation no adjacent task was started.

The PR must contain code and tests for only one task.

## 7. Merge gate

Automatic merge is permitted only when all are true:

- The task does not require an unresolved decision.
- Required plan approval occurred.
- Required CI and task validation commands pass.
- New tests exercise positive, negative, ownership, and edge behavior required by the packet.
- No unrelated files changed.
- No secret scanning alert.
- No unresolved review finding.
- Migration is idempotent and verified when applicable.

Financial and migration tasks should retain a human approval gate even when Jules creates the PR automatically.

## 8. Failure categories

Jules must use one of:

- BLOCKED_DEPENDENCY: starting branch lacks a required artifact.
- DECISION_REQUIRED: a product/security/financial contract is ambiguous.
- ENVIRONMENT_FAILURE: setup or dependency installation fails before task work.
- BASELINE_FAILURE: an unrelated required baseline check already fails.
- TASK_FAILURE: implementation or directly related tests fail.

## 9. Recovery

### Environment failure

Fix scripts/jules/setup.sh in a dedicated maintenance task, run and snapshot again, then retry the same task from the unchanged starting branch.

### Baseline failure

Compare with docs/jules/BASELINE.md. If new, create a separate prerequisite bug task. Do not weaken the active task's tests.

### Task failure

Send focused feedback in the same Jules session if its branch is still usable. Otherwise close the PR, create a new session for the same task ID, and start from the last merged dependency commit.

### Merge conflict

Do not ask Jules to solve conflicts by discarding either branch. Rebase the later task on the newly merged branch, rerun all required checks, and regenerate the PR.

### Partial feature

Do not mark the task complete. Either continue the same session within its existing scope or create a follow-up task ID that explicitly becomes a dependency of downstream tasks.

## 10. GitHub Issue mode

Jules can start work when a GitHub Issue has the label jules.

Use the issue form in .github/ISSUE_TEMPLATE/jules_task.yml:

1. Choose exactly one manifest task ID.
2. Paste its exact prompt.
3. Name dependency PRs.
4. Add label jules.
5. Do not label the issue until dependencies are merged.

## 11. Program completion

J82 may declare the program complete only when:

- Every task J00–J82 in the manifest has a merged PR or an explicitly approved superseding task.
- The deterministic end-to-end fixture passes.
- Security, performance, migration, rollback, and rollout evidence exists.
- The Definition of Done in the development total plan is fully evidenced.

No individual Jules session before J82 may claim the full program is complete.

