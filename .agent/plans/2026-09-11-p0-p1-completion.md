# Finish the remaining P0/P1 foundations in independently delivered slices

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log,
and Outcomes. It supersedes the September10 development stop only for the scope
explicitly renewed by the owner on September11.

## Purpose and user-visible result

Complete the unfinished P0/P1 work reported after PR7: trustworthy evaluation
finalization and real-project measurement, additional Provider/Harness qualification,
and broader usable Session/readiness/Node/cold-start journeys. Each accepted slice
gets its own coherent commit, push, PR and merge with authoritative remote readback.
A user should be able to inspect real test evidence instead of treating one canary
or an implemented adapter as whole-system qualification.

## Scope

### In scope

- Original-database atomic evaluation finalization, then independent oracle and
  preregistered 24-task/six-repository campaign from S1.1.
- Anthropic/Google opt-in canaries and six-task qualification, cross-provider
  role bindings, OpenAI Agents SDK/LangGraph and mixed-Harness qualification.
- Ten Session journeys, six-repository readiness, four role bundles, five
  strategies, Python/Node environment evidence and three cold starts.
- Necessary shared security, cancellation, recovery, packaging, tests and docs.
- Small independently validated GitHub deliveries; retain `[skip ci]` because
  the owner has not lifted the Actions-minutes constraint.

### Out of scope

Dashboard expansion, product GitHub/MCP connectors, durable project Memory and
self-evolution, remote sandbox backends, plugin marketplaces, formal package
release/license changes and broad productization. Native Codex/Claude adapters
remain conditional on proven interception; subprocess wrapping is not admission.

## Current repository state

Starting local and freshly fetched remote main are
`d2793f6454881bbd4cdbd563f1b3389b36391e31`; the checkout is clean. PR7's foundation
and exact historical quality/live evidence are in README and
`2026-09-10-verified-foundations-merge.md`. Source closure61e79cba has546 inputs.
Historical4093 default passes/23 skips, Docker29, install3 and live1 are not
automatically acceptance for future source changes.

`EvaluationOutcomeService.record_final_outcome` and the persistence terminal
entry fail before state access with `write_boundary_unqualified`. The accepted
read capture is deliberately not an original-DB write boundary. Prior native
NOFOLLOW/SHM/locking failures remain valid counterexamples; the old plan's
S1.1c original-transaction and identity requirements are unchanged.

Additional providers and Harnesses have actual-SDK offline implementations. The
existing live test fixes all roles to PydanticAI; its launcher additionally fixes
OpenAI nano. Session and model-free baseline routes exist; acceptance gaps must
be measured rather than rebuilding a REPL or weakening existing tests.

## Security impact

Preserve Broker/Gateway, exact sandbox selection, immutable role/model binding,
finite budgets, unknown outcomes, no automatic retry and no host project-code
execution. Native database write qualification must protect main/sidecar handle
identity and interoperate with existing SQLite writers; no staged-copy overwrite,
path-lstat substitute, relaxed stale-write rule or fabricated terminal success.

Only configured selected credentials may enter a trusted ephemeral control-plane
process. They never enter the repository, workers, logs or command arguments.
Presence-only checks found no configured OpenAI/Anthropic/Google credentials in
the current process. The owner subsequently explicitly authorized reuse of the
previously supplied OpenAI credential until this project work is complete. Use
it only in transient trusted test-process scope, never in tracked files, logs,
command arguments or worker context. This does not supply Anthropic/Google keys.
Total live budget was requested; no live dispatch until a finite attempt/campaign
envelope and usable selected credentials are established. Offline work continues.

User explicitly authorizes scoped GitHub push/merge. Use ordinary non-force writes,
exact-head merge guards and remote ref/tree/Actions readback, without protection
changes or workflow dispatch. A failed or ambiguous external result is inspected
before retry. No subagent may access credentials or perform GitHub writes.

## Proposed design and public contracts

Use three read-only investigations to freeze small implementation contracts for
evaluation, Session and qualification infrastructure. One writer per owned file
set; isolated worktrees for concurrent writers. Sol may implement bounded code
slices at the owner's request; root owns integration and delivery. A fresh
independent verifier checks each immutable candidate against observable criteria.

Do not change public schemas, dependencies, migration numbers or CLI behavior
until a concrete slice contract below specifies its compatibility and failure
semantics. Work on independent P1 slices may proceed while the native P0 writer
boundary is qualified; priority does not make unrelated work wait unnecessarily.

## Milestones

1. Map current gaps and freeze executable slice contracts before implementation.
2. Qualify a safe original-DB write backend; integrate atomic finalization only
   after identity, sidecar, CAS, locking and cancellation counterexamples pass.
3. Add bounded reusable provider/Harness live qualification infrastructure with
   offline admission/ledger tests; missing keys remain NOT_RUN, never PASS.
4. Complete remaining Session and repository-environment journeys with actual
   state/artifact/command evidence, including negative cases and cleanup.
5. Run the finite independent-oracle and Provider/Harness campaigns when their
   execution prerequisites exist; report every frozen slot and unknown cost.
