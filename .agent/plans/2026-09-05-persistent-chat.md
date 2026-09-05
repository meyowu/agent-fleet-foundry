# Persistent bounded CoS conversation and responsive CLI

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log and Outcomes. It implements Milestone 3 of `2026-09-05-adaptive-workflow-chat.md`; the parent MVP plan remains the release and final GitHub authority.

## Purpose and user-visible result

A user runs `fleet chat .`, gives CoS a goal, sees concise stage/approval progress, inspects the resulting evidence and returns to the same conversation after restarting the CLI. The user does not manage individual agents. Slash commands are deterministic control-plane operations, not prompts asking a model to authorize itself.

```text
fleet chat .
> Fix the validation behavior and prove it with the reviewed tests.
> /status
> /approve <exact-request-id> --once
> /resume
> /artifacts
> /exit
```

`fleet chat . --message "Explain the current validation path" --json` offers the same persisted journey without an interactive terminal. Existing explicit patch show/apply commands remain the patch-review surface.

## Scope

### In scope

- Project-bound durable conversations, summaries, exact root Run links, submission idempotency and non-reclaimable execution ownership.
- Bounded recent context for CoS, never whole repositories, raw SDK histories, automatic budget resets or model-controlled authority.
- Line-oriented asynchronous input, event-driven compact progress, required slash commands, exact approval/deny/resume helpers, noninteractive message/JSON mode and explicit conversation selection.
- Cancellation and exit that await owned work before resource cleanup, including existing non-graph workflows.
- Reconstruction, cross-project/corruption/duplicate-submit tests, subprocess CLI E2E and a separately gated real-Docker chat journey.

### Out of scope

- Operational FleetPatch proposal/apply/rollback (Phase 6), external tools/providers, background daemon, web UI, arbitrary graph changes or full-screen TUI.
- Raw provider prompt/history retention. Default conversation history is bounded summaries and authoritative references. Existing Run.goal remains the one stored current user goal.
- Silent approval, trust changes, patch application, new credentials, model selection or license decisions.

## Current repository state

Phase 5 Milestone 1 is committed as `ab28aaa`. Milestone 2 implements durable adaptive graphs and is running final acceptance; **no chat source implementation starts before its acceptance passes**. The current source has migration 6, 55 public schemas and all five workflow strategies. `WorkflowEngine.start` validates repository/project/configuration/runtime/credential/sandbox, constructs Run, then calls `StateStore.create_run` immediately before budget initialization and the first CoS invocation. `SqliteStateStore.create_run` atomically inserts the row and run.created event. Chat must bind at this exact registration boundary, not after awaiting a finished run.

`WorkflowEngine.resume` already refuses public internal-child control and fences graph continuation ownership. Ordinary direct/single/pair runs have no cross-process conversation owner. ResourceService retains cleanup across cancellation, but cancelling a plain workflow coroutine does not by itself finalize its Run and all leases. Recovery currently recognizes uncertain graph owners, not conversation owners. CLI presentation is thin and uses Typer/Rich with stable JSON envelopes.

## Security impact

All existing permission, credential, sandbox, artifact and graph invariants remain mandatory. A conversation is context and coordination identity, not a capability grant. The root Run continues to own its exact task, approvals and budget; graph children keep their independent bindings. Only the current user can choose approval duration or patch application.

Resolve only the project's explicitly registered runtime credential during the existing preflight. Register its value with the shared redactor before any new conversation turn/context persistence or model call. Validate and scan every stored/context record before use; never persist credential references/values or SDK messages in conversation records. Known secret material is rejected from proposed context/summaries, and typed public errors must not retain raw exception context.

One conversation may have one active turn. Concurrent identical submissions create one Run; only the execution-owner CAS winner can invoke CoS. Public `fleet resume <run>` must enforce the same authoritative conversation binding, not bypass a chat-only lock. Mutable Run display fields are not the sole ownership authority. Claims never expire into a right to replay. Unknown owners require explicit operator-stopped recovery.

