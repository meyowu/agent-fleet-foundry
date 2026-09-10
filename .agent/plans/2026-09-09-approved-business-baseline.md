# Approved one-command business baseline — S2.1b

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log and Outcomes. Its first implementation slice is approved below; physical acceptance and Session integration remain explicit later gates. The original clone-only contract and its history are retained. After independent acceptance, the root-only main-integration contract at the end authorized the exact45-file transplant at21:51:44UTC. Main code is now frozen at30b8f476 for combined gates; clone implementation authority does not permit further main edits.

## Purpose and user-visible result

An initialized project's user can review one configured verification command, approve its exact scope once, run it against a private read-only snapshot without any model, and inspect durable bounded evidence of the existing project's outcome. A nonzero command is an observation, not a diagnosis of a code defect. This does not create a CoS/Engineer/Verifier, TaskSpec, Run, patch or EvidenceBundle.

Example: `fleet baseline plan . --command python-test --json`; inspect the returned review and its SHA256, then `fleet baseline run REVIEW_ID --allow-once --review-sha256 SHA --json`, followed by `fleet baseline show BASELINE_ID --json`. These commands are intended behavior until the acceptance gates below pass.

## Scope

### In scope for the first coherent slice

- Complete standalone CLI plan/run/show/revoke/recover lifecycle, model-free composition, exact user-owned permission control, separate baseline owner/lease/dispatch persistence, Git snapshot materialization, read-only Docker command transport and immutable redacted observations/reports.
- Additive schema-13 migration and compatibility/regression tests. Preserve existing Run schemas, ordinary Workflow/resource APIs, all model/provider adapters and existing evaluation terminal-write containment.
- Existing registered, committed and clean projects only; one configured command; explicit Docker with a preloaded image and exact daemon identity. No implicit preparation or dependency installation.

### Out of this first slice, but still unfinished S1–S3 work

- Session `/baseline plan` → existing one-use `/confirm` → `/baseline run` UX is a subsequent slice after this controller/store/Gateway path passes. Do not pretend the standalone UUID/hash path is the final Session UX.
- Six actual Python/Node baseline repositories, three cold starts and independent real-model first-task completion require later preregistered physical acceptance. Node image qualification is absent.
- S1 external oracle/finalization/campaign, new Harness live campaigns, other provider credentials and GitHub merge remain separate. Do not reopen disabled evaluation finalizers.
- No model calls, credentials, Docker execution, image pull/build, dependency install, network, external writes, package release or Git mutation by the implementation Writer. Offline SDK/transport test doubles are allowed and must not be described as physical acceptance.

## Original repository state and isolated ownership (historical)

This isolated local clone starts at commit `864ad43de7c653d0307907d0d82f36eddab2394d` on branch `codex/s2-business-baseline`. The main checkout independently tests a later two-file strict OpenAI output change. Do not edit the main checkout, its `.venv`, its index or any of its evidence. This clone avoids changing the main checkout's Git worktree registry. Its origin points to the local source checkout: never push to that origin.

The main source/test/dependency checkpoint `092b8228` is frozen for its own full matrix and independent review. Those results do not accept baseline development in this clone. Baseline integration needs a separate reviewed patch and final main-candidate gates.

Current SQLite version is 12. Existing resources and dispatch claims require real Run/Task/Agent/stage identities, and the existing Docker `/workspace` bind is writable. Neither nullable IDs nor a fake Run is a valid baseline shortcut. The accepted evaluation observer uses a clean read-only capture child; both final-write entry points remain disabled.

## Security impact

Every project command goes through a new typed entry on the existing ToolGateway, the existing PolicyPermissionBroker's new baseline method, exact once-only persistence and Docker. CLI/BaselineService must not call a provider executor directly. Model tools cannot select baseline ownership or obtain its dependency bundle.

Repository configuration may request a command but cannot grant it. User denies and hard safety ceilings remain authoritative; project/role rules, trust modes and Always-Allow cannot replace explicit baseline allow-once consent. Never reuse the historical Phase-1 class named BaselinePermissionBroker as a new authorization shortcut.

No SecretStore/RuntimeRegistry/model factory is constructed or resolved by the standalone baseline composition. No ambient credential/environment copying, shell interpretation, worker Docker socket/home/credential mount, network or LocalUnsafe fallback. Source is physically read-only in Docker; fixed bounded scratch is separately inspected. Hostile same-user host processes are not stopped by application locks or SQLite CAS; do not claim unseen host ABA detection or absolute filesystem atomicity.

## Proposed design

Use baseline-owned sibling DTOs and additive internal protocols, not a public owner union or widened legacy models. The normative owner/lease/transport appendix below is part of this contract. Its immutable snapshot, source-manifest, redaction, no-replay and cleanup requirements are mandatory, not future placeholders.

BaselineService coordinates a separate BaselineStore with existing configuration/project/repository/trust primitives and a baseline dependency bundle on ResourceService/ToolGateway. `build_baseline_container` only constructs this model-free graph. Missing baseline capability fails before a permanent owner claim or resources.

Planning persists an immutable review and planned BaselineExecution for an already registered project. An unknown project or unknown command is a fixed safe admission error, not an invented Project/Run. Known commands with missing image/daemon prerequisites may produce a not_ready review, which cannot be approved. A ready review binds the canonical committed source manifest and exact command/configuration/policy/image/daemon/mount/resource limits before approval.

The run call revalidates that review and current policy under the existing cooperating-project publication guard, consumes one exact authorization and permanently claims its controller owner before worktree creation. Every allocation has a prior exact lease. Gateway derives the command from persisted immutable review bytes, verifies the actual materialized source and scope, and makes one permanent dispatch claim. Approval and claims cannot be recreated by restart, absence of a container, expiry or an unknown result.

Normal/error/cancellation cleanup self-fences the joined owner and fixes its whole lease set. Stopped-owner recovery uses a different reviewed cleanup claim; it cannot expand its targets or dispatch a command. Record a controller PID owned by this local installation at claim creation; a user flag or timeout alone is not proof it stopped. At minimum recovery must conservatively reject a still-existing/inaccessible/unknown controller PID, including reuse; a read-only existence check must never signal/kill an unrelated process. Baseline state is local-machine-only; no remote/shared-state recovery claim. Unprovable ownership remains recovery_required. Preserve exact same-process normal drain independently of stopped-owner recovery.

## Public contracts

- `fleet baseline plan [path] --command COMMAND_ID [--json]`: inspect configured scope and persist review; never execute project code, install or pull an image. Show exact nonsecret argv/cwd, limits and immutable identities; escape terminal controls/markup.
- `fleet baseline run REVIEW_ID --allow-once --review-sha256 SHA [--json]`: both consent arguments required. Without them report REQUIRE_APPROVAL without resource/command effects. Repetition returns the existing baseline/report or recovery_required, never a second dispatch.
- `fleet baseline revoke REVIEW_ID [--json]`: revoke only unconsumed authorization/review. A consumed grant is not cancellation; report that honestly.
- `fleet baseline show BASELINE_OR_REVIEW_ID [--json]`: validated persisted review, execution, current report and exact recovery-scope hash. Never create resources or silently repair state.
- `fleet baseline recover BASELINE_ID --owner-stopped --cleanup-sha256 SHA [--json]`: explicit exact-snapshot cleanup only after genuinely stopped-owner checks and whole-set CAS. No replay or broad sweep.
- Exit 0: complete zero-exit observation and complete cleanup. Exit 1: actually observed nonzero with complete cleanup. Exit 2: invalid/not-ready/denied. Exit 3: unknown/inconclusive/recovery_required. No exit code means VERIFIED_COMPLETE.

Public strict/frozen models are BaselineReview, BaselineAuthorization, BaselineExecution, BaselineReport and the necessary bounded show/recovery views. No run_id/task_id/agent_id/stage fields. IDs are distinct: `breview_`, `bauth_`, `baseline_`, `bclaim_`, `bws_`, `bsandbox_`, `bexec_`, `blease_` followed by 32 lowercase hex digits; observed/report content IDs use the SHA256 prefixes in the appendix. Review hashes exclude their own derived hash field, not any authority-bearing field.

Review TTL is five minutes; one use; canonical review <=128 KiB, command output <=64,000 retained bytes, report <=256 KiB. One command, one worktree/sandbox/execution, network none, at most 180 command seconds/300 attempt seconds, one CPU, 512 MiB memory, 64 PIDs and 256 MiB private scratch; lower configured ceilings win. Cleanup is bounded and incomplete drain must retain recovery_required rather than claim release. Empty configured command and sandbox environments in v1; only fixed reviewed transport scratch settings. No arbitrary metadata dictionaries or retained mutable legacy models in authority DTOs.

## Persistence and migration compatibility

Freeze exactly these ten new tables for migration 0013: baseline_reviews, baseline_authorizations, baseline_executions, baseline_owner_claims, baseline_dispatch_claims, baseline_resource_leases, baseline_command_observations, baseline_reports, baseline_cleanup_receipts, baseline_events. Use ordinary DDL/indexes/constraints, no triggers or migration-parser changes. BaselineExecution may exist as planned before consent, but only a permanent claimed owner can allocate or dispatch. Review creation binds its planned baseline ID; no circular self-hash. Every indexed identity/payload/hash is cross-validated on read and CAS.

Existing tables/rows and migrations 1–12 stay unchanged. Increment only the actual supported-version constant and append migration 13. Update three historical fixture constructors narrowly: migration12 rollback test must genuinely reconstruct v11/remove all new tables and >=12 markers; the schema7 config/release-upgrade copies must drop every new baseline table before deleting >=8 markers. Preserve all their meaningful assertions and failures; never weaken SQL idempotency/validation to accommodate a broken fixture.

The evaluation capture helper imports the supported-version constant: no new numeric allowlist or production projection change is needed. Keep baseline BLOB tables out of its Run/evaluation semantic fingerprint. Test migrated v12 Run observations, quiescent unrelated baseline-row invariance, conservative concurrent-write rejection and unchanged 32 MiB per-file/128 MiB capture limits. BLOB growth may hit these limits; document it. New child requires complete schema13; old schema12 child rejects13. A monkeypatched constant is not actual old-binary proof; root separately qualifies a frozen old distribution. Normal migrating composition rejects a future DB, but this does not imply every low-level read has a version gate or zero WAL-side effects on refusal.