6. After each accepted slice, update docs, pass applicable full/local gates,
   commit/push/merge/read back, then continue the next slice.

## Detailed implementation steps

Freeze exact ownership, changed interfaces and test oracles in a new section for
each slice following investigation. Reuse existing evaluation/runtime/baseline
ports and real Workflow paths; do not add unused scaffolding or replace production
paths with test-only successes. Root serializes shared composition/docs/schema
changes. Preserve historical failed attempts and all unrelated work.

## Validation plan

### Slice E frozen contract: user-visible retained baseline output

Inspection during Slice D found that ordinary standalone and Session run/show
only expose an observation reference, while the actual bounded redacted output
is reachable only through the internal store. This meets the literal original
S2.1b field list but leaves its user-facing troubleshooting/evidence promise
incomplete. Complete this narrow P1 route alongside the six-repository cohort;
do not add Dashboard/productization or a new command.

One separate writer owns `src/agent_fleet/domain/baseline_resources.py`,
`src/agent_fleet/adapters/persistence/baseline.py`,
`src/agent_fleet/cli/baseline.py`, the generated
`src/agent_fleet/schemas/baseline-show.schema.json`,
`tests/contract/test_baseline_readback.py`,
`tests/integration/test_business_baseline_integration.py`,
`tests/e2e/test_business_baseline_cli.py` and
`tests/e2e/test_session_business_baseline_cli.py`. Root owns docs and the Docker
cohort. No table/migration, application port, dependency or capture behavior
change. The existing observation schema remains byte-identical.

Add an optional observation body to BaselineShow, using the existing validated
BaselineCommandObservation type. Return it from the same validated persistence
read transaction as review/execution/report; enforce exact matching identities,
digest/reference and existing observation/resource facts. Null remains null
before capture. Corruption must fail closed rather than hide evidence or return
unvalidated text. Standalone CLI explicitly projects the field; Session's full
serialization must expose the same result. Only retained redacted/control-escaped
stdout/stderr and their existing redacted hashes are returned, never raw capture,
raw hashes, secret bytes, new tool execution or an invented completion status.

Acceptance: pre-capture null and valid/missing/corrupt/ref-mismatched readbacks;
secret/control/truncation-safe public output; successful and nonzero standalone
and Session run/show; no model/provider/Docker/side effect merely from show.
Update cohort assertions to use public output and compare it with durable
reopen. Existing exit codes and baseline_observation_only/target_applied=false
semantics remain unchanged. Fresh independent verification and an integrated
full local matrix precede this coherent baseline slice's GitHub delivery.

### Slice D frozen contract: six generated repository baseline journeys

Root owns new `tests/baseline_cohort_fixtures.py`,
`tests/unit/test_baseline_cohort_fixtures.py`,
`tests/docker/test_business_baseline_cohort.py` and a documented optional
Python/Node test-image build context. No production change, new dependency,
direct project registration or mocked command transport is admitted here.
The separately frozen Slice E is the only permitted production extension and
will be integrated before this cohort's final immutable acceptance.

Freeze six tiny generated Git repositories: Python and Node each have a passing
test, a deliberately missing module, and a pre-existing assertion failure. Each
has its own new state home. Run public readiness before initialization and prove
no command/state creation; public fake-runtime/Docker initialization must pass
its independent bootstrap canary. Commit generated Fleet configuration within
the disposable fixture, then use fresh-process `baseline plan`, missing-consent
rejection, exact `baseline run --allow-once --review-sha256`, and `baseline show`.
No fixture business code may run on the host. Python uses the profiler's actual
`python -m pytest` command; Node uses `npm run test` with `node --test`.

For every slot bind the immutable review, actual observation, source hashes,
command, native Docker handle, policy inspection and cleanup receipts. Check
fixture-specific output and exit code: a nonzero assertion/dependency result is
an observed baseline, never a successful business test or inconclusive result.
Assert unchanged target source, no model/patch/application claim, one consumed
authorization, one command dispatch, and released exact baseline resources.
Reopen state and use public show for durable report equality. Failure cleanup
uses only the test-owned baseline's reviewed recovery scope after its CLI child
has exited; never reuse the normal Run cleanup parser for baseline labels.

The optional image must be content-pinned, built from a tiny reviewed context,
contain Python/pytest plus Node/npm, and execute fixture commands with the
existing non-root/network-none/read-only/resource-limited provider. Preserve
Docker opt-in gates and run offline fixture/profile tests by default. This
cohort proves six generated baseline journeys, not six external business
repositories, the 24-task evaluation campaign or three paid first-task cold starts.

### Slice C frozen contract: native descriptor-bound SQLite qualification

This backend is independently implemented in an isolated worktree before any
production finalizer is enabled. Own only new `native/evaluation_vfs.c`,
`native/evaluation_vfs.h`, `native/evaluation_vfs_probe.c` and new
`tests/native/test_evaluation_vfs.py`. Root owns docs/build integration. Existing
terminal guards and all normal StateStore/read-capture paths remain unchanged.
Use the available trusted local C compiler and SQLite development library only
against disposable test fixtures. No runtime auto-compilation, installed dependency
upgrade, user-state mutation, provider or Docker. No compiled binaries in Git.

