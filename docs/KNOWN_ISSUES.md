# Known issues

## Mixed-Harness real OpenAI Canary is not yet qualified

The bounded 2026-09-12 selection using PydanticAI for CoS, OpenAI Agents SDK for
Engineer and LangGraph for Verifier, all selecting `openai:gpt-5-nano`, failed
at the Engineer response boundary. The target CoS completed one real request
with 8,758 reported tokens; the Engineer's first request was reserved and then
marked unknown. The result is `PROVIDER_FAILED` with
`provider_sdk/response_policy`, not successful end-to-end delivery. No target
tool call, command evidence, patch or Verifier invocation occurred. The separate
scripted bootstrap's real Docker receipts are not target-task evidence.

The current fixed diagnostic does not distinguish SDK failed/incomplete output,
response model/terminal-state rejection, and invalid raw JSON/usage. Exact model
identity checking also rejects an alias if the provider returns a dated model
name; this is an offline hypothesis, **not the proven cause of this attempt**.
Do not weaken these checks, infer unknown usage as zero, or automatically retry.
The total invoice cannot be derived from the retained local usage records.

The launcher stopped normally and reported complete cleanup with zero outstanding
leases. The failed run and its evidence remain retained. Per-role selection
infrastructure passed its independent offline gate, but this does not qualify
the mixed-Harness path or Anthropic/Google providers. See the [selection guide](LIVE_CANARY_SELECTION.md)
and [acceptance ledger](MVP_ACCEPTANCE.md#p1-b--explicit-canary-selection-infrastructure-2026-09-12).

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