## Milestones and acceptance

1. Complete importable controller/store/owner/permission/Git/Docker/CLI slice, not empty protocols or commands. Offline positive journey must exercise plan → exact consent → one dispatch → redacted immutable report → idempotent show/repeat, with no model or credential resolution. Explicit Fake/LocalUnsafe cannot be admitted as physical baseline providers.
2. Negative and compatibility tests cover the full appendix, genuine process claim races, revoked/stale/mixed scopes, source/config/materialization drift, all creation crash windows, repeated cancellation, whole-lease-set cleanup CAS, partial cleanup, secret/control escaping, immutable report conflicts and schema13 migration/legacy preservation.
3. Freeze a candidate; run focused and affected whole modules plus static/schema/lock checks; fresh independent verifier checks actual persisted state/artifacts and distinguishing adverse controls. Main integration and full default/package/optional gates are separate. No physical baseline or S2 completion claim before the root-owned real Docker acceptance.

## Detailed implementation steps and ownership

One Writer owns this clone only and these source paths under src/agent_fleet: new domain/baseline.py, domain/baseline_resources.py, ports/baseline.py, ports/baseline_resources.py, application/baseline.py, adapters/persistence/baseline.py, cli/baseline.py; additive scoped changes to application/gateway.py, resources.py, permission_policy.py, sandboxes.py, adapters/repository/git.py, adapters/sandbox/docker.py, bootstrap.py, cli/app.py, adapters/persistence/sqlite.py, the new migrations/0013.sql, and schemas/generate.py plus only newly generated baseline schema files. Add a narrowly named helper only when an actual implementation need is first recorded in this plan. Do not edit runtime adapters, existing domain/models.py semantics, ports/state_store.py, old Run schema bytes, Fake/LocalUnsafe or evaluation finalizers.

Owned tests: new unit/test_business_baseline.py, contract/test_baseline_store.py, contract/test_baseline_sandbox.py, integration/test_business_baseline.py and e2e/test_business_baseline_cli.py plus narrowly scoped new baseline owner/Gateway/recovery tests. Existing test_docker_sandbox/test_resource_cleanup/test_schema_generation may receive additive controls. The three legacy fixture constructors and new migration/observer compatibility coverage may change only as described above; keep release/installed baseline-table additions separate from actual installation evidence. Root owns README, guide, SECURITY_MODEL, architectural decisions and main plan; Writer updates this plan's living results. Any broader path change requires an explicit amendment before edits.

Start by inspecting exact seams and enumerating guard/store paths, then implement deeply immutable DTOs and complete transactional store together; add typed repository/Docker/ResourceService/Gateway/Broker integration; wire standalone model-free CLI only when the cluster is executable. Test the full positive/negative journey, not only mocked call counts. Keep all source compatibility and failure evidence.

## Validation plan

Root-owned isolated-runtime preparation is approved before installation: assess a separate clone-local `.venv` using exactly the unchanged `pyproject.toml`/`uv.lock` dependency closure. Root runs an offline dry-run first, disables Python downloads, makes no network call, and stops if required artifacts are missing. Never alter the main environment or weaken subprocess test origin checks. Preparation is not test acceptance and may bind only dependency/package metadata until the complete clone source is frozen. The Writer continues using the explicitly selected clone imports and does not install or mutate either environment.

Use the already installed exact dependency environment with PYTHONPATH explicitly selecting this clone's src and cwd selecting this clone. Verify loaded module origins before interpreting results. Never install into the shared environment, invoke uv sync, or treat the main checkout's editable installation as this candidate. Every subprocess has a minimal credential-free environment, PYTHONNOUSERSITE=1, UV_OFFLINE=1 and live/Docker/install flags=0. Own each private test basetemp; preserve logs/JUnit, exact expanded commands and source/dependency digests. Do not run a heavy full suite concurrently with the root main matrix; fast focused tests are allowed, and root coordinates larger gates.

Required static equivalents: ruff format --check .; ruff check .; mypy src tests scripts/run_live_canary.py; python -m agent_fleet.schemas.generate --check; uv lock --check --offline; git diff --check. All prior108 schema bytes and dependency/lock bytes must remain unchanged. New exported baseline schemas must agree exactly with code. Final default collection must include every new identity; old failures must not disappear through deselection.

Physical later qualification preregisters six generated committed Git repositories: prepared Python unittest, absent Python dependency, preexisting Python assertion failure; prepared Node node:test, absent Node dependency, preexisting Node assertion failure. Run each through actual public consent/Gateway/Docker and prove read-only source, bounded scratch, exact output/exit evidence and cleanup. Missing environments remain NOT_RUN, not success. Three distinct cold starts and their first real Session tasks remain later required gates, not satisfied by this baseline alone.

## Rollback and recovery

No main integration or Git push is authorized for the Writer. Preserve this clone and every failed test. Root will review the exact patch before applying it to the main candidate, then reverify. Do not overwrite another Writer's changes or delete evidence. Migration13 is additive and old binaries normally reject it: use transaction rollback on migration failure and forward repair, never delete baseline tables or lower version markers in a user's database. Disposable test downgrade fixtures are not a user rollback procedure.

Permanent owner and dispatch claims never refund execution. Normal/recovery cleanup acts on one immutable fenced full-lease snapshot in execution → sandbox → workspace order. Incomplete child cleanup blocks parent removal; repeated cancellation drains the same owned operation. Unknown command result or missing container is not permission to rerun. A new attempt requires a new review and fresh explicit consent, retaining previous failure/unknown evidence.

## Progress

- [x] (2026-09-09, independent bounded correction) Hume's fourth review rechecked all14 held hashes and released the hold: five unchanged private distinguishing probes completed0.96s and exactfive-module60 cases6.34s, each exit0. The initial private fixture-import collection error is retained separately. Evidence: `agent-fleet-baseline-corrective-review.9uda7b/FOURTH-EVIDENCE.md`. No remaining blocker was found in this bounded DTO/store/guard correction; this is not whole-baseline acceptance.
- [x] (2026-09-09, private-runtime worker evidence) Permission/observer cohort38 completed8.01s/exit0, including real schema12→13 Run preservation, quiescent unrelated baseline invariance and actual clean-child refusal of a concurrent cooperating baseline write. Both disabled terminal finalizers remain unchanged. The predecessor Permission run retained34failed/2passed due only to new-test enum/constructor assumptions, corrected without weakening production validation; all failure logs remain retained.
- [x] Added `tests/contract/test_baseline_resource_cleanup.py` for exact full-plan before/after-effect CAS, tier ordering and repeated cleanup join controls using real SQLite and explicitly synthetic cleanup facts. The five controls completed1.19s; the original five constructor-setup failures remain in `resource-01.log`. The corrected fixture uses a runner that refuses every process call.
- [x] Added `tests/unit/test_baseline_permission.py` and `tests/integration/test_baseline_observer_compatibility.py` for Broker ceilings/deny projection and schema13 clean-child observer compatibility. Creation callback, staged source drift, two-baseline Gateway identity substitution and exact transport cleanup controls also completed. These are offline fixture tests, not physical execution. Earlier held14/eight-file review holds were released and superseded by the final45-file candidate freeze.
- [x] (2026-09-09 20:56:58 UTC, root preparation evidence) Root prepared the isolated clone `.venv` offline after dry-run, using locked metadata, no Python downloads and copy mode. Resolved99/installed96 distributions; reported exact same96 versions/Python3.14.6, unchanged metadata and main environment. Evidence cache: `agent-fleet-baseline-runtime.yfJV0i`. This is origin/version preparation, not dependency byte equality or full source qualification. NEW worker checks now use this clone-local interpreter; previous shared-runtime focused logs retain their original scope and are not replaced.
- [x] (2026-09-09, worker continuation) Corrected the six early independent DTO/store/trust findings: complete reserved sandbox identity, strict effective-control projection, typed exact cleanup facts, active controller PID, fork-inherited guard refusal, and full observation-reference identity. The current focused DTO/store/trust selection completed 68 tests in 4.15 seconds (worker evidence only), including a spawned foreign-controller negative and persisted malformed-inspection/report-reference rollback controls. Hume's earlier blocked review remains historical; corrective review is still required.
- [x] Completed controller error-path self-fencing/drain after a permanent claim, including failure while leaving an admission guard. Persist a finite `controller_error` proof gap and inconclusive/recovery report rather than accepting an earlier observation after controller failure; no exception messages or dispatch refunds. Cancellation and non-Exception control signals are re-raised only after retained cleanup drain. The complete offline journey and repeated-cancel/creation-crash tests exercise this behavior.
- [x] (2026-09-09 19:07 UTC) Root read both architecture proposals, corrected mutable legacy DTO embedding, froze distinct ownership/immutable observations and mapped migration13 blast radius. A separate local clone at864ad43 preserves the main092b test freeze and its Git worktree registry.
- [x] (2026-09-09 19:22 UTC) Writer read AGENTS, PLANS, this complete contract and the required product/architecture/security/configuration/roadmap specifications. Clone branch/HEAD match the contract; only this plan was initially untracked. An `env -i` import probe through the existing interpreter loaded both Fleet and SQLite exclusively from this clone's src and reported schema12 (exit0). No model, credential, Docker, dependency or main-checkout mutation occurred.
- [x] Implemented immutable sibling DTOs/store and the complete guarded repository/Docker/ResourceService/Gateway/CLI capability cluster; no model or ordinary Run owner is constructed.
- [x] (2026-09-09, worker evidence) Implemented the first full offline controller/Gateway/Docker-adapter/real-Git/SQLite journey in the isolated clone. `journey-03.log`: 1 test in 13.65s; `cli-01.log`: 4 tests in 17.97s; `journeys-04.log`: 12 tests in 107.95s covering observed nonzero, timeout/truncation unknown, source/assume-unchanged drift, revoked review, repeated cancellation/drain and no replay. All use an explicit synthetic Docker transport; no Docker daemon, project command or model ran. This is not independent or physical acceptance.
- [x] (2026-09-09, worker evidence) `boundaries-02.log`: 68 tests in 6.20s after correcting a new test's expected existing redaction marker (`<redacted:1>`). `legacy-adapters-01.log`: 295 existing Docker/resource/permission/schema tests in 40.52s. `migrations-01.log`: 4 actual migration/DDL rollback tests in 1.54s. Full `mypy src tests` at that intermediate candidate checked381 files without issues; later new tests still require a final repeat. Original failed runs and independent3/1 corruption failures remain preserved.
- [x] Completed the fourth bounded DTO/store/guard review and narrow control-path corrective review, retaining every predecessor failure. Historical held14 store77b5ef64/readback30a4a0ba was rejected for released-lease write/read divergence; current store8293fa3f/readback67ab2216 rejects that write before effects. Control-path successor application/baseline8fe95c35 passed the unchanged pre-claim probe in0.05s. These bounded independent controls are not whole-baseline acceptance.
- [x] (2026-09-09 21:22 UTC, worker evidence) Completed the coherent standalone baseline lifecycle and all150 new offline tests in254.49s, with two existing observer-fixture JUnit record_property warnings. Narrow affected legacy cohort372 completed110.08s. Both exits0; no skips/failures in either final cohort. Worker total522 distinct tests is separate from independent private probes.
- [x] Froze45 source/test/schema paths: inventory SHA256 `49de00cc6da33bd2de95bf59723ac9a7bb2f88642da45e2a45844b5fb3829e40`, reproducible patch SHA256 `30915d87ffc03bd9b0c22be351aab05b4b3fb64930d5994f1f371d0db0164c18`. Complete Ruff check/format453files, mypy385files, generated schemas, offline locked metadata and diff checks completed with exit0. Legacy108 schema bytes, migrations1–12, ordinary models/StateStore and both disabled finalizers match base864ad43.
- [x] Final sealed-candidate independent replay: Hume's six unchanged distinguishing probes completed0.96s/exit0. All45 file hashes, canonical inventory49de00cc and96 installed distribution names/versions were independently matched before/after. Evidence cache `agent-fleet-baseline-final-controls.hpEkQD`; XML SHA256 `6f0d225c7b806e6165426a24028a165b27ae43206de6b13a6ee0de6d7f82fdb3`. This remains bounded control acceptance, not whole-candidate or physical acceptance.
- [x] (2026-09-09 21:27:19 UTC, root-owned actual old-binary evidence) Root checked the real frozen schema12 installed wheel against a private schema13 fixture:316 installed files matched sealed wheel36b738, actual `SqliteStateStore.migrate` refused with `STATE_SCHEMA_INCOMPATIBLE`, without monkeypatching its supported version. All13 migration rows, table rows and before/after file hashes remained equal; fixture review/execution/project counts each1, owner/dispatch/lease/Run counts0. Exact six baseline source hashes were unchanged, including migration13 51058b and store8293fa3f. Evidence cache `agent-fleet-baseline-old-binary.gzTQ2L` (`check.py`, `result.json`). This does not prove zero transient WAL/SHM I/O, all low-level reads refusing future schemas, whole-baseline acceptance or a new installation by this Writer.
- [ ] Fresh whole-candidate independent acceptance, main integration, complete default/packaging/installed/optional matrix and root-owned documentation. Per root instruction, do not duplicate the full clone default suite or commit/push this isolated candidate.
- [ ] Root-owned physical Docker/Node baseline acceptance, then separate Session/cold-start slice.