Implement a real private SQLite VFSv2, not a wrapper around pathname-based base
VFS auxiliary opens or SQLite syscall test hooks. Retain component-walked
O_NOFOLLOW directory descriptors and exact regular single-link file identities;
own main/WAL/journal opens and SHM map/lock/unmap/access/delete. Use SQLite's
documented POSIX lock ranges and public methods, with one connection per clean
child. Do not close duplicate descriptors for an inode while its locks are live.
No journal-mode conversion, exclusive-WAL substitute, /dev/fd shortcut, staged
publication, arbitrary attach/extension/temp-file escape or broad native loader.
Support existing DELETE and WAL databases and interoperable parent stdlib writers;
unsupported path/type/size/platform/method requirements fail closed.

Qualification must include ordinary commit/rollback/reopen in DELETE/WAL,
committed/uncommitted WAL and real concurrent writer contention, parent stdlib
locks unchanged by child exit/failed open/cancel, main/parent/WAL/SHM/journal
symlinks and regular-file swaps, no writes to outside sentinels, exact retained
native handle identity and absent child resources. Retain failures without
loosening assertions. Fixed probe/test SQL is trusted qualification code only;
the later product helper will expose no caller-provided SQL.

This is the native backend gate, not S1 finalization completion. Following an
independent PASS, freeze the package/child bridge and same-transaction observer
CAS + failure-only immutable insertion contract separately. Begin with the real
failed-CoS/no-Task/no-artifact fixture; external oracle/verified-success and all
post-Task cases remain later explicit acceptance. The finalizer may never be
enabled solely because a basic native read/write smoke passes.

### Slice A frozen contract: Session strategy rejection matrix

Writer owns only new `tests/integration/test_session_strategy_rejections.py` and
`tests/fixtures/session-journeys.json` in an isolated worktree. Root owns docs and
integration. No production edit, dependency, permission or validator relaxation.

Enter through real `ConversationService.submit`, Workflow, Planner and SQLite,
using an explicit fake CoS fixture only for proposed outputs. Freeze five illegal
shapes: direct requests code-change assurance; single Engineer claims independent
verification; Engineer/Verifier picks an ineligible verifier; parallel engineers
overlap write scopes; specialist plan references an undeclared role. Adjust only
the fixture encoding to actual domain fields, not the intended negative criterion.

For each strategy assert persisted failure, zero specialist invocation, child
Runs, worker leases, command effects and grants; unchanged target Git/config;
and a subsequent legal task in the same Session without rewriting old failure.
Keep the existing five-strategy success/plan-confirmation matrix. Verify manifest
references resolve and label these cases offline, not live/cold-start acceptance.
If a product defect appears, preserve the failure and request a new scoped repair
contract before source changes. Full default/static/package gates precede merge.

### Slice B frozen contract: explicit bounded single-canary selections

Writer owns `scripts/run_live_canary.py`, `tests/live_provider_support.py`,
`tests/conftest.py`, `tests/live/test_provider_smoke.py`,
`tests/unit/test_live_canary_launcher.py`, `tests/unit/test_live_provider_support.py`
and new `tests/unit/test_live_canary_selection.py` in another isolated worktree.
Root owns docs; no production adapter, persistence, schema or dependency change.

Add optional `--selection FILE`: bounded strict JSON with schema_version1 and
exact cos/engineer/verifier objects containing only runtime_name, provider_model,
credential_ref. Use existing production configuration validators and explicit
env: references. Reject fake, unknown fields, endpoint overrides, malformed/
unsupported combinations and unsafe credential variable collisions before output
directory creation, child launch or secret lookup. Preserve the exact old default
when absent: PydanticAI/OpenAI nano/FLEET_OPENAI_TEST_KEY for all three roles.

The child receives only validated role selections and their explicitly selected
credential values in a cleared allowlist environment. No ambient endpoint, proxy,
provider fallback or secret command-line argument. The smoke uses public profile
configuration/binding operations, freezes each role and verifies actual role/runtime/
model/usage identities. Scan all selected credential forms in persisted evidence
and output. Preserve structured verdict, CompletionGate, actual Docker command,
patch and cleanup assertions. Preserve the existing finite ROOT_LIMITS and
PROFILE_LIMITS,12 approval-loop ceiling, one whole attempt,900-second wall,
capture limits, no automatic retry/apply and original failure records.

Parse the selection once and pass bounded canonical JSON in
`AGENT_FLEET_LIVE_SELECTION_JSON`, never a mutable file pointer. Bind its digest
in attempt/evidence/summary and reject evidence from another selection. Reject
shared credential references or equal selected key values across distinct
provider families with a fixed safe error. Profile revisions and actual usage
must match all selected roles; pytest exit0 or skipped tests alone are not PASS.
Include actual offline public model set/bind and persisted binding inspection,
not only mocked CLI argv checks; their fake execution remains explicitly simulated.

