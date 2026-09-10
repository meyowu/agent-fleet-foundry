# Session review and once-only business baseline — S2.1c

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`,
`Decision Log`, and `Outcomes` as implementation proceeds. Root has released
one isolated-clone Writer against the named candidate below after standalone
baseline acceptance and current-source qualification. This does not authorize
changes to the currently frozen main checkout or imply Session acceptance.

## Purpose and user-visible result

An already selected foreground Session can inspect one configured project command,
review its exact source and isolation scope, explicitly authorize it once, then
run and inspect the durable baseline without entering a model conversation.

Intended interaction, not yet implemented:

```text
fleet chat .
/baseline plan python-test
/confirm <displayed short code>
/baseline run
/baseline show
```

Confirmation alone must never execute the command. The existing standalone
`fleet baseline` lifecycle remains compatible. Baseline observations are not a
Verifier verdict, accepted patch, task completion, or ConversationTurn.

## Scope

### In scope

- Typed Session-bound review, confirmation-only authorization, explicit run and
  readback for one current baseline; bounded terminal rendering and help.
- Existing baseline controller/store/Gateway/Docker boundaries; exact once-only
  claims; independent baseline cancellation and cleanup drainage.
- Metadata-only admission after ordinary Session selection, with no additional
  credential lookup or model/runtime construction during baseline operations.
- Offline stateful integration, real-process Session E2E and negative security
  tests; preserve all existing Session history/key-redaction behavior.

### Out of scope

- A globally credential-free Session startup, new provider/Harness, model calls,
  global history redesign, automatic bootstrap, image/dependency preparation.
- Session baseline recovery shortcuts, automatic approval/replay after restart,
  new DB migration, changed baseline public schemas, fake Run/Task/Turn records.
- Physical six-repository/cold-start qualifications, evaluation terminal-write
  admission, external oracle, unrestricted background execution or whole-goal PASS.

## Current repository state

The combined standalone baseline is integrated into main source543-file digest
`30b8f4762e92da2c001b189b32a42fddba41cf9ebd8be6b1fee9924b82f874e6`.
Full default coverage has3966 passes/23 deliberate skips; independent matrix/static,
ordinary Docker29, fresh installation3 and archive1 readbacks pass. First physical
Python baseline independently passed at23:06:20UTC and root accepted its narrow
generated-fixture scope at23:10UTC. These are prerequisites, not Session acceptance.
Main remains held for the separately gated live canary. The Writer's private
`agent-fleet-session-baseline-development.8BF1tw/repository` clone starts from
local commit8fdf7eb2830b644061c0a36dffd62e28df214f1e, with the exact543-file30b8
source inventory. This plan remains root-owned in main; the clone's older plan
snapshot must not replace it. The clone's local origin is not a GitHub push target.

`application/baseline.py:BaselineService.run` currently combines authorization,
claim and execution. `adapters/persistence/baseline.py:claim_baseline` already
validates and consumes an exact authorization ID/hash/expiry atomically.
`application/session_review.py` owns bounded short-lived review tickets, nonce
nonreuse and selection invalidation. `domain/session_review.py` has Run-centric
selection types that must not be widened with fabricated Run IDs.

`application/conversations.py` owns selected project/conversation state. Its existing
selection/status/history helpers can resolve credentials for safe per-key history
redaction; simply reusing them would violate the new operation-scoped claim.
`cli/chat.py` dispatches local slash commands and polls ordinary Run progress.
`bootstrap.py` composes these services. Existing model-profile persistence shows a
connection-local metadata reader pattern for same-transaction binding checks.

## Security impact

All invariants in `docs/SECURITY_MODEL.md` remain authoritative. User confirmation
does not alter hard denies, persistent trust or Sandbox authority. The original
five-minute baseline review cannot be extended by a Session ticket. User input
and model text cannot grant arbitrary executable/argv/path/environment scope.

Session confirmation and claim must jointly validate the exact conversation
metadata in the same short SQLite transaction and the local foreground generation
through a trusted pure in-memory validator. No second connection, history lookup,
filesystem operation, model call or awaited work may occur in that transaction.
Preserve baseline publication/trust guards without nested non-reentrant guards.

After normal Session selection, baseline operations reuse the same Redactor but
perform no additional SecretStore inspect/resolve or RuntimeRegistry/runtime/model
construction. This explicitly does not remove normal Session startup or explicit
history/model operations' credential and redaction duties. Ordinary progress and
completion rendering must not silently re-enter those paths during baseline focus.

## Proposed design

Use the existing authority chain:

```text
local /baseline plan -> immutable baseline review + Session ticket
local /confirm      -> exact available authorization, no owner/resources
local /baseline run -> consume authorization + permanent owner/dispatch
                    -> existing Gateway/Broker/read-only Docker
                    -> baseline report + exact cleanup, no Run/Turn