## Proposed design

### Domain and persistence

Add `domain/conversation.py`, `ports/conversation.py`, a SQLite conversation adapter and transactional migration 7. Use dedicated prefixed conversation/turn IDs and frozen strict UTC/bounded schemas. Exact names/signatures are frozen in this plan before assigning implementation writers.

Conversation records bind project ID, repository identity, revision, sequence and active turn. Turn records bind conversation/project/sequence, submission key/hash, one root Run, immutable Run/config/budget binding, frozen compact context/hash, user/result summaries, status and revision. Separate claim rows retain generation, opaque owner token and release/fence history. Unique constraints cover conversation/submission, conversation/sequence and Run ownership; a partial unique constraint limits active turns.

Submission uses a typed optional `ConversationSubmission` on the trusted `WorkflowEngine.start` entry point and an injected ConversationStore. After the existing full preflight, replace only the Run registration step when a submission exists. `register_turn_run` performs one SQLite transaction creating the exact Run, run.created event, turn/context/summary, immutable binding and execution claim. It returns whether this caller created/owns the execution; identical duplicate submission returns the existing binding without a claim and skips budget/model/resource execution. Different content under the same submission key fails. A new key while another turn is active fails.

Reuse a narrow connection-local Run insertion/event helper extracted from the existing SQLite adapter; do not call StateStore.create_run inside a separate adapter transaction or copy the workflow's policy checks. Authority-bearing conversation reads must cross-check SQL and JSON identity/status columns and immutable initialization receipts; do not add a weaker getter than graph/budget adapters. No application-facing generic transaction API is needed.

The registration transaction follows runtime/credential preflight so secret scanning is ready before turn persistence. The existing start flow remains the only place deciding runtime, sandbox, base/config and effective budget. A large prepare/execute workflow split is an alternative, not required for this bounded integration.

### Ownership, lifecycle and restart

The conversation store exposes an authoritative `binding_for_run` that detects mismatched/deleted bindings when registration receipts declare one. Workflow resume acquires the exact conversation turn's next owner generation before any asynchronous resume effect; graph roots also retain their existing graph continuation claim. Ownership losers cannot fail or clean the winner's Run. A shared lifecycle wrapper settles/releases the turn on orderly approval pause, delivery or terminal failure, deriving its outcome from the validated Run/evidence rather than an assistant summary.

An approval pause keeps the same active turn and Run but releases its execution claim. New goals remain blocked; approval plus `/resume` or the normal resume command reuses the same budget and exact role checkpoints. Graph WAITING_FOR_CHILDREN is also a waiting conversation turn, not a new parent approval. A READY_FOR_REVIEW Run is a delivered conversation result; it is not permission to apply a patch.

The registration/first-dispatch gap is deliberately conservative: a crash after an owner claim, even before visible work, is not automatic replay authority. The CLI shows exact Run/conversation recovery instructions. Extend explicit stopped-owner recovery to conversation-owned CREATED/PAUSED/WAITING states with retained claims, atomically fence the turn, fail/abandon the exact Run and clean its resources/graph descendants. Reconcile conversation history only from verified terminal Run state, cleanup and recovery receipts; do not infer an old process stopped from elapsed time.

Cancellation first cancels and awaits the execution task owned by this process, allowing runtime/process cleanup to settle, then invokes exact cancellation/resource services and records the turn fence/result. No new turn starts while cleanup or an uncertain owner is unresolved. `/exit`, EOF and Ctrl-C must not leave a silently running background task. External cancellation/recovery is still exact and must not clean unrelated conversations/runs.

### Bounded context and retention

Default durable conversation history stores concise user/result summaries and Run/artifact references; full user goal already lives once in Run.goal. Do not store provider histories or tool transcripts as conversation messages. Proposed ceilings are a 16 KiB current message, 2 KiB user summary, 4 KiB result summary, eight recent settled turns, 32 KiB total selected context and 1,000 turns per conversation. Reject oversized input; explicitly report summary truncation rather than silently changing the executed goal. At capacity, create/select another conversation.