Offline tests cover all admitted Provider/Harness combinations, invalid selection,
missing/conflicting refs, environment isolation, credential-form rejection,
single-attempt guard and no false pass. No live/Docker calls by the writer. This
is executable test infrastructure, not a six-task qualification result or proof
that any previously untested combination passed. Full default/static/package
gates and independent verification precede its own separate merge.

Slice B verification repair, September11: the first immutable candidate's focused
tests passed but independent adversarial probes found unsafe credential-variable
destinations (TLS/key-log, loader, shell, Git/Docker and telemetry controls) and
a blocking FIFO selection-file open. Reject credential references outside the
dedicated `FLEET_` namespace during parsing, preserving the legacy
`FLEET_OPENAI_TEST_KEY`; an incomplete OS-variable denylist is insufficient.
Open selection inputs with O_NONBLOCK and O_NOFOLLOW and reject non-regular
descriptors before reading. Add prompt FIFO/symlink/size rejection and prove
invalid variable categories fail before resolver/output/capture calls. All
other frozen interfaces, finite budgets and security assertions stay unchanged.
Retain the failed candidate and verifier evidence; freeze and independently
verify the repaired hashes before integration.

Slice B exhaustive-gate repair, September12: all4198 collected identities were
executed with no gaps/duplicates and548 unchanged source inputs, but one existing
release-prerequisite unit fixture still supplies the removed direct-pytest model/
credential variables instead of canonical selected-role JSON. Full result is
4174 passed/23 skipped/1 failed; all three integration groups, the serial
cancellation case and all static gates passed. Preserve canary-full-01 as FAIL.
Add only `tests/unit/test_release_prerequisites.py` to B ownership: update its
synthetic input fixture to the exact new selection contract, prove every required
input remains necessary, and reject malformed/legacy-only metadata. Keep the
ordinary network and model denial assertions. Do not change the seven accepted
B implementation/test files, production code, gating function or limits.
Freeze and independently verify this fixture-only repair before delivery.
For this test-fixture-only correction, reconcile a fresh whole repaired module
and current collection with the exhaustive run's other byte-identical modules;
exclude the entire old module, not only its failed case. Independently prove
the other547 source/test inputs unchanged and no importer of this test module.
Run fresh static and post-documentation package gates. Label carried-forward
cases as such, never as re-executed; the original exhaustive run stays FAIL.
Any changed production/helper/source dependency invalidates this shortcut and
requires full replay. The later combined baseline candidate still gets a fresh
exhaustive run of every current identity before final delivery.

Mixed-Canary fixture repair, September12: the single authorized attempt
openai-mixed-live-01 ended NOT_PASSED in10.523s with complete cleanup. Explicit
three-role profile set/bind succeeded, but the shipped catalog contains five
roles. With no default, architect/researcher lack bindings; Workflow resolves
the complete catalog before preflight/target Run creation and correctly raises
CONFIG_INVALID. Independent path/ledger review (mixed-canary-diagnosis.BigTA9)
found only the fake bootstrap and zero target Runs/model requests/bindings.
This proves no target model dispatch, not API-key validity or live qualification.
Retain the attempt as consumed; no automatic retry or model fallback.

Freeze a test-fixture-only repair in `tests/live/test_provider_smoke.py` and
`tests/unit/test_live_canary_selection.py`. Factor/reuse the actual public
profile configuration sequence if needed. Explicitly bind the reviewed CoS
profile as default for the two nonexecuted ancillary catalog roles, then preserve
all three exact primary overrides (revision4). Assert the default mapping and
the actual initialized five-role closure; do not remove roles from production
resolution or relax missing-binding rejection. The canary may observe only its
three execution-role kinds; defaults are configuration completeness, not new
execution permission. Extend offline tests through real default FleetSpec and
Workflow admission (offline controlled transport only), preserving per-role
freeze, budgets, provider denial, cleanup and no-false-pass assertions. Root
updates the guide to disclose this deterministic ancillary-default policy.
Freeze both hashes; independently verify the repair and all actual importer
tests. No further live attempt is authorized by an automatic fixture retry;
root must record any additional finite attempt as a separate manual decision.

After the exhaustive offline/static gate, root may run exactly one mixed-Harness
OpenAI canary: CoS=PydanticAI, Engineer=OpenAI Agents SDK, Verifier=LangGraph,
all explicitly bound to `openai:gpt-5-nano` and the one authorized dedicated
OpenAI credential. Preserve the existing 12-invocation/24-request/32-tool/
65,536-reported-token/600-active-second root envelope and 900-second launcher
wall; one whole attempt only, with no automatic restart or fallback. This is
a finite smoke, not a dollar spending cap or authorization for the complete
qualification campaign. Credentials enter via hidden transient input in a
trusted parent, reach only the selected child environment, and are never
serialized. Preserve every failed/unknown result and exact cleanup evidence.

Use the existing pinned environment, cleared credential-free environment for
ordinary tests, and new private basetemp/JUnit paths for every run. Record exact
expanded commands and terminal results in evidence; commands include:

```text
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src tests scripts/run_live_canary.py
.venv/bin/python -B -m agent_fleet.schemas.generate --check
uv lock --check --offline --python .venv/bin/python
git diff --check
.venv/bin/python -B -m pytest -q
```