## Discoveries

- Hume's early control-path review reproduced a missing-capability admission-order defect: an already reviewed run could consume its authorization and prepare a workspace before discovering that the explicit baseline adapter registration was absent. Preserve `agent-fleet-baseline-control-review.LpU9ap/test_preclaim_capability.py` and its1failure/0.15s. Re-run `SandboxRegistry.require_baseline` from freshly reconstructed configuration inside `_assert_current`, before authorize/claim and every later guarded check. This is a local capability lookup, not Docker preflight or permission expansion. All eight held files were released before this correction; add a public-service no-claim/no-workspace control and rerun the unchanged independent probe.
- Third independent boundary review retained 58 successes and four unchanged distinguishing probes, but found normal-API write/read divergence: finalizing an already released original lease under a later cleanup scope could commit a second receipt/revision then make read-back fail. Reject `status=released` before any new receipt/update; retries of failed leases under a new exact scope remain allowed. Preserve the failing private probe and add explicit released-versus-failed retry controls; no oracle weakening.
- Final test origin must be explicit: existing subprocess E2E tests may drop PYTHONPATH then launch the shared interpreter's `fleet` entry point, which would select the main editable checkout. Do not count those as clone acceptance. New baseline subprocess tests explicitly select clone/src; root must provide a coherent private installed/overlay runtime for the exhaustive later matrix. No dependency installation or unrelated test/configuration rewrite is authorized for this Writer.
- Hume's second corrective review reproduced one further whole-scope defect while the prior three negatives passed: a hash-consistent historical scope omitting all leases/dispatch allowed vacuous complete cleanup despite unchanged active permanent records. Preserve this failure. Exact indexed scope lookup must also compare the permanent dispatch and the entire current bounded lease ID/kind set, each immutable owner/payload/creation identity, monotonic revision, and unchanged already-released leases. Read current rows directly without invoking recursive `_snapshot`; current terminal transitions still require the existing exact scoped receipt validation. This does not scan or substitute a newer cleanup plan.
- Root approved renaming the NEW integration module to `tests/integration/test_business_baseline_integration.py`: the originally listed unit and integration basenames collide under the repository's existing mypy/pytest module mapping. Change only this test path and its new helper imports; no mypy exclusions, package/configuration edits or test weakening.
- The first offline full Git/Gateway/transport journey reached one native dispatch and complete cleanup but correctly produced missing-result/controller-error because the store incorrectly required pre-start physical inspection to occur after command start. Align the chronology with the actual transport: owner claim <= effective inspection <= native start <= completion. Do not move inspection after execution or weaken controls; add before-owner/after-start rejection tests. This failed attempt remains retained separately from later successes.
- Hume's corrective review retained 44 focused successes and three distinguishing report-read failures: a hash-consistent row could substitute the claim or observed exit, or assert complete cleanup despite active leases. Repair write/read validation parity, not hashes or assertions. Add `baseline_events.scope_sha256 TEXT NOT NULL CHECK(length(scope_sha256)=64)` and unique index `baseline_events_scope` on `(baseline_id, scope_sha256)` to the unreleased migration13. The sole event kind remains `cleanup_claimed`; every event must correlate this index with its full typed immutable claim/snapshot/hash. Exact lookup uses LIMIT 2 and rejects absent, duplicate, mismatched or cyclic references. Historical report validation uses its original scope and receipt-derived lease states, not whichever cleanup event is newest. Receipt read-back repeats exact resource/unknown-create rules. Existing migrations1–12 and the ten-table inventory remain unchanged. Root approved this internal lookup seam before edits.
- Existing resource and Docker dispatch contracts require real Run/Task/Agent/stage; a fake owner would bypass their semantics. Separate sibling DTOs/tables avoid that.
- Frozen legacy models can contain mutable nested dictionaries. Authority uses canonical owned bytes/hash with fresh validated point-of-use projections.
- SQLite migration13 automatically changes the exact-version child observer gate; it does not require widening its semantic evidence targets or capture ceilings.
- Existing committed_source omits file sizes. Add `BaselineRepositoryPort.baseline_source_manifest(root, commit)` and the matching Git adapter method to freeze a regular-file-only path/type/mode/size/hash manifest. Symlinks/submodules are rejected, not silently normalized. A new owned `adapters/sandbox/baseline_docker.py` helper holds the separate baseline prepared state and shares the existing Docker adapter's neutral local-daemon/process/image/control primitives; ordinary Run state/labels are unchanged. Root approved these concrete seams before source edits.
- OrganizationService admission can write organization baseline rows and its run guard resolves credentials. Baseline instead uses OrganizationFileSystem.session directly, capture_target and config.snapshot_from_files; no OrganizationService/SecretStore. The publication session can create its sibling lock file; this is disclosed, not called a side-effect-free read.
- TrustStore.load does not share the save lock. Root approved additive `ports/trust_store.py` and `adapters/trust/filesystem.py` ownership for a cooperating read guard. Acquire organization publication guard before trust guard; bind full freshly validated policy hash and revision. The guard may create an absent trust directory/lock, while ordinary load remains nonmutating. Nonblocking acquisition, same-process contention and existing save compatibility are being specified before implementation; no synchronous blocking flock may be held as a hidden event-loop wait.

## Decision Log

- (2026-09-09) One real command behind the current control plane is the first complete vertical slice; Session UX and physical cold starts remain explicit follow-ups, not placeholder successes.
- (2026-09-09) Use an isolated local clone while main gates run. Do not mix those results with unintegrated baseline bytes.
- (2026-09-09) Preserve the disabled strong evaluation finalizers and all unsafe-local/credential/network restrictions. No broader authority is inferred from this baseline feature.
- (2026-09-09 19:22 UTC) Whole-tree Docker source access requires literal `.` in the effective user allowed_paths; command cwd is not a read boundary. Baseline denies every freshly validated active `command.run` deny whose project ID and repository identity match. No role/workflow/stage/path/command narrowing is used to prove disjointness in this first conservative slice; only a different project or repository identity, different capability, revocation/expiry or future creation can exclude a deny. Check `created_at <= now` explicitly in addition to rule_is_active. Ordinary allows and trust modes do not grant baseline authority. This intentionally conservative interpretation was explicitly approved by root and does not modify ordinary rule_matches.
- (2026-09-09 19:31 UTC) Root approved the complete read-guard design before trust implementation: immutable canonical bytes/hash and assert_current; one LOCK_EX|LOCK_NB; process-wide token-owned guard/save reservations keyed to validated lock/directory identities. Refuse nested or contended baseline guards immediately; same-process saves refuse an existing baseline reservation before backup/policy writes. Reserve saves before their existing flock to close check/acquire races. No metadata mutex spans I/O/body and guard metadata acquisition is fail-fast. Ordinary cross-process save behavior/CAS/backups remain unchanged. Lock order is publication → trust → short SQLite; retain trust through actual start/bounded transport and repeated-cancel drainage, never SQLite across await. Isolated watchdog-process race/deadlock controls are mandatory; async timeout alone is not evidence. This excludes cooperating writes only, not hostile host ABA.
- (2026-09-09 19:32 UTC) Add the narrowly named owned test helper `tests/business_baseline_fixtures.py` for shared immutable baseline/store/transport test inputs. No generic conftest or oracle changes. The initial DTO import probe exposed a property/field name collision; renamed the common derived property to digest (snapshot sha256 and content-reference record_sha256 remain real fields). The next import probe succeeded without warnings; this is an implementation correction, not an acceptance result.

