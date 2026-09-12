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

The newer finite diagnostics distinguish SDK processing, response model/status/
error and raw JSON/usage rejection without changing validation or error classes.
They cannot retroactively identify the field rejected in this older attempt.
SDK failed/incomplete response processing shares one fixed message because raw
exception text is not inspected. Exact model identity checking still rejects an
alias if the provider returns a dated model name; this is an offline hypothesis,
**not the proven cause of this attempt**.
Do not weaken these checks, infer unknown usage as zero, or automatically retry.
The total invoice cannot be derived from the retained local usage records.

The launcher stopped normally and reported complete cleanup with zero outstanding
leases. The failed run and its evidence remain retained. Per-role selection
infrastructure passed its independent offline gate, but this does not qualify
the mixed-Harness path or Anthropic/Google providers. See the [selection guide](LIVE_CANARY_SELECTION.md)
and [acceptance ledger](MVP_ACCEPTANCE.md#p1-b--explicit-canary-selection-infrastructure-2026-09-12).

## Resolved in the current candidate: same-process Docker resume

The exact retained-sandbox restoration repair passed independent physical
acceptance on 2026-09-12: 22 Docker cases passed, with 22 ordinary cases
deselected and no failures, errors or skips. The public same-process terminal
journey now reaches verified completion after separate Engineer/Verifier
approvals and real pytest receipts. Retained and recreated conversation cases
also pass; originals change only after the existing explicit public patch apply.
The current integrated full suite passed4246/26 with independent exact-identity
review; all six static gates and the separate806-case offline adversarial gate
passed. Final artifact and GitHub delivery records are separate. This is bounded scripted-runtime Docker
evidence, not live-provider qualification; see [P1-F acceptance](MVP_ACCEPTANCE.md#p1-f--exact-docker-session-restoration-2026-09-12).

Restoration reuses only the exact persisted handle/specification and held
Git-shadow pin, rechecking identity after awaited validation. Absent retained
state follows strict restoration; conflicting state fails closed. Duplicate
creation is still rejected, with no command replay, automatic recovery or host
fallback. This does not convert old failed or uncertain Runs into resumable work.

The original failure was reproduced during the public quickstart review on
2026-09-12, against base
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

The Session then reported uncertain execution ownership. This run did not execute
the requested repair to verified completion, and no patch was applied. A successful
bootstrap alone did not expose this problem. This historical failure and the
later physical01/physical02 failures remain failures; the physical03 acceptance
is a new, separately identified run.

The separate-process `fleet run`, `fleet approve`, `fleet resume`, `fleet status`
and `fleet patch` route in the [quickstart](../README.md#7-run-your-first-task)
remains supported.
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
not live-model reliability. The separate restoration repair is qualified only
by the newer acceptance record above.