For full runs reconcile all collected identities against disjoint partitions in
`docs/session-first-test-partitions.json`; include newly added files exactly once.
Run the existing timing-sensitive cancellation regression after heavy workloads
stop. Optional Docker/install/live gates remain separately recorded, never
converted from skips to passes or summed as disjoint business tasks.
Refresh `tests/integration/test_distribution.py` after final README/guide edits.
Exact release/readback details are recorded per slice below.

## Rollback and recovery

No resets, broad cleanup, force pushes, branch deletion or evidence deletion.
Preserve permanent execution reservations and unknown dispatches. A schema change
requires forward compatibility/migration tests, not a user-data downgrade.
Candidate failures retain evidence and yield a new candidate after repair;
independent verification never edits its candidate or weakens the oracle.

## Progress

- [x] September12 final B documentation/package refresh: the exact updated
  Foundry README, selection guide, known issues and acceptance ledger preserve
  the distinction between offline infrastructure PASS and mixed live02 FAIL.
  Credential-free `.venv/bin/python -B -m pytest -p pytest_asyncio.plugin -q
  tests/integration/test_distribution.py`, with unique private basetemp/JUnit,
  returned1passed/2.85s, exit0. Both rebuilt archives match current332 package
  resources/current README; installed resource smoke passed. Evidence:
  canary-final-package.j41UcnnR/results.xml. No production, dependency, schema
  or workflow changes entered B. Final independent doc/diff readback and
  staged GitHub delivery remain pending.
- [x] September12 reconciled Slice B full acceptance (canary-full-03):4181
  passed,23 explicitly optional skips,4204 exact collected/JUnit identities,
  zero missing/extra/duplicate/failure/error records. All548 source inputs are
  unchanged. Integration partitions249/264/251 and default-other3415/23 precede
  both original serial cases (wall16.403791s and20.625948s). Six static gates
  passed: Ruff472 files, mypy392, schemas, offline lock and whitespace. Independent
  terminal readback also matched620 held files and both package archives'332
  current resources plus current README. Original interrupted/full-failure
  records remain separate; this is a new exhaustive replay, not their overwrite.
- [x] September12 separate manual decision after that independent PASS: run
  exactly one additional mixed-Harness canary (openai-mixed-live-02), using the
  already reviewed selection digest0ed325d81f65ee619a0f114fee838e89972d7de57202a5347b034a8fc95a2e0d.
  CoS=PydanticAI, Engineer=OpenAI Agents SDK, Verifier=LangGraph; all OpenAI nano.
  Reuse only the owner-authorized key through hidden transient input. Keep the
  exact12-invocation/24-request/32-tool/65536-reported-token/600-active-second
  limits,900-second wall, one whole attempt, no fallback/retry/apply. This is
  not a dollar cap or a full campaign. The first predispatch failure remains
  consumed and retained. Inspect this attempt's actual result and exact cleanup
  before any later decision; do not infer completion from process exit alone.
- [x] September12 mixed live02 completed **NOT_PASSED**: one attempt from
  09:24:18.047687Z to09:25:00.076977Z, launcher42.03s, pytest1failed/40.29s
  with13 SDK deprecation warnings. Target run_a9580c06384644688ea9bf3ec1bed908
  reached implementing: CoS completed one real request (4681input+4077output=
  8758reported tokens), then Engineer failed with PROVIDER_FAILED,
  provider_sdk/response_policy. Two invocations/two request reservations,
  one unknown request/32768 unknown-token reservation, zero target tools,
  no command evidence/patch/Verifier. Total charge remains unknown. All five
  selected bindings persisted at revision4. Normal stop and cleanup report
  complete, zero outstanding leases; independent terminal audit remains separate.
  The scripted bootstrap's two Docker commands are not target evidence.
- [x] September12 independent live02 terminal audit at09:35:07Z confirmed FAIL
  for the target and complete later physical cleanup: all8 leases released
  (2target/6bootstrap),3 workspace paths absent,2 retained native container
  identities absent on the matching daemon, installation-filtered inventory
  empty. All receipt hashes validate. Exact stopped SQLite admission and
  immutable SELECT readback preserved database identity and created no sidecars.
  Target Git baseline/five tracked files, original evidence and620 candidate
  files remained unchanged. Keep the pre-cleanup failure bundle unchanged;
  it does not become a successful delivery from later cleanup. Evidence:
  mixed-live02-verifier.hpQt3D/VERDICT.md, alongside the original failed attempt.
- [x] September12 read-only response diagnosis narrowed the matching guards to
  SDK ModelBehaviorError, response identity/terminal-state/error validation,
  and raw JSON/usage validation. Current evidence cannot identify which field
  failed. Alias versus dated-response identity is only an offline hypothesis.
  Keep exact identity, endpoint, body/header, budget and tool guards unchanged;
  no live03 or automatic retry has occurred. A distinct bounded diagnostics
  slice must precede any separately decided additional paid attempt.