## Outcomes

IMPLEMENTED as a frozen isolated-clone worker candidate, not self-approved or integrated. The standalone plan/run/show/revoke/recover path has150 new offline tests plus372 narrow legacy regression tests, strict/generated-schema/locked-metadata gates and retained bounded independent distinguishing controls. The exact45-file manifest and patch are in the private worker evidence cache; the absolute checkout/evidence mappings remain in the private handoff, not this tracked plan. No Git mutation, physical Docker, model call, credential use or installation was performed by this Writer.

Full main-candidate default/security/Gateway/execution-recovery/Session/package/installed qualification is still required after independent review and integration. Actual six Python/Node Docker baselines, Node toolchain/image, Session integration, three cold starts, S1 campaign/oracle and whole S1–S3 completion remain unfinished. Fake/LocalUnsafe tests prove their old contracts only; they do not qualify a baseline executor. The Worker's patched version constant only demonstrates refusal logic; root's separate frozen-wheel gate now supplies actual old-binary schema13 refusal evidence, not broad reader compatibility. Capture retains its32MiB/file and128MiB aggregate limits: unrelated baseline BLOB growth can make observation unavailable. Existing trusted-host/OS-account limitations and conservative PID reuse/inaccessibility refusal remain.

Two final observer compatibility cases retain benign `record_property`/xunit2 warnings without suppressing them. The injected unknown-native-callback test intentionally retains its failed execution and active parent leases/worktree even after synthetic local removal: absence is not durable proof. Partial-cleanup/corrupt-state fixtures and all earlier failed logs remain in private basetemps. No user repository, actual Docker container or live-provider state was created or cleaned by this slice.

### Exact final worker check selections

All commands used the clone `.venv/bin/python`, cwd at the isolated checkout, and a minimal `env -i` environment: PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin, PYTHONNOUSERSITE=1, PYTHONDONTWRITEBYTECODE=1, UV_OFFLINE=1 and all three `AGENT_FLEET_ENABLE_{LIVE_PROVIDER,DOCKER,INSTALL}_TESTS=0`. Final logs/JUnit/private basetemps use the prefixes below; full absolute commands and paths are retained in the private handoff.

`baseline-final-01`: `python -m pytest -q` with these13 whole modules, no selection filter:

```
tests/unit/test_business_baseline.py
tests/unit/test_baseline_gateway_output.py
tests/unit/test_baseline_permission.py
tests/contract/test_baseline_store.py
tests/contract/test_baseline_readback.py
tests/contract/test_baseline_trust_guard.py
tests/contract/test_baseline_owner.py
tests/contract/test_baseline_sandbox.py
tests/contract/test_baseline_resource_cleanup.py
tests/contract/test_baseline_migrations.py
tests/integration/test_business_baseline_integration.py
tests/integration/test_baseline_observer_compatibility.py
tests/e2e/test_business_baseline_cli.py
```

`legacy-final-01`: `python -m pytest -q` with the following exact selection:

```
tests/contract/test_docker_sandbox.py
tests/contract/test_fake_sandbox.py
tests/contract/test_local_unsafe_sandbox.py
tests/contract/test_trust_store.py
tests/unit/test_resource_cleanup.py
tests/unit/test_permission_broker.py
tests/unit/test_permission_path_scopes.py
tests/unit/test_permission_policy_security.py
tests/unit/test_schema_generation.py
tests/unit/test_evaluation_capture.py
tests/contract/test_evaluation_execution_store.py::test_migration12_preserves_reservations_and_rolls_back_ddl
tests/integration/test_config_snapshot_binding.py
tests/integration/test_release_upgrades.py
```

Static commands: `python -m ruff format --check .`; `python -m ruff check .`; `python -m mypy src tests`; `python -m agent_fleet.schemas.generate --check`; `uv lock --check --offline` with UV_PYTHON_DOWNLOADS=never; `git diff --check`. Every command exited0. Final resolved metadata remains99 packages, installed runtime96 versions/Python3.14.6. No claim of dependency byte equality is made by the preparation receipt.

### Preliminary worker evidence and early independent findings

Evidence cache: `agent-fleet-business-baseline-development.4LTxwH/worker-evidence.UgYqhq`.
DTO/store run01 retained9failed/16passed (nested snapshot alias reserialization bug); run02 retained1failed/24passed (new fixture queried nonexistent `agents`, corrected to real `agent_instances`); run03 completed25tests/0.30s/exit0. Guard01 completed30tests/0.57s/exit0, including6 new guard controls and24 unchanged trust-store tests. These preliminary worker checks do not accept the unfinished execution slice.

Hume's early immutable read-only review found six defects before public wiring: incomplete sandbox activation identities; unchecked nested effective controls; untyped execution cleanup allowing unknown-create release; missing current-process owner guard; inherited fork guard authority; and partial observation-reference comparison. All remain recorded as predecessor defects. Corrections add a baseline-owned neutral effective-controls schema (never a fabricated legacy sandbox ID), complete reserved-handle equality, typed cleanup binding/unknown-create checks, controller PID checking, inherited-reservation fail-closed semantics and full reference comparison. Dedicated negative controls and subsequent independent review are required; preliminary25/30 results do not cover the corrections. No model/Docker/network/credential access occurred.

## Normative owner, lease, transport and evidence contract

## Decision and preservation boundary

Choose **baseline-owned sibling DTOs and additive internal protocols**. Do not replace
existing owner fields with a public RunOwner | BaselineOwner union, make run_id nullable,
subclass a Run resource to override run_id, construct a dummy Run/Task, or use model_construct.
The current ResourceService is the concrete resource manager; no separate ResourceManager exists
in the inspected seams. Extend it, ToolGateway and the existing Docker adapter, not a second runner.

Keep existing Run, TaskSpec, WorkflowStage, WorkspaceKind, Workspace, ResourceLease,
SandboxHandle, ExecRequest, SandboxExecutionHandle/Metadata/RecoveryRequest and ExecResult
JSON/schema unchanged. Keep PermissionBroker.evaluate, StateStore, ordinary recovery,
all existing SandboxProvider/RepositoryPort signatures, old Docker labels and old Run paths.
No baseline route enters an agent tool catalog, ScriptedAction, role template or TaskPurpose.
Only the trusted user controller obtains the new internal dependency bundle from bootstrap.

Observed barriers: models.py:1278/1298/1918/2092/2146/2181/2276 are Run-bound;
gateway.py:94/456/478 construct full Task/Agent/stage dispatch and lease identities;
sqlite.py:500 requires their persisted active context, not merely non-null strings;
migrations/0001.sql:84 has resource_leases.run_id REFERENCES runs(run_id).
Docker create/exec/reconcile at docker.py:190/320/721 and labels at 1682 require that family.

## Exact new data boundary

Put resource DTOs in new domain/baseline_resources.py, separate from public Run models.
The public BaselineExecution/Review/Authorization remain in domain/baseline.py.
Define frozen strict BaselineResourceOwner(baseline_id, project_id, review_sha256).
BaselineId uses baseline_<32hex>; resource IDs use bws_, bsandbox_, bexec_, blease_;
owner-claim ID uses bclaim_. Their typed aliases and generators never accept old prefixes.
Every sibling resource carries owner: BaselineResourceOwner, never run_id/task_id/agent/stage.

BaselineWorkspace: owner, workspace_id, path, base_revision, approved_source_sha256,
materialized_source_sha256 (absent until checked activation); no old WorkspaceKind.
BaselineSandboxSpec: owner, workspace: BaselineWorkspace, sandbox: BaselineCanonicalSnapshot,
mount_policy Literal['baseline-readonly-v1']; require exact project/path agreement,
Docker/network-none/image/daemon bindings, no ambient environment or unsafe confirmation.
BaselineSandboxHandle: owner, sandbox_id, workspace_id, workspace_host_path,
provider Literal['docker'], capabilities/config/image/daemon/recovery_scope bindings,
mount_policy; carry every existing Docker identity check, not just equivalent strings.
BaselineResourceLease: lease_id, owner, revision, kind/status/timestamps and a discriminated
payload for the exact workspace, sandbox, or command execution. Avoid free-form identity metadata.
Execution payload binds claim_id, bexec ID, canonical command hash, workspace/sandbox,
creation_dispatched, and optional exact native handle; insertion identities are immutable.

BaselineExecRequest: owner, claim_id, execution_id, workspace_id, command: BaselineCanonicalSnapshot;
all required. Reconstruct through CommandSpec canonical argv/cwd/environment/bounds validators, not ExecRequest
with omitted identity fields. There is one reviewed command per BaselineExecution in this slice.
BaselineExecutionHandle: owner, claim_id, execution_id, sandbox_id, provider='docker',
native_resource_id, exact labels and canonical labels hash. No Run-compatible serialization.
BaselineExecutionRecoveryRequest: same complete owner/claim/command/workspace/sandbox binding,
creation_dispatched and expected exact labels; no nullable stage or fabricated intent.
BaselineSandboxInspection: owner, legacy_control_inspection: BaselineCanonicalSnapshot,
mount_policy, workspace_read_only and exact writable scratch limits/mount inspection digest.
All baseline checks require physical workspace read-only=true, not merely read_only_root=true.
BaselineExecutionMetadata/ExecResult mirror necessary result/timestamp/redaction/hash checks
but reference sibling handles/inspection. Reuse owner-neutral SandboxCleanupResult only nested
inside a separately owner-bound lease receipt. Do not emit CommandEvidence/EvidenceBundle.
The baseline service wraps the returned observation into its separate BaselineReport, with the
immutable output/storage bindings below. Neither a frozen wrapper nor model_copy(deep=True) makes
borrowed SandboxSpec/CommandSpec dictionaries immutable; none are retained in sibling state.

### Immutable projection and point-of-use reconstruction (normative correction)

