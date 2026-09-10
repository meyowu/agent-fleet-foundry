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

Implemented in the independently accepted isolated candidate; not yet integrated:

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

- [x] (2026-09-10 final parent closeout) Combined61e79cba now also has final
  pre-live archive1/2.60s plus independent0203fb88 and one actual nano/PydanticAI
  CLI E2E1/77.00s plus independent a9681755. These are separate from this plan's
  warm model-free Session journey and do not count as live interactive Session,
  Node or coldstart qualification. The source and9837 dependency files were
  unchanged through the real-model run/audit. Result documents now record the
  completed bounded test and remaining limitations; user requests stop, with no
  further development, paid call, commit, push or merge in this turn.
- [x] (2026-09-10 02:27:33 UTC actual audit) The new model-free physical
  Session journey is independently PASS: sG3d6c/VERDICT.md
  SHA53f97483d39a70a7ac7a0ef15f14ed35f6f014620aa96f9e2b8a36250f3ac62a;
  JSONd580f7e4, deliverye7e35650. Root fully read/hash-checked. Six original
  phases include actualshow, nine fixedSQLite snapshots/currentstate match,
  confirm-only/noordinaryRun/model effects hold, all canonical owner/report/three
  releasedlease/receipt bindings pass. Fresh exact native c8586d6f/worktree absence,
  original-onlyGit registry and14unchangedtargetfiles pass; six boundedread-only
  commands exit0. Source546/61e/runtime9837/predecessors unchanged. One warm
  pinnedDocker Python baseline_observation_only path only: not physicalcancel,
  Node,coldstart,liveS1businessorwholegoal. Earlier9jlfrb remainsFAILED_JOURNEY.

- [x] (2026-09-10 02:24 UTC, original execution only) New z7zFWN prepare
  wrapper84321 and execute wrapper19035 both ended0. Original Session PID15828
  ended0 after25.982928124954924s, six complete phases including actual show,
  full EOF/drain,73233 bytes,zero signals/transport failures/truncation. Run/show
  raw phase hashes both b79243906b46df51994adfa174bdc9790ee171ad936ab783903684e9c410ad83.
  Three real unittest cases pass and both source-write probes report EROFS30;
  runner physical audit records exact container/worktree absence and unchanged
  b74cc720 target. Execution-result45e49129, process5909f517 and originalterminal
  e5ecc174 are retained; independent actual resource/DB/source readback is pending
  in sG3d6c, so this entry does not yet award independent physical acceptance.
  This new attempt is spent and never replayed. Older9jlfrb remains FAIL.

- [x] (2026-09-10 02:20 UTC seal) Oracle-only z7zFWN passes fresh independent
  qualification32ad0710: all67 cases2.47s (2.945743s wrapper0), eight direct
  oracle groups and two static checks0. Full51 original cases retained plus16
  additions; only match_database function changed, protocol439301bd unchanged.
  Source546/61e and9837 runtime checks hold; new attempt absent. Root fully read
  and hash-checked finaldelta/contract/HANDOFF/bundle32fb5e51 and verdict, now
  releases prepare-only in root-prepare-release.json. This is not physical PASS;
  actual execution requires separate prepare readback and release. No pytest
  overlap: independent parent was terminal before root's full matrix began.

- [ ] (2026-09-10 01:55 UTC) The one actual9jlfrb journey is FAIL and spent:
  root parent84055 exited3; actual Session PID75428 exited0 after16.078463666s,
  complete untruncated66905-byte drain, no signal/transport failure. Selection,
  plan, preconfirm refusal and confirmation-only checkpoint completed; run
  returned observed/command exit0/cleanup_complete=true. The private
  match_database oracle then raised unexpected_recovery_scope, so actual Session
  show and its final physical audit were NOT reached. Root raw terminala39b9a1f,
  execution resultc76bdfcd, process91d87f58 and run DBaf441c3a are retained.
  SQLiteBaselineStore.show:1456-1473 returns the resource snapshot digest whenever
  owner_claim_id exists, even after successful cleanup; the null-only private
  assertion contradicts that existing contract. Fresh independent actual-result
  audit confirms this diagnosis and is reconciling exact physical resources.
  No product defect/fix, retry or full physical PASS is inferred. No paid request.