- [x] September12 continuation reconciled the independently merged Foundry PR9
  (`09c5a64`) and the renamed GitHub remote. Preserve its public README, Apache
  license and specification/link changes. The interrupted canary-full-02 has
  only one terminal integration group (251 passes) and six passing static
  checks; no terminal summary or after-freeze exists. Three frozen inputs
  changed in PR9 (package metadata, CLI presentation, runner README), so this is
  **interrupted**, not current full acceptance. No failed or partial evidence
  is removed. A new canary-full-03 runs all default identities and six static
  gates on the reconciled candidate, with the two unchanged timing-sensitive
  cases serialized after the heavy groups. No other heavy test jobs run beside
  it. Subsequent documentation changes require a fresh package smoke.
- [x] September11 owner scope and staged GitHub delivery authorization captured.
- [x] Fresh remote/local main identity and clean worktree confirmed.
- [x] Separate read-only evaluation, Session and runtime investigations started.
- [x] Credential presence checked without exposing values; missing provisioning
  and total live budget requested without stopping independent development.
- [ ] Freeze first implementation contracts and complete their acceptance.
- [x] Slice A frozen implementation has exactly two paths: new257-line Session
  rejection test SHA0369281a and20-line journey-manifest addition SHAd5790adf.
  Main integration preserves both hashes and all production bytes. Worker new
  matrix5/8.87s and positive+negative10/48.47s passed; earlier focused42/95.051s
  passed. An initial /tmp fixture setup failed before product execution; its
  evidence is retained, and subsequent basetemps use the project-shared volume.
  Fresh independent verification passed22 focused cases plus real boundary and
  five SQLite/full-event immutability replays. Nine manifest references resolve
  to21 collected cases with zero missing; candidate bytes remain unchanged.
  Exhaustive default/static gate passed:4098 passed/23 optional skips,4121 unique
  collected and JUnit identities, zero gaps/duplicates/failures/errors; all547
  source/test inputs are unchanged. Disjoint integration groups249/264/251 and
  default-other3333 plus23 skips precede the final single cancellation case.
  All six static gates passed. Private evidence: session-full-01 (exact argv,
  process status/timestamps, JUnit, source maps and summary) and independent
  session-verify-A.PgmWXB. No merge or whole-S2 acceptance is implied yet.
  The exact root integrated source/manifest hashes match that candidate. After
  README/plan updates, `python -B -m pytest -p pytest_asyncio.plugin -q
  tests/integration/test_distribution.py` passed1/8.69s with a new private
  basetemp/JUnit (session-package-01). The source diff and secret/machine-path
  scan are clean; production, dependencies and shared fixtures are unchanged.
- [x] Both implementation worktrees received separate copy-mode offline/frozen
  environments:96 pinned distributions, Python3.14.6, no metadata or main runtime
  changes. Candidate-local import origin verified.
- [ ] Slice B explicit live selections are being implemented in a separate
  worktree; no credentials or provider/Docker calls by its writer. First frozen
  candidate bd4a7a73 passed79 focused tests/one expected live skip, but independent
  adversarial verification identified the credential namespace and FIFO issues
  above. It is not accepted or merged.
  Repaired candidate27df532f now restricts destinations to the dedicated FLEET_
  namespace and uses nonblocking regular-file admission. Fresh independent
  verification passed116 focused cases/45.68s,34 unsafe-name rejections, four
  safe names, ten malformed metadata probes and all six SQLite binding
  readbacks; FIFO rejection took0.0893s. All seven file hashes were unchanged.
  Evidence: canary-reverify-B.6tQYRZ. Full/static/package gates and delivery are
  still pending; no live qualification is inferred.
  The exhaustive run subsequently ended with the one obsolete prerequisite
  fixture failure recorded in B's repair contract above. Its frozen replacement
  SHAa2ddd60b passed10/0.04s for the writer and10/0.02s independently. Fresh
  collection is4201; independent comparison confirms exactly one changed input
  out of548 and the other547 unchanged. Evidence: release-prereq-B.qA9oW9 and
  release-prereq-B-verify.qhKNQc. Complete the explicitly labeled source-closure
  reconciliation and fresh documentation/package gate before delivery/live.
  That reconciliation subsequently passed4178 with23 skips across4201 exact
  identities:4167 carried-forward passes/23 skips, ten fresh prerequisite cases
  and one fresh package case/4.19s. Six refreshed static gates passed, including
  mypy392 files. This is an explicit composite, not a second full re-execution.
  The first manually initiated mixed-Harness attempt then failed before target
  dispatch (openai-mixed-live-01, started07:23:56UTC September12; launcher10.523s,
  pytest1 failed/8.94s). The five-role initialized catalog lacked ancillary
  bindings; production correctly rejected architect before creating a target
  Run. Independent mixed-canary-diagnosis.BigTA9 found only fake bootstrap and
  zero target model requests. Cleanup is complete. Preserve the consumed attempt;
  it proves neither key validity nor mixed-Harness inference. The new two-file
  fixture-repair contract above supersedes prior B acceptance for those bytes;
  fresh independent and integrated gates are required, without guard relaxation.
  The mixed-role repair is frozen at live-test30cefb0c / selection-testca7529eb.
  Writer gate passed56 with1 live opt-in skip/14.31s and scoped statics. It uses
  the same public setup helper in the live and offline cases, freezes all five
  roles and proves the old revision3 no-default configuration fails before Run,
  binding or invocation effects. Legacy revision1 remains covered. Evidence:
  agent-fleet-mixed-canary-repair.rUT3xf, including retained intermediate errors.
  A new exhaustive root candidate gate (canary-full-02) now replaces source-closure
  reuse for these changed helper bytes. Its two original timing-sensitive cases
  run once after heavy groups: cancellation and successful baseline Session;
  no assertions/deadlines change. Source/docs stay frozen during this gate.
