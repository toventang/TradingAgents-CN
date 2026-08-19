# Google Jules autonomous development entry point

## Why this directory exists

The feature specifications under docs/01-features/ are intentionally comprehensive. They are too broad to be submitted to Jules as one task.

Jules works most reliably when each session is specific and scoped. Each session runs in its own Ubuntu VM and owns its own plan, logs, code changes, and branch. This directory converts the domain specifications into atomic Jules task packets with explicit dependencies and validation commands.

## Required repository configuration

In the Jules repository view:

1. Connect this GitHub repository.
2. Open Configuration → Initial Setup.
3. Enter:

       bash scripts/jules/setup.sh

4. Select Run and Snapshot.
5. Fix setup failures before dispatching feature tasks.

Do not paste secrets into the setup script or repository. Tests use fixtures.

## How to run one task

1. Start from a branch containing every task listed in depends_on.
2. Create one Jules session for exactly one task ID.
3. Use the prompt from task-manifest.json.
4. Include AGENTS.md and the task's phase file with Jules file selection when available.
5. Let Jules create its plan.
6. For guarded foundation or ledger tasks, require plan approval.
7. Review required checks and the diff.
8. Merge the PR before dispatching dependent tasks.

Never submit “implement all feature enhancements” as one session.

## Fully automatic PR mode

The Jules Sessions API supports automationMode AUTO_CREATE_PR. For low-risk tasks, use:

    {
      "prompt": "<prompt copied from task-manifest.json>",
      "title": "<task id and title>",
      "sourceContext": {
        "source": "<connected Jules source>",
        "githubRepoContext": {
          "startingBranch": "main"
        }
      },
      "requirePlanApproval": false,
      "automationMode": "AUTO_CREATE_PR"
    }

For tasks marked risk=high, set requirePlanApproval to true. Full automation means automatic execution and PR creation, not automatic merging without required checks.

## GitHub Issue mode

Jules can start from GitHub Issues labeled jules. Create one issue per task using the body from the corresponding task packet. Do not put multiple task IDs in one issue.

## Files

- AGENTS.md: repository-wide instructions automatically read by Jules.
- scripts/jules/setup.sh: Ubuntu environment setup and snapshot input.
- scripts/jules/verify.sh: stable validation entry point.
- docs/jules/task-manifest.json: machine-readable task DAG and exact session prompts.
- docs/jules/TASK_TEMPLATE.md: required packet structure.
- docs/jules/AUTOMATION.md: dispatch, dependency, PR, and recovery protocol.
- docs/jules/tasks/: detailed task packets.
- docs/01-features/: domain truth and acceptance rules.

## Source-of-truth order

1. Security, ownership, ledger reconciliation, and no-look-ahead rules in AGENTS.md.
2. The active atomic task packet.
3. Referenced sections of docs/01-features/.
4. Existing source behavior when it does not conflict with the above.

If a task cannot be completed within its declared boundary, Jules must stop with a blocker rather than expanding scope.

## Official Jules behavior used by this design

- Jules automatically reads root AGENTS.md.
- Each task runs in a short-lived Ubuntu VM.
- Repository setup scripts can be validated and snapshotted.
- Jules works best with clear, specific prompts.
- Sessions can be created with automatic PR mode.
- GitHub Issues labeled jules can start tasks.

Official references are recorded in OFFICIAL_REFERENCES.md.