### Post-run oracle correction and stage reordering — before successor edits

Preserve the complete failed9jlfrb attempt, predecessor scripts and all receipts;
never replay its Session or baseline. Root will integrate the separately accepted
ten-file read-scope candidate after the independent failed-journey audit releases
the old938589 source hold. This explicitly reorders private qualification work,
not acceptance: combined61e79cba must still pass all full/default/static/optional
and physical gates before a new paid test or completion claim. The new physical
bundle will bind combined546/61e79cba and the exact prospective map whose live
bytes root verifies at integration. The old actual attempt stays FAIL, not PASS.

One private Writer may copy the frozen9jlfrb core files into a NEW sibling and
change only source/manifest/path bindings plus match_database's recovery-scope
oracle and its direct tests. Keep protocol439301bd byte-identical. Reconstruct
BaselineResourceSnapshot from the exact already-captured execution, owner claim,
dispatch and canonical lease payloads; before any owner require null, afterward
require equality with that typed full snapshot's digest. Do not merely accept any
nonnull hash, hide the field, call show to supply its own expected answer, or
change production/store/permissions/cleanup/command predicates. Test the actual
retained run response against retained DB bytes; null-with-owner, forged/stale
scope, altered execution/lease/claim, and unexpected rows must fail. Update the
older synthetic retained-record fixture to reconstruct the documented digest,
without editing the original evidence. All original51 controls must remain;
retained actual input hashes, every revised source/test snapshot and failure
receipt stay separate. Exact current source checking waits until root integrates.

Fresh independent review and all private synthetic/static controls remain
mandatory before a new prepare/execute release. That next attempt is one new
model-free fixture/Session, never an extension or replay of the spent attempt.
Root may run combined full offline gates while the independent private bundle is
reviewed, but limits all pytest parents to three globally and does not edit frozen
main code or public documents during the matrix. No new paid budget or provider
key is part of this correction.

- [x] (2026-09-10 01:53 UTC) Root's one physical fixture preparation exited0
  on original parent28211. New target HEAD51ea2207 has14 committed files and
  unchanged fixture manifestb74cc720. Setup is registration-only, not bootstrap:
  one Project, two existing policy events and13 migrations; all Conversation,
  baseline, Run/Task/artifact/tool/model/evaluation rows are zero. Explicit Git
  argv and original-only registry target only new9jlfrb; old helper default is
  recorded unusable. Prepare resultb89fb1c6, setupcd19d0c5 and original terminal
  d9dbb99c are retained. Source546/938589 and9837 runtime hashes match. Root read
  these records and now separately releases exactly one model-free public Session
  execution and one pinned-Docker baseline under the frozen contract; no replay,
  provider key/request, patch application or new image/dependency authority.
- [x] (2026-09-10 01:52 UTC) Independent successor pre-execution qualification
  is PASS: private OuKNWZ verdictab57433c/JSONcfd1e930/deliverybd5366a0,
  root completely read/hash-checked. Fresh51 pass2.48s pytest/2.954274459s
  child-wrapper interval; seven original semantic groups pass; Ruff/format0.
  A verifier-only wrong argv index made its initial outer wrapper exit1 after
  the successful pytest child. Original script/traceback remain retained; only
  a new private replay's index lookup changed, no suite/candidate rerun. Source
  546/938589, runtime9837 and all predecessor/revision bytes remain unchanged.
  Root now releases exactly one prepare-only stage in new9jlfrb, not the public
  Session or Docker execution. Physical acceptance and broader OS startup/storage
  guarantees are not inferred from these controls.