- [ ] Slice C native qualification implementation assigned after the Session
  writer's file freeze; the production finalizer guards remain unchanged.
  Its latest retained native JUnit has20 passes/1.538s, but does not cover the
  final tombstone verification-to-unlink race. The implementation turn ended
  with a tool-side security restriction before final qualification/verdict.
  This experimental candidate stays unmerged and is NOT_GO for production.
- [ ] Slice D has a frozen six-generated-repository contract and separate
  worktree. Fixture/profile default checks passed7 with6 optional Docker skips;
  the first actual Node public CLI/Docker baseline journey passed1/112.10s.
  Full cohort and independent acceptance remain pending. No live models used.
  First full cohort trial failed6/658.63s because its new spent-retry assertion
  wrongly required exit2. Production correctly returns the identical retained
  result with its original exit0/1 and no redispatch. Preserve that trial and
  correct the test to assert exact result equality and one command lease.
  Final cohort will also assert Slice E's public observation body; no production
  retry semantics are changed and these failures are not counted as passes.
  D-only independent static review then rejected three test-oracle issues:
  installation-wide normal-Run cleanup, missing exact reviewed command-body
  assertions, and rejecting legitimate business tracebacks inside JSON stdout.
  Preserve the rejected cohort source as baseline-D-static-failed-01.py.
  Repair only those test behaviors: exact public baseline recovery without
  a Run sweeper; typed command reconstruction and exact executable/argv/cwd/
  empty-environment/network-none checks before consent; CLI-stderr traceback
  rejection plus strict JSON parsing and unchanged business-output assertions.
  Re-review the repaired D bytes before final six-case execution. E production
  bytes, failure semantics and resource boundaries stay unchanged.
  Independent D-only re-review accepted the repaired cohort SHA13cd8489
  with all three issues closed; the other five D-file hashes are unchanged.
  This is static acceptance only. The integrated candidate passes Ruff and
  mypy395 files; final Docker/default/package gates remain pending.
  Six real Docker cases subsequently passed295.59s on the integrated553-input
  candidate (baseline-cohort-docker-02). These normal-exit results remain valid,
  but an additional exceptional-path review found that hard-killing the CLI
  group cannot stop separately-sessioned Docker/Git clients. The test must not
  infer whole-child quiescence or automatically invoke stopped-owner recovery
  after its watchdog/interrupt. Freeze this D-only repair before delivery:
  transfer sole ownership of the cohort test and its existing fixture unit-test
  module to one writer; introduce an explicit hard-termination distinction,
  preserve/reap only the owned CLI group, and fail with retained state without
  automatic show/recover after unknown quiescence. Normal completed CLI paths
  retain exact public recovery. Raise only the external test watchdog above the
  product's300-second attempt ceiling with bounded cleanup grace (360 seconds);
  do not alter product limits, Session's30-second assertion or result semantics.
  Add offline watchdog/interrupt/no-recovery regressions without real commands;
  then independently review and rerun the six-case cohort on repaired bytes.
  Preserve all prior source hashes/results. No E production or B file changes.
  The hard-stop repair is frozen: cohort e6185253, unit bef8f5da. Writer checks
  passed13/0.83s with scoped Ruff/mypy. Evidence: baseline-D-hard-stop.2mJLbi.
  Fresh independent review is running; root started a new exact-source six-case
  Docker replay (baseline-cohort-docker-03). The earlier normal-path six passes
  do not accept the changed exceptional paths.
  Independent hard-stop review then found another concrete exception boundary:
  communicate can return normally with a negative signal return code. The helper
  left that owner KNOWN and could invoke show/recover after SIGTERM/SIGKILL.
  Preserve baseline-D-hardstop-verify.M4dJdW as FAIL and the frozen e6185253 /
  bef8f5da files until the in-flight normal cohort ends. Freeze the next two-file
  repair: immediately mark any negative CLI return code UNKNOWN before output
  parsing and fail the test; do not kill an already-reaped child or invoke public
  show/recover. Regress both valid-JSON and empty-output signal exits, the full
  helper/finally path and ordinary nonzero business observations. No production,
  model, watchdog, recovery scope or existing result assertion changes.
  Root takes sole ownership of this final D two-file repair after Docker-03
  ended: six normal journeys passed210.24s, all553 inputs unchanged. Original
  e6185253/bef8f5da sources are retained separately; physical readback may inspect
  only that terminal evidence while the new test-only repair proceeds.
  The new signal repair is frozen at cohort0a155070 / unit64f41ae7:23 offline
  cases passed0.74s, Ruff470 files and mypy395 passed. Six signal/output pairs
  exercise the actual helper and finally recovery boundary; four ordinary
  exit-code controls preserve0/1/2/3 behavior. An initial scoped-mypy invocation
  stopped before tests for import discovery and an incompatible list comparison;
  its record is retained. The comparison was split without relaxing assertions,
  and the required whole-source mypy command passed. Independent re-review and
  final repaired-byte Docker execution remain pending.
