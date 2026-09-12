# Known issues

## Interactive Docker resume can fail in the same Session

Reproduced during the public quickstart review on 2026-09-12, against base
`3bcf735` plus the pre-existing local canary-development changes. No production
code was changed by the documentation review.

Environment: macOS, Python 3.14.6, local Colima Docker, the packaged runner v1
image, the public learning canary, `fake` runtime and Safe permissions.

Reproduction:

1. Complete public Docker initialization for the packaged learning project.
2. Enter `fleet chat . --review-plan` and submit the division-by-zero repair.
3. Inspect/approve the plan with `/plan`, `/plan approve`, `/confirm`, `/resume`.
4. When the Engineer command pauses, inspect and approve it with `/approve`,
   `/approve --once`, `/confirm`, then `/resume` in the same process.

Observed result:

```text
SANDBOX_CREATION_FAILED
Docker sandbox preparation is already active for this identity.
Terminate the existing logical sandbox before preparing it again.
```

The Session then reports uncertain execution ownership. This run did not execute
the requested repair to verified completion, and no patch was applied. A successful
bootstrap alone did not expose this problem. The root cause and production fix
are outside this documentation change; do not claim the Session journey passed.

Use the separate-process `fleet run`, `fleet approve`, `fleet resume`, `fleet status`
and `fleet patch` route in the [quickstart](../README.md#7-run-your-first-task).
Do not use a repeated original task or broad cleanup to force the failed Session
to continue. For an already affected task, stop its original owner, inspect the
exact run and follow [documented recovery](USER_GUIDE.md#运行资源恢复). Recovery
terminates and cleans the old run; it does not resume uncertain work.

During this reproduction, the original Session exited before a separate
`fleet recover <run-id> --confirm-owner-stopped --json` call. Recovery marked the
failed run terminal and returned two recovered lease IDs with zero outstanding
leases. The failed run and its evidence were retained.

The replacement CLI quickstart was subsequently executed in a fresh learning
project/state: two explicit allow-once approvals, two successful resume commands,
`ready_for_review`, `verified_complete=true`, and no proof gaps. Engineer and
Verifier each produced a separate real-Docker exit-zero pytest receipt; the source
remained unchanged until explicit patch apply, which then succeeded. The runtime
budget recorded zero model requests. This verifies the scripted learning route,
not live-model reliability or a fix for the Session issue.
