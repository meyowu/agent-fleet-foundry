# ADR 0003: Account for physical runtime attempts in the control plane

- Status: Accepted for the Phase 5 budget/evidence slice; complete Phase 5 acceptance remains pending
- Date: 2026-09-05

## Context

An approval pause reconstructs a runtime invocation. Provider libraries may retry structured output inside one invocation. Counting only successful final output resets allowances on resume and loses usage from failed, timed-out or cancelled responses. A role's configured `maxSteps` is not an effective ceiling if each physical retry receives it anew. Parallel agents must not independently spend the same remaining allowance.

## Decision

Persist immutable run budget limits and physical attempt/request/tool reservations in explicit SQLite tables. The application opens a new attempt for each invocation, bound to the exact run/task/logical-agent/stage/iteration. The logical agent keeps its step ceiling across approval resumes; a repair uses a new Engineer identity and consumes the same run budget. An internal child run may later share the explicitly bound parent's budget owner without sharing its authorization grants.

Pass a trusted accounting sideband through the project-owned runtime port. The normal composition root always supplies it; adapter conformance tests may omit it. PydanticAI's wrapped physical `request` reserves allowance before provider dispatch, including internal structured-output retries. It records normalized usage immediately after a response, before output validation or tool execution. The complete tool batch is validated and charged before the first execution. A fake invocation charges a simulated step and tool attempts but does not invent provider usage.

Duplicate reservation keys do not authorize another request or tool batch. Repeated exact settlement is idempotent. A dispatched request with an unknown outcome keeps its reservation and prevents further dispatch pending recovery; it is never assumed free. Older runs without a reliable ledger are explicitly `legacy_unknown`, not backfilled with zero usage, and cannot continue an unaccounted active invocation.

The application bounds active invocation time separately from time spent waiting for human approval. Limits and remaining usage come from the durable control plane, not model messages, role prose or an approval. Provider-reported token limits are not guaranteed monetary pre-spend caps: responses may overshoot, costs may be absent, and incomplete token reports retain uncertainty rather than refunding allowance. Final status exposes these limitations. A strict shared parallel time-allocation claim requires the graph scheduler's later acceptance evidence.

## Consequences

- Usage remains inspectable after errors and restart without persisting raw prompts, provider message histories, SDK objects or credential values.
- Approval cannot reset the run budget or the paused logical role's step counter.
- Unknown provider outcomes fail closed even when replay would be convenient.
- SQLite transactions serialize reservations; successful output is not the accounting authority.
- Existing role/tool/permission/sandbox boundaries are unchanged. Accounting cannot authorize any action.
- The default runtime continues to expose separate actual provider usage, simulated steps, reserved allowances and unknown outcomes.

## Rejected alternatives

- Count only final `AgentInvocationResult.usage`: loses failed and paused attempts.
- Store full provider history: couples persistence to an SDK, creates sensitive-data and size risks, and does not itself enforce aggregate limits.
- Reset counters on user approval: converts permission into new execution budget and permits unbounded continuation.
- Refund timed-out requests: a timeout does not prove the provider did no work or incurred no usage.
- Let each parallel worker keep independent totals: concurrent agents could each spend the same remaining run allowance.