```

Add `BaselineService.authorize` and `run_authorized` as separately tested trusted
controller seams. Extract only shared parts of the existing execution path.
Standalone `run(...allow_once...)` retains its existing behavior. `run_authorized`
must never synthesize or reissue an authorization when the supplied ID is invalid,
expired, revoked, consumed, mismatched or absent.

Represent baseline Session binding with immutable scalars: project/repository
identity, conversation ID/revision and local selection/inspection generation.
Do not reuse a Run ID slot. Carry the exact baseline/review/hash and subsequently
returned authorization ID in a bounded process-local focus object. Planning a new
review, dismissing, switching away and back, or restarting invalidates old local
tickets/focus. Never infer authority from the latest stored baseline.

Extend the existing bounded ticket registry with a typed baseline branch. Dispatch
by the stored ticket type before the old `_review_selection` path; a consumed or
failed ticket must not fall through into another ticket family. Expiry is at most
the earlier of the ticket TTL and original baseline review expiry.

A metadata-only ConversationService helper reads the already selected state,
registered Project and conversation metadata without `_conversation`, `_turn`,
`_view`, `_require_current`, `_review_selection` or history summaries. Persistence
then checks conversation metadata using its current SQLite connection. A trusted
local generation validator runs inside that same admission transaction, not only
before it, to close same-process selection ABA races.

Inject a lazy baseline factory sharing the Session Redactor. During a baseline
operation use dedicated bounded escaped presentation, suppress ordinary Run
progress polling and do not call history-based status on completion. Explicit
ordinary `/status` and history retain their existing behavior after the baseline
operation; they are not covered by the no-additional-credential-operation claim.

Own baseline async tasks separately from Run work. Capture baseline ID/task at
cancel time; repeated cancellation, interrupt and EOF join the same cleanup drain.
Never call ordinary `ConversationService.cancel` for a baseline. Reuse baseline's
existing cancellation/report/cleanup implementation. Conservatively refuse
overlapping local Run/recovery/baseline mutation. Unknown execution keeps its
permanent claim and retained resources; no automatic second dispatch.

## Public contracts

- New foreground commands `/baseline plan COMMAND_ID`, `/baseline run`, and
  `/baseline show`, plus existing `/confirm CODE` for an exact typed review.
- No implicit confirmation, hidden command execution or model-generated control.
- Internal immutable baseline Session binding and typed ticket/focus state; no
  altered public baseline schema, Run/Task/ConversationTurn schema or migration14.
- Narrow BaselineService/BaselineStore optional Session-binding admission contract
  and authorize-only/run-authorized seams. Existing standalone consumers continue
  to work without Session binding.
- Denied/expired/stale/unknown outcomes remain explicit and bounded. A zero-exit
  baseline report is still only `baseline_observation_only`.

## Milestones

### Milestone 1: Authorization is separate from execution

Acceptance: confirm-only creates one available authorization and no owner,
dispatch or lease; exact run consumes it once. Wrong/stale/revoked/consumed IDs
refuse without replacement grants. Existing standalone lifecycle still passes.

### Milestone 2: Foreground Session path with exact selection binding

Acceptance: plan -> confirm -> run -> show works under post-selection secret,
runtime and history-read failure sentinels; one owner/dispatch and complete normal
cleanup are observed; existing Conversation/Turn/Run rows are unchanged. Cross-
process conversation revision, local ABA, switch, dismiss, expiry and restart
invalidate the original local review. Confirm never starts execution.

### Milestone 3: Cancellation and compatibility

Acceptance: cancellation/EOF/interrupt drain only the captured baseline task,
double cancellation cannot target a later operation, unknown-create stays unknown
without replay, and all existing history/per-key redaction regressions pass.
Independent acceptance precedes root integration and fresh combined-main gates.

## Detailed implementation steps

1. Freeze named input files and tests before Writer work. One Writer owns only
   `application/baseline.py`, `ports/baseline.py`,
   `adapters/persistence/baseline.py`, `domain/session_review.py`,
   `application/session_review.py`, `application/conversations.py`, `bootstrap.py`
   and `cli/chat.py` under `src/agent_fleet`, plus the three tests below. Root owns
   this plan, README, USER_GUIDE and security/architecture documentation. No Writer
   main edit is authorized while the current30b8 checkpoint is held. The Writer
   is not alone: preserve all other edits and stop on overlap rather than revert.
2. Add authorize-only and run-authorized seams with same-connection conversation
   metadata checks and pure selection-generation validation; preserve standalone
   guard ordering, exact review revalidation and existing cleanup implementation.
3. Add immutable baseline ticket/focus binding to the existing review registry;
   clamp TTL, invalidate exact generations and reject replay/family fallthrough.
4. Add lazy shared-redactor baseline composition and metadata-only Session methods;
   separate task cancellation/drain and prevent ordinary history/status re-entry.
5. Route the local slash commands in chat with bounded rendering/help; reject
   unknown arguments rather than forwarding them to a model or a shell.
6. Add `tests/unit/test_session_baseline.py`,
   `tests/integration/test_session_business_baseline.py`, and
   `tests/e2e/test_session_business_baseline_cli.py`. Reuse actual baseline Git/
   SQLite/Gateway fixtures and synthetic Docker transport for offline behavior,
   plus existing QueuedInput/InteractiveChat helpers for real-process input.
7. Freeze the complete candidate, independently verify it, integrate only owned
   bytes after root's current checkpoint release, and rerun final main gates.

## Validation plan

Expected commands (results must be recorded only after actual execution):

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m agent_fleet.schemas.generate --check
uv lock --check --offline
uv run pytest -q tests/unit/test_session_baseline.py tests/integration/test_session_business_baseline.py tests/e2e/test_session_business_baseline_cli.py
uv run pytest -q
git diff --check
```