BaselineCanonicalSnapshot is frozen and contains only schema_tag: bounded literal,
canonical_utf8: strict bytes, and sha256: lowercase hex. Bytes, not bytearray/memoryview/dict or
a Pydantic object, are the authority. Tags identify command-v1, sandbox-spec-v1,
sandbox-inspection-v1, capabilities-v1 and other explicitly admitted nested legacy schemas.
The review's sandbox-policy-v1 projection excludes not-yet-allocated workspace_host_path and
contains only the approved project/configuration/requirements/limits/environment/image/daemon.
Command bytes cap at 128 KiB, sandbox/inspection/capability bytes at 16 KiB each; the complete
review still caps at 128 KiB and may reject an otherwise valid oversized legacy command.
Serialize nested snapshots as {schema_tag, canonical_json: strict UTF-8 text, sha256} in new
baseline JSON only; decode into owned bytes. No implicit Pydantic bytes/base64 configuration.

Admission: encode a detached input snapshot, then validate fresh JSON through the corresponding
existing model's model_validate_json; do not use model_validate(existing_instance), which can
reuse an already-mutated instance. Apply narrower baseline limits, including empty configured
CommandSpec.environment and SandboxSpec.environment in v1, with only fixed reviewed transport
scratch settings. Validate sandbox-policy fields through their existing component models;
reconstruct the full SandboxSpec only by adding the exact claimed workspace path. Canonicalize the
validated JSON tree using sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False;
store only its UTF-8 bytes/hash. Reject duplicate keys, invalid UTF-8, non-finite numbers, unexpected
fields/tags and bounds violations. No caller-owned container/model/reference survives admission.
All sibling claims/reviews/leases/requests use scalar/tuple fields or these snapshots, including
capabilities, labels (sorted tuple pairs), inspection, cleanup and canonical resource payloads.
Returned public views are fresh decodings; mutations cannot alter stored/transport authority.

Define freeze_command(raw_json: bytes) -> BaselineCanonicalSnapshot and
freeze_sandbox(raw_json: bytes) -> BaselineCanonicalSnapshot; matching reconstruction helpers
validate tag, byte cap, sha256 and exact canonical reserialization before returning fresh local
CommandSpec/SandboxSpec instances. The allocated full sandbox-spec snapshot has its own digest,
recorded before provider preparation in the exact lease and subsequent dispatch claim. Reproject
it to sandbox-policy-v1 and require byte/hash equality with approval; its only added workspace
path must equal the claimed workspace. Do not compare its full digest to a pre-allocation review
digest or silently approve new settings. The transport reconstructs again at point of use, checks
the appropriate command/policy/full-spec digests against persisted review/claim/lease, then projects
to private scalar/tuple launch
values (argv tuple, sorted environment tuple, fixed mount/resource scalars). No mutable validated
model crosses an await or escapes to callers. Recheck the immutable launch projection's canonical
hash immediately before create/start dispatch; executable argv/environment/mounts must be derived
only from that projection. The launch projection digest is bound to review policy, actual full-spec
digest, mount/source identities and dispatch request; fixed transport flags are versioned, not
unreviewed overrides. Reconstruct a fresh subprocess environment mapping for that call only.
Prepared Docker state retains snapshots/projections, never mutable SandboxSpec or shared dicts.

## Before / after API: additions only

All current methods remain exact. New internal protocols go in ports/baseline_resources.py;
BaselineStore goes in ports/baseline.py. DTO names below are normative contract names.
New methods on GitRepository satisfy BaselineRepositoryPort, not widened RepositoryPort:

    prepare_baseline_workspace(owner: BaselineResourceOwner, base_revision: str,
        *, approved_source_sha256: str) -> BaselineWorkspace
    materialize_baseline_workspace(root: Path, workspace: BaselineWorkspace) -> BaselineWorkspace
    baseline_workspace_fingerprint(workspace: BaselineWorkspace) -> str
    cleanup_baseline_workspace(root: Path, workspace: BaselineWorkspace) -> None

Use a distinct sibling state-root/baseline-workspaces/baseline_ID/bws_ID path namespace;
validate exact owner-derived path plus existing safe-path/Git registration/source rules before I/O.
Share private index materialization and exact worktree removal primitives. Baseline cleanup must
not accept an ordinary workspaces/ path; Run cleanup cannot resolve the baseline namespace.
No baseline patch apply/write helper is exposed. Hash checks supplement, not replace, read-only mount.

Approval binds approved_source_sha256, not just HEAD/status: a versioned canonical manifest of the
complete reviewed committed tree's mount-visible paths, entry types, executable modes, sizes and
content hashes (symlink targets when admitted by the existing hardened materializer). Apply the
same rejection and representation rules to expected tree and actual staged files; reject extras,
missing entries, unsupported nodes and unsafe links. This slice remains committed/clean only.
The .git shadow mount and fixed scratch are separately bound to the approved mount policy, not
silently excluded mutable source. The review carries this manifest digest before approval; after
materialization, walk the actual private source under exact path/inode identity checks, require its
digest to equal approval, and bind that digest plus exact workspace identity into the activated
lease, sandbox, dispatch claim, execution observation and report. Never replace the approved digest
with whatever staging produced. ResourceService supplies approved_source_sha256 only from the
stored review; activation may fill the previously absent materialized digest exactly once with
that equal digest, while every preallocated workspace identity stays unchanged.
Revalidate original repo identity/HEAD/tree/index/clean status,
mount-visible source digest and config after staging and again before command start; any mismatch
aborts without starting the command, keeps the claim spent, and enters exact cleanup.
Recheck staged digest and inspected readonly mount before start, and record a post-command digest
before removal. A post-run mismatch makes the observation inconclusive; it cannot undo execution.
Internal locks serialize cooperating Fleet operations only. They and SQLite CAS do not prevent
hostile same-user writes/ABA between checks; readonly Docker protects against the command, not its
host. Do not claim host-atomic source freeze or detection of an unseen change-and-restore.

New methods on DockerSandboxProvider satisfy BaselineSandboxProvider:

    async create_baseline(spec: BaselineSandboxSpec, *, sandbox_id: BaselineSandboxId) -> BaselineSandboxHandle
    async inspect_baseline(handle: BaselineSandboxHandle) -> BaselineSandboxInspection
    async exec_baseline(handle: BaselineSandboxHandle, request: BaselineExecRequest, *,
        on_creation_dispatched: Callable[[], None],
        on_resource_created: Callable[[BaselineExecutionHandle], None]) -> BaselineExecResult
    async cleanup_baseline_execution(handle: BaselineExecutionHandle) -> SandboxCleanupResult
    async reconcile_baseline_execution(sandbox: BaselineSandboxHandle,
        request: BaselineExecutionRecoveryRequest) -> SandboxCleanupResult
    async terminate_baseline(handle: BaselineSandboxHandle) -> SandboxCleanupResult

Callbacks are required on this new path and must complete before create/start respectively.
Do not introduce these methods into Fake/LocalUnsafe or fall back to their ordinary exec methods.
SandboxRegistry.require_baseline(config, requirements) -> BaselineSandboxProvider performs the
existing capability checks plus explicit registered Docker baseline-adapter capability selection;
missing capability is a pre-claim refusal. Existing registry methods remain unchanged.
Private Docker create/start/wait/log/inspect/remove mechanics are shared under typed wrappers;
an internal closed discriminant may select label/mount encodings, but no public owner union.
Prepared-state maps are separate or use (owner_kind, owner_id, sandbox_id), never bare strings.

    ResourceService.create_baseline_workspace(claim: BaselineOwnerClaim) -> tuple[BaselineWorkspace, BaselineResourceLease]
    async ResourceService.create_baseline_sandbox(claim: BaselineOwnerClaim, spec: BaselineSandboxSpec) -> BaselineSandboxHandle
    async ResourceService.cleanup_baseline(plan: BaselineCleanupClaim) -> None
    ToolGateway.execute(...) -> dict[str, JsonValue]  # UNCHANGED
    async ToolGateway.execute_baseline(*, claim: BaselineOwnerClaim,
        workspace: BaselineWorkspace, sandbox_handle: BaselineSandboxHandle) -> BaselineCommandObservation
    PermissionBroker.evaluate(intent, task, sandbox) -> PermissionDecision  # UNCHANGED
    PolicyPermissionBroker.evaluate_baseline(scope: BaselineCommandScope,
        sandbox: SandboxCapabilities) -> PermissionDecision

Add a separate baseline-broker protocol. Wire the existing PolicyPermissionBroker's new method,
not its ordinary Task-based context and not the confusingly named Phase-1 BaselinePermissionBroker
as a substitute for user policy. The decision carries no forged Run grant ID. It checks this plan's
exact controller approval/current policy/hard ceilings with no trust-mode autoallow or model role.
Gateway re-loads immutable review/claim/leases, derives the only command itself, checks all owners,
revalidates current policy/source/config/image/daemon, and atomically claims command dispatch.
It accepts neither ScriptedAction nor arbitrary argv. Shared private command transport retains
canonical validation, creation callbacks, bounded outputs, redaction and cancellation drain;
Run patch/evidence logic stays in the Run branch. Baseline binds approved and actual materialized
source digests, not merely original-source fingerprints or a shallow-frozen CommandSpec object.
ResourceService and Gateway may take one optional keyword-only baseline dependency bundle;
existing construction/callers behave identically when absent and baseline methods fail closed.

## Durable state: unavoidable additive migration and exact CAS

Do not alter or insert into runs/tasks/agents/tool_intents/tool_dispatch_claims/resource_leases.
Use baseline tables already proposed by the draft plus baseline_resource_leases, a permanent
baseline_owner_claims row UNIQUE(baseline_id), and baseline_dispatch_claims UNIQUE(baseline_id).
Use foreign keys to BaselineExecution and owner-specific prefix/check/unique constraints.
Store canonical payload/hash plus indexed identity/revision; validate SQL columns against JSON.
Add the next migration (currently 0013) and raise supported version from current 12; do not rewrite
prior migrations or old rows. Old binaries will reject the newer schema: unchanged Run JSON
does NOT imply backward database-opening compatibility. No version suppression or downgrade.