- [ ] (2026-09-10, successor freeze before physical stages) Private9jlfrb
  bundle71d16ec6 is frozen; root read all runner/protocol/test/contract deltas
  and complete HANDOFF84bc81f5, then checked hashes. Runner5949c861,
  protocol439301bd and contract585bb287 preserve source546/938589 and runtime9837.
  Writer final51 synthetic cases pass3.58s pytest/3.964583083s wrapper,exit0;
  Ruff check/format both0. Its revision001 and003 static failures, revision002's
  50 passes and final004 each retain source snapshots and raw receipts under
  manifestd047fcb5. No old fixture/default was modified. Fresh independent
  replay is released on these exact bytes; physical prepare/execute are not.

- [x] (2026-09-10 01:29:45 UTC seal) Independent physical-bundle review is
  terminal FAIL: VERDICT.md1ba1479c, VERDICT.json3c8c77d1 and delivery0988ade2,
  all root read/hash-checked. Independent35 pass/0.89s but three pure/virtual
  counterexample commands exit1. Main546/938589 and9837 runtime inputs remain
  unchanged; physical attempt is absent. Root released only the new private
  successor preparation below, not either physical stage. All old bytes retained.

- [ ] (2026-09-10 01:29 UTC, before successor edits) The frozen physical
  bundle D9T4et/b20a7b9b is rejected before setup. Independent unchanged35 tests
  pass, but additional pure/virtual controls reproduce four blockers: the reused
  fixed_git keyword default still targets the old standalone fixture; complete
  JSON with pending UTF8 bytes is accepted; output first observed after the
  deadline is accepted; an operator-triggered SIGINT is omitted from the receipt.
  A fifth control shows exited-leader/no-EOF closes the pending output pipe;
  that case already fails normal acceptance, but drainage ownership is unproven.
  Root read the complete scripts, contract, manifest, tests and all three
  independent facts files. No setup, Git mutation, Session or Docker was run.

### Private physical-bundle successor contract — 2026-09-10 01:29 UTC

After the independent FAIL seal, one private Writer may create a new sibling
bundle only; the original bundle and old standalone fixture/evidence are immutable.
No production code, test oracle, main source, provider setting or dependency may
change. Preserve the accepted546/938589 source and existing9837-runtime binding,
original three-test fixture hashes, exact daemon/image, staged one-attempt design
and all prior typed DB/resource checks. This is preparation/synthetic testing only;
root must release physical prepare and execution separately after fresh review.

Repair only the demonstrated private harness faults. Replace the reused old
prepare entrypoint with an explicit local fixture setup using the same public
configuration/registration operations and exact commands. Every Git command must
pass cwd=the new TARGET explicitly; audit all reused helper defaults and reject
old-target output paths before any setup. Do not patch helper function defaults,
product methods, provider APIs or transport implementations. Synthetic recording
controls must exercise the actual setup command construction without running Git,
prove all three mutation commands and both registry reads use the new target,
and prove no path under the old fixture is writable through this bundle.

Do not complete a response while the incremental decoder has pending bytes.
Retain strict duplicate-key/extra-document rejection and bounds; cover incomplete
2/3/4-byte UTF8 suffixes, split continuations and genuine split Unicode positives.
Check elapsed time after each read and before publishing completion, with late
output recorded as timeout rather than success. Persist all requested SIGINTs
across finish/retained observation, including operator interruption and signal-
request failure, and ensure interrupted shutdown cannot satisfy the normal
no-signal success predicate. Keep the original five-minute review expiry.

If the leader has exited without pipe EOF, keep the pending drain owned and
record that separately from a live process. Publish a failed receipt before
retained observation; late drain/exit must never upgrade failure to PASS. No kill,
global sweep, deletion or replay. Initialize ownership fields before spawning;
if setup fails after spawning, retain the exact child/pipe for the same failure
shutdown path. Bound and explicitly report any receipt/transport failure rather
than losing an original child behind a constructor exception. Add narrow virtual
and real-synthetic-child regression controls; no physical cancellation claim.