The schema command matches the actual argparse entry and current six-static-gate
receipt; this new slice has not executed it yet. Run the ordinary suite in the
existing locked environment with offline tooling, disabled provider/Docker/install
opt-ins and no credential variables. Preserve the existing full identity-partitioned matrix strategy and serial
timing-sensitive cancellation test rather than increasing test timeouts.

Focused assertions must inspect durable states, exact authorization/owner/dispatch
and lease sets, escaped output and no ordinary execution records. Include injected
metadata/revision changes at transaction admission, callback re-entry rejection,
selection ABA, wrong IDs/hashes/expired TTL, model-text slash spoofing, no implicit
replacement grants, ticket capacity/nonreuse, restart, cancellation/EOF and failed
cleanup. Preserve `test_conversation_safety.py` fresh-history key registration and
`test_model_profile_service.py` rotation/companion-key controls unchanged.

The frozen independent verdict must bind source/dependency identity, exact test
collection/results, resource/DB evidence and all remaining gaps. Physical Docker,
fresh install, packaging, paid models and cold starts need separate explicit
root-operated contracts; offline synthetic transport is not physical evidence.

## Rollback and recovery

No new migration means no database down-migration. Reverting the unshipped Session
adapter must leave standalone baseline rows and existing protected controls intact.
Never delete attempt records or restore a pre-command DB to make a retry possible.
Available authorization can be explicitly revoked through existing standalone CLI.
For an interrupted consumed attempt, retain the baseline ID and evidence; only the
existing separately reviewed stopped-owner cleanup path may act. Expiry, restart
or absent containers are not proof that an effect did not occur or permission to
run again. Local focus is intentionally not restored as authority after restart.

## Progress

- [ ] (2026-09-10 00:02 UTC) Writer's first frozen11-file candidate33ff32ae
  produced40 passes and2 failures in228.28s (232.071s wrapper). Both failures
  are the new cross-process fixture passing Path where get_project_by_root
  requires str; mypy independently found the same test-only argument error.
  Those controls fail before child authorization/admission and do not prove
  cross-process acceptance. All other static gates passed. Preserve this failed
  candidate and its receipts unchanged while legacy Session and standalone
  baseline cohorts finish; then correct that one test line, create a successor
  freeze and repeat the full new cohort/static checks. Eight production-file
  bytes remain unchanged, with bounded read-only security review in parallel.