BaselineStore resource/dispatch methods, in addition to this plan's review/authorization API:

    claim_baseline(review_id, review_sha256, authorization_id, expected_revision) -> BaselineOwnerClaim
    reserve_baseline_lease(claim, lease: BaselineResourceLease) -> BaselineResourceLease
    activate_baseline_lease(claim, lease_id, expected_revision,
        resource: BaselineWorkspace | BaselineSandboxHandle) -> BaselineResourceLease
    claim_baseline_dispatch(claim, expected_snapshot_sha256, request: BaselineExecRequest,
        lease: BaselineResourceLease) -> BaselineDispatchClaim
    mark_baseline_creation_dispatched(claim, lease_id, expected_revision) -> BaselineResourceLease
    activate_baseline_execution(claim, lease_id, expected_revision, handle) -> BaselineResourceLease
    finalize_baseline_lease(cleanup_claim, lease_id, expected_revision, receipt) -> BaselineResourceLease
    baseline_resource_snapshot(baseline_id) -> BaselineResourceSnapshot
    begin_baseline_cleanup(claim, expected: BaselineResourceSnapshot) -> BaselineCleanupClaim
    claim_baseline_cleanup(expected: BaselineResourceSnapshot,
        stopped_owner: BaselineStoppedOwnerReview) -> BaselineCleanupClaim

claim_baseline atomically consumes one exact allow-once authorization and permanently claims the
owner BEFORE worktree creation. reserve methods require the current unfenced owner claim.
claim_baseline_dispatch atomically inserts the CREATING execution lease and the permanent one-shot
dispatch claim while rechecking the full owner/current lease snapshot and canonical command binding.
Every new method uses BEGIN IMMEDIATE, exact payload/revision validation, redaction and a committed
CAS before returning; duplicate claims never dispatch again. Command observations and cleanup
receipts are immutable independently recorded facts; report publication is atomic with its exact
baseline state/revision and receipt references, never through Run ArtifactService/events.
begin_baseline_cleanup is the still-owned normal/error/cancellation drain path: after transport
join it fences its own exact claim and captures the full resource set. claim_baseline_cleanup is
the distinct stopped-owner recovery path. Neither permits allocations once its cleanup fence wins.
Review/permission/source locks needed by the approved plan span final validation through claim;
SQLite atomicity alone does not freeze mutable files. No absolute filesystem/DB atomicity claim.

### Exact bounded observation/report persistence

Add BaselineStore.record_command_observation(claim, expected_revision, canonical_utf8: bytes)
-> BaselineObservationRef and publish_baseline_report(cleanup_claim, expected_revision,
canonical_utf8: bytes) -> BaselineReportRef. Strict schemas bind schema version, owner/review/
authorization/claim, command/sandbox/request hashes, approved AND actual source digests, execution
and native-handle/inspection identities, UTC times, observed exit/timeout/cancel/truncation state,
and separately referenced cleanup facts. No Run artifact ID, task ID, patch hash or CommandEvidence.

Capture at most the reviewed aggregate output limit (v1 maximum 64,000 bytes) into bounded volatile
stdout/stderr buffers; never persist or stream raw chunks, exceptions or raw-output hashes.
Decode with explicit replacement accounting, redact complete bounded fields with the existing
Redactor/credential-shape rules, sanitize terminal controls, then bound the resulting UTF-8 fields
again. Freeze these redacted bytes and hash exactly those bytes. Record capture truncation,
post-redaction truncation and decoding replacement flags honestly. No ambient environment or
credential loading; this does not promise discovery of every unknown secret in arbitrary output.
Observation canonical JSON is bounded to 128 KiB and report to 256 KiB, inclusive of output and
metadata. Reports reference the observation rather than duplicating its output. Oversize/invalid
metadata fails closed into inconclusive/recovery-required state, never by silently dropping bindings.

Persist canonical bytes as BLOBs in baseline_command_observations and baseline_reports, with
SHA256-derived IDs bobs_<sha256>/brpt_<sha256>, baseline/execution IDs and full binding hashes as
validated indexed columns. Command observation UNIQUE(baseline_id, execution_id); insert-only:
an identical retry reads back identical bytes, any differing replacement fails. A report is also
insert-only; later cleanup recovery may append a new report with predecessor_report_sha256 and
CAS-update the execution's current-report reference, never overwrite historical evidence.
One transaction validates full columns/payload/hash, current claim/revision and referenced receipt
hashes, inserts bytes, and updates the matching execution state/reference. Read-back revalidates
sizes, schema, canonical hash, owners and all references; corruption/staleness is an error, not
permission to re-run. Crash before publication may leave a spent attempt with missing observation;
report unknown/inconclusive, never infer exit=0 or not_run from absence. Cleanup failure permits an
inconclusive report referencing its incomplete facts; it never claims resources released.
Only validated observed execution is labeled OBSERVED (including an actual nonzero exit).
Keep completion_assurance=baseline_observation_only, target_applied=false; no CompletionGate/S1 score.

## Labels, crash, cancellation and exact cleanup

Run label set remains byte-identical. Baseline labels have exactly agent-fleet.{managed,
installation,owner-kind,baseline,project,review,claim,sandbox,execution,command,daemon}; values bind
owner-kind=baseline and the complete persisted request. Prohibit run/task/agent/stage/intent keys.
Baseline native name is agent-fleet-baseline-bexec_ID, distinct from agent-fleet-exec_ID.
Both paths verify their exact key sets, values, native name, installation and daemon before effects.
Do not accept a baseline handle through a Run API even with fields relabeled or IDs colliding.

Crash after owner claim but before resource creation: recover/revoke/abort only, never rerun.
Crash after dispatch claim: command remains spent even if no container is found. Persist the
creation-dispatched flag before Docker create; if that callback fails, do not create.
Unknown dispatched create + no native ID + zero matches remains incomplete/unknown, matching
current docker.py:721 reconciliation; absence is not execution evidence or replay permission.
Native-handle callback failure triggers the same exact locally known cleanup, not a second create.
Cancel fences new allocations/dispatch and joins/drains the in-flight transport before taking the
final cleanup snapshot. Stop/recovery requires genuinely stopped owner evidence, not timeout alone.
The cleanup CAS binds owner generation/claim plus the ENTIRE lease set/full payloads, including
terminal leases; late additions, revisions, identity substitutions or corrupt rows reject the fence.
Successful cleanup claim owns only that immutable snapshot; never query to expand its targets.
Cleanup order: execution -> logical sandbox -> worktree. Incomplete child blocks parent removal.
Join repeated cancellation on one tracked cleanup task; retain failed leases, exact receipts and
permanent claims. Cleanup interruption/restart may retry exact cleanup, never command execution.
No cross-owner sweep or installation-wide deletion. Existing Run recovery remains untouched.

## Minimal ownership and compatibility gates before implementation acceptance

One owner-seam Writer owns domain/baseline_resources.py, new ports/baseline_resources.py,
the baseline store additions/next migration, application/{gateway,resources,permission_policy,
sandboxes}.py and bootstrap.py wiring; baseline.py DTO/store groundwork must land in that same
importable cluster. Transport/Git methods and their new contracts must be complete before enabling
the bundle. Existing models.py/ports/state_store.py/public Run schemas require no semantic edits.
Git and Docker changes are adapters/repository/git.py and adapters/sandbox/docker.py; factor
private neutral helpers only as needed. Do not modify fake/local_unsafe or their acceptance labels.
Add baseline-only exported schemas if required; all existing generated schema bytes must match.

Required tests: old Run DTO/schema roundtrips, labels/argv and Fake/LocalUnsafe contracts unchanged;
old 12->new migration preserves existing row bytes and restart behavior; new-old binary refusal;
Run/Baseline and two-Baseline substitution denial at repository, broker, gateway, store, transport
and cleanup; unregistered baseline capability refuses without resource/claim; concurrent claims,
revoke/cancel races and every creation callback crash boundary; full-set CAS with late terminal
lease, payload-only change and ABA; repeated cancellation/cleanup ordering; wrong labels/native
name/daemon/image, zero/multiple reconciliation results, read-write workspace inspection rejection.
Add mutation probes for original and returned nested command/environment/sandbox/inspection values;
noncanonical/duplicate-key/hash/tag corruption; mutation during callback/await; projection hash
mismatch before dispatch; staging source/config drift and extra file/mode changes; approved versus
materialized digest mismatch; redaction across capture chunks, post-redaction byte bounds, immutable
observation conflict, report-reference CAS/restart/corruption and missing-result unknown semantics.
Extend tests/contract/test_docker_sandbox.py, tests/unit/{test_resource_cleanup,test_schema_generation}.py
and add baseline owner/store/gateway/recovery contracts; retain existing gateway/security/execution
recovery/Session CAS suites unchanged as regression gates. The final worker selections and exact results are listed above; complete main-candidate regression/physical/installed gates remain separate and have not been claimed here.

Feasibility: additive implementation is coherent; a zero-DTO/zero-migration wrapper is incompatible.
Physical Docker readonly-source/scratch and Node image/toolchain qualification remain separate
unmet gates. This design does not turn six static descriptor fixtures into executed target baselines.

## Root main-integration contract (before transplantation)

- [x] (2026-09-09 21:50 UTC) Root read and SHA-checked full independent
  VERDICT31858f7be941304dfecbc0a18b411a9a676a0d7d23860d7590452ac85693555a,
  private baseline-acceptance.e0GkpV. Fresh150/281.12s,391/195.44s and one
  genuine-stopped-owner public CLI recovery/25.40s passed,542 fresh identities;
  six earlier exact-candidate controls make548 independent identities total,
  not548 fresh reruns. Twenty original databases/23 baseline identities validated;
  released paths absent, unknown-create worktree and active parents retained.
  Known-handle stopped-owner recovery releases three leases, appends report and
  preserves controller_error/CLI3 with no redispatch. All45+18 protected file
  hashes held. Two invalid initial spawn-runner cohorts remain excluded; entire
  guarded replacements pass. The independent review hold is released.

At2026-09-09 21:49UTC the root Writer may transplant the complete frozen45-path
candidate49de00cc (patch30915d) only after the whole isolated runtime verdict is
sealed and read. The separate static integration review already passed21:45:08UTC,
seal34513efb:15 existing mainfd958db preimages match864ad43 and30 additions are absent;
the regenerated patch and apply-check match. Existing108 schemas/migrations1–12,
Run/StateStore and disabled finalizers remain exact. Six Run-default Docker helper
comparisons and12 malformed-control refusals agree with the immutable predecessor.
This is not a claim that the intentionally extended TrustStore or schema version
has no compatibility effect.

Root is the only Writer in the main checkout and retains every later guidance,
provider, CoS, workflow and user-document change. Use the exact45-file set from the
private handoff, verify every post-copy byte against the accepted manifest, and
verify the rest of the main source/dependency inventory unchanged. Do not cherry-
pick unrelated clone history, overwrite the main index, apply a target task patch,
or transplant any private fixture/state/evidence. The clone stays frozen and intact.