Freeze successor scripts/tests/contract/manifest only after its own full private
synthetic cohort plus Ruff check/format pass. Preserve failures in separately
identified receipts. A fresh Verifier must replay the original counterexamples
and all successor controls without modifying the candidate. Root then completely
reads the final delta and checks all hashes before any physical stage release.

- [x] (2026-09-10 00:49:37 UTC) Root integrated exactly11 accepted paths with
  apply_patch after full production diff read and exact preimage checks. Main546
  now equals the entire independent938589 source closure;535 other prior inputs,
 9837 previously inventoried runtime files and both then-held packaged documents
 remained unchanged. Private UJKV7V before4b9fa625/after8bf314cd receipts bothPASS.
 Initial read-only helper mistook site-relative dependency keys for absolute paths
 and exited1 before any edit; corrected lookup used the recorded site root. No
 source/test oracle changed. Result/user/architecture/security/schema documentation
 is being updated separately; complete main gates still remain pending.

### Physical Session qualification contract — 2026-09-10 00:55 UTC

Root authorizes preparation of one private, model-free physical Session smoke
bundle, not immediate execution. Bind execution to an exact accepted source freeze
and existing pinned daemon/image; if source changes before dispatch, stop and
rebind/review before a new attempt. Use one new generated clean Git target and
private Fleet state with the original three-test invoice/read-only/scratch fixture
from the accepted standalone smoke. Register through the existing fixture-only
Project/config/Safe whole-repository path (not public bootstrap). No image pull,
build, dependency install, new model/key, global trust or Docker changes.

Use one unmodified isolated public `python -I -B -u -m agent_fleet.cli.app chat
TARGET` child with a cleared, explicit environment and no provider credentials.
Wait for normal selection, then drive complete output-delimited responses:
`/baseline plan python-baseline-smoke`; a preconfirmation `/baseline run` must
refuse without any table/schema fingerprint change; `/confirm ACTUAL_CODE` must
produce exactly one available authorization with zero owners/dispatch/resources;
only then `/baseline run` may execute once, followed by `/baseline show` and EOF.
Codes come from fully parsed original output, not guessed strings/substrings.
Preserve complete bounded output, original exits, deadlines and all checkpoints.

At selection and each phase, retain bounded typed SQLite backups, full noninternal
table/schema fingerprints and canonical payload hashes. After normal selection,
conversation metadata and unrelated tables stay unchanged, with zero Run/Task/
Agent/Turn/artifact/tool/model/attempt rows. Baseline rows remain separate. The
Session's report must match persisted exact identities, status, hashes and one
consumed authorization/owner/dispatch/observation/report. Controller PID must be
the actual Session process. Require all three genuine unittest outcomes, both
EROFS30 source-write refusals, inspected nonroot/readonly mounts/bounded scratch,
approved/materialized/post-run source equality and unchanged original target.
Verify three released leases, exact recorded native-container absence, exact
worktree absence and original-only Git registry. Retain fixture/state/evidence.

The root-read original standalone helper may be imported as a hash-bound private
dependency for its explicit fixture setup, read-only platform/source/DB snapshot
and resource auditing functions. Never invoke its old main/check_code/run/review
entrypoints unchanged or fabricate a CLI envelope; clearly distinguish any
standalone corroborating show from the mandatory actual Session show. No product
method, provider, Docker or secret/runtime seam may be replaced with a fake.
Provide a staged prepare/execute interface and an exclusive once marker before
starting a Session execution attempt. Root must read and independently qualify
the immutable bundle before releasing execution. Review/input timeout60s and
bounded execution timeout360s do not extend the original five-minute review;
on uncertainty retain ownership and evidence, request normal child shutdown/drain,
never replay, sweep or infer Docker cleanup from a killed process. This one
successful path does not qualify active physical cancellation, Node, cold starts,
S1 business oracle or live-model acceptance.