- [ ] (2026-09-09 23:53 UTC) Worker reports two actual new journey cases
  passed43.32s in the clone,including a real-process CLI journey with synthetic
  Docker, and mypy src/tests passed389 files. These are intermediate mutable-
  candidate results,not acceptance. Retained first failures include a fixture
  assertion and BaselineShow presentation conversion; current work also preserves
  the legacy APPROVAL_INVALID result for unknown/restarted review codes and
  metadata-free repeated dismiss. Complete cohort and legacy replay remain pending.

- [x] (2026-09-09 23:43 UTC) Root prepared a clone-only exact-lock environment
  after identifying that existing real-process chat fixtures intentionally strip
  PYTHONPATH. Offline locked sync using existingPython3.14.6 exited0:99 locked
  packages,96 installed including the clone editable. Isolated import origin
  points to clone/src; main543source,59Markdown and9837 installed dependency
  files remain unchanged. Private runtime receipt46590c77. This only enables
  candidate tests; it does not accept source still being written or claim tests.
- [ ] (2026-09-09 23:47 UTC) Writer's eight production paths are mutable in
  the clone; CLI and three test modules are underway. No main integration,
  independent candidate verdict or new Session test result exists yet.

- [x] (2026-09-09 23:00 UTC) Read-only Session integration map completed against
  current30b8; root prepared this living plan before any implementation.
- [x] (2026-09-09 23:28 UTC) Standalone first physical acceptance and current
  source/default/static/Docker/install/archive checkpoint reconciled. Main stays
  frozen; only a separate clone may proceed.
- [x] (2026-09-09 23:28 UTC) Root released session_recovery_writer as sole
  implementation Writer in private8BF1tw clone from8fdf7eb/30b8, only the eight
  production and three new test paths specified above. No main, receiver, release,
  dependency, provider, Docker, GitHub or unrelated file changes are permitted.
- [x] (2026-09-09 23:30 UTC, before first Writer edit) Writer correctly stopped
  on a contract typo: the existing service module is `application/conversations.py`,
  not singular `conversation.py`. Root verified the actual file/class and corrected
  only that production ownership path. All other seven production and three test
  paths remain unchanged; no new alternate module or scope expansion is allowed.
- [ ] Scoped implementation and immutable handoff.
- [ ] Focused/static/full compatibility checks with exact persisted evidence.
- [ ] Fresh independent verdict, root integration and combined-main acceptance.

## Discoveries

- Observation: BaselineService.run currently authorizes and executes together.
  Evidence: existing service and BaselineStore.authorize/claim_baseline methods.
  Consequence: /confirm cannot directly call it; split only the trusted seam.
- Observation: normal Session status/selection/history may resolve credentials.
  Evidence: ConversationService and cli/chat progress path; read-only map found
  existing per-key redaction regressions depending on those reads.
  Consequence: isolate baseline operations after selection, not all Session startup.
- Observation: a pre-transaction selection comparison can miss ABA/revision changes.
  Evidence: existing connection-local model-profile admission pattern and baseline
  permanent claims. Consequence: same-transaction metadata plus local generation.

## Decision Log

- Decision: confirmation-only authorization and separate explicit run,2026-09-09.
  Rationale: user review must not hide code execution. Alternative: using existing
  run on /confirm would violate the intended consent boundary.
- Decision: operation-scoped no-additional credential/runtime access,2026-09-09.
  Rationale: preserve mandatory existing history redaction while making this
  model-free operation precise. Global credential-free Session is a larger change.
- Decision: process-local bounded focus, no migration or automatic restore,2026-09-09.
  Rationale: smallest secure implementation; durable baseline remains inspectable
  while restart cannot recreate execution authority.

## Outcomes

The isolated-clone implementation and tests now exist, but the first frozen
candidate failed two new fixture controls and mypy. A test-only successor and
complete legacy/independent acceptance remain pending. No main integration,
physical Docker execution, model call, commit or whole-goal acceptance is claimed
for this Session slice. The root-checkout package and live receipts are separate.
The standalone first Python smoke and current qualification work are recorded in
the preceding baseline and parent S1–S3 plans, not counted as this slice's evidence.