Root owns README, USER_GUIDE, SECURITY_MODEL, CONFIG_AND_SCHEMAS, ARCHITECTURE,
ADR0011 and the parent/this living plans for integration documentation. Run the
existing exhaustive identity-partitioned default matrix, six static gates,
fresh wheel/sdist plus installed-resource readback, and applicable optional gates
on the actual combined main bytes. Public115 schemas,13 migrations and332 package
runtime/guide resources must be verified, not inferred from source filenames.
No paid request is authorized by this integration contract. Physical baseline,
Session/cold-start, provider and S1 terminal/oracle acceptance remain separate.

- [x] (2026-09-09 21:51:44 UTC) Root transplanted all45 accepted files using
  apply_patch and compared every resulting byte with inventory49de00cc. All498
  previous source/dependency inputs outside those45 remained byte-identical.
  Combined543-file code/dependency SHA256 is
  `30b8f4762e92da2c001b189b32a42fddba41cf9ebd8be6b1fee9924b82f874e6`;
  whitespace check exited0. No target patch, private evidence or unrelated clone
  history was copied. The clone remains intact and frozen.
- [x] Unified main default matrix and six static gates completed in private
  `agent-fleet-baseline-main-gates.JOTgxT`. Its unchanged partition runner freshly
  collects every default test, executes disjoint groups with at most three pytest
  parents and serializes the existing timing-sensitive cancellation test. Exact
  JUnit identity reconciliation and source/dependency drift checks are mandatory.
  No live/Docker/installation opt-in or credential is in this gate environment.
- [x] (2026-09-09 22:32:07 UTC) Full combined main matrix PASS:3966 passed,
  23 explicit skips (19 Docker,3 installation,1 live),3989 unique freshly
  collected/executed identities,zero failures/errors/gaps/duplicates/code drift.
  Raw result543c1bef and collectionda9301ee. JUnit/pytest durations: integration
  groups247/1752.17s,245/1142.93s,245/947.15s; other3228 passed+23 skipped/1148.29s;
  isolated cancellation1/9.20s. Wrappers1754.945/1146.165/949.991/1152.923/11.442s.
  All commands exit0. Independent exact-identity/static readback passed at
  22:36:17UTC, sealda654c0c in `agent-fleet-baseline-matrix-readback.miKSs1`;
  root read and SHA-checked it. The39 reported warnings are retained (JUnit
  record_property/xunit2 compatibility and Google SDK deprecation), not zero-warning
  acceptance. Code remains30b8f476 across543 inputs.
- [x] (2026-09-09 22:33:03–22:37:04 UTC) Root ran reviewed helper224553c4 `docker`
  against the exact local native bindings, after complete default/static gates.
  One ordinary29-case optional selection, process70120; fresh private
  docker-fixtures/XML/log/result, no live key/model/download or baseline command.
  Actual Docker result:29 passed/239.06s,241.36s wrapper,exit0,no code drift;
  daemon/image/endpoint match before/after. README changed during this permitted
  documentation work, so this is not a frozen-document installation receipt.
  Independent physical evidence readback is pending.
- [ ] Freeze final integrated documentation, rebuild wheel/sdist and independently
  read installed resources; rerun applicable optional gates on the combined bytes.
- [x] (2026-09-09 21:57:47 UTC) All six combined static gates exited0 on30b8f476:
  Ruff format457 files, lint, mypy387 source files,115 generated schemas,
  offline99-package lock and diff check; zero code drift. Exact outputs and command
  times are retained in `agent-fleet-baseline-main-gates.JOTgxT/static-results.json`.

### Subsequent ordinary optional-gate contract (before execution)

After the complete3989-identity default matrix and static gates pass, root may
run the unchanged ordinary `tests/docker`29-case selection, then the unchanged
`tests/release`3-case selection against the exact543-file30b8 inventory. These
are regressions of existing Run/Session/install behavior, not physical baseline
qualification. The private `run_optional_gates.py` in the main-gates directory
refuses missing/failed default gates and source changes. It creates unique
test-owned fixture paths only, with live opt-in explicitly0 and a minimal
credential-free inherited environment. Recheck prepared local daemon
e470601e-5d84-43d4-8c9d-2038812fa634, the exact local Unix endpoint recorded in the
private helper and existing image
`sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241`
before/after; drift fails rather than switching context or preparing an image.
Install tests use only the existing95-wheel offline closure at
`agent-fleet-s1s3-locked-dependencies.iq2Zxi/prepared`, whose manifest binds the
unchanged99-package lock. No network download, Docker pull/build, model call,
global cleanup or existing user-target edit is authorized. Existing learning
fixtures may apply their own reviewed patch only to newly created private targets.
Frozen README/USER_GUIDE bytes must hold throughout installation, and all outputs,
archives, exact JUnit identities and physical resource readback remain evidence.
Run these after heavy default groups to avoid timing/cancellation contention.

Independent preparation review found that the first uninvoked private helper
did not enforce Docker-before-install order or absent fixture/XML/result paths.
Root corrected it before any optional execution: all four mode output paths
must be absent including dangling symlinks, installed mode requires the same
30b8 Docker29 PASS receipt, and an explicit matching frozen README/guide manifest
must exist. Corrected helper SHA256 is
`224553c47150f3ca16e5653b4ba80885e1cc650d530036eaea07c0ee3fecd6ed`.
This is a test-runner preflight correction, not a product or acceptance relaxation.
Independent helper review passed38 pure-memory exact-AST controls at22:09:42UTC,
including eight existing/dangling-output refusals, prerequisite/source failures,
minimal environment and daemon/image/context substitutions. Root read and
SHA-checked seal435b34c2 in private `agent-fleet-baseline-optional-review.1nFPyZ`.
The full helper and its physical operations were not invoked by that review;
complete matrix and documentation freeze are still prerequisites.

Root also checked the public help entry in a minimal credential-free environment
at22:11UTC: `.venv/bin/fleet baseline --help` exited0 and lists exactly plan/run/
show/revoke/recover. The first attempted `python -m agent_fleet` entry exited1
because the package intentionally has no `__main__`; `pyproject.toml` registers
the `fleet` script instead. No source workaround, project registration or command
execution was made for this operator invocation correction.

### Final archive contract refinement (before execution)

Root read the independently prepared archive contract (preparation45e2470e,
private `agent-fleet-baseline-final-archive-prep.2tiUxV`). The new private archive
helper in `agent-fleet-baseline-final-archives.rR245B` uses exact543 source inputs
plus frozen README/guide, with331 runtime files/332 including guide,115 schemas
and migrations1–13. It must require a final execution-release manifest binding
raw matrix/static/collection files and their hashes, the independent matrix seal
and its same-candidate/input/totals fields, plus helper/plugin/document hashes.
The release manifest remains absent until actual full acceptance and docs freeze.

Independent pre-execution review reproduced an old draft helper accepting a
foreign PASS seal without sealed raw input entries; root narrowed these guards.
The old draft also lacked proof of actual imported source. The corrected helper
will execute the unchanged distribution test from its retained private source
snapshot, with explicit source paths and a read-only pytest origin observer.
That observer asserts and records every loaded Fleet/test file's strict origin
and frozen hash, including actual conftest and distribution module, at collection
end and session end; it cannot change tests, tools or model behavior. Main source,
snapshot, documents and the actual Python/dependency bytes must remain identical
before/after. The distribution test remains one unchanged test; no fresh dependency
installation, physical Docker, live compliance or broader goal success is implied.

Before any invocation, two drafting assumptions were also corrected from source:
the actual metadata distribution is `pydantic-ai-slim`, and the exact test is
`test_wheel_and_sdist_ship_runtime_resources_without_development_fixtures`.
Current private helper4cf4a490 and observer36dc5bd9 passed independent bounded
pre-execution review at22:23:08UTC:35 fresh pure-memory controls, including the
original foreign-seal counterexample, missing/wrong prerequisite and origin/
hash/symlink substitutions. Root read and SHA-checked seal2bfb8844 in private
`agent-fleet-baseline-archive-helper-review.zslaZT`; original3a51 helper FAIL
bd66261e remains retained. Full matrix, document freeze and execution release are
still required. No build/install or archive execution has occurred under this contract.

### First physical Python smoke contract (before fixture preparation)

Root has fully read the prepared998-line private helper7ecd3650, both fixture
sources, execution contracta4da5860 and runbook, and SHA-checked bundle
`3be1589af68c76e9a67ce4237eedac0761abf2ce5ac1295cf0cdf6912de5d968`
under `agent-fleet-python-baseline-smoke.4dyr1y`. All stages remain NOT_INVOKED.
After independent pre-execution review, root as the non-Worker operator may
explicitly release only `prepare --authorize-fixture-setup` to create its new
private attempt: commit one generated Python target/config and register it via
the real Project state API, with private Safe trust and literal `.` scope. This
is registration-only fixture setup, not a public Bootstrap/cold-start result;
there must be zero legacy Run/Task/Agent/artifact/command/lease identities.
No existing Git index/target/state, main/clone source, dependency or model changes.

Only after combined main default/static and ordinary Docker regression acceptance
may root separately release its read-only `review` stage against the pinned local
daemon/image already named above. Inspect the actual review/scope/DB before one
explicit `run --allow-once --review-sha256 <actual-digest>` within the original
five-minute expiry. Each stage/output/spent marker is exclusive. Missing consent
must first refuse with full logical table/schema equality and no owner/dispatch/
leases, then at most one approved command may dispatch. Do not chain stages,
refresh the review, repeat execution, widen permissions or automatically recover.

Exact configured command: `python -B -m unittest discover -s tests -p test_*.py -v`,
command ID `python-baseline-smoke`, cwd `.`, empty environment,30 seconds and64000
output bytes. Nonroot/no-network/read-only Docker uses1 CPU,512MiB,64 PIDs,
64MiB each `/tmp` and `/cache`,16MiB shared memory (144MiB total scratch ceilings,
not144MiB actually written). Three tests cover arithmetic, real source mount `ro`
and EROFS30 on create/truncate, and tiny write/read/delete of command-owned scratch.
Only the private candidate worktree is exposed; failed boundaries do not authorize
application to any original target. No model, install, image pull/build or host
fixture-test execution; the Worker remains prohibited from physical invocation.