Freeze selected context and its covered sequence/hash when the turn is registered. Context consists of deterministic summaries plus exact same-project run/status/assurance/artifact references; no path-selected file loading or raw whole-run log dump. CoS receives it only under `AgentInvocation.input["conversation_context"]` as untrusted data. The normal scoped TaskSpec/criteria carry the resulting complete goal to workers; context cannot carry a permission token or choose an execution boundary.

### CLI and application service

Add an application ConversationService for project/conversation selection, bounded context, submission/resume/cancel and read-only status/artifact/permission projections. Add a dedicated CLI chat module with an injectable input/output boundary and asynchronous line handling; business rules remain in services.

`fleet chat [PATH]` reopens the selected project's recent conversation, with explicit `--conversation <id>` and `--new` alternatives. `--message` plus `--json` is the noninteractive mode; expose a bounded explicit submission key for safe automation retries. No mandatory model/provider choice is introduced. Existing local-unsafe confirmation remains explicit for every execution-bearing entry point.

Implement `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, `/exit`; deterministic `/approve <id> --once|--run|--always --scope project`, `/deny <id>` and `/resume` reuse existing exact services. The selected conversation/run and its child graph constrain request IDs; a foreign request cannot be approved accidentally through a selected chat. Unknown commands fail locally without contacting a model. Patch review/application stays with existing explicit CLI commands.

While a run is active, accept inspection/cancel input without waiting for model completion; reject additional natural-language submissions rather than creating a hidden queue. Progress displays only new bounded recorded stage/approval/result events, with a cursor; no raw prompts or unbounded events. Test actual pipe/terminal behavior. Do not use an uncancellable background `input()` thread that can prevent clean process exit; supported POSIX asynchronous pipe/TTY handling may fail clearly on unsupported platforms pending Phase 7 evidence.

## Public contracts

### Frozen implementation contract (2026-09-05)

The graph source/test freeze passed the complete default suite (1344 passed, 13 skipped in 1160.72s), the separately enabled complete Docker suite (12 passed, 3 deselected in 140.05s), offline E2E (9 passed in 214.64s) and independent delivery audit (11 passed in 144.48s). Its documentation-final archive/checkpoint is the remaining gate before chat source work. The following signatures are frozen for the next slice; changes require updating this plan and notifying adjacent owners.

All conversation domain records are frozen strict Pydantic models with UTC timestamps and bounded serialized bytes. `ConversationId` uses `conv_` plus 32 lowercase hex digits; `ConversationTurnId` uses `turn_` plus 32 lowercase hex digits. Add corresponding IdPrefix values. Claims use existing `corr_` identifiers. Submission keys are canonical ASCII `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`.

- `Conversation`: version/kind, conversation/project/repository identity, revision, next sequence (1–1001), optional active turn, created/updated timestamps.
- `ConversationSummary`: nonempty text up to 4096 UTF-8 bytes and explicit `truncated`; user summaries are additionally capped at 2048 bytes.
- `ConversationArtifactRef`: artifact ID/hash/root Run/kind; only CoS response, run summary, evidence bundle, patch, cleanup and runtime usage kinds, at most eight unique references per turn. These are references, not permission or completion claims.
- `ConversationContextEntry`: turn ID, sequence, Run ID/status, user/result summaries and artifact references. `ConversationContext` binds conversation/project, through-sequence and at most eight ordered settled entries, at most 32768 serialized UTF-8 bytes; its canonical hash freezes selection. Omitted count is explicitly displayed as through-sequence minus selected entries.
- `ConversationSubmission`: conversation/project/repository identity, submission key, expected conversation revision, context and user summary. No Run/provider/credential object is accepted in this sideband.
- `ConversationRunBinding`: conversation/turn/project/repository identity, sequence, submission key/hash, redacted goal hash, root Run ID, immutable initial Run binding hash, reviewed config hash, RunBudgetLimits, context hash and creation timestamp.
- `ConversationClaim`: exact claim/conversation/turn/project/root Run IDs, generation and claim timestamp.
- `ConversationTurn`: version/kind, binding, revision, status, owner generation, optional active claim ID, context, summaries/references, observed Run status, creation/update and optional settled/fenced timestamps.
- Turn statuses are RUNNING, WAITING, DELIVERED, FAILED, CANCELLED and RECOVERY_REQUIRED. Registration is RUNNING even if the root Run is still CREATED; there is no automatically replayable PREPARED state.
- `ConversationRegistration`: turn plus optional claim. Only the atomic creator receives the generation-1 claim; duplicate registration returns no execution authority.

Submission hash covers project/conversation identity, redacted goal hash, frozen context hash, user summary, effective budget limits and reviewed config hash. It excludes newly allocated Run IDs/timestamps and current Git HEAD. First registration separately binds the exact initial Run/base/runtime/sandbox identity. A retry reuses its original context, never acquires a claim and never resets budgets; changed logical content under the same key fails closed. Normal project/configuration preflight may still refuse a retry after unrelated target/config drift.

`ConversationStore` is synchronous. Revision arguments refer to the turn except `submission.expected_revision`, which is the conversation revision:

```python
create(project_id, repository_identity) -> Conversation
latest(project_id, repository_identity) -> Conversation | None
get(project_id, conversation_id) -> Conversation
list_turns(project_id, conversation_id, *, before_sequence=None, limit=50)
get_submission(project_id, conversation_id, submission_key) -> ConversationTurn | None
get_turn(project_id, turn_id) -> ConversationTurn
binding_for_run(run_id) -> ConversationRunBinding | None
register_turn_run(submission, run, *, config_snapshot_sha256, budget_limits)
assert_claim(claim) -> ConversationTurn
claim_resume(run_id, *, expected_revision) -> ConversationClaim
settle(claim, *, expected_revision, summary=None, artifact_refs=()) -> ConversationTurn
fence(run_id, *, expected_revision, reason, claim=None) -> ConversationTurn
reconcile_fenced(run_id, *, expected_revision, summary=None, artifact_refs=())
```

`claim_resume` permits only WAITING turns with no active owner. An unresolved approval may be inspected by the claimed workflow and then settle without effects. `settle` derives lifecycle from authoritative Run state. `fence` invalidates the exact owner and atomically cancels/fails a nonterminal root Run using shared transition validation, retaining RECOVERY_REQUIRED and the active turn until cleanup. Normal cancellation requires the exact active claim, or an owner-free waiting turn. Only the explicit stopped-owner RecoveryService may use `reason="recovery"` without the former claim. Reconciliation requires terminal Run state and no outstanding parent/descendant resources. No elapsed-time takeover exists.

The SQLite constructor is `SqliteConversationStore(database_path, clock, ids, redactor, state)`. Reuse narrow connection-local Run insertion and event helpers. Add bounded `StateStore.list_events_after(run_id, after_sequence, limit)` with a maximum 100 events and validated SQL/JSON identity/sequence. Container fields are `conversation_store` (adapter) and `conversations` (application service).

The CLI-facing application contract is `ConversationService.select(project_path, conversation_id=None, create_new=False)`, `status(id)`, async `submit(id, message, submission_id, options)`, async `resume(id, allow_unsafe_local=False)`, async `cancel(id)`, `artifacts(id)`, `permissions(id, identifier=None)`, `approve(id, request_id, choice)`, `deny(id, request_id, reason=None)`, and `progress(id, cursor=None, limit=50)`. Each bare ID must first have been selected against its validated registered project in that service instance. Shared workflow ownership remains enforced independently of this UI selection.

`ChatExecutionOptions` is a frozen application dataclass mirroring optional runtime_name, sandbox_name, provider_model, credential_ref, fake_scenario and explicit allow_unsafe_local. It introduces no new model choice or budget override. View dictionaries contain conversation/project/revision/active turn, selected latest turn/root Run/status, validated InspectionService Run projection, bounded user/result summaries, truncation/recovery indicators and warnings. Progress pages contain bounded cursor, events and has_more; events expose identity/sequence/type and deterministic bounded summary, never raw payload. Cursors bind the selected conversation/root Run. Approval IDs are obtained from authoritative current requests.

The service retains and awaits one locally owned execution task per conversation; the CLI multiplexes input/progress/completion and delegates cancel/EOF/exit cleanup to the service. `--json` and `--submission-id` require `--message`; slash-prefixed noninteractive messages are rejected locally. Interactive slash commands remain deterministic and exact.

Single-writer ownership: persistence/domain/port/migration/ID/state pagination and their isolated tests belong to the persistence worker; CLI chat module and only import/registration hunks in cli/app.py plus CLI tests belong to the CLI worker; root owns workflow/service/resources/bootstrap and integration tests. A fresh verifier owns additional independent tests after those source contracts are implemented. Writers must preserve one another's edits.

- `fleet chat` selection/message/JSON/submission flags and the documented deterministic slash commands.
- Conversation/turn/context/claim/binding schemas, dedicated identity prefixes and migration 7; prior Runs remain unchanged and no conversation is fabricated during upgrade.
- Typed trusted optional submission/owner sidebands on workflow entry points; no SDK objects or raw callbacks.
- Conversation registration/claim/pause/delivery/failure/cancellation/recovery events; all redacted and append-only through the application API.
- Stable typed busy/ownership/recovery/invalid-context errors using existing categories where possible. Exact names are finalized before implementation.

## Milestones

### Milestone 1: atomic conversation-run ownership

Acceptance: real SQLite migration/reopen and process races produce one Run/owner; foreign projects, altered SQL/JSON, duplicate keys with different payload, missing bindings and owner clearing fail before model calls. Registration occurs before the first recorded CoS request. Existing non-chat workflows stay runnable.

### Milestone 2: normal persistent application journey

Acceptance: submit, exact pause, reconstruct, approve, resume, inspect and cancel all retain one turn/Run/ledger. Context is bounded and secret-free; no full provider history is persisted. Terminal/ready lifecycle and evidence strength remain distinct. Repeated cancellation and uncertain claim recovery leave exact recoverable state without replay.

### Milestone 3: responsive CLI and full Phase 5 acceptance

Acceptance: line/pipe input processes `/status` and `/cancel` while work runs; EOF/exit/interrupt wait for cleanup. Separate CLI invocations reopen the same conversation, preserve exact approval identities and present evidence/usage/proof gaps. A normal offline FunctionModel + real Docker bootstrap/chat/approval/verification/explicit-patch-apply journey passes. Run every quality/default/offline E2E/Docker/archive gate and independent review before updating whole-phase metadata to 5.

## Detailed implementation steps

1. Wait for and record final Milestone 2 graph acceptance/checkpoint. Finalize domain/port contracts in this plan before source changes.
2. Add bounded conversation domain schemas and independent SQLite storage/claim/migration tests. Extract only the shared private Run-row/event helpers needed for atomic registration.
3. Integrate trusted workflow registration/resume ownership and shared lifecycle settlement, including ordinary-run cancellation and stopped-owner recovery.
4. Add ConversationService context/history/submission/inspection/approval/cancel methods. Validate current registered project/runtime/selection and same-project references.
5. Add asynchronous line CLI and noninteractive JSON mode, event cursors and deterministic commands. Exercise real subprocess input, not callback-count-only mocks.
6. Add adversarial/restart/multiprocess tests, normal FunctionModel and opt-in Docker E2E; regenerate schemas, update specs/README/parent ledgers, run final quality/package gates and independent verification, then commit the accepted whole Phase 5 checkpoint.

## Validation plan

Focused domain/SQLite tests cover bounds, UTC/IDs, migration6→7, redaction, atomic registration rollback, duplicate submissions, one-owner process races, corruption, immutable context/reference/Run bindings, pause/reopen and claim fencing. Application tests assert persisted states/events, exact model-call counts, artifacts, evidence and resource cleanup. CLI E2E uses real subprocesses with pipes and separate invocations for restart, approval/resume, active cancellation/EOF/exit and cross-project denial. Ordinary tests deny sockets/live model requests.

Run formatting, lint, mypy, schema check, unit/contract/integration/offline E2E/default suite, opted-in complete Docker suite, managed-resource read-back and source-identical wheel/sdist checks. Whole Phase 5 acceptance requires prior graph regressions too. Live provider and fresh-user/platform/license release gates remain separately labeled; no fake/offline test substitutes for those observations.

## Rollback and recovery

Keep accepted phase/graph commits intact. Migration 7 is transactional and forward-only; old binaries reject newer state. Registration publishes Run+turn+binding+claim together or none. Identical retries expose the same Run without new execution rights. Claimed unknown outcomes are never retried automatically or refunded. Explicit stopped-owner recovery fences the exact conversation turn and delegates exact parent/descendant resource cleanup; it does not reset the target repository or alter another conversation.

## Progress

- [x] (2026-09-05) Read-only workflow/SQLite/chat investigations completed while graph source was frozen for final tests.
- [x] (2026-09-05) Recorded this plan before chat implementation; selected typed atomic workflow registration instead of post-hoc Run attachment.
- [x] (2026-09-05) Graph final behavioral gates passed; froze the exact domain, persistence and CLI-facing contracts above. Chat source still waits for its accepted graph checkpoint.
- [ ] Graph documentation-final archive gate and checkpoint; authorize chat implementation.
- [ ] Atomic persistence and workflow ownership integration.
- [ ] Bounded context/service and responsive CLI.
- [ ] Full Phase 5 tests, independent acceptance, docs and checkpoint.

## Discoveries

- Observation: attaching a turn after awaiting WorkflowEngine.start can occur after CoS, writes and verification. Consequence: registration must be atomic at the pre-model Run creation boundary.
- Observation: a chat-only owner lock would not govern ordinary fleet resume. Consequence: authoritative binding/owner validation belongs in the shared workflow lifecycle, with exact graph child/continuation rules preserved.
- Observation: graph recovery does not cover conversation-owned CREATED/PAUSED states, and plain workflow cancellation alone does not prove Run/resource finalization. Consequence: extend explicit recovery and cancel/await/cleanup before releasing conversation ownership.
- Observation: the architecture forbids default unbounded prompt/history retention. Consequence: default summaries/references plus the already-existing Run.goal, bounded context and explicit truncation; no raw SDK transcript persistence.

## Decision Log

- Decision: integrate a typed optional registration contract at existing WorkflowEngine Run creation. Rationale: preserve one policy/preflight path and atomically create the turn/Run before any CoS effect. Alternative: broad prepare/execute workflow split; not needed for this slice. Date: 2026-09-05.
- Decision: one active turn per conversation, no hidden new-goal queue while waiting/running. Rationale: clear ownership, bounded budgets and deterministic restart. Date: 2026-09-05.
- Decision: conversations persist context identity, not a shared cross-Run AgentInstance or permission principal. Rationale: retain exact Run/Task/Agent grants and isolated final evidence. Date: 2026-09-05.
- Decision: no automatic claim expiry/replay, even before visible CoS output. Rationale: elapsed time or a paused display state does not prove the original owner stopped. Date: 2026-09-05.

## Outcomes

Design only. No chat source, migration or CLI has been implemented by this plan. Exact contracts still require freezing after graph acceptance. Phase 6 FleetPatch, Phase 7 detailed guide/release hardening and final GitHub delivery remain open.