- [x] (2026-09-10 00:49 UTC) Root read complete successor HANDOFF and fresh
  independent VERDICT, checked their hashes, and accepts the narrow offline slice.
  Candidate546/93858963,patch85ffc734 stays frozen in the isolated clone. Writer
 604 unique current cases pass:50 new,404 existing Session,150 standalone; no
 failures/errors/skips, two existing standalone warnings. Independent62 pass:
 50 new (201.22s pytest/203.563s wrapper),7 private adversarial (30.47s/32.075s),
 5 unchanged security (3.94s/6.264s); six fresh static gates all0. Verifier reconciled
 Writer404/150 separately, not as independent replays. Seal3f7b3917 at00:40:27UTC,
 VERDICTc834ddbd in private v9c8fy. Source/9837 runtime files remained unchanged.
 Readback verifies49 private DBs; two intentional uncertainty fixtures retain two
 Git workspaces and six nonreleased logical leases. No resources were deleted or
 recovered. Worker separately retains three workspaces/84 logical fixture leases.
 Main integration, combined quality/package gates and physical Session acceptance
 remain pending; synthetic Docker is not native container or whole-S2 proof.

- [x] (2026-09-10 00:33 UTC) Worker successor closure is terminal:50 new,
  404 legacy Session and150 standalone baseline tests pass,604 distinct retained
  identities,all original exits0 and no source drift. Root read the original
  remaining results/logs and checked hashes: legacy404 passed864.56s/867.009s
  wrapper,receipt26104796541390d13c5d0346f194279f1f0b5891e1f2b953c33187cfcc38eb5b;
  baseline150 passed376.98s/380.826s wrapper,2 existing JUnit warnings,
  receipt970449887ce654fe73734823b5417653d5ba2fa8c89495c14729dd4f19e69652.
  Independent seven-control result a26b503f also root-read at its governing
  command/identity/result fields and hash-checked:7 passed,32.075s wrapper,
  no source/dependency drift. Full independent new50 now runs alone with all
  Writer test parents stopped,original timeouts unchanged. No main integration
  or whole-suite/package/live acceptance is inferred from this component closure.

- [x] (2026-09-10 00:30 UTC) Worker reports successor standalone150 terminal0,
 380.826s wrapper and no source drift; legacy404 remains running. Independent
 verifier reports seven fresh private non-cancellation controls passed,32.075s
 wrapper, with unchanged candidate/dependency identities. They check same-
 connection admission, callback-time expiry rollback, UI notification inability
 to bypass durable metadata checks, actual lazy factory under secret/runtime/
 history sentinels and prior-focus retention after rejected plan/run. These
 reports are pending root receipt readback and final independent verdict; full
 new50 independent replay and main integration are not yet complete.

- [x] (2026-09-10 00:23 UTC) Root read the successor new-test result and original
  log and checked receipt hashes:50 passed/267.43s,270.26s wrapper,exit0,0failure/
  error/skip/source drift,receipt7911d1e934c590c5ce65dcd1004ecf691e653ae69d8e9df8d12783ce37b61396.
  All six successor static commands exited0,receiptc27c7ac4a0944ab9c67522b9b4d2ea838cf5c0b5b088adf3b6c2bf773bb1112a;
  mypy covers src/tests389 files,not the additional root script scope. These are
  Worker-executed original receipts,not fresh independent replay or main gates.
  Legacy404/standalone150 and independent acceptance remain pending; all eleven
  successor files stay frozen and main30b8 is unchanged.

- [ ] (2026-09-10 00:17 UTC) Writer froze successor938589639808c80d8b3168e06ebef07a269f513f12efdbad957316bc919e8fb8
  (546 source inputs,11 owned files,patch85ffc734). Targeted corrective29 cases
  passed20.84s and mypy389 passed before this freeze; these do not replace the
  fresh new50/legacy404/static cohorts now running. Successor standalone150
  follows in a freed slot. Independent verifier starts read-only review now and
  waits for a global pytest slot before fresh behavioral controls. Preserve
  predecessor33ff's40pass/2fail new tests,404pass Session,150pass standalone,
  test-only mypy failure and independent production cancellation finding.