Retain original CLI exit/timeout/truncation, typed review/observation/report/native
inspection, full private logical DB backups and row/schema digests, actual
controller PID, all source bindings and exact worktree/container absence. Require
one consumed authorization/owner/dispatch/observation/report, three released leases
and complete receipts, zero legacy execution rows, unchanged original target,
`baseline_observation_only` and `target_applied=false`. Helper observations are not
an independent verdict; obtain separate readback after actual execution. Unknown
handle/cleanup/result stays uncertain with preserved resources. A420-second outer
timeout can interrupt normal cleanup and is not evidence of absence. Diagnostic
`inspect` is separate and no recovery or broad deletion is authorized. Node,
six-business-repository acceptance, Session, cold starts and S1 oracle remain open.

- [x] (2026-09-09 22:43 UTC, before preparation) Independent final static review
  of helper7ecd3650/bundle3be1589a confirms the three reported preparation issues
  corrected, exact four-file manifest and absent attempt directory. This is no
  physical verdict. Root now releases only the exact `prepare
  --authorize-fixture-setup` stage under the contract above; review and execution
  remain separately gated. No model or key may be accessed.
- [x] (2026-09-09 22:44 UTC) The separately released prepare stage exited0 and
  retained setup plus raw DB/table evidence. New target commitfad23f32 has14
  committed regular files, clean source manifestb74cc720; one registered Project,
  thirteen migrations and zero baseline/Run/Task/Agent/artifact/tool/lease/model
  execution rows. Two normal registration/policy audit events are not execution.
  Existing default Project fields remain unbootstrapped/fake, while the committed
  baseline configuration requests the pinned Docker provider; no public bootstrap
  or fake execution was fabricated. Review and dispatch have not run.
- [x] (2026-09-09 22:44:59–22:49:38 UTC) Completed the separately enabled three-case fresh
  installation gate with helper224553c4 on30b8f476 after Docker PASS286dee19.
  Frozen READMEed1323b7 and USER_GUIDE92a10891 are held for this gate. Only the
  prepared95-wheel offline closure and already pinned local Docker may be used.
  Result0434e528:3 passed/276.18s,278.518s wrapper,exit0,exact source/docs/native
  bindings held. Independent installed/archive/physical readback is assigned,
  not inferred from exit0. Subsequent result-document changes are allowed only
  after this terminal receipt and require a fresh final archive binding.
- [x] (2026-09-09 22:53 UTC, before review) Root separately releases only the
  prepared `review` stage. Current default/static independent acceptance and
  actual ordinary Docker29 regression pass; independent Docker readback reports
  no blocking resource finding, with its final seal still being written. This
  release permits pinned local Docker metadata reads and one persisted review,
  not a command dispatch. Root must inspect the resulting exact scope/digest and
  original expiry before any separately authorized run; it cannot refresh/replay.
- [x] (2026-09-09 22:53 UTC, before dispatch) Public plan exited0/5.428s and
  produced ready reviewbreview_3e410640a602422e98f355d2ebeae280 for
  baseline_4bede594bddd47b6a5bacf23e61f5253. Root read actual CLI/scope/raw logical
  DB evidence: digestb1d1af5e25d75a4d482b040fc19cd72fcbee71b0d10d96f0f31018ee52074d3a,
  sourceb74cc720,configuration31376601,trust312d6af5 revision1,exact command68b23402,
  pinned image2afebd51/daemon815f9bce,read-only/no-network policy5180b411 and the
  documented resource limits. One planned execution/review,zero authorization/
  owner/dispatch/observation/lease/model/legacy execution rows. Original review
  expires22:58:13.749218UTC; it is not renewed. Root explicitly grants allow-once
  for this exact existing scope and releases one `run` stage with that full digest.
  Missing-consent negative check must precede at most one approved dispatch.
- [x] (2026-09-09 22:54:07 UTC) First physical Python baseline command completed
  through the unchanged public CLI,exit0/10.904s,no timeout/truncation; root helper
  stage also exited0. Missing-consent invocation first returned2/APPROVAL_REQUIRED
  with unchanged full logical tables/schema. Exactly one approved Docker command
  ran three unittest assertions (3 OK/.001s), with nonroot/read-only mount markers,
  two actual EROFS30 refusals and tiny scratch write/read/delete. Approved,
  materialized and post-command source hashes allb74cc720; original target remains
  unchanged. The helper observed three released leases, three cleanup receipts,
  exact native/worktree absence and normal report586e2701 with no proof gaps,
  baseline_observation_only/target_applied=false. Retained result5544cb86,
  raw-DB summary647e415d and typed readbackf15cb512. This is root execution evidence,
  not an independent verdict; independent physical readback remains pending.
  No second run, diagnostic inspect, recovery, image preparation or model occurred.
- [x] (2026-09-09 22:55:26 UTC) Ordinary Docker29 independent original-evidence
  readback PASS60497364,root complete read/hash-check.45 DBs,681 artifacts,199
  terminal leases (190released/9recovered),26 matching CompletionGate replays
  (16true/10false),66 absent worktree paths,29 original-only Git registries,52
  absent known native IDs and19 empty exact installation scopes. Two no-handle
  recovered cases preserve historical uncertainty, with current exact-label
  queries empty; no claim they never created an execution. Eight test-authorized
  applied targets and21 unapplied targets remain correctly distinguished.
  All543 source and9837 installed dependency files unchanged; audit performed no
  execution/cleanup. Installed and separate physical-baseline readbacks remain open.
- [x] (2026-09-09 22:57 UTC, before archive execution) Root releases the reviewed
  helper4cf4a490/observer36dc5bd9 in private
  `agent-fleet-baseline-final-archives.rR245B` for one frozen-document checkpoint.
  README70af2ccf and USER_GUIDE92a10891 are frozen; documents explicitly retain
  pending installation/physical independent acceptance and the latest live FAIL.
  Release binds exact raw matrix/static/collection and independent matrixda654c0c
  hashes,3989 identities/3966passes/23skips,543-code30b8 and helper/plugin hashes.
  No other acceptance is implied. Keep these documents/source held throughout
  execution/readback. Later result-document edits require a new uniquely named
  archive checkpoint, never overwriting this one.
- [x] (2026-09-09 22:57:22 UTC) Frozen-snapshot archive command exited0:
  1 distribution test passed/2.85s,6.314s wrapper. Wheel61352c76 and sdist0bd8da05
  were freshly built; exact snapshot manifest458a943c includes543-code30b8 plus
  README70af2ccf/guide92a10891. The origin observer checked159 actual Fleet/test
  modules before/after; source/snapshot/documents and installed runtime byte
  inventories were unchanged. This is existing-dependency installed-wheel smoke,
  not another fresh installation or model execution. Independent332-resource/
  115-schema/13-migration/installed-state readback is assigned; docs remain held.
- [x] (2026-09-09 23:02:32 UTC) Current installed3 independent PASS98088803,
  root complete read/hash-check. Six archives/three environments match332 runtime/
  guide files,115 schemas,13 migrations and original READMEed1323b7/guide92a10891.
  All95 prepared wheels match the lock; each environment has79 dependencies plus
  Fleet,7607 checked wheel-content files and7867/7868/7867 verified RECORD hashes.
  Six original DBs,215 artifacts,10 matching gates,54 released leases,18 absent
  paths,6 absent known native IDs and1 empty exact installation scope checked.
 147 original CLI receipts include20 expected refusals, not20 test failures.
  Three learning targets intentionally applied; two reviewed-plan targets unchanged.
  No execution/cleanup replay. Initial private audit discovery error is retained
  separately, not a production test failure. Final archive and separate physical
  baseline independent readbacks remain pending.
- [x] (2026-09-09 23:06 UTC) Frozen archive independent PASS84a0d527 in
  `agent-fleet-baseline-final-archive-audit.zHySP0`,root complete read/hash-check.
  Actual wheel61352c76/sdist0bd8da05 and installed wheel match332 resources,
  115 exact schemas and migrations1–13; README70af2ccf/guide92a10891 match exactly.
  All545 snapshot inputs and543 main code inputs match,159 root-executed origin
  records bind only snapshot modules,9837 dependency bytes unchanged. Original
  quiescent migrated DB has53 empty application tables;347 retained fixture
  entries unchanged. No new test/build/install/physical/model execution or cleanup
  was performed by this readback; original installed-origin smoke was root-run.
  The checkpoint's pending-audit prose is accurate at its freeze and will be
  updated only with a new result-document archive after the separately gated live
  attempt. Separate physical baseline readback remains pending.
- [x] (2026-09-09 23:10 UTC) Root accepts the narrow first physical Python
  baseline after independent readbackcd66a97d/resultf0200038, completed23:06:20UTC.
  All14 canonical baseline rows,one consumed authorization/permanent owner/
  dispatch/observation/report,3released leases/receipts,exact3 test outputs and
  b74cc720 source equality verified. Full no-consent table/schema equality and
  original non-baseline state invariance hold. Fresh exact native/worktree queries
  are empty. All102 original input files and543 source files unchanged; original
  DB quiescence and retained backup sidecars accounted separately.800 readback
  assertions are not800 tests. No helper/CLI/model/recovery/cleanup was replayed.
  This accepts one generated registration-only physical baseline, not Session,
  Node,real business cohort,cold starts,oracle or the whole S1–S3 goal.
- [x] (2026-09-09 23:10 UTC, before Git staging) Root authorized one coherent
  local baseline implementation commit: exactly45 accepted code/test/schema files,
  this plan and five accompanying architecture/security/configuration/user-guide/
  ADR documents (51 paths). README,parent plan and the new prepared-only Session
  plan remain for a separate documentation checkpoint. Existing unrelated changes
  and prior guidance commit remain intact. Source30b8 and README70af/guide92a
  must remain byte-identical; no GitHub merge or paid execution is authorized by
  this local commit operation.
- [x] (2026-09-09 23:12 UTC) Local commit8fdf7eb recorded exactly51 reviewed
  paths after staged-byte equality to the accepted45-file manifest,complete543
  source inventory equality and cached whitespace check. Code30b8 unchanged.
  No push/merge or paid request occurred. This final post-commit plan entry and
  README,parent/Session plans belong to the next documentation checkpoint.
