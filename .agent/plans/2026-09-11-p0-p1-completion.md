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
- [ ] Slice E's additive validated public observation field is assigned in an
  isolated worktree; it is the only production extension to the baseline cohort.
- [ ] Deliver each accepted slice through commit/push/merge and exact readback.
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
GitHub delivery is next. Slice B's repaired candidate passed independent offline
verification, and its integrated exhaustive gate now also includes Slice A's
exact frozen test/manifest bytes. Baseline D/E and native P0 status above remain
separate; no full P0/P1, paid-model or remote-CI completion is claimed.