- [ ] Slice E's additive validated public observation field is assigned in an
  isolated worktree; it is the only production extension to the baseline cohort.
  Its eight-file candidate is frozen (manifest02a5de2b):48 focused tests passed
  in1045.10s; Ruff format/lint, mypy390 files, schema/offline lock/diff gates
  passed. Independent corruption/identity/output/read-only verification is
  pending; writer checks alone are not acceptance. Root overlaid all eight
  exact hashes into the separate A+B+D+E cohort candidate. Its fixture/profile
  check passed7/2.97s with6 explicit optional Docker skips (baseline-focused-03);
  the corrected final real-Docker cohort has not run yet.
  Independent E focused gate is FAIL:13 passed/1 failed in482.92s. The existing
  successful Session journey hit its unchanged30-second completion-marker
  deadline after baseline run, before output assertions/show. At failure the
  durable execution was still executing with no observation/report, one consumed
  authorization and three synthetic leases; the owned CLI child was killed and
  reaped by test teardown. Root cause is unproved, not assumed to be CPU load.
  Twelve corruption/identity probes and same-transaction/read-only checks passed.
  Preserve this failure and all hashes. After B's full/serial jobs stop, permit
  one isolated unchanged-case diagnostic with a new evidence directory and the
  same30-second assertion; no timeout increase, assertion relaxation or automatic
  retry. D final and combined baseline acceptance remain held pending diagnosis.
  The one isolated unchanged Session diagnostic passed1/16.26s with its original
  deadline and all output/show assertions. Durable state is observed, exit0,
  retained output correct and all three leases released; original timeout cause
  remains unproved. Evidence: baseline-E-isolated-diagnostic.snVPpX. Final
  combined test orchestration defers this case, like the existing cancellation
  regression, until heavy groups finish; neither test nor product timeout is
  changed. Exact collection/JUnit reconciliation must still include both once.
  Independent E functional verdict is PASS for the fourteen distinct focused
  behaviors plus transaction/corruption/privacy invariants; its prior13/1FAIL
  and unknown timeout cause remain explicit, with no stress/reliability claim.
- [ ] Deliver each accepted slice through commit/push/merge and exact readback.
- [x] Slice A delivered: commit8a06ce3362720f4222e5666fae42671e2c5781c7,
  PR8 merged2026-09-12T06:36:48Z as3bcf735329d4af312c3fe58f408b3f10f901b29e.
  Exact head/merge trees match; fetched local/main and remote/main agreed, with
  a clean root worktree before the next branch. GitHub Actions returned0 runs
  for both SHAs; every commit/merge used `[skip ci]`, with no workflow dispatch
  or protection changes. This is local verification, not remote CI success.
- [x] Root integrated all seven repaired Slice B files with exact verifier
  hashes on a new delivery branch based on the accepted PR8 merge. Added the
  public selection guide and preserved Slice A test/manifest hashes. The
  exhaustive candidate gate uses the same combined A+B source/test bytes.
- [ ] Finish all available P0/P1 acceptance and report residual external blockers.

## Discoveries

- Original evaluation finalization is blocked by a concrete filesystem/SQLite
  boundary, not an absent API key; read-side acceptance cannot turn it on.
- Current live infrastructure does not exercise selected mixed Harness roles,
  despite their existing offline implementations.

## Decision Log

- September11: preserve original S1/S2/S3 numerical criteria and scope; explicitly
  exclude the deferred productization work from this continuation.
- September11: use pinned dependencies first; qualify any necessary native
  backend separately before changing the production write boundary.
- September11: the owner explicitly renewed use of the previously supplied
  OpenAI key. Transient use only, with no worker/log/repository exposure and no
  unbounded paid campaign; other-provider credentials remain unavailable.

## Outcomes

Slice A's five Session rejection/continuation cases and all applicable default
and static gates have passed. Tests-only scope preserves every production byte,
permission and validator. Its final documentation/package check passed1/8.69s;
GitHub PR8 is merged with exact tree/ref and zero-Actions readback as above.
Slice B's repaired candidate passed independent offline
verification, and its reconciled full03 gate passed4181/23 with4204 exact
identities and548 unchanged source inputs, including Slice A's frozen tests.
All six static gates and current-source package inspection passed. Final
documentation/package refresh passed1/2.85s. GitHub delivery remains pending here.
The actual mixed live02 attempt failed at the Engineer response-policy boundary,
after a successful CoS request and before tools/patch/Verifier. Its unresolved
usage is not zero cost, and its bootstrap is not target success. Baseline D/E,
same-process Session repair F and native P0 status remain separate; no full
P0/P1, mixed-Harness qualification or remote-CI completion is claimed.
