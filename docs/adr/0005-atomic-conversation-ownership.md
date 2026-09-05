# ADR 0005: Atomic conversation ownership without provider-history replay

Status: accepted in Phase 5 on 2026-09-05; exact gates and retained failure/fix evidence are tracked by the persistent-chat ExecPlan.

## Context

The product exposes one persistent Chief of Staff but executes fresh bounded specialists. A CLI restart must recover a conversation's exact Run, approval and budget without treating prior model prose as execution authority. Attaching a turn after awaiting a workflow could persist its identity after model/tool side effects. A chat-only process lock would also leave public `fleet resume` as an alternate unguarded entry point.

## Decision

Register the root Run, turn, immutable context/config/budget binding and execution claim in one SQLite transaction at the existing workflow registration boundary, after preflight and before budgeting or model invocation. Use a typed optional submission sideband and private shared connection-local Run helpers, not a second workflow path. A duplicate submission returns its original Run with no claim. The shared WorkflowEngine validates conversation ownership at start/resume and each role invocation, independently of CLI selection and graph ownership.

Claims are non-expiring. Only orderly supported checkpoints release ownership; uncertain persistence outcomes require explicit operator-stopped recovery with exact fencing and root/descendant cleanup. Cancellation binds its original Run/task before scheduling or waiting and never reselects a newer turn. A terminal outcome already persisted is preserved while reconciling its clean fenced turn.

Persist bounded typed summaries and content-addressed artifact references, not raw SDK history. CoS receives at most eight settled turns and 32 KiB of context. Read-back validates actual bounded artifact bytes and registered secrets; summaries cannot grant tools, change verification strength or imply patch application. Slash commands remain deterministic application operations.

## Alternatives

- Post-hoc Run attachment: rejected because it can occur after side effects.
- Process-local chat mutex: rejected because another process or ordinary resume bypasses it.
- Time-expiring execution claims: rejected because elapsed time does not prove the owner stopped or the request was not dispatched.
- Full provider message history: rejected as the default because it adds unbounded secret/context exposure and couples persistence to one harness without proving safe replay.
- Broad prepare/execute workflow refactor: unnecessary for this bounded slice; retain one existing preflight and registration path.

## Consequences

One conversation admits one active turn. Restart preserves exact original submissions, approvals and cumulative budgets, but unknown-owner work is not automatically resumed. New goals are refused while a prior turn is waiting/running/recovering; there is no hidden queue. History truncation and evidence limitations are visible. Migration 7 is transactional and forward-only; older binaries reject the newer state. POSIX terminal/pipe input is supported with bounded buffering; unsupported input contexts fail clearly. Local OS-account access to state remains in the trusted computing base.