- [x] (2026-09-10 00:10 UTC, before successor edits) Root freezes the narrow
  routing correction within existing ownership: optional trusted RAM-only
  per-attempt on_admitted notification in baseline plan/run, after all local
  busy/selection/focus/authorization rejection checks and immediately adjacent
  to child-task registration without await. The CLI notification only marks its
  captured attempt; show changes presentation mode only after service success.
  Restore precise previous mode after a rejected async attempt terminates, but
  retain captured baseline ownership after an admitted failure for cleanup/cancel.
  Keep same-transaction metadata/generation validation and existing atomic claims;
  the callback is neither durable admission nor authority. Add rejected show,
  plan and run followed by ordinary /cancel regressions, plus admitted-failure
  retention. No shared stale foreground flag as the admission oracle, no new
  persistent schema or permission, and no changes outside the original11 files.
- [x] (2026-09-10 00:10 UTC) Predecessor33ff's standalone baseline compatibility
  cohort is terminal150 passed/276.84s (280.454s wrapper),2 warnings,exit0 and
  no code drift. Legacy Session/model-profile cohort is still running. This
  acceptance is not carried as fresh successor execution after production repair.

- [ ] (2026-09-10 00:05 UTC) Independent production read-through found a
  cancellation-routing defect in first frozen chat.py: baseline_focus and
  progress suppression are set before service admission, then retained after
  a denied plan/show. In a waiting ordinary Run, later /cancel can incorrectly
  call baseline_cancel(None) rather than cancel that Run. Source-level finding
  only so far; no dynamic reproduction or candidate acceptance is claimed.
  Writer must preserve active frozen test receipts, then repair admission/focus
  rollback and add an exact negative regression in the owned successor files.
  All prior no-overlap, cancellation-drain and standalone compatibility criteria
  remain in force; this does not authorize a new capability or main mutation.

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
- [x] Scoped implementation and immutable successor handoff938589.
- [x] Focused/static/legacy compatibility checks with exact persisted evidence.
- [x] Fresh independent offline verdict and exact root integration.
- [ ] Combined-main quality/package gates and physical Session qualification.

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

The successor938589 is independently accepted for the narrow offline Session slice
after correcting the predecessor's fixture and production routing defects. Root
integrated its exact11 paths at00:49:37UTC. Worker604 and independent62 case counts
overlap; they are not a combined full-suite count. All predecessor failures remain
retained. Physical9jlfrb execution is now recorded but the complete journey is
FAIL: three actual tests and exact resource cleanup independently pass, while the
private null-only recovery oracle stopped before show. AuditjZHtiG/VERDICT.md
SHA b94d9dc82791ea90b99bc9125b3a73e5bc44d9d795781e675fcb4f829c1deb51
sealed that distinction and released source hold. No product fix is indicated.
Root integrated read-scope10 at02:10:20UTC, yielding546/61e79cba with Session11
unchanged. New oracle-only z7zFWN binds this combined source and now has independent
physical PASS53f97483 for its one complete model-free journey, including actual
show and exact cleanup. The predecessor remains failed. Combined main default
matrix passed4093 with23 skips/4116 unique at02:45:47UTC; all six statics pass,
independently reconciled by CQfxc3/4788e9f7. Optional Docker29 and installed3 now
pass, independently sealed5c428a0e and8402821b; final pre-live archives now
pass1/2.60s with independent0203fb88. The separate parent real nano/PydanticAI
CLI E2E passes1/77.00s with independent a9681755; it is not live interactive
Session acceptance. Post-live result wording is not rebuilt into those archives.
Node/coldstart/cancellation scope remains separate. No additional model call,
commit or whole-goal acceptance is claimed for this Session slice; work stops.
The standalone first Python smoke and current qualification work are recorded in
the preceding baseline and parent S1–S3 plans, not counted as this slice's evidence.
