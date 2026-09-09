# S1–S3: measured real-model operation, usable sessions and replaceable Harnesses

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

After the bounded live prerequisite, develop the whole-system S1–S3 objectives in `docs/NEXT_OKRS.zh-CN.md`: measured real tasks and additional model providers, repository readiness and ordinary Session workflows, and independently qualified runtime adapters. A user should be able to inspect `fleet readiness .`, remain in `fleet` for review/approval/diagnostics, select admitted per-role models/Harnesses, and receive evidence whose independent evaluation can be recomputed. These are intended journeys, not claims that every command or adapter already exists.

The latest owner instruction authorizes autonomous testing and completion of the active goal: confirm E2E, implement S1–S3, split coherent commits and merge to the GitHub repository. The earlier September7 planning-only restriction is superseded for S1–S3, not for unrelated S4–S8 features. Preserve the historical planning documents and all failed test results. GitHub Actions minutes are exhausted: use local gates, do not disable protection or infer remote acceptance from local tests.

## Scope

### In scope

- S1.1 immutable evaluation contracts, durable campaign/attempt accounting, external evidence/oracle checks and the preregistered 24-task/6-repository baseline. Existing six calibration attempts remain their own history, not retrospectively selected campaign successes.
- S1.2–S1.4 explicit Provider boundary, Anthropic and Google Gemini adapters with actual-SDK offline contracts, then credential-specific opt-in live qualification when credentials exist.
- S2.1–S2.4 read-only readiness, bounded approved business baseline, existing Session management improvements, four reviewed role/verification bundles, five-strategy and cold-start journeys.
- S3.1–S3.4 shared Runtime conformance/admission, OpenAI Agents SDK, mixed-Harness operation, bounded LangGraph beta and evidence-backed Codex/Claude Code feasibility.
- Necessary security/regression/package checks and scoped GitHub delivery. No unrelated repository changes or private evidence/key commits.

### Out of scope

- S5 Dashboard expansion, S6 connectors, S7 Memory/self-evolution, Modal/Hosted deployment, automatic dependency installation, unrestricted network/host execution, native checkpoint/token-streaming claims without separate proof, public package release/license decisions.
- Reusing the supplied OpenAI credential at any other endpoint/provider, storing it in a file or global environment, mounting it into workers, or reading unrelated credentials.
- Unlimited paid retries, lowering frozen success thresholds, silently swapping models, deleting failed samples or turning product self-reports into external oracle truth.

## Current repository state

Baseline Git HEAD is `3fb09711851b27b5276d7faddd50bc317e2536fb`; the checkout contains accepted but uncommitted Session/live-correction work and user-authored untracked roadmap documents. Preserve that work and stage only reviewed, exact file sets.

`application/workflow.py` owns task/role lifecycle and `CompletionGate`; `application/runtime_tools.py` owns bounded runtime tools through Gateway/Broker/Sandbox. `adapters/runtime/pydantic_ai.py` supplies the real Harness with explicit OpenAI transport, secret boundary and pre-request accounting. Fake runtime remains deterministic offline support, not a live adapter. Model Provider, Harness and Sandbox are separate capabilities.

`domain/models.py:FrozenStrictModel` freezes attributes, but some existing nested dictionary/list fields remain mutable. New immutable evaluation models must not embed such mutable historical wrappers and call them deeply immutable. Existing Run JSON remains unchanged; later evaluation persistence will use sidecars.

SQLite `runtime_budgets` owns durable Run accounting. Campaign budget extensions must reserve atomically before provider/tool side effects and bind attempts to actual root Runs; do not synthesize a cross-project parent Run. `SqliteStateStore._insert_run_in_transaction` is the existing atomic Run-admission integration point. Inspect the current migration maximum immediately before a migration; do not reserve a number early.

The existing Session already supports foreground interaction, reviewed plans/permissions/patches, custom roles and immutable model bindings. S2 is not another REPL. `DoctorService.inspect` currently migrates state; a default side-effect-free readiness command must not accidentally reuse this path or construct a migrating container.

The bounded prerequisite source/test/script digest is `7af364db0934f12f46e35304e2feee07d7ebfb5a2e59ce5a54b693bca25d1577`. At2026-09-09 10:37:04UTC an independent verifier accepted attempt6: real CoS/Engineer/Verifier, two Docker pytest receipts,18 valid artifacts,116 events, strict completion replay,7 reported requests/36365 tokens and12 released leases with no remaining exact-scope containers. Original target remains unapplied. The canary has one procedural criterion, so it is not the S1 external-oracle baseline. Exact prior quality results and five paid failures are retained in `.agent/plans/2026-09-08-low-budget-live-e2e.md`.

## Security impact

All existing `docs/SECURITY_MODEL.md` invariants remain in force. Pure evaluation contracts grant no execution authority. Artifact references first prove only structural linkage; a later trusted evidence reader verifies actual bytes, identities and oracle provenance. Hidden oracle execution must use an authorized isolated Gateway path, never host subprocess shortcuts. Successful patch application is not independent correctness proof.

Provider credentials remain in a trusted transient control-plane process, with explicit provider/endpoint binding, no ambient fallback, redirects, retries, cookies or telemetry. A key disclosed in chat should be rotated after testing. Missing Anthropic/Gemini credentials permit offline implementation but not their live-verified label. All SDK native tools, handoffs, hosted tools, sessions and tracing stay disabled unless individually admitted and proven safe.

Campaign limits are finite and frozen before dispatch. A schema limit is a parser protection, not spending authorization. Unknown requests consume conservative reservations, cannot be called zero usage, and cannot be automatically reissued. Budget/permission/cancellation checks precede effects across every claimed Harness. Recovery must reconcile existing identity, not create a replacement attempt to improve reported results.

## Proposed design

Work as coherent vertical slices, with one writer for shared contracts/persistence/workflow and a fresh independent verifier. Freeze each task contract before source changes. Narrow independent read-only investigation may proceed in parallel.

The first slice is deliberately pure: immutable `EvaluationManifest`, `OutcomeRecord`, `EvaluationReport` and `evaluate_records(manifest, records)`. A manifest preregisters repository/cohort identity, exact tasks/configuration/oracle/commands, every attempt slot and finite budget values. Outcomes keep product status, external result, usage, cleanup and apply observations separate. A deterministic report uses the frozen first-round denominator, reports repeated/auxiliary attempts separately and never awards automatic KR acceptance. It performs no I/O or live calls.

Subsequent persistence adds atomic campaign ownership/reservation and immutable evidence-backed outcomes before an execution CLI is enabled. Runtime budgets join exact bound root Runs, include all roles and retain unknowns across restart. Only then may a frozen, credential-scoped live campaign run. Readiness first statically profiles supported environments without migration/execution; an explicit baseline invokes existing approval and sandbox machinery. New Provider/Harness admission is closed until its relevant contracts pass.

## Public contracts

First slice adds three generated public JSON Schemas, with bounded tuple-only nested models, strict integers and UTC timestamps. Models have no arbitrary metadata extension. Manifest hash is derived from canonical content, not caller supplied. Evaluation records identify the manifest hash, case and preregistered repetition; report recomputation rejects conflicting/duplicate records and root-Run reuse. New schemas must not alter bytes of existing schemas.

Engineering limits for the first schema:16 repositories,64 cases,256 slots,3 attempts per case,128 permitted paths and1MiB encoded manifest. Reuse existing bounded strings/identifier/hash conventions. These are validation ceilings only; a campaign requires separate lower authorized limits.

No exclusions in v1: every preregistered legal first-round task stays in the denominator. Missing differs from explicit not_run, unknown differs from zero, and all-unmeasured percentages remain null. Do not call first-attempt success “no-repair first-pass” because Run-internal repair needs separate observations. Holdout retirement requires a new manifest revision; labels do not themselves prove isolation. Code-change success requires the frozen patch/apply/post-apply/oracle/cleanup evidence; read-only success does not fabricate a patch. Structural validity alone never asserts that evidence bytes were audited.

Later CLI, events, migration and adapter-contract changes require an amendment specifying exact names, compatibility and error semantics before implementation. Ordinary historical Run/configuration wire contracts must remain stable unless separately reviewed.

### S1.1a exact field freeze (2026-09-09 11:08 UTC, before implementation)

`EvaluationManifest` contains schema_version1,manifest_id,campaign_id,revision,previous_sha256,frozen_at,repositories,cases,slots,budget; its sha256 is derived only. RepositoryDescriptor contains repository_id,source_sha256,commit_sha,cohort. Case contains case_id,repository_id,task_kind,requirement,allowed_paths,required_evidence,oracle_sha256,scoring_sha256,command ID/hash tuples,image identity,dependency digest,profile ID/revision/digest,configuration digest,finite run-budget projection and nullable auxiliary purpose. Slot contains case_id and repetition0..2. Auxiliary slots may reuse a development repository without entering the cohort denominator; source identity cannot cross development/holdout.

OutcomeRecord contains outcome/campaign/manifest/case/repetition/attempt identity,optional rootRun/task,UTC recorded_at,configuration/oracle/scoring digests,nullable product status/verdict/verified_complete,external result,user acceptance/apply status,immutable typed evidence references and usage/cost observations. Evidence references bind exact IDs,run and digest. Report contains manifest/campaign identity,overall/development/holdout/per-repository first-round groups,repeats,auxiliary groups,all slot observations including missing,aggregate reported usage lower bounds/unknown counts and per-currency costs. Its assurance is structural_only and KR status is not_evaluated; reference validation does not audit physical bytes.

Rate clarification: only missing and explicit not_run count as unobserved. dispatch_unknown and inconclusive are observed non-successes, so a group containing one has a success/frozen-denominator rate plus explicit uncertainty counts, not null. Null means no observed attempt in that group at all; it never turns unknown into success or known zero cost. Nested fields use strict frozen scalar/tuple contracts, accepting canonical JSON arrays as tuples while rejecting mutable Python list input.

### S2.1a frozen next contract: static readiness only (2026-09-09 11:27 UTC)

This is a second bounded slice, queued until the S1.1a independent hash/scope audit closes. `fleet readiness [path] [--json]` provides a real static repository/configuration report without execution, state connection/migration or preparation. It uses hardened RepositoryPort.inspect, a real ReadinessProfilerPort,ConfigurationPort and Redactor, never build_container/DoctorService/StateStore/RuntimeRegistry/Sandbox/SecretStore. Git calls only establish repository identity using the existing hardened adapter; no host python/node/npm/version probing is allowed.

Preserve `StaticRepositoryProfiler.profile(root) -> RepositoryProfileResult` and its old serialized bytes. Add opt-in `profile_with_metadata(root) -> tuple[RepositoryProfileResult,StaticReadinessMetadata]`, calling the same private `_profile(root,capture=None)` once. Capture receives the same successfully read/parsed pyproject/package text in memory; it may parse that text but cannot reopen files,expand discovery or read lock contents. New capture errors affect only metadata diagnostics, not old profile semantics. Preserve existing512KB/20k-entry/depth12 ceilings.

Capture bounded Python requires-python,direct/optional/dependency-group declarations and dynamic/unsupported markers; Node packageManager,engines,direct/dev/optional dependencies. Never retain script bodies,raw manifests,URL/userinfo/VCS/path dependency strings or raw parse exception text. Report normalized source type/unknown reason instead. Lock presence is only a filename signal, not resolved/install proof. Dependency/version declarations are not a dependency solver or sandbox attestation.

New ReadinessReport includes repository/HEAD/status/profile/config hashes,boundaries,static declarations,configured commands separate from detected candidates,diagnostics/truncation and next steps. All first-slice reports fix environment_status=unverified,baseline_status=not_checked,execution_authorized=false,commands_executed=0. Existing .fleet is read and validated,never initialized; config failures cannot silently become default config. Do not import stale canary reports or invent baseline pass/fail from filenames. Exit0 means static inspection complete,not ready; exit1 means a report with parse/limit/missing-verification/config issues; exit2 means invalid arguments or no safe repository boundary. Human output states no environment verification,baseline or project command execution. No unimplemented --run/--prepare/--verify options.

Limits:64 captured manifests,512 declarations,256 commands,64 boundaries,128 diagnostics and1MiB report UTF8. All truncation is explicit incomplete. Avoid raw existing ambiguity strings if they can expose source/exception text; project only bounded safe categories/provenance. Registered secrets and URL credentials must not escape JSON or human errors.

Writer ownership: new domain/readiness.py,ports/readiness.py,adapters/repository/readiness_metadata.py,application/readiness.py,cli/readiness.py; metadata/readiness unit tests,integration/test_readiness_service.py,e2e/test_readiness_cli.py. Limited profile.py refactor and existing profile regression tests; then serialized bootstrap.py lightweight factory,cli/app.py registration,schemas/generate.py/test_schema_generation.py and readiness-report.schema.json after S1 writer release. Root owns documentation. Preserve all other changes; no new evidence-reader placeholder,DB migration,provider/dependency installation or actual execution.

Filename correction after initial collection: the integration test uses
test_readiness_service.py because this repository's pytest import mode cannot
collect unit/test_readiness.py and integration/test_readiness.py together.
No global pytest configuration or acceptance scope changes.

Acceptance: legacy/new profile JSON equality,single file-read proof,no lock-body reads,accurate Python/Node declaration projection,dynamic/unsafe/ambiguous/malformed/oversized input diagnostics,configured-vs-candidate separation. Negative CLI tests preserve target,index,.fleet,state and sidecar bytes; absent state remains absent. Monkeypatch forbidden construction/connect/execution boundaries to fail if reached. Every valid output remains unverified/not_checked. Actual6 prepared/pass/fail repository cases,external baseline execution and Session integration belong to subsequent evidence-reader slices and remain unfinished KRs.

### S1.1b1 durable preregistration ledger (2026-09-09 11:46 UTC)

The next S1 writer may implement a complete non-executing Python service:
register immutable manifest, reserve a preregistered slot with its full finite
Run-envelope commitment, record a preflight observation, reopen and recompute the
pure report. This is useful durable measurement preparation, not paid-run admission
or campaign-wide runtime enforcement. No execution CLI, dispatch token, existing-Run
attachment API or unused future execution methods are permitted.

Add strict immutable CampaignRegistration,EvaluationReservation and
EvaluationLedgerSnapshot models in domain/evaluation_campaign.py, a real
EvaluationStore protocol, SqliteEvaluationStore and EvaluationLedgerService.
Methods are register(manifest),reserve(campaign_id,case_id,repetition,idempotency_key),
record_preflight_outcome(record),snapshot(campaign_id); the service report method
recomputes evaluate_records from one consistent snapshot. Return values fix
execution_authorized=false. Counters distinguish permanently committed envelopes
from reported actual usage/cost; zero committed work is legal, unknown usage/cost
is not invented. IDs/UTC/hash/tuple bounds follow the accepted evaluation models.

Return-shape clarification: record_preflight_outcome returns the consistent
EvaluationLedgerSnapshot, containing the immutable original outcome and its time,
so every ledger operation exposes execution_authorized=false. It does not wrap or
mutate the accepted OutcomeRecord wire schema.

The next migration number must be confirmed immediately before writing (currently
maximum10). Four tables: evaluation_campaigns holds immutable canonical JSON/hash
and trusted registration time with campaign identity and manifest ID/revision
uniqueness; evaluation_slots preregisters exact slots; evaluation_reservations binds
globally unique attempt IDs,one slot,activity-local idempotency digest,UTC reservation
and exact case budget commitment; evaluation_outcomes binds unique outcome/attempt
identities and immutable canonical JSON/hash. Do not alter existing Run JSON or
tables. A campaign ID binds one immutable manifest. Later manifest revisions need
an already retained exact predecessor with the same manifest ID,revision+1 and a
new campaign ID; registering a revision is not execution/spending authorization and
does not release prior commitments.

All mutations use BEGIN IMMEDIATE and fully validate existing rows/hashes/foreign
identities before decisions. Existing migrated state only: no implicit migration or
connection-time creation from this service. Reject future schemas and malformed,
oversized,duplicate or contradictory rows with safe typed errors; no raw SQL,
model-validation input or secrets in messages/causes. Inject Clock/IdGenerator and
Redactor. Reject secret-bearing inputs before persistence, including their canonical
JSON forms. Keep raw idempotency keys out of persistence; accept a bounded explicit
identifier and store its digest. Read snapshots consistently before reporting.

Exact repeated registration/reservation/outcome returns the original object and
time without a second charge. Conflicting content/key/slot/attempt/outcome identities
fail closed. Reservations permanently consume a slot and full case envelope;
atomic summed attempts,agent invocations,model requests,tool calls,tokens and active
seconds cannot exceed the frozen campaign. No refund or replacement sampling after
failure. Registration cannot predate frozen_at, and outcomes cannot predate actual
registration/reservation. Missing after interruption remains missing,never silently
not_run. This slice accepts only no-Run preflight results (environment_failure,
provider_failure,budget_exhausted,timeout,cancelled,inconclusive,not_run); rejects
verified_success,functional_failure,dispatch_unknown,Run/task/product observations,
applied/failed patch observations,non-diagnostic references,positive model/tool/token
usage,unknown requests and positive cost. Nonnegative measured preflight elapsed
time is permitted without claiming model execution. Reuse evaluate_records for
all linkage/global identity checks. Diagnostic references remain structural only.

Writer owns domain/evaluation_campaign.py,ports/evaluation_store.py,
adapters/persistence/evaluations.py,application/evaluations.py,new domain/store/service
tests and migration, the supported SQLite version and necessary historical migration
test-fixture corrections. Preserve byte assertions for old tables; construct genuine
pre9/pre10 states rather than deleting migration markers beneath newer tables.
Schema registration/test additions are serialized after the S2 writer releases those
shared files; no bootstrap/CLI/workflow/runtime-budget edits. Root owns docs. Existing
Run-admission and runtime-ledger integration remains a later written slice; the
current separated create_run/initialize_run transactions cannot be waved away.

Migration-fixture amendment (2026-09-09 12:08 UTC, before those edits):
tests/integration/test_release_upgrades.py and test_config_snapshot_binding.py
construct schema-7 copies from current databases. Exclude only the four new
evaluation tables from these historical-copy fixtures, preserving all existing
old-state and byte assertions. Otherwise their later migration would encounter
newer tables with historical markers. No production migration relaxation.

Acceptance: real SQLite register/reserve/record/reopen/report path, exact idempotency,
two-process same-slot and last-budget races, injected rollback,36-slot upper bound,
permanent commitments after failure/restart,secret/invalid/corrupt/future-schema
rejection,old table preservation and retained missing/unknown semantics. No provider,
Docker,credential reads or execution effects. Preserve failures and publish exact
per-file inventories/commands/JUnit; do not call this paid campaign acceptance.

### S1.1b2 real reserved-campaign execution (2026-09-09 13:34 UTC)

Implement `EvaluationExecutionService.execute_reserved(campaign_id,
expected_manifest_sha256,case_id,repetition,idempotency_key,project_path)` as a real
Python service into the existing Workflow, not a second orchestrator or merely an
unused dispatch schema. Require an already registered project and reservation.
No model/budget/command/image overrides, automatic setup, dependency downloads,
CLI, live calls or campaign evidence-outcome invention in this slice. Ordinary
Runs and Session wire contracts remain compatible. Campaign and conversation
submissions are mutually exclusive before mutation.

One BEGIN IMMEDIATE transaction must bind a unique reserved attempt/root Run,
create the Run and run.created event, save immutable RunModelBindings, initialize
the exact budget owner/limits/receipt and consume a single-use dispatch claim.
Extract same-connection private helpers from the existing stores; do not imitate
their validation in a second path. A failure rolls back every new execution row,
not the earlier permanent reservation. An exact retry returns the original Run
without another dispatch capability. Preflight outcomes exclude later execution.
No lease expiry, replacement root, automatic claim takeover or crash replay.
Ordinary resume and child runtime dispatch must not bypass campaign claim checks.
First slice deliberately rejects interactive campaign resume; paused Runs remain
inspectable/cancellable. Explicit stopped-owner recovery may fence/clean known
resources without refund, replacement execution or inferred success.

Use bounded immutable domain/port/application/SQLite evaluation_execution modules
and the next migration (confirm current maximum11 immediately before writing).
Persist exact manifest/case/attempt/project/root identities, source commit/hash,
configuration and bindings hashes, image/dependency/command identities, exact
limits, UTC admission and claim lifecycle. Attempt and root IDs are independently
unique and reference an existing reservation. Reject corrupted, oversized, stale,
secret-bearing or contradictory rows with fixed typed diagnostics. Keep raw
idempotency keys and process credentials out of persistence.

Define source_sha256 as a versioned sorted committed-tree descriptor containing
canonical relative path, Git mode and file-byte SHA256. Read Git objects without
filters/hooks/repository execution; reject symlink/gitlink/noncanonical and
over-limit trees. RepositoryInfo.identity_hash is repository identity, not content.
Bind a clean checkout and exact commit separately. Dependencies use a versioned
bounded list of declaration/lock paths and content hashes, explicitly not installed
dependency proof. Reuse actual ConfigSnapshot serialized-byte hash and existing
CommandSpec canonical JSON hash. Require all selected roles to resolve to the case's
one exact ModelProfile record/revision/configuration; mixed-profile campaigns are
not admitted by this first contract. Validate image preflight's exact SHA256 and
required command IDs plus contents. External files are not locked by SQLite:
recheck under existing organization admission and use captured snapshot/pinned
commit. Accepted CoS scope must satisfy frozen kind/path/command constraints before
workspace preparation; reject rather than silently repair an out-of-scope decision.

Graph initialization must register every child budget owner in its existing
transaction before any dispatch. Root actual parent must be absent/self-owned;
child initialization argument, actual Run parent and validated graph binding parent
must agree, inheriting exact root limits. Child initialization without parent must
not mint a fresh allowance. Strengthen existing owner verification accordingly.

Campaign admission checks run in the same write transaction as root creation,
begin_attempt, reserve_request and reserve_tool_batch. Validate at most256 bindings
and their existing durable receipts; never blindly sum unvalidated JSON. Effective
commitment equals permanent complete envelopes plus each root's positive observed
token/active-time overrun. Any unknown request quarantines new campaign admissions;
do not refund, relabel zero or automatically retry it. Outstanding requests remain
charged, but need not block otherwise permitted concurrency. Reserve an entire
tool batch before any effect. Already dispatched requests/batches cannot be recalled.
These are conservative future-admission limits, not an absolute token/time/billing
cap: preserve observed10-reserved/12-used overruns and stop continuation.

Fixture amendment (2026-09-09 13:40 UTC, before fixture edits): the historical
runtime-budget test's _related_run(parent=True) constructs a root with no actual
parent, then initializes it as a child. Noether may correct only that fixture/test
to a genuinely graph-bound child or assert rejection of the former forged alias;
retain real Graph inheritance coverage. Root's second shared test run crossed the
writer's in-progress import wiring and cannot accept a dependency closure. Defer
new admission wiring until its concrete store exists; do not add a permissive stub.

Noether owns the four new execution modules, required repository source-descriptor
port/adapter code, workflow.py, persistence/model_profiles.py, runtime_budgets.py,
graphs.py, necessary execution-store port additions, next migration/SQLite version,
new focused tests and narrowly required historical migration-fixture exclusions.
Root owns bootstrap wiring and all docs; Helmholtz owns only the four new SDK files.
Schema generation edits require an explicit handoff because root is checking
registration compatibility. Preserve prior user/agent changes; no other writer may
edit Noether's existing files until freeze/release. Public existing methods retain
their signatures/behavior except the explicitly hardened child-owner checks.

Ownership amendment (2026-09-09 13:43 UTC, before further edits): Noether also owns
the narrow evaluations.py record_preflight_outcome guard rejecting an already
bound execution, symmetrically with dispatch rejecting an existing preflight
outcome. Test their concurrent race; neither operation gains outcome authority.
Root has completed runtime-enum schema generation and releases the shared
generator/schema-test files for the execution-model registration only.

Image-identity amendment (2026-09-09 13:49 UTC, before correction): the first real
bridge fixture exposed that EvaluationCase requires a Docker image SHA while
existing FakeSandbox/Run/Project explicitly forbid an image identity. Do not
invent an image hash for simulation. Noether may make the existing required
EvaluationCase.image_identity field nullable (no omitted/default field), update
its generated schema and focused domain tests. Execution admits only fake or
Docker: fake requires manifest and preflight identity both null and preserves
SIMULATED_EVIDENCE_ONLY; Docker requires exact non-null preflight image SHA equality.
LocalUnsafe campaigns are not admitted. Configuration hash still pins the selected
sandbox, preventing a null-image case from silently changing to Docker. Negative
tests cover fake-with-SHA, Docker-with-null, identity mismatch and attempted unsafe
provider, all before dispatch. This is an explicit simulated-vs-image contract,
not a claim of a fake image or weaker Docker proof. Earlier structural inventory
334c is historical after this reviewed schema change. The9 fixture failures and
their origin remain retained;36 ordinary root/graph/budget tests passed1.82s.

Required-command clarification (2026-09-09 13:58 UTC, before correction):
EvaluationCase.commands freezes exactly the REQUIRED command IDs and hashes, not
every optional entry in the catalog. Validate that set against the actual derived
requirements before and after CoS scope. The entire optional catalog is still
frozen by ConfigSnapshot hash and remains subject to task/Gateway/Broker limits.
A read-only case may require no commands even when its repository declares tests;
do not grant or run those optional commands. Add a public read-only execution case.

Acceptance requires actual SQLite/public-service/FakeRuntime/FakeSandbox workflow
producing patch, evidence and cleanup; two-process same-slot winner; injected
rollback at each atomic-registration step; crash-before/after-claim and no replay;
source/profile/config/image/command drift with zero dispatch; forged child owners;
cross-root unknown and positive-overrun admission denial; whole-batch zero effects
when rejected; observational ledger/report table equality; ordinary Run, Session,
Graph and profile regression. Reports remain purely observational and return no
fabricated executed OutcomeRecord. Retain every failing test/result and immutable
candidate inventory before independent review. No live or whole-S1 acceptance is
inferred from this simulated execution bridge.

### S3.1a bounded shared invocation-admission contract (2026-09-09 11:39 UTC)

After S1.1a source-scope closure, root may implement this independent slice while
the S2 writer owns readiness. It is not complete Harness conformance or new-Harness
admission. Add a pure domain `require_runtime_invocation` guard over existing
AgentInvocation fields, exact selected runtime, trusted execution kind and declared
capabilities. It rejects unsupported checkpoints unless both checkpoint and resume
are declared, absent structured output/tool capability, unknown unbound custom
roles, built-in role rebinding and custom CoS impersonation. Each current adapter
declares its actual supported five execution kinds; Fake additionally rejects
nonempty CoS tools. Return the resolved execution kind without reading credentials,
calling a model, recording a simulated step or executing a tool.

Both shipped adapters call this guard at entry before credential/model/accounting
effects; PydanticAI's later output schema and Workflow's principal/result checks
remain intact. Fake currently ignores checkpoint_ref and counts a simulated step
before validating its role; fix these discrepancies rather than claiming native
resume. No new public wire fields, schema, protocol placeholder, CLI or capability
claim is added. This centralizes existing admission semantics with two fail-closed
corrections; typed output and effect authority remain independently checked.

Root owns only new domain/runtime_contract.py, new
tests/unit/test_runtime_contract.py and tests/contract/test_runtime_conformance.py,
plus limited Fake/PydanticAI entry-guard edits. No S2-owned files or workflow,
persistence, dependency, configuration or generated-schema edits. Preserve other
writers. Freeze per-file inventories for each slice, because the independent
readiness slice can change the whole-tree aggregate concurrently.

Acceptance: shared adapter-parametrized offline cases for all five built-in kinds,
four legal custom specialist kinds and typed outputs; capability/checkpoint/wrong
selection/rebinding rejection precedes model calls, credential resolution, simulated
steps and catalog execution. Include pure unsupported-kind/capability cases, explicit
no-native-resume assertions and real existing runtime/workflow regressions. The new
shared suite is an initial applicable admission/output matrix, not proof that all
budget/approval/cancellation/evidence or new SDK contracts have been unified. No
live request is needed for this guard-only slice.

## Milestones

### S1.2–S1.3 first Provider implementation contract (2026-09-09 12:14 UTC)

Root owns a working Anthropic API-key Messages path through the existing
PydanticAI tool loop. Admit only canonical anthropic:<model>, alongside unchanged
openai/openai-chat. No arbitrary endpoint,Vertex/Bedrock/Foundry/profile/OAuth,
native tools,streaming,hosted files,SDK tool runner or model fallback. Public
RuntimeConfiguration wire fields remain unchanged. A used provider-selection
module may centralize exact parsing/preflight policy; do not add unused ports.
Preserve OpenAI construction symbols and transport behavior for existing contracts.

Install the already source-qualified pure wheel anthropic==1.3.0, add its explicit
PydanticAI extra and update uv.lock without upgrading unrelated packages. Record
resolved changes and preserve previous lock/image evidence as historical. SDK
imports are lazy after rejecting ANTHROPIC_CUSTOM_HEADERS/ANTHROPIC_LOG and unsafe
debug logging, before credential resolution. No global environment/logger mutation.
An explicit-key AsyncAnthropic subclass avoids the base client's unrelated
profile-discovery warning probe; no credential fallback is reachable. Qualify this
pinned SDK behavior with tests rather than assuming subclassing alone proves it.
Pass webhook_key="",fixed https://api.anthropic.com,explicit caller-owned httpx2
transport,trust_env=false,redirects=false,cookie-rejecting jar,SDK retries0 and
finite timeout. Never pass auth_token="" (which creates a Bearer header).

The final request guard validates exact POST host/path/query/auth/model and finite
token envelope, scans secret-bearing bodies, rejects duplicate/extra credential
headers,cookies and unsupported native/streaming/fallback payloads, then minimizes
headers. Response headers are sanitized before SDK diagnostics/cookie reuse.
Only text and local function-tool/tool-result messages are admitted. Model identity
and usage remain observable; absent counters remain unknown,not known-zero cost.

A per-request single-send gate wraps this actual Model inside the existing secret/
budget wrapper. Each wrapper request opens one context-local mutable ticket; the
transport consumes it before the first send and denies every implicit subsequent
send. This is needed because PydanticAI's Anthropic implementation has its own
stale-thinking/container/streaming fallback paths independently of SDK retries.
The existing outer RuntimeAccounting still reserves before the wrapper and records
unknown on failure/cancellation; this guard cannot allocate extra budget or execute
tools. Never serialize the ticket or pass it to a worker. Provider exceptions are
projected outside exception handlers to finite typed diagnostics with no raw cause,
context,headers,body or request ID. No new live request is authorized by this slice.

Root writer scope: new adapters/runtime/anthropic_provider.py and focused provider
selection/single-send support modules, limited pydantic_ai.py branch/preflight,
pyproject.toml/uv.lock, new actual-SDK transport and workflow tests, necessary
additive existing runtime/model-profile tests, root docs. No Session,SQLite,
readiness,workflow/tool authority/schema edits. Anthropic live remains NOT_RUN
without its own explicitly provided credential and frozen qualification budget.

Acceptance: actual SDK offline request serialization and typed output for all five
execution kinds; multi-step tools through the existing catalog/accounting path;
exact selected keys/models with poisoned ambient configuration; zero fallback or
unreserved second send; timeout/cancellation/429/5xx/malformed output/secret leakage
and client cleanup; shared existing runtime and relevant workflow regression.
Do not label actual-SDK MockTransport tests as live provider or Docker execution.

Anthropic cancellation correction contract (2026-09-09 12:56 UTC, before edits):
independent review of ef721 reproduced repeated cancellation returning while the
physical HTTP transport close was incomplete, although is_closed was already true.
Preserve this failed freeze. Root may add the used adapter-local
provider_lifecycle.py helper and its unit tests. SDK and HTTP closes must run in one
strongly retained cleanup task; repeated caller cancellation cannot cancel that
task. Wait for actual completion, attempt both closers, safely project cleanup
errors without raw causes/contexts/notes and then re-raise cancellation. Remove the
Anthropic unprotected SDK context-manager exit, so its first close cannot be
interrupted before entering retained cleanup. Do not infer physical completion
from an HTTP library's early CLOSED marker. Add actual-SDK double-cancel tests with
an event-controlled physical transport close and safe cleanup-failure tests.
No request replay, budget reset, background fire-and-forget or permission change.
This helper may later be shared by the explicitly scoped OpenAI factory extraction.

Diagnostic correction (2026-09-09 13:06 UTC, before edits): c15ab passed199 independent
tests and the original physical-close probe, but its new client_cleanup cause was
not in RuntimeFailureCause, so the existing safe event projector dropped it. Root
may add that one fixed enum member in domain/runtime_diagnostics.py, a projector
regression in tests/unit/test_runtime_failure_diagnostics.py and an actual Anthropic
Workflow cleanup-failure case checking persisted agent.failed. No arbitrary cause
strings or raw error details become admissible. Retain c15ab's diagnostics gap.

### S1.1c trusted execution observation and terminal ledger (2026-09-09 14:22 UTC)

This contract is frozen before implementation. Ownership: Noether writes new
domain/evaluation_observation.py, ports/evaluation_evidence.py,
adapters/persistence/evaluation_evidence.py, application/evaluation_outcomes.py and
corresponding new unit/integration tests. Narrow existing evaluation_campaign.py,
ports/evaluation_store.py and persistence/evaluations.py changes permit explicitly
validated executed outcomes, never loosen validate_preflight or synthesize success.
Root retains composition, CLI, schema registration and documentation. The prior
campaign32-file candidate stays frozen for its snapshot verifier; changes to
shared campaign models require a new candidate, not retroactive acceptance.

Provide useful inspect_attempt(campaign_id, attempt_id) and
record_final_outcome(campaign_id, attempt_id, expected_observation_sha256). Neither
accepts caller-supplied outcome JSON as physical truth. A dedicated read-only,
query_only SQLite transaction reads one bounded consistent manifest/reservation/
claim/binding/Run/Task/model-binding/root-budget/event/artifact metadata snapshot.
Do not call generic StateStore._connect, migrate, create directories, resolve
credentials or run commands. Open only existing explicit local files; reject
unsafe links and identity swaps. Verify registered Artifact IDs, kind, bounded
size, digest and exact project/root/task relationships against actual bytes through
an injected bounded reader, not only metadata. Selected raw artifacts may contain
untrusted text; return bounded safe typed projections, not raw logs/context.

Observation is non-authorizing, immutable, bounded to1MiB, distinguishes awaiting
apply/oracle, failed/cancelled, active, dispatch_unknown and corrupt evidence.
No Task is invented for CoS failure. Root budget is counted once, never duplicated
by graph descendants; retain unknown requests, lower-bound usage, unknown cost
and absent evidence. Physical cleanup observations distinguish durable released
leases from checked absence; do not infer Docker inspection from a DB flag. Exact
identities and data-derived observation hash permit repeatable inspection across
restart; no wall-clock-only drift belongs in its fingerprint.

The final-write path runs its own fresh observation, compares the explicit expected
digest, then atomically revalidates its persisted identity fingerprint before one
immutable outcome insert. The application derives the finite terminal failure
classification from actual retained status/error, not model verdict. Active and
READY_FOR_REVIEW candidates are not prematurely finalized: absent future oracle
evidence must remain awaiting, not permanently inconclusive. An ended dispatch
with unknown reservations can be recorded dispatch_unknown, never zero or replayed.
Applied/completed candidates also remain awaiting_oracle in this slice; never
emit verified_success or functional_failure without an external oracle producer.
Exact retries return the original receipt/time without a second outcome; changed
content, stale fingerprints, cross-attempt/root bindings and concurrent distinct
finalizations fail closed. Corrupt evidence does not become functional failure.
No model dispatch, apply, oracle execution, new migration unless a concrete atomic
requirement is demonstrated, or future empty API is allowed.

Acceptance includes actual public Workflow CoS-before-Task failure/cancellation/
unknown, nonterminal fake candidates, graph root-only usage, missing/changed/wrong
kind/cross-Run artifacts, safe errors/redaction, bounded corrupt rows, read-only
file/DB/table/event preservation, reopen equality, immutable repeated terminal
write and races/stale observations. Old pure/ledger/campaign suites must pass;
new schemas generated by root. Root CLI will expose this accepted Python service
after audit, not a parallel implementation. Independent oracle/apply/post-apply
receipts and24-task real campaign remain separate mandatory unfinished work.

S1.1c seam amendment (before persistence changes): the actual port filename is
ports/evaluation_store.py. Noether may also narrowly amend
adapters/persistence/evaluation_execution.py:_record, whose earlier blanket
outcome rejection would otherwise treat a newly legitimate executed terminal
record as corruption on campaign reread. Permit only the exact validated terminal
outcome for the same permanent retained execution binding; preflight/executed
exclusion and no new claim/replay remain unchanged. New and historical candidate
identities stay separately recorded.

### S1.1c failed-boundary qualification before repair (2026-09-09 15:06 UTC)

The observer6f058497 is explicitly NOT accepted after independent sidecar and
Artifact/DB pathname-ABA counterexamples. Before production repair, Noether owns
one new exact private qualification cache only. Read the verifier's probes and
official SQLite/APSW documentation, obtain one exact binary wheel into a private
Python3.14.6 environment with existing versions unchanged, and qualify a narrow
native no-follow connection boundary. No canonical dependency/source mutation,
live request, credential, Docker or production-state write is authorized here.

Prefer SQLite's own coherent WAL interpretation over a hand-written WAL merger.
For inspection, qualify descriptor-relative O_NOFOLLOW component/file opens with
retained directory anchors, bounded regular-file reads, stable repeated byte and
physical identity capture; copy only captured DB plus optional WAL bytes into an
explicit0700 private ephemeral staging directory, then let SQLite interpret WAL
and back the result into RAM. No SHM is copied or trusted; all SQLite temporary
writes stay in staging. This is an explicit exception to the earlier no-directory
rule limited to a new private temporary directory, never source/repository/state
mutation. Mandatory success/failure/cancel cleanup, finite capture attempts and
aggregate bytes, no raw path/content error exposure. Validate nonempty committed
WAL, uncommitted frames, partial tails, checkpoint races and hostile links. No
immutable=1 original-file shortcut may silently drop committed WAL data.

Final outcome writes are a separate gate: plain sqlite3.connect plus before/after
lstat is not descriptor-bound and cannot be retained as the supposedly safe CAS.
Qualify APSW's explicit SQLITE_OPEN_NOFOLLOW/native VFS behavior on both final
filename and parent-component swaps, actual underlying handle identity, WAL/SHM
sidecars and transaction races. Reject unexpected global connection hooks,
extension loading, URI/VFS/ATTACH or writable-schema escape. Never assume the flag
alone solves a regular-file ABA or all auxiliary-file opens. Determine the smallest
portable adapter capable of exact original DB CAS without changing other writers'
SQLite locking model. If no defensible write boundary is proven, report NOT_GO
for writes and leave terminal recording blocked; do not label read repair full
acceptance. Return exact package/wheel evidence, actual probes and retained failures
before root freezes a production repair contract.

### S1.1c read-only repair and write containment (before repair implementation)

Independent native and storage-design reviews both leave the original atomic
terminal-write criterion NOT_GO. Do not replace it with historical receipt
semantics, silently weaken its stale-write oracle, or insert outcomes into a staged
database and copy it over the source. Historical publication is not implemented
in this slice. Keep original registration/reservation/execution/budget authority
and migrations unchanged; missing terminal records remain visible as missing,
never success, refund or permission to replay.

One new Writer owns adapters/persistence/evaluation_evidence.py, a narrowly scoped
fixed observation capture helper, application/evaluation_outcomes.py, and focused
observation/capture tests. Other observer domain/port changes require a concrete
internal type need and preserve its external JSON. Root owns docs/schema/public
composition; the unsafe observer remains unwired until independent read acceptance.
Immediately fail closed both record_final_outcome and record_terminal before
inspection, artifact or DB access with a fixed actionable diagnostic. Retain prior
terminal-write successes/failures as historical evidence; successor tests prove
containment, not completion of the still-unmet terminal-write requirement.

Serialized ownership refinement before containment edits: root first owns only
the two existing terminal method bodies/import cleanup and new
tests/unit/test_evaluation_write_containment.py. Root freezes those bytes before
handoff to the Session Writer's next disjoint task. The read-repair Writer may
then own the observer adapter while preserving both fail-closed entries and this
test. No concurrent edits or removal of another worker's changes.

Replace source sqlite3.connect and pathname artifact reads with the qualified
separate-process capture design. Use the existing installed interpreter and a fixed
bundled helper, explicit minimal environment without credentials/provider settings,
no inherited file descriptors or shell, and bounded strictly validated input. The
child holds component-walked O_NOFOLLOW directory/file descriptors for source DB,
optional WAL/journal and selected artifacts. Reject nonregular/multilink/unsafe or
unstable identity/content, nonempty rollback journal, oversized inputs and capture
drift. Read source descriptors only in the clean child, never the parent with live
SQLite locks. One attempt/two identical capture passes; each file<=32MiB and
aggregate read<=128MiB. Do not copy SHM or hand-merge WAL. Interpret captured DB+WAL
using ordinary SQLite solely inside a new0700 private stage with exclusive0600
files; then validate bounded existing schema/rows and physical artifacts using
the existing observation rules. Source-origin identity must remain explicit;
temporary-copy inode/path/time cannot enter the semantic fingerprint. Return only
the existing bounded safe observation, never source DB bytes, logs or credentials.

Parent IPC enforces byte ceilings while reading stdout/stderr, not only after
communicate(), and uses one finite child timeout. Unexpected output/exit/corruption
is one fixed corrupt observation. Retain actual child kill/wait and private-stage
cleanup through repeated cancellation; cleanup uncertainty must not return accepted
observation. No global monkeypatch, raw exception/path exposure, dependency install,
APSW, source migration/sidecar write, network, model or Docker is authorized.

Credential-registry refinement before the capture implementation: do not pass
registered secret forms, credentials, keyed fingerprints or lengths to the child.
Root adds only a lock-protected boolean Redactor.has_registered_secrets() query
and its focused tests. The read adapter rejects a nonempty registry before
launch and checks it again before accepting the returned observation, including
concurrent registration. This explicitly limits the first read repair to a fresh
credential-free control-plane instance; it is not a claim to validate raw source
rows against unavailable secrets. Return a fixed safe corrupt/unavailable result,
never registry contents. Preserve final parent-side redaction and all existing
observation checks. Writer retains sync inspect_attempt compatibility and may
provide an internal cancellable async boundary whose retained thread owner drains
the child through repeated cancellation; no public protocol change is required.

Acceptance: actual selected campaign/Workflow inspection preserves DB/WAL/SHM,
artifacts and parent SQLite locking. Replay closed-DB sidecar and transient DB/
artifact ABA counterexamples, hot committed/uncommitted/partial WAL/checkpoint,
link/size/row/schema/redaction/IPC overflow/timeout/repeated-cancel tests, restart
equality, graph root-only usage, actual cancellation/failure/no-Task fixtures and
unchanged pure/ledger/execution regressions. Verify process/path absence and exact
frozen source/dependency identities independently. Read-side PASS does not accept
S1.1c finalization, external oracle, the real24-task campaign or whole S1–S3.

### S1.4 Google Provider implementation contract (2026-09-09 13:55 UTC)

After the accepted direct Anthropic slice, implement one real Gemini Developer API
path behind existing PydanticAI, exact prefix `google:<model-id>`. Source qualification
used google-genai2.18.0 wheel SHA256
4c5e60ccaed3ed35ac2ee81e87c5bebf7280cd49b81526d872a526e97ce25f46 and installed
PydanticAI Google provider/model/profile. Qualification alone is not admission.
Root owns new adapters/runtime/google_provider.py, google_response_policy.py,
their actual-SDK contract and Workflow tests, and later serialized PydanticAI/
provider-selection/profile registration plus dependency lock. First work may use
a separate private locked-base environment; do not change the SDK verifier's
private environment or accepted snapshot. Canonical dependency/registration changes
wait for that audit closure. No Google credential or live request is authorized or
available; never reuse the supplied OpenAI key at Google.

Construct explicit genai.Client with nonempty selected key, enterprise=False,
vertexai=False, fixed https://generativelanguage.googleapis.com/v1beta route,
explicit all-disabled DebugConfig(client_mode=None,replays_directory=None,
replay_id=None), owned sync+async HTTPX2 transports, finite millisecond timeout and
HttpRetryOptions(attempts=1). Exact wheel converts attempts=0 to1, correcting the
earlier private qualification note; use1 explicitly. Reject ambient replay/logging
customization before imports/credential resolution. SDK may read ambient key and
project variables, but explicit arguments must prevent fallback/use; prove no ADC,
replay client/file, alternate host, injected proxy or additional client creation.
Never claim no environment reads. No Vertex/enterprise/mTLS/media/streaming/native
execution, cached content, files, countTokens, batches, MCP or endpoint overrides.

Supply explicit certifi-rooted SSLContext in both transport verify settings and
SDK client_args.verify, async_client_args.verify and async_client_args.ssl, preventing
HTTP or websocket SSL initialization from consulting ambient certificate files.
Both caller-owned transports use trust_env=False, no redirects, stateless cookie
jars and final outbound guards. Reject the sync request path; only exact POST
/v1beta/models/<bound-model>:generateContent with empty query/fragment/userinfo,
fixed Host and selected x-goog-api-key may send. Validate and minimize merged
headers, byte-bounded JSON body, exact model route, text/function declaration/result
shape, finite output-token setting and secret exclusion before SingleSendGate.
One already-reserved request owns one physical-send ticket; SDK retry cannot mint
another. Reject duplicate/unknown headers and any callable/native/MCP tools.

A version-qualified GoogleModel._build_content_and_config override calls its real
superclass once, then forces automatic_function_calling.disable=True and text-only
output and validates plain function declarations before high-level SDK entry.
MCP parsing can precede AFC-disable, so the flag alone is not an execution boundary.
Do not replace the real SDK loop with a fake model. Wire schema transformation can
drop exclusive bounds/string formats; neither VALIDATED nor ANY is original-schema
proof. Preserve all existing Fleet validators and enforce strict JSON validation
of role-bound terminal arguments before SDK/PydanticAI coercion, with a trusted
adapter-only output-model mapping. Do not alter domain schemas or silently repair
model output. Custom roles inherit existing execution kinds; all five kinds and
CoS FleetPatch output remain bounded by their normal contexts.

Response hooks clear untrusted headers before parsing/logging. For successful
HTTP responses, validate bounded raw JSON before SDK conversion: no duplicate or
nonfinite keys/numbers, exact modelVersion, exactly one supported candidate, no
native/media/grounding content, and bounded text/function-call parts. Any allowed
opaque thought signature is only bounded continuation data, not executable content
or evidence. Explicitly bind PydanticAI-generated IDs as local RAM continuation IDs
when Google omits a tool ID; never call them provider-issued. Normal full-batch
validation/reservation/Gateway rules still precede effects. Non2xx errors keep safe
finite HTTP status rather than being misclassified as missing usage.

Raw usage must precede SDK non-strict model_validate and later usage model_dump
warnings. Require strict nonnegative primary counters and validate every accepted
optional/nested count; malformed/missing usage is a wholly unknown request before
effects. Reconcile input=promptTokenCount+toolUsePromptTokenCount,
output=candidatesTokenCount+thoughtsTokenCount,total=input+output; cached tokens are
not added again. Omitted optional counters may contribute0 only under the explicit
provider formula, never substitute0 for missing primary evidence. Retain one-use
request-bound RAM receipt and compare the resulting PydanticAI usage/identity before
return to durable accounting. No raw response body or unredacted error is persisted.
The initial response byte limit is explicitly post-read acceptance, not bounded
network allocation. Secret-bearing warnings/errors/exception chains must not escape.

Fleet owns SDK and both physical transport cleanup: SDK close/aclose deliberately
do not close injected clients. Use retained provider_lifecycle closers for normal,
partial-construction, failure and repeated-cancellation paths, preserving safe
client_cleanup diagnostics and unknown accounting. Do not globally suppress
warnings, mutate environment/logging, or claim forced-process cleanup guarantees.

Acceptance uses the actual pinned SDK over offline MockTransport: exact selected
role model/key/endpoint; poisoned env/replay/SSL/auth and forbidden constructors;
all five builtins/four custom kinds/FleetPatch; real three-turn local tool loop;
ALLOW/DENY/REQUIRE_APPROVAL through actual Workflow/SQLite/Gateway; whole-invalid-
batch zero effects; retries/429/500/timeout/cancellation; strict raw primary/nested
usage and identities; no native candidate/part; repeated cancellation closes both
physical clients and preserves durable unknown. Keep FakeSandbox's simulated proof
gap. Fresh independent review, original providers' regression, generated schema
comparison and exact dependency closure precede admission. Live canary and6-task/
mixed-provider qualification remain NOT_RUN without the corresponding credential.

Google ownership/environment amendment (2026-09-09 13:58 UTC, before code):
Helmholtz now owns only the two new Google adapter modules and corresponding
tests/contract/test_google_provider.py, tests/integration/test_google_workflow.py
and optional new tests/google_provider_fixtures.py. Root retains all shared
PydanticAI/provider/profile/dependency/registry/docs edits. The four frozen Agents
SDK files remain untouched. The separate Google Python3.14.6 environment has the
locked73 platform packages plus8 new packages for exact google-genai2.18.0; no
existing version changed. It is a development environment, not the final project
lock or provider acceptance. SDK verifier's private environment is unchanged.

### S2.2 next implementation contract (2026-09-09 12:12 UTC)

After corrected S2.1a independent acceptance, the same S2 writer owns a complete
same-Session management slice, not a replacement REPL. Add /models (catalog,
future-task selection and inspected Run's immutable binding clearly separated),
/roles (bounded configured identity/kind/requested ceilings/model preference/hash,
never prompt bodies or permission grants), /readiness (current-project static
report), and /tasks [before-sequence] (20 bounded current-conversation summaries).
/tasks select <sequence> selects the displayed sequence, not a copied internal ID;
/tasks current clears inspection selection. Resolve an exact sequence through
bounded existing list_turns/get_turn/binding_for_run and reject cross-project,
cross-conversation or child-Run inconsistencies. No migration or task queue.

Keep a separate process-local inspection cursor. Never retarget _turn globally:
active execution, cancellation, progress and ownership retain their existing
resolution. /status,/artifacts,/diff and bound-model inspection may inspect history;
/cancel always targets the active owned Run and labels it. Other task mutations
(resume,plan approval,tool approval/denial,apply) reject a non-current inspection
selection and direct the user to /tasks current. Do not silently mutate history or
cancel the wrong Run. Read-only /plan may inspect history. Every selection change,
including A-to-B-to-A, invalidates all one-use reviews and display cursors. New
submissions use the current session, not a historical cursor. Clearly separate
inspected task and active task in views. Pagination, EOF and SIGINT stay bounded.

/models use <alias> --default|--role <role> prepares an exact one-use review using
the existing /confirm mechanism; it never selects or enters credentials. It changes
future tasks only. Extend the existing ticket union with a ModelSelectionReview
binding project/conversation selection, profile name/revision/configuration hash,
target role/default and expected project-selection revision. Confirmation consumes
the code on success or failure. ModelProfileStore.save_selection must compare the
expected profile revision/config hash/enabled state inside its existing SQLite
transaction, together with a selection validation callback. Service pre-reading is
not enough. Existing callers can omit the added review expectation; preserve their
current behavior and immutable historical RunModelBindings. Unknown roles and
disabled/stale profiles fail closed. No catalog create/edit/remove command is added.

Atomicity refinement (2026-09-09 12:22 UTC, before implementation): existing
conversation reads also use BEGIN IMMEDIATE. A current_selection callback that
re-enters those stores from save_selection would deadlock. Instead, the reviewed
SessionSelection is checked by direct SQL reads of conversation/root binding inside
the model-store transaction; its callback checks only process-local selection
generation and expiry, with no store I/O. Retain and recheck the configuration hash
and role membership during confirmation. Do not claim the database transaction
locks a concurrently editable repository config file; future Run admission still
revalidates/fixes its own configuration.

Writer scope: cli/chat.py,application/conversations.py,bootstrap.py;
application/session_review.py,domain/session_review.py;
application/model_profiles.py,ports/model_profiles.py,
adapters/persistence/model_profiles.py; new focused Session management tests plus
necessary existing test doubles/contract expectations. Root owns docs. No workflow,
runtime,budget,conversation-store migration,Provider or readiness schema edits.
Main will serialize any additional shared-file scope before writing.

Acceptance: real SQLite/service and subprocess same-Session journeys for new
inspection commands and exact model review/confirm, plus existing task/plan/tool/
patch/cancel/resume paths. Negative cases include sequence bounds and foreign IDs,
selection ABA,expired/reused/stale codes,concurrent profile/selection changes,
unknown roles,history inspection during cancellation,slash commands never sent as
goals,secret/control-character redaction,missing configuration,and zero model or
project-command execution from inspection. Readiness remains unverified/not_checked;
model selection is not provider connectivity. No persistent shell input history or
completion that records secrets is introduced.

### S2.3 reviewed role-bundle preview (2026-09-09 13:59 UTC)

Root implements four packaged, language-independent combinations: general-change
(general-engineer/general-verifier), public-interface (interface-engineer/
interface-verifier), stateful-change (state-engineer/state-verifier) and design-guided
(design-researcher/design-architect/design-engineer/design-verifier). They offer
bounded responsibilities for adaptive selection, not fixed team sizes or strategies.
Guidance focuses respectively on minimal regressions, API compatibility, state/
idempotency/recovery, and evidence-backed design before implementation. No fixed
provider, model, credential, new execution kind or broader base role is introduced.

The first complete user path is `fleet role-bundles list` and
`fleet role-bundles preview <id> --path . --workflow <declared-id> --scope <path>
--command <existing-command-id>` (repeat scope/command as needed). Preview is
read-only: inspect current Git/configuration using lightweight adapters, never
construct StateStore, migrate/register a project, resolve secrets, invoke models,
write files or initialize/pull/build a sandbox. It binds repository identity and
current ConfigSnapshot hash, not an unobserved SQLite organization revision.

Return strict versioned bundle identity/content hash, exact current configuration
hash, selected workflow/scopes, exact CommandSpec ID/hash/definition, full before/
after file changes and diff, plus a single-line escaped adoption brief no larger
than16384 UTF-8 bytes. Refuse over-limit previews rather than silently truncate
desired configuration. Complete public JSON is limited to1MiB including envelope,
escaping/redaction/newline; unsafe source/secret content is rejected safely. Explicit
fixed execution_authorized=false/publication_authorized=false cannot coerce0 into
false. No persistence or unused future installer methods are added.

Render only the current snapshot plus packaged assets. Require declared workflow,
all needed built-in bases, explicit canonical unprotected scopes and at least one
existing reviewed verification command. Do not guess Python/npm invocations.
Merge the catalog preserving existing role records; reject role/instruction/skill
path collisions or already-adopted bundles rather than overwrite. Add bounded role
Markdown, one VerificationSkill with explicit paths/commands and one skill reference
to the selected existing workflow, preserving old skills, stages, limits, commands,
permissions and all unrelated bytes. Resolve the complete proposed snapshot with
the ordinary parser/role ceiling/required-command validator. Role tools are a subset
of current base capabilities; model preferences and maxSteps inherit unchanged.
Do not modify fleet.yaml, trust, registration, sandbox, credential or base guidance.

The brief asks for a NEW ordinary CoS task to produce the exact files as a FleetPatch
proposal, never to apply them. It states current expected configuration and complete
desired contents; a stale or nonmatching model proposal must be reviewed/rejected,
not called successful adoption. The first slice does not automatically submit the
brief or assert that a model will obey it. Users paste it into the existing Session,
then use existing fleet-patch diff/apply/rollback and exact confirmation. Never attach
a new template proposal to an unrelated historical terminal Run or fabricate a Run.
This is useful preview plus the existing organization workflow, not another installer.

Root owns new domain/role_bundles.py, application/role_bundles.py,
adapters/config/role_bundle_assets.py, cli/role_bundles.py, packaged
assets/role-bundles/catalog.json, new unit/integration/E2E tests and root entry wiring.
Do not change Planner, Workflow or permission logic. Schema generation is serialized
after Noether's execution schema edits are released. Existing default configurations
and assets stay byte-compatible when no bundle is selected.

Acceptance: four exact packaged definitions/rendered closures; denied collisions,
missing commands/bases/workflows, invalid scope, prompt/secret/size leakage, and
read-only source/DB/index preservation; real CLI subprocess preview. For each bundle,
use a NEW actual Workflow/CoS fake-runtime task to create proposal/artifacts, explicit
publication, reread real resolver/planner/Gateway command requirements, then rollback
to original tree. These tests may use internal fixture initialization but never count
as public cold-start or real-model qualification. Freeze exact inventories and fresh
independent verdict before marking this slice accepted. Five strategy positive/
negative matrix and ten Session/cold-start journeys remain a separate S2.4 contract;
current /deny still needs an ID and there is no Session /recover command.

### S2.4 bounded Session recovery and no-ID denial (2026-09-09 14:34 UTC)

Before implementation, root owns application/session_recovery.py and narrowly
extends ConversationService, CLI chat protocol/parser, bootstrap and new tests.
Existing reviewed Session/bundle snapshots remain historical as these successors
change shared wiring; do not claim their earlier frozen acceptance for new bytes.
No new persistence schema, model calls, tool authorization, provider choice or
background recovery sweep is introduced.

`/recover` presents only the exact current conversation root and its known
descendants/outstanding lease IDs, stopped-owner warning and a fresh five-minute
single-use recovery code. It does not fence or clean anything. The operator must
then use `/recover --confirm-owner-stopped <code>` after confirming the prior Fleet
process stopped. A recovery code is distinct from /confirm permissions/patch/model
codes and never becomes model input, history or persistent trust. No internal Run
ID need be copied. Recovery fails/interruption-fences the old Run and reconciles
leases; it never resumes/replays a model or silently retries unknown work.

The process-local ticket binds SessionSelection including its inspection ABA
revision, actual selected turn/claim and root/descendant Run/graph/lease digests.
Reject history, wrong conversation/project/root, no current task, stale state,
changed claim/lease, expiry, invalid/reused codes and any known local execution,
cancellation or recovery still active. Bound retained tickets and issued codes
as existing SessionReview does. Consume once before awaiting any work, re-read the
exact binding at confirmation, then call existing RecoveryService.recover_run for
that root only. Existing conversation fencing performs its transactional revision
check. Operator stopped-owner assertion is required because the application cannot
prove another process is dead; do not call a review hash an OS ownership lock.

Recovery runs in a retained task that is drained even through repeated cancellation;
do not clear local ownership or return a settled status before physical cleanup
finishes. Mutating Session operations reject while that task remains active. On
failure/unknown, preserve normal recovery evidence, consume the old ticket and
require a new review; no broad retry. Selection changes never retarget the retained
cleanup. Read-only status/history may continue without authorizing mutations.

`/deny` may omit an ID only when exactly one pending request exists under the
current root/descendants; otherwise list exact pending choices without mutation.
Retain explicit-ID compatibility and optional bounded reason. Denial cannot match
another conversation or historical selection and cannot turn into approval.

Acceptance: real public interrupted-owner Session recovery then a new task in the
same Session with no model replay; preview state unchanged, missing confirmation,
stale/reused/expired/cross-selection/ABA code rejection, current local execution
rejection, repeated-cancel drain, exact graph resource ownership. No-ID denial
sole/none/multiple and legacy syntax tests. Run all prior Session CLI/management/
review/recovery tests. A frozen ten-journey fixture will enumerate task selection,
plan, approval, denial, patch, cancellation, recovery, model selection, role/readiness
and history expectations before its final acceptance replay. This is not the
three real Docker cold starts or business baseline; those remain separately unmet.

### S2.4 reviewed recovery CAS repair (before successor implementation)

Candidate720d7a875 FAILED independent acceptance: after final review digest check,
a real new worktree/lease can be added before RecoveryService entry and is then
deleted without a new review. The275 ordinary cases and62 focused passes do not
override this. The original ticket revision is also not propagated to the initial
fence. Preserve the independent probe and failed candidate as historical evidence.

After Euler completes that immutable verdict, assign a separate implementation
agent (not the independent verifier) single-writer ownership of
application/session_recovery.py, application/resources.py,
ports/conversation.py, adapters/persistence/conversations.py, a new internal
domain recovery-binding model and focused new/old Session recovery tests. Narrow
StateStore/SqliteStateStore or GraphStore changes are allowed only where an actual
atomic reviewed cleanup operation requires them, with all existing methods and
unreviewed CLI semantics preserved. Root retains bootstrap, CLI, dependency,
schema and documentation integration and must be told exact additional paths
before edits. No borrowing the unaccepted evaluation observer or native SQLite
qualification work; Session mutation uses its existing trusted state transaction.

Bind an immutable original reviewed selection/turn revision/claim, root and exact
descendant/graph identities and canonical full lease payloads, not just IDs. The
confirmation helper compares this entire original binding in ONE existing SQLite
transaction/connection, then fences exactly the reviewed turn/claim. It never
refreshes the expected revision from current state. Return a fixed post-fence
cleanup plan; do not expand dynamically to later descendants or leases. All
outstanding resources must be covered and finite; corrupt/missing/mismatched
binding rejects before any resource cleanup or new ownership mutation.

The reviewed cleanup path operates only captured exact resources in dependency
order execution→sandbox→worktree, child before parent. Validate/claim the original
lease identity and full payload atomically before effect, never substitute a
re-fetched lease with a changed path/metadata. Bind any retained cleanup task to
its plan digest and reject conflicting joiners. Do not use an await gap or a
before/after path check as a transactional ownership guarantee. Physical cleanup
still uses the existing trusted Sandbox/Repository adapters; no new host command
or permission is introduced. Keep final persistence conditional on the same
claimed identity, and retain recovery_required on failure/unknown/late drift.

If new resources/children or identity changes appear after the fence, never clean
them on the old review. Fail conservatively and leave the current exact remaining
identities for another stopped-owner review. Final reconciliation must establish
no unexpected descendant/outstanding lease and cannot silently settle an expanded
run tree. An already started physical cleanup is retained/drained through repeated
cancellation; ticket consumption and no model replay remain unchanged. Preserve
legacy one-shot recover_run behavior when no reviewed binding is supplied, while
new Session calls always use the reviewed path.

Acceptance adds actual-store interleavings immediately before fence, after fence,
same-ID changed lease path/metadata, new graph child, concurrent confirmation and
conflicting retained cleanup joiner. Prove all newly introduced resources remain
untouched on rejection, original physical worktree cleanup still completes, and
no execution/replay grant is restored. Repeat all275 Session/recovery cases,
relevant Graph/resource tests and fresh independent audit on the successor freeze.
This is not a claim that an operator assertion proves another OS process dead.

Reviewed-recovery implementation seam clarification: the writer may narrowly
refactor adapters/persistence/graphs.py request_cancel into a connection-local
helper and reuse its existing validated _get inside the same ConversationStore
transaction. Root passes graphs=graphs to the optional new ConversationStore
constructor argument. No migration/StateStore schema change is needed. One-use
plan identity and existing append-only Run events retain plan, exact lease claim
and terminal receipts; full original/claimed payload hashes bind RELEASING and
final CAS. Every following operation checks this plan's legitimate transitions,
not arbitrary status changes. Preserve bounded historical settled leases in scope.

### S3.4 LangGraph isolated behavioral qualification (2026-09-09 14:40 UTC)

Helmholtz completed source-only inspection of langgraph1.2.11 wheel SHA8bab70de,
and eight selected dependency wheels whose hashes match official metadata. That
is not a registered Harness. Before production implementation, create one private
Python3.14.6 environment outside the checkout, install the current locked Fleet
dependencies there, then exactly the following binary-only additive candidate:
langgraph1.2.11,langchain-core1.4.7,langgraph-checkpoint4.1.0,
langgraph-prebuilt1.1.0,langgraph-sdk0.4.4,langchain-protocol0.0.15,
langsmith0.12.2,uuid-utils0.12.0,ormsgpack1.12.0,xxhash4.0.1,orjson3.11.5,
jsonpatch1.33,jsonpointer3.0.0,requests-toolbelt1.0.0,zstandard0.25.0.
Resolve/install and compare inventories; reject unexpected changes to existing
versions. Do not mutate canonical lock/.venv or held Google private environment.
No provider key, real model/network request, Docker, repository config or runtime
registration is part of the probe. Dependency acquisition uses official packages;
actual probes deny sockets and package exporter/client/thread construction where
applicable, retaining failures rather than modifying global warnings policy.

Probe actual StateGraph execution with request→validate→gateway_batch→request/END,
no PydanticAI Agent, Agents Runner, prebuilt ToolNode or delegated whole loop.
Credential/messages/raw response/receipts remain outside graph state; graph state
contains only bounded counters/routing. Explicit checkpointer=False,store/cache=None,
retry_policy=(),no interrupts/debug/transformers, finite recursion,max_concurrency1,
fresh contextvars.Context task, explicit empty AsyncCallbackManager and scoped
langsmith.tracing_context(enabled=False,parent=False) need behavioral validation.
Reject ambient LANGGRAPH/LANGSMITH/LANGCHAIN tracing, debug and registered hook
paths rather than silently mutating user global settings. No inherited runnable
store/checkpointer/cache/callback may operate. This context policy must coexist
with request-local Fleet accounting/SingleSend tickets in the actual node.

The principal go/no-go gate is physical cancellation closure: pin probes before
request, during request, Gateway, graph exit and client closure, with repeated
parent cancellation. The pinned loop can attach an exit task in CancelledError.args,
and a first cancellation during exit may itself cancel that task. Merely awaiting
a cancelled exit task is insufficient. Track actual owned node/request/exit tasks
and physical close barriers; demonstrate no late effect, worker or request remains.
Do not expose task args/notes/raw exceptions. A single initial graph cancel with
retained draining may be chosen only if these phase-controlled probes prove it.
If the underlying package cannot meet the boundary, report NOT_ADMITTED with exact
blocked phase and preserve proof; do not register a placeholder or unsafe wrapper.

Writer owns only newly created files under its exact private qualification cache
for this probe, not repository implementation files. Root handles documentation
and later dependency/registry integration. After passing this prerequisite, freeze
a separate production vertical-slice contract for new langgraph.py,boundary and
actualSDK/Workflow tests. Qualification tasks are not the six live KR tasks.

### S3.4 bounded production LangGraph Harness (2026-09-09 14:56 UTC)

The isolated prerequisite completed29/2.533s on pinned real packages with receipt
SHA22ecdab138350a5d2b79bcd465a20bc57556ba4ca938cd7ea9c1f3fa01eaae68.
This is permission to implement the next closed slice, not runtime admission.
Helmholtz owns new adapters/runtime/langgraph.py,langgraph_boundary.py,
tests/langgraph_fixtures.py,contract/test_langgraph_runtime.py and
integration/test_langgraph_workflow.py only. Root owns serialized dependencies,
shared registration/config/profile factories, schemas and documentation. Existing
Google/Agents files remain frozen; do not import their private adapter boundaries
or delegate the actual execution loop to PydanticAI/Agents Runner.

Public runtime name is langgraph. Initial admitted Provider is explicit
openai:<exact-model> Responses only, with an explicitly resolved secret reference.
Use the existing trusted open_openai_client, SingleSendGate, runtime admission,
accounting, role prompt assets, strict action definitions and Gateway services.
No environment key/base/model fallback, HTTP retry/redirect/cookie/native tool,
provider session, checkpoint persistence, tracing exporter or direct subprocess
is allowed. Preflight and runtime policy fail before secret resolution; root
registration follows actual production adapter conformance, not just the probe.

Every invocation builds an actual all-async StateGraph with bounded integer/
routing state: request→validate→gateway_batch→request/END. Messages, credentials,
raw responses and passive tool results stay in a bounded invocation-local RAM
owner, not graph state/checkpoints. Compile checkpointer=False, store/cache=None;
no ToolNode, inherited callbacks, runnable config, retries, interrupts, debug,
streaming, timeout policy or caller-supplied graph transformation. Invoke finite
recursion_limit,max_concurrency1,values-only in a fresh context task, explicit
empty async callbacks and scoped tracing-disabled context. Reject unsafe ambient
LangGraph/LangChain/LangSmith configuration and already registered exporters/hooks
before execution. Do not mutate process-global environment/logging/warnings.

Use real SDK with_raw_response so raw bounded JSON/duplicate/nonfinite checks,
exact response identity/status, output batch and usage precede SDK type coercion
or error rendering. The2MiB bound is explicitly post-read acceptance, not claimed
network allocation control. SDK exceptions are mapped to finite safe errors with
no raw body/cause/context/task notes. Validate the entire proposed action batch,
exact unique call IDs and every strict argument before any tool reservation or
effect. Terminal tool output is role-kind-specific and locally strict; a CoS
FleetPatch output is allowed only with trusted organization context. Mixed action/
terminal batches, hosted/native actions, extra effects and unknown outputs fail
closed. Strict local validators are unchanged even where provider JSON-schema
strict mode must be false. Tool calls return only through Fleet Gateway results.

Reserve each model attempt before transport, consume exactly one physical send
ticket, record actual raw input/output/total usage before tool effects. Missing,
invalid, failed or cancelled request accounting retains unknown usage; no automatic
reissue, fake zeros or cancellation refund. Enforce total model/tool/time budgets,
five builtin role kinds/custom role kind mapping and conservative capabilities.
No raw object or foreign SDK execution-state continuation crosses RuntimePort.

Production cancellation must retain independently tracked actual node/request/
graph-exit/client tasks. Repeated cancellation cannot finish the invocation or
close its client while any owned execution can still issue effects. Track/drain
native children even when graph exit itself was cancelled, as the negative control
proved necessary. Return a fresh argument-free cancellation after physical drain.
Cleanup failure is failure, including after a terminal output. The private probe's
OpenAI _platform='Unknown' excluded diagnostic OS-header threads: qualify the real
client initialization separately or explicitly set this value only on the exact
owned pinned SDK client before use and test that source-qualified behavior. Do
not call the untested default SDK initialization threadless.

Acceptance: actual compiled graph traversals, five builtin/custom role terminal
outputs, normal/two-step tools, entire-batch zero-effect negatives, raw identity/
usage/coercion/duplicate JSON, unknown/retry/budget/cancellation/cleanup/tracing
tests. Three real Workflow/SQLite/Gateway ALLOW, REQUIRE_APPROVAL and DENY journeys
must retain complete evidence and FakeSandbox limitations. Shared provider/profile/
runtime conformance plus fresh independent audit precede registry admission and
six live KR tasks. Actual live qualification, mixed-Harness success and user key
use remain separate bounded campaign work.

LangGraph shared-client seam amendment (before raw-response factory edits):
the pinned SDK's with_raw_response requires x-stainless-raw-response:true on the
actual request to defer typed parsing. Root may add a trusted factory-only
raw_responses:bool=False flag to open_openai_client. ExactTrue requires a real
SingleSendGate and Responses-only URL checks; exactFalse preserves every existing
header/endpoint behavior. Admit and retain only one exact raw header with value
true in this mode, require it on each request, and reject absent/duplicate/other
values, wrong paths/query and nonboolean flags before send. No caller arbitrary
header hook or user-configurable transport mode is exposed. Tests use real pinned
SDK raw calls and unchanged default-path regression; prior shared freezes remain
historical as these narrowly changed factory bytes need fresh review.

LangGraph registration step (2026-09-09 15:18 UTC, before shared edits): the writer's
38 direct actual-StateGraph/SDK contracts now pass. Root may add only langgraph to
the closed configuration/profile/runtime-required-credential sets and bootstrap
registry for the next three Workflow acceptance tests. Canonical dependencies add
the15 previously qualified exact versions and declare already locked jsonschema
4.26.0 directly; no existing-version drift is allowed. Serialized lock/sync follows
completion of root's old Session replay and does not touch held private audits.
Correct fleet version/help and credential-needed Session metadata to report the
same registered runtime names, including previously omitted openai-agents. All
new Harness combinations remain explicitly under qualification until full current
conformance and independent acceptance; no live call or installed-release claim.

Registration refinement before the remaining config edit: RuntimeSpec.adapter in
domain/config.py is a separate closed Literal and must also include langgraph;
otherwise generated FleetSpec fails before Workflow dispatch. Regenerate only
the schemas whose content derives from this explicit new enum, inspect the exact
changed files and revalidate all existing/new config/profile tests. The first
three LangGraph Workflow failures before model dispatch remain retained; do not
change fixtures or bypass the configuration validator.

Independent config/schema correction (before successor edits): dc91ce7's
RuntimeRequest Literal included langgraph but its validate_runtime_selection and
both generated allOf provider conditions omitted it. An actual edited FleetSpec
and shipped schema accepted missing/null/openai-chat/anthropic/google selections,
despite default_fleet_files correctly rejecting them. Runtime preflight still
rejects unsupported invocation; do not claim a provider bypass. Preserve independent
718 passes and the five config counterexamples as a failed candidate. Root owns
only RuntimeRequest conditions, generated fleet.schema.json and test_config.py
direct edited-YAML/distributed-schema cases for both OpenAI-only Harnesses. Add
langgraph to existing required-provider and Responses-only conditions, no provider
expansion or schema default relaxation. Regenerate, compare exact affected schemas,
freeze successor19-file inventory and replay affected/shared checks independently.

### S3.2 first implementation contract (2026-09-09 12:50 UTC)

Implement a real OpenAI Agents SDK0.22.1 Runner adapter, not a fake loop or CLI
wrapper. First admission is explicitly bound OpenAI Responses HTTP only, all five
builtin execution kinds and the existing four custom-role kinds. No streaming,
native tools/handoffs/MCP, hosted conversation state, checkpoint export or fallback.
Use the existing runtime admission and strict output models without schema changes.
The SDK qualification wheel is SHA256
41e09c74ac8a1de4735a16f687b544a9c4a611602bc83a83dccad0e28b955615.

Every FunctionTool including terminal output submission requires interruption.
Wire compatibility amendment (2026-09-09 13:08 UTC): the pinned SDK strict-schema
converter refuses the existing bounded-dictionary role_selections output schema.
Terminal submission tools therefore explicitly use strict_json_schema=False while
retaining the original schema and mandatory strict local Pydantic/role validation
after interruption. External action tools remain strict=True and locally validated.
This is a fixed terminal-tool design, not runtime non-strict fallback or validator
relaxation. Malformed terminal output cannot be accepted or authorize effects.
Do not introduce a payload_json wrapper or rewrite existing domain schemas to fit
the SDK. Tests assert both wire flags and rejection of invalid terminal fields.
Raw-usage refinement (2026-09-09 13:27 UTC, before edits): actual SDK tests found
typed response.usage can coerce wire Boolean true into integer1 before
preserve_raw_usage captures it. Root may add an optional trusted async
response_observer to the shared client, called after the existing header guard and
before SDK parsing. The Agents boundary captures only strictly validated usage
scalars in one request-bound RAM receipt, never persists/logs the raw body or
exposes the observer through user configuration. Preserve missing/Boolean/malformed
usage as unknown and reject duplicate/nonfinite JSON as appropriate; no token
coercion or SDK-normalized zero may become raw proof. Failed response identity or
status still fails before any tool effect. Add actual-SDK wire-type regressions.
Before returning ModelResponse to Runner, inspect raw output for secret content,
unknown/native actions, duplicate current or historical call IDs and mixed terminal/
action batches. SDK deduplication cannot erase a malformed request. Match the full
raw batch exactly to interruptions; validate all local tool arguments, reserve the
entire external-tool batch, then invoke Fleet Gateway sequentially. SDK approve is
only passive loop continuation after those effects, never PermissionBroker approval.
A passive invoker holds only single-use RAM results bound to ID/name/arguments and
cannot access catalog/Gateway/credentials. Partial completion and approval failure
stop without automatically replaying effects. Output submission validates the same
role-bound Pydantic model and terminates without charging an external-tool action.

Wrap actual SDK Model.get_response with durable request accounting and single-send
transport admission. Explicit AsyncOpenAI and ModelRetrySettings both disable
retries. Preserve raw usage; missing or malformed raw fields remain unknown even
if SDK Usage supplies zeros. Apply the existing request/token/time/tool/role budget
semantics across all RAM resumes; max_turns cannot reset the durable owner budget.
Reject unsafe SDK/HTTP logging before credential resolution. Map raw SDK errors to
fixed diagnostics before Runner can log them, and remove raw exception chains.
Before the first Runner use, install one explicitly disabled DefaultTraceProvider
with no processors, without calling a lazy default-provider initializer first.
This is an explicit process-level Fleet SDK policy, not a per-call isolation claim;
test concurrency and prove no exporter is created. Client closure is mandatory.

Writer Helmholtz exclusively owns new adapters/runtime/openai_agents.py,
adapters/runtime/openai_agents_boundary.py, tests/contract/test_openai_agents_runtime.py,
and tests/integration/test_openai_agents_workflow.py. Root owns SDK dependency/lock,
shared OpenAI transport extraction, registry wiring and documentation. No shared
file edits by the writer. Shared transport extraction waits until the Anthropic
freeze is independently checked; root publishes the exact factory seam before SDK
integration. New dependency installation is serialized outside frozen test audits.
The writer may implement independent SDK code first but cannot claim qualification
before the pinned SDK is installed and actual offline Runner tests execute.

Acceptance: real SDK five-kind/custom output and tool-pause-Fleet-execute-resume
journeys; malformed second action gives zero reservation/effects; duplicate IDs,
forged interruption, native action and mixed terminal batches fail closed; all
three Broker decisions, budgets, unknown accounting, cancellation, no retries,
no traces/log secret leakage and client cleanup are tested. Real Workflow/SQLite/
Gateway evidence is asserted, with FakeSandbox clearly simulated. Fresh independent
review and existing PydanticAI/shared-conformance regression precede admission.
Live qualification is separately preregistered and bounded, not inferred from mocks.

Shared-factory refinement (2026-09-09 13:03 UTC, before extraction):
`openai_client.open_openai_client(raw_credential,redactor,timeout_seconds,gate=None)`
is an async context manager retaining SDK/HTTP cleanup with provider_lifecycle.
The SDK wrapper owns its SingleSendGate and opens a ticket per reserved request;
the final HTTP hook consumes it only after the proven OpenAI guard. For the new
Agents path, reject unsafe openai/httpx2/httpcore2 INFO/DEBUG logging and OPENAI_LOG
before resolving credentials. Existing PydanticAI explicit-client test hooks and
policy behavior remain compatible; trusted optional constructor factories may be
forwarded from that adapter, never supplied by repository/model configuration.
Extract existing constants/guards rather than privately importing the PydanticAI
adapter from another Harness. Retained SDK close uses its __aexit__ operation inside
the cleanup task, so existing constructor doubles and real SDK closure both apply.
Root owns the new shared module and focused tests; serial PydanticAI wiring follows
the corrected Anthropic independent freeze acceptance. No new provider/model
fallback, native action or authority is introduced by sharing construction.

Pinned SDK response refinement (2026-09-09 13:05 UTC, before edits): the Responses
adapter discards raw response.model/status/error when forming ModelResponse. The
writer may override its source-qualified _fetch_response seam only to call the
real superclass once and require the exact selected model, completed status and
no error before conversion. Invalid or absent identity/status remains unknown
accounting and zero tool effects. Tests cover all those fields, one physical send
and safe errors before Runner logging. This version-specific seam requires future
SDK upgrades to requalify it; no generic compatibility claim is made.

Root registry scope also includes the existing closed runtime allowlist in
domain/model_profiles.py and credential requirements in domain/models.py, plus
their focused unit tests. Add only openai-agents with explicit provider/key
requirements; do not relax other unknown-runtime rejection or change persistent
field defaults. Profile/Session dependencies stay frozen until their independent
audit releases them. Generated schema comparison must establish whether any wire
shape changed rather than assume registration changes are invisible.

Registry refinement (2026-09-09 13:34 UTC, before edits): include the closed
default_fleet_files YAML runtime allowlist. Admit only openai-agents/OpenAI
Responses, and the separately qualified Anthropic PydanticAI provider in the
profile routing allowlist. Require explicit provider/key and reject unknown
combinations. Add actual selected-profile transport tests. The shared HTTP observer
must reject malformed raw usage before SDK parsing can emit value-bearing warnings;
that failed request is conservatively unknown, without global warning suppression.

SDK review refinement (2026-09-09 13:40 UTC, before correction): preparse validation
also covers optional nested cached/cache-write/reasoning usage fields before the
pinned SDK's unconditional serialization can warn with raw values. Optional absent
detail dictionaries remain absent, never invented. The2MiB response check is a
post-read acceptance bound, not a transport receive-memory guarantee; explicitly
retain that limitation rather than add an unqualified streaming transport here.
For process-level tracing, acquire the Fleet lock and SDK0.22.1's
_GLOBAL_TRACE_PROVIDER_LOCK for one atomic compare/install. Use the pinned module's
GLOBAL_TRACE_PROVIDER and existing _SHUTDOWN_HANDLER_REGISTERED/atexit handler
protocol directly under that lock, without nested set_trace_provider deadlock or
calling lazy get_trace_provider. A foreign installed provider is rejected, never
overwritten. Test concurrent foreign initialization and exactly-once shutdown
registration. Trusted later process-global mutation is not prevented or sandboxed;
admission rechecks the policy. Future SDK upgrades must requalify this private seam.

Registry completeness refinement (2026-09-09 13:39 UTC, before edits): actual
integration still rejected the runtime at domain/config.RuntimeRequest's closed
enum. Root also owns that enum/conditional provider schema, Session bootstrap
options and CLI onboarding's explicit runtime selection so the public journey is
usable. Add only the same qualified runtime, preserve explicit credential and
approval rules; regenerate and identify exact affected schemas. Root's first
shared integration retained225passes/5failures in7.83s: one missing config enum
and four test constructor-hook mistakes, not provider effects. Correct the
Anthropic test hook to its actual AsyncClient seam, never change production to
fit a mistaken fixture.

### Milestone 1: immutable measurable baseline foundation (S1.1a)

Acceptance: the same synthetic manifest/records produce byte-stable reports; all registered failures/missing/unknowns remain visible; repetitions never replace first rounds;24 independent tasks,32 cohort slots and4 auxiliary slots are modeled as36 planned attempts, not36 independent tasks or real results. Deep immutability, malformed/cross-cohort identity, duplicate slot/Run and missing evidence cases are rejected. No DB/CLI/runtime or live side effects.

### Milestone 2: durable evaluation and readiness (S1.1b, S2.1)

Acceptance: registered slot reservation is atomic and idempotent; preflight failure can exist without a fake Run; requests/tools cannot exceed either Run or campaign budget; unknown ownership pauses without replay. Reopened evidence produces the same outcomes/denominators. Readiness is truly read-only and diagnoses healthy/unprepared/originally-failing Python and Node fixtures honestly. Explicit business baseline and external oracle use exact sandbox/approval boundaries.

### Milestone 3: usable Session and existing-model baseline (S1.1c, S2.2–S2.4)

Acceptance:10 frozen same-Session journeys,4 reviewed role/verification bundles,positive/negative cases for5 strategies,6 repository readiness cases and3 cold starts. S1 baseline preregisters24 tasks across6 selected Python/Node repositories,including12 sealed first rounds requiring at least9 independent successes;32 cohort attempts plus1 campaign canary and3 cold starts share one finite36-attempt campaign budget. No retroactive sample selection or claiming a failed campaign passed. The 3 cold starts may share S2 evidence only if all identities/contracts match exactly.

### Milestone 4: additional Providers (S1.2–S1.4)

Acceptance: actual SDK offline transport/secret/output/tool/usage/cancel contracts for OpenAI,Anthropic and Gemini; each new Provider has a separately preregistered opt-in canary and6 tasks requiring at least5 independent successes;3 mixed-provider tasks all pass. Missing credentials produce NOT_RUN, not live support. No arbitrary base URL or implicit fallback.

### Milestone 5: replaceable Harnesses (S3.1–S3.4)

Acceptance: shared applicable conformance covers5 execution kinds/custom roles,whole tool batch validation/reservation,approval,budget,cancel,error,recovery and evidence. Capability mismatch fails before model invocation. OpenAI Agents SDK qualifies on6 frozen tasks with at least5 successes and3 mixed-Harness tasks all passing. LangGraph bounded beta qualifies on6 tasks with at least5 successes and every applicable safety test. Coding Harness feasibility is supported/blocked only with evidence of native side-effect/credential-boundary control; no unsafe CLI wrapper counts. No unsupported streaming/checkpoint claims.

### Milestone 6: verified local and GitHub delivery

Acceptance: all required current formatting/lint/type/schema/lock/unit/integration/offline E2E/installation and applicable real-Docker gates pass with exact collection/JUnit reconciliation. Freeze source before final testing and verify package bytes. README and this plan distinguish implemented, offline-tested, live-verified and blocked external acceptance. Review coherent small commits, exact staged scope and secret scan. Read current remote protection/status before push/merge, avoid Actions usage where supported without disabling protections, and read back actual remote commit/merge identity. If protected checks or missing external credentials block full goal completion, state that rather than mark complete.

### S3.3 offline mixed-Harness Workflow qualification (before test implementation)

Root owns only new tests/integration/test_mixed_harness_workflow.py. Run three
cyclic assignments of PydanticAI, OpenAI Agents SDK and LangGraph to CoS, Engineer
and independent Verifier through actual ModelProfileService bindings and Workflow,
not substituted runtime adapters or direct isolated invoke calls. Each role uses
its own explicit synthetic model/key. Actual SDK clients receive only bounded
offline Responses through MockTransport; FakeSandbox stays visibly simulated.
Exercise ALLOW, explicit per-principal approval/reopen, and DENY for each assignment
(nine cases, not nine independent live tasks). A future profile edit during pause
must not change the pinned Run binding. Assert actual serialized model/key/endpoint,
durable selected-model artifacts, exact Gateway write/command counts, single root
usage accounting without unknowns, original-target preservation, client closure
and terminal resource cleanup. Neither passing mocks nor fake command receipts
can satisfy the three real mixed-Harness task KR. No production changes or new
network/credential authority are part of this test-only slice.

## Detailed implementation steps

1. Close the accepted canary's post-result archive evidence without another paid request. Create this plan before source changes.
2. Writer owns only new `domain/evaluation.py`, `domain/outcomes.py`, `domain/evaluation_metrics.py`, their three unit-test modules and `tests/fixtures/evaluations/domain-cohort-v1.json`; also the three entries in `schemas/generate.py`, three generated schemas and `tests/unit/test_schema_generation.py`. No existing model/schema semantics change. Root owns documentation; verifier is read-only. Other participants' edits must be preserved.
3. Use immutable scalar/hash references rather than mutable existing CommandSpec/budget/CompletionDecision wrappers. Validate repository/source cohort separation and preregistered contiguous attempt slots. Pure reporting must reject wrong manifest/config/oracle linkage, duplicate outcome/attempt/slot/root Run and missing evidence for a success claim. Output grouped first-round counts, repeat/auxiliary counts and reported usage lower bounds without inventing costs.
4. Run focused pure/schema/static checks and fresh adversarial review. Update this plan with real numbers and limits; then freeze the next persistence/readiness contract before its first edit.
5. Extend persistence and budget integration as a reviewed vertical slice; add public observation and opt-in execution only after race/restart/secret/no-replay tests pass.
6. Implement S2 journeys and preregister the S1 baseline. Inspect preloaded Node environment and prepared dependencies first; do not host-execute install hooks or silently download/build images. Missing environment support remains explicit while independent safe work proceeds.
7. Qualify actual SDK hooks and dependencies before new Provider/Harness implementation. Share only proven explicit-client/secret/accounting primitives, not authority; add one adapter at a time behind closed admission. Freeze each live qualification manifest and finite aggregate budget before dispatch.
8. Complete the full applicable candidate gates, independent evidence audit, documentation/package refresh and exact GitHub delivery. Never convert partial milestones into whole S1–S3 completion.

## Validation plan

Installed-distribution S1–S3 refinement before release-test edits: root owns
tests/release/test_installed_distribution.py only, retaining its existing fresh
wheel and sdist installation, exact lock and source-origin checks, network denial,
fake Workflow/approval/plan/apply journeys, and opt-in Docker separation. Extend
both archive journeys to assert all four packaged Harness modules and the three
provider modules originate inside the fresh environment, four packaged role-bundle
definitions validate, version advertises the exact closed runtime list, and public
readiness and role-bundle list remain non-executing before state initialization.
Add configuration-only installed profile creation for each admitted Provider/
Harness combination and reject wrong-provider native Harness profiles; do not
resolve a credential or call a model. Package import/configuration checks are not
installed live qualification. Use the prepared95 exact locked wheels offline;
record source identity and retain intermediate packaging failures separately from
the eventual fully frozen current-release matrix.

Every test process uses its own new private evidence parent and basetemp; all ordinary gates set `AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0`, `AGENT_FLEET_ENABLE_DOCKER_TESTS=0`, `AGENT_FLEET_ENABLE_INSTALL_TESTS=0`. Substitute an already created, exact private path for `<evidence>` and retain the expanded command and JUnit in its manifest.

First-slice commands (from repository root):

```text
.venv/bin/ruff format --check src tests scripts
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src tests scripts/run_live_canary.py
.venv/bin/python -m agent_fleet.schemas.generate --check
uv lock --check --offline
git diff --check
AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_ENABLE_DOCKER_TESTS=0 AGENT_FLEET_ENABLE_INSTALL_TESTS=0 .venv/bin/pytest -q tests/unit/test_evaluation_manifest.py tests/unit/test_outcomes.py tests/unit/test_evaluation_metrics.py tests/unit/test_schema_generation.py --basetemp=<evidence>/domain --junitxml=<evidence>/domain.xml
```

Before a candidate's final acceptance, collect every current test identity and run the exhaustive default partitions in `docs/session-first-test-partitions.json`, adding any new integration files exactly once. The separate selection is `tests/unit tests/contract tests/e2e tests/docker tests/live tests/release`. Run the timing-sensitive `tests/integration/test_conversation_safety.py::test_cancel_after_rejected_cleanup_reconciles_terminal_fence` alone only after heavy test workloads stop; do not change its timeout/assertion. Retain exact expanded commands and reconcile all JUnit identities for duplicates/missing/extra. All affected source changes require fresh relevant coverage; historical results are not automatically current proof.

Opt-in prepared Docker gate: same test command with `AGENT_FLEET_ENABLE_DOCKER_TESTS=1 AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:0.1.0-py314-v1` and `tests/docker`, unique basetemp/JUnit. Installed gates reuse only exact verified offline wheelhouse and declared image; freeze expanded configuration before running. `tests/integration/test_distribution.py` verifies current archives after final README/guide edits. Independently audit actual handles, ledger, artifact bytes and terminal resources; a cleanup summary alone is insufficient.

Live campaigns are separate, opt-in and bounded; retain all dispatch/reservation/response/unknown records, profile/config/patch/oracle hashes and cleanup. Never sum overlapping gates as independent tasks. Other platforms and absent-provider credentials remain unverified rather than inferred from macOS3.14/OpenAI proof.

## Rollback and recovery

GitHub delivery preparation (read-only rechecked2026-09-09 after16:30UTC): main
still points to3fb09711851b27b5276d7faddd50bc317e2536fb, branch API reports
protected=false and no open pull request exists. This is not a push or merge.
The repository workflow uses push/main and pull_request/main, not
pull_request_target. GitHub's [official skip instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)
allow a `[skip ci]` head commit to suppress those triggers. For eventual authorized
delivery, preserve local full gates and use the marker in each pushed commit and
the final merge commit; recheck the actual head, workflows and required protections
first. Skipped required checks can remain pending: do not disable protection or
force a bypass. No tag/package publication or unrelated workflow edits are
authorized. Record actual remote branch/PR/merge readback separately; local commit
or an open PR cannot establish delivery.

First slice has no migrations or external effects; rollback is only its exact reviewed file edits, preserving all prior changes. Later persistence must use forward-compatible migrations/transaction rollback and append-only evidence. A duplicate request returns its existing identity and cannot acquire a second owner; uncertain dispatch cannot be retried automatically. Stop affected campaign slots on accounting/evidence ambiguity, preserve artifacts and use production exact-identity cleanup/recovery, never broad Docker prune or repository resets. Commit rollback must not erase failed experiment history or unrelated user planning files.

## Progress

- [x] (2026-09-09, latest-result archive gate) After the current live failure was recorded in README93a8ca9c (guide60dd47b1), `.venv/bin/python -m pytest -q tests/integration/test_distribution.py --basetemp=<private-new-directory>/fixtures --junitxml=<private-new-directory>/results.xml --tb=short` passed1/2.51s. This rebuild checks current runtime/package resources plus README/guide; it is not another dependency-install,Docker or live run. These checkpoint archives precede the proposed seven-file diagnostic successor.
- [ ] (2026-09-09, frozen successor contract before edits) The latest live Verifier failure has no retained field-level cause. Offline reproduction shows three distinct faults (uppercase verdict enum,missing rationale,object in narrative criterion_results) produce the same current diagnostic; none proves the actual live fault. After the21700932 checkpoint commit, one Writer may change only adapters/runtime/failure_diagnostics.py,domain/runtime_diagnostics.py,adapters/runtime/pydantic_ai.py,adapters/runtime/prompts/verifier.md and their three existing tests unit/test_runtime_failure_diagnostics.py,contract/test_pydantic_ai_runtime.py,unit/test_criterion_mapping_guidance.py (all under src/agent_fleet or tests respectively). Root owns docs. Add optional expected_output_contract=verifier_verdict only from trusted identity output_model is VerifierVerdict; this identifies expected output,not which SDK subcomponent failed. Add at most8 sorted/deduplicated finite validation_issues records {field,issue}. Generic existing diagnostics never inspect error records. Only exact builtin ValidationError in the existing bounded eight-cause chain is eligible; exact integer error_count over32 emits one unknown pair without materializing errors. Otherwise call errors with input/context/url disabled,never stringify/read messages,title,provider bodies or dynamic class names. Field whitelist: schema,unknown,verdict,criterion_results,evidence_artifact_ids,regressions,required_repairs,proof_gaps,rationale,structured_criterion_results,and structured_criterion_results.{criterion_id,verdict,evidence_artifact_ids,command_ids,explanation}. Consume/discard exact integer list positions only at expected depths; unknown/Boolean/subclass locations become unknown,never emit dynamic keys,indices,hashes or lengths. Issue whitelist:missing,type,enum,pattern,length,value,unknown mapped from fixed reviewed builtin Pydantic type literals; custom/unknown kinds become unknown. Domain event projection revalidates exact builtin shapes/whitelists/maxima and strips extras; no raw counts or truncation lengths. Clarify lowercase pass/fail/inconclusive wire values,all required Verifier fields,nonempty rationale,list[str] narrative criterion_results distinct from structured criterion objects,using empty lists rather than omitting required fields. Preserve receipt/command/criterion bindings,strict output schemas,no retry after effects,and all permission/budget/provider behavior. Acceptance: three discriminated offline real-FunctionModel failures after one synthetic side effect with at mosttwo callbacks and no replay,valid lowercase positive,secret-bearing unknown keys/custom types/input/message/context exclusion,hostile subclasses,error/chain/issue bounds and malicious event projection controls. Keep old privacy tests. Run changed modules,relevant conformance/workflow/event tests,full formatting/lint/types/schema/lock and independent successor audit. No new paid test is authorized by this diagnostic slice; it cannot recover or retroactively explain the lost live payload.
- [x] (2026-09-09, local checkpoint commits) Seven exact reviewed groups are now local commits on codex/s1-s3-verified-foundations:00e00e9,c20b5c2,48abb26,9cce538,f52040d,5bd0e17,412fe2a. Every staged blob matched its reviewed manifest and index was empty afterward; all include [skip ci]. The private commit helper initially stopped on trailing-NUL parsing before any commit,then on an intentional offline credential sentinel before staging group6; both checks were corrected narrowly with the exact synthetic test sentinel allowlisted. No user credential was found or persisted. Current production/tests/scripts/dependencies remain21700932; docs are the final eighth group. No push/PR/merge or Actions execution occurred.
- [ ] (2026-09-09 17:41:48 UTC) The one authorized current21700932 live regression FAILED, preserving the full unchanged code freeze. Real Run run_1589f3c7d1234980b39c14df1a0d7cee reached VERIFYING; agent.failed114 reports RUNTIME_OUTPUT_INVALID / structured_output_after_side_effect / schema_validation and no VerifierVerdict artifact exists. Engineer patch and both command receipts exist. Ten requests reported37173 input+12514 output=49687 tokens,seven tools,97.868783 active seconds,zero unknown/outstanding/reserved usage; money unreported. Pytest107.98s,launcher109.681s,outer111.475s all exit1. Launcher cleanup_complete=true; independent exact resource/artifact/target readback is underway. The zero-request Fake bootstrap Run's ready_for_review state is not this live Run's success. The malformed response is not retained, so its invalid field cannot be inferred. No whole-run retry, acceptance relaxation, target apply or credential persistence. Preserve this failure separately from historical attempt6; diagnosis-only offline follow-up may improve bounded safe diagnostics, under a new contract before edits.
- [x] (2026-09-09, eight cumulative checkpoint validation) All eight exact private cumulative overlays from HEAD3fb0971 passed package/CLI imports,version,--help and bounded smoke checks:222 overlapping executions,not full intermediate-suite acceptance. All snapshots stayed unchanged; final code matches21700932. Two private-harness failures remain recorded (role fixture Git-denial setup and unsupported multiprocess probe), with subprocess-free supplemental checks and no production/assertion edits. No regrouping was required by these bounded gates. Handoff SHAdb81f824e36265a633ce8c71302fe603855c55d785888c51326a51cbb606ce0c; sealed checkpoint receipt SHAb17a21b6a513ba68ad0e20271835651e5f44be0210632412187b8abbb5caec08. Captured docs precede final live-result prose and require separate final archive refresh. No index/commit/remote mutation yet.
- [x] (2026-09-09 17:35:27 UTC) Final-prose archive refresh before the new live outcome passed1/2.54s (wrapper4.591s),unchanged21700932 code. README3a5bbda3/guide60dd47b1 produced wheel62d08a05 and sdist3f977503,checked108 schemas,migrations1..12 and installed resource smoke. This is archive/existing-dependency proof,not a new fresh dependency installation or Docker/live journey. The later live-result README amendment requires another exact archive refresh; keep these earlier bytes and receipt intact.
- [ ] (2026-09-09, before current-checkpoint live regression) After21700932 local/default/optional acceptance, authorize exactly one fresh execution of the existing live-provider CLI canary on unchanged current code, using the user-supplied OpenAI credential only in temporary control-plane process scope. This is a new regression attempt, not a retroactively registered campaign success or a new-Harness qualification. Preserve openai:gpt-5-nano, official endpoint, prepared image/daemon,12 agent invocations/24 model requests/32 tools/65536 total-token ledger/600 active seconds; each profile8 requests/12 tools/32768 tokens/120-second request timeout and existing one pre-effect correction; launcher wall900 seconds, no automatic whole-run retry. No key in files/argv/sandbox or worker messages. A private no-echo stdin receiver launches the unchanged shipped launcher with a minimal child environment, then discards its process-local credential. Model capability was rechecked in the fetched official GPT-5 nano model documentation; no model substitution. No request has been made at this entry. Retain failure/unknowns and all resource/evidence readback regardless of result.
- [x] (2026-09-09, independent21700932 replacement audit) Fresh568-file snapshot/511-code-path audit found no remaining five-file defect or coverage gap. Exact3614-node fresh collection/3.18s and independent eight former failures/6.73s passed. All five predecessor bytes matched the earlier frozen snapshot; no assertions/markers/cases were removed, no product/dependency/conftest/shared-helper changed, and the sole external fixture reference is covered by the737 adversarial replay. Every changed-module case is freshly covered (130:127 passed/3 unchanged skips). Deduplicating all current receipts gives870 fresh nodes (867 passed/3 skipped) plus2744 byte-identical carried nodes (2724 passed/20 skipped), thus3591 passed/23 skips/0 failures over3614 identities. This is not3614 fresh executions. Verdict SHA9315ffe603fadbb20ff108958cdd2998fdf45940c82e085fde128b0ea8ee35d1 and per-node receipt/carry ledger retained; root accepts the local test-only checkpoint, not whole S1–S3 or new live proof. Final README now records exact gates and outstanding business/live acceptance; archive readback follows this prose change.
- [x] (2026-09-09 17:25:32 UTC) Successor21700932 root regressions passed67/168.55s plus3 explicit default installation skips; the whole two changed CLI/config modules are included, alongside migration12/upgrade/unsupported-provider contracts. Named adversarial script passed737/218.40s,0 skips/errors/failures, unchanged code/dependencies. Counts overlap the default matrix and are not additive independent tasks. Independent replacement reconciliation and snapshot former-failure replay are still closing.
- [x] (2026-09-09 17:25:02 UTC) Optional proposal-entry903b correction independently accepted:three actual full-entry installed version positives,three actual internally spelled symlink-to-external-package negatives andthree distinguishing predecessor controls. Old6432 reaches a guarded fixture-load sentinel; new903b rejects before loading fixtures or creating state. All aliases removed and installed bytes unchanged. Receipt SHA6f9da40a82e63847ae45767be005eda978d01c57a0f9a553d2658edb2a38aebe. No additional install/workflow/Docker/model execution claimed.
- [ ] (2026-09-09, delivery review) Explicitly select the eight earlier user-requested, dated architecture/OKR planning documents unchanged so the current plan links remain complete; they are planning artifacts, not implemented future scope. The private205-path map has eight cumulative groups8/50/37/12/67/11/10/10. A single Writer is validating intermediate snapshots before any index/commit/branch mutation. Scoped scan of all205 proposed files found no credential-pattern or current-machine identity matches. A broad scan found an unchanged historical machine-path note in .agent/plans/2026-09-04-phase-3-docker-sandbox.md; it is outside these changes and remains untouched, not concealed by a global-clean claim. Read-only GitHub check still reports main3fb0971,protected=false,no open PR; no push/merge/Actions execution yet.
- [ ] (2026-09-09, after17:22 UTC) Test-only successor21700932 changes exactlyfive test files fromafb64027, with all production/scripts/dependency bytes identical. Root format429,lint,mypy363,schema108,offline99-lock21ms and diff checks passed. Writer's two graph-fixture modules plus graph-store contracts passed118 unique/11.05s (29 admission,54 journal,35 graph); all six former failures are included, unchanged assertions. Eight added setup/import lines only, source8ef4322b/89b85a12. Root changed-module/migration regressions and named adversarial gate are running; a fresh independent verifier is assigned whole3614 replacement/closure reconciliation and independent former-failure probes. No full-successor acceptance yet.
- [x] (2026-09-09 17:22:41 UTC) Independent optional readback sealed PASS for immutableafb64027 only, receipt SHA3a343911560b1ad31ec6149359f2cb9724f4ca85de8ee631423759d34d2865d5. Three installed environments and six archives match316 runtime/guide files,95 prepared wheels/99 lock;54 installed leases released,18 paths absent,215 Artifact hashes,18 command bindings and10 CompletionGate replays validated. Together20 exact optional installation scopes havezero containers. Final live-tree equality check detected the authorized five-test successor edit and is retained as a coordination gap; this receipt does not accept those new tests. Actual strict optional-entry positive/symlink-negative controls are a separate903b successor gate. Later README/security prose refresh requires fresh archive readback.
- [ ] (2026-09-09 17:18:07 UTC) Full afb64027 default matrix FAILED with exact3614 unique identities:3583 passed,8 failed,0 errors,23 intentional optional skips; no missing/extra/duplicate identity or code drift. Integration partitions:238 passed/1458.86s (wrapper1461.389s,35 retained warnings),237 passed+1 failed/1128.86s,236 passed+1 failed/902.08s; other group2871 passed+6 failed+23 skipped/961.86s. Unchanged isolated cancellation oracle passed1/9.40s after heavy gates ended. Actual six graph traces confirm missing parent budget ownership at GraphStore.initialize:826, not a Session-CAS regression. Keep this complete failed matrix and optional successes as their original freeze.
- [ ] (2026-09-09, successor test-only repair contract before edits) Production/source/lock bytes stay held. Root owns only tests/integration/test_config_snapshot_binding.py (drop the missing migration12 table in its isolated pre8 copy), tests/integration/test_cli.py (use truly unsupported provider sentinel), and tests/release/test_installed_distribution.py (strict physical module-origin resolution in its optional proposal test entry). One Writer owns only tests/contract/test_organization_admission_hooks.py and tests/contract/test_organization_journal.py:initialize the original parent Run budget immediately after creation, before INTAKE/SCOPING, using the existing store; preserve every admission/publication/graph lifecycle assertion. All active frozen tests have now settled before these edits. Replay all changed default modules, actual strict installed-entry positive/symlink-negative controls, relevant migration/graph contracts and the named adversarial gate. Fresh collection plus per-file/import-closure comparison must explicitly replace affected old cases and carry only byte-identical unaffected results, not claim all3614 re-executed under the successor. Current package/runtime bytes remain independently audited; final documentation changes need fresh archive checks. No permission, output, migration or resource validator is relaxed.
- [x] (2026-09-09 17:11:25 UTC) Current afb64027 installed wheel/sdist/real-Docker gate completed3 passed/484.59s (488.357s wrapper), prepared95 wheels, no provider calls/downloads, frozen code unchanged. Independent archive/runtime/resource readback remains underway. The old optional offline-proposal entry still has a lexical import-origin assertion; current physical origin checks may establish these particular installs but do not prove that assertion rejects symlinks. After the frozen matrix settles, add strict physical resolution to this test-only entry and execute a real symlink-negative control; preserve current results as their original candidate, never retrospectively call the old assertion repaired.
- [x] (2026-09-09, after17:10 UTC) Independent readback of current Docker29 results verified45 databases,41 Runs,681 actual Artifact hashes,64 command receipts,26 CompletionGate replays,199 terminal leases (190 released/9 recovered),66 absent leased paths and29 Git registries containing only original targets. All19 Docker-test installation scopes containzero containers on the exact pinned daemon/image. Readback SHAa319373ac39ed935abfa95073f2ee46064491f68bfc41e66a2d6679d433b8991. These are independent checks of root-executed tests, not another29 execution passes or blanket absence of other concurrent test resources.
- [ ] (2026-09-09, after17:07 UTC) Exhaustive afb64027 partition2 completed1 failure/237 passes/1 excluded serial case1128.86s, plus the known Google Python3.14 deprecation warning. Its CLI negative fixture still used newly admitted anthropic:not-enabled and correctly reached CREDENTIAL_MISSING. Read-only audit found the sole obsolete PydanticAI sentinel; replace only that literal with existing unsupported-provider:offline after all current gates settle. Preserve unsupported-before-secret/state assertions and legitimate Anthropic denial in OpenAI-only Harness tests. Combined successor repair scope is exactly these two test files; production admission/migrations remain unchanged. Current failed candidate and its full identities/results remain retained.
- [x] (2026-09-09 17:04:56 UTC) Observer read repair independently accepted, narrowly:seven-pathf346092d plus root security524ecd,561-file8ec710 snapshot;71 fresh/314.28s +6 actual boundary probes/83.88s +2 registry/.60s =79 unique. Ruff/format/mypy9 and108 exact schemas passed;40 default child PIDs/private stages physically absent, actual ABA/overflow/cancellation/fault controls checked. All9826 dependency files and held source bytes unchanged. Receipt SHAe0d21b0bbf802893d2a703bb4886438710887b60d717463dc3fc6e7585c1470d. Intentional cleanup faults need exact test-owned recovery, not product-drained claims. Original terminal-write NOT_GO and public-wiring/whole-suite/live gaps remain. Independent Docker/installed evidence readback assigned separately.
- [x] (2026-09-09 16:58:19 UTC) Current afb64027 optional real-Docker gate completed:29 passed/462.21s (466.669s wrapper), unchanged code, no live requests or downloads. Exact daemon e470601e and image2afebd51 bindings match the start receipt; independent physical-resource audit is pending. Final installed wheel/sdist plus Docker gate started17:03:17 UTC against the same frozen source and prepared95-wheel closure; no result yet.
- [ ] (2026-09-09, after17:02 UTC) Exhaustive afb64027 integration partition3 retained1 failure/236 passes902.08s: old-state credential test copied schema12 but omitted evaluation_executions from its pre8 downgrade fixture, then removed migration receipts>=8, so correct strict migration12 collided with the retained table. Read-only diagnosis identifies a test-only projection repair; do not relax CREATE TABLE or edit the frozen candidate before all active gates settle. Partition2 also shows an unfinished failure indicator; await its actual diagnostic rather than infer the same cause. No all-green or current whole-suite acceptance is claimed.
- [ ] (2026-09-09, after16:47 UTC) Exhaustive default matrix started on current code/tests/scripts/dependency freeze afb64027e0021ae118a61efbda5598efb99669b5c42076022f8573c84c104299 (full initial tracked/untracked inventory3b91ed325cdc5328a1aaff30029e87753884a8507525afe6871861a03a539126). Exact3614 collected identities are partitioned238/238/237 integration,2900 other/default optional cases, and1 unchanged serial cancellation oracle run last. Three test processes at most in this matrix; other group queues until a slot is free. Current format429,lint,mypy362,108 schemas and offline99-lock/20ms passed. No current test result or overall acceptance claimed until exact XML/source reconciliation. Root may update result-only docs; code/tests/scripts/dependencies remain held.
- [ ] (2026-09-09 16:50:33 UTC) Explicit optional Docker gate started on the sameafb64027 code freeze, no provider calls or downloads. Fresh local daemon identity e470601e-5d84-43d4-8c9d-2038812fa634 and existing linux/arm64 image SHA2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241 were rechecked; initial container list empty. This is a fresh environment observation, not reuse of a historical daemon binding. Only generated test-owned fixture scopes may execute/clean up.
- [ ] (2026-09-09, after16:47 UTC) Observer read repair IMPLEMENTED on seven-pathf346092d (five changes plus two unchanged containment paths), requiring root security524ecd. Current71 exact unique tests/143.20s passed, scoped Ruff/format7/mypy180 and38 recorded child PID/private-stage absences checked. Independent561-file8ec710a1 snapshot now running71/security probes; original terminal-write NOT_GO is unchanged. Root full matrix supplies still-required pure/ledger/execution coverage. Kill/stage fault residuals were manually cleaned by exact tests, not called product drainage. Original DELETE-mode fixture setup and native/observer failures retained.
- [x] (2026-09-09 16:47:14 UTC) Release prequalification independently read back PASS, receipt SHAbf9b27318937ea7005692209adb6e3c40f495f5c0b939cce34c99247adb91c96. Exactd272558-file snapshot/overlays,315 package/guide bytes across two installs and four archives,95wheel/99lock bindings,36released leases/12absentpaths/130artifact hashes checked. Two strict-origin positive and two symlink-negative controls freshly replayed; root257.22s journeys audited, not claimed rerun. Learning targets intentionally applied, reviewed-plan targets unchanged. Optional Docker entry and final current observer/release acceptance excluded.

- [x] (2026-09-09 16:37:28 UTC) Session CAS independent PASS:8-file3a7fcc33 /557-filef65a5eab,353 regression/755.69s +11 unchanged original probes +8 new probes +4 resource cases =376 unique fresh passes. Ruff/format/mypy8 and108 generated-schema byte checks passed,9826 dependency files unchanged. New29 CAS fixtures contain64 terminal leases,46 absent worktrees,0 active claims;61 child PIDs absent and32 public-journey artifacts/noapply checked.11 intentional legacy residual fixtures retain18 nonterminal metadata leases/six private worktrees; no blanket-zero claim. Receipt SHAdd31481cb3a2c314cbd96bca140be4f708e0117c07bebc2ad3d80619cbcc4dcd. Original failure and initial seven verifier fixture-registration errors retained; later observer/security/docs/release-test successors excluded.
- [x] (2026-09-09, after16:37 UTC) Corrected installed-origin assertions from release-test6432db49 passed on both existing d272 installations; two actual inside-venv symlinks to snapshot source were rejected with exit1 before smoke-state creation and removed afterward. Positive package-module/distribution maps equal the original installations. This direct assertion replay accepts the strict-origin correction only, not a full fresh execution of the successor release test or current observer package.

- [x] (2026-09-09 16:34:54 UTC) Frozen558-filed27254d7 release prequalification passed2 fresh wheel/sdist journeys/257.22s, exit0 and all snapshot bytes unchanged. It uses accepted Sessionf65 plus an explicit root-only overlay and deliberately excludes concurrent observer repair. Seven actual module origins/hashes,108 schemas,all packaged assets/guide,four bundles,six synthetic provider/Harness profile admissions and six wrong-provider rejections, static readiness and existing fake Workflow/review/apply journeys passed with network denied and no key. Read-only review found the new origin checks were lexical; current release-test successor6432db49 resolves origins/venv/checkout strictly. The prior two passes do not accept this successor or final current archives; fresh final release matrix remains required. Root's48 registry/redaction/path regressions passed/.17s.

- [x] (2026-09-09, after16:18 UTC) Pre-observer-edit whole-source static snapshot passed Ruff formatting425 files, lint and mypy358 files. Root then added the boolean-only Redactor registry-presence query:2 focused tests/.03s and scoped Ruff/format passed. S1 read-repair explicitly rejects nonempty or concurrently populated registry rather than copying secrets to the child. These checks are not current observer or whole-release acceptance.
- [ ] (2026-09-09, after16:18 UTC) Session successor3a7fcc worker handoff froze8 files:45 focused/89.36s, worker replay11/16.13s, scoped mypy177/Ruff8 passed;29 new fixtures have64 terminal leases,0 outstanding/active claims and46 absent worktrees. Historical78a23 broad344/808.88s is retained separately. Independent557-filef65a5eab snapshot passed the original11 probes/12.40s and is running the full353 exactly once. Original720d failure is not erased. Writer is now assigned the disjoint observer read repair; Session bytes remain frozen.
- [ ] (2026-09-09, release-test refinement) Added installed wheel/sdist checks for four actual packaged Harnesses, three provider module origins/hashes, four role bundles, nonexecuting public readiness and six credential-free model-profile combinations plus six wrong-provider rejections. Tests are not yet executed as installed distributions. Ruff passes; an intermediate full-source type invocation encountered four diagnostics in the concurrent unfinished observer helper, not release-test acceptance. Do not weaken checks or count a mutable intermediate run as a frozen result.

- [x] (2026-09-09 16:13:30 UTC) Separate mixed-Harness overlay independently accepted: d8d89 test /556-file71fedc snapshot,9 fresh passes/37.26s.159 artifacts byte-checked,42 reported requests/630 synthetic tokens,42 released leases15 absent paths; immutable profileRevision1 survived revision2 future-only edits and reopen. Receipt SHA1225dedfc612669f4fcc1ebfde44667ca3bf9010b6d30113718dad2d43c3753f. No new production delta from corrected LangGraph closure, no live or whole-checkout claim, no duplicate addition of repeated9 root executions.
- [x] (2026-09-09 16:08:04 UTC) Corrected LangGraph/shared integration independently accepted on19-file17303dd0 /555-filec0d9a5f0 snapshot:732 unique fresh cases/84.43s, six direct config controls,16-file static and108 schemas,709 exact wheel-file hashes,53 physical artifact hashes,48 released leases and17 absent paths. Receipt SHA12e03e3544856f2c4c167236c371062fcbdbbbb5f428f1f04eee433e1a2a6646. Predecessordc91 FAILED edited-config and distributed-schema admission despite718 passes; its final receipt SHAa26e0ed5d02cad85fefd79baf8a90b7c57fed50b75c77337a0b57248d06b520a remains unchanged. Five invalid LangGraph provider cases now reject in both layers; no actual provider bypass was observed. Root correction122/1.53s overlaps732. Narrow existing unstubbed-jsonschema import annotation, no new dependency/global type relaxation. Current Session, mixed-Harness overlay, observer, live/Docker/package/whole-checkout acceptance excluded.
- [ ] (2026-09-09, before successor recovery edit) Session78a23 source review found originally malformed cleanup metadata could fence ownership before physical helpers rejected it. No unsafe deletion was observed, but the pre-fence corrupt-binding requirement remains unmet. Authorize only existing pure metadata/identity parser preflight over the immutable ticket before the same-transaction compare/fence; no filesystem opens/effects or new paths. Add malformed workspace/sandbox/execution no-fence tests. Retain the pending344 result as78a23 historical evidence, then freeze the focused successor; coordinate full-current regression once, without relabeling prior bytes as newly executed.
- [x] (2026-09-09, containment follow-up) Root disabled both terminal-recording method bodies before any input/dependency access. New hostile-input/no-constructor containment2/.06s passed with scoped Ruff/format3 and mypy175. No original-DB writer remains reachable through either observer entry. Existing terminal-success integration expectations require explicit successor containment oracles during read repair; original atomic-finalization acceptance remains unmet, not converted to a pass. Old read implementation remains unqualified and unexposed.
- [x] (2026-09-09, release preparation) Explicit scripts/prepare_release_dependencies.py preparation completed exit0 with95 platform-applicable hashed wheels for the99-package lock. New private wheelhouse is separate from the historical52-wheel baseline and does not change canonical environment/source. Dependency download/preparation is not installation/package verification; those tests remain pending.
- [x] (2026-09-09, after15:46 UTC) Root mixed-Harness test-only slice9/59.71s passed: three cyclic PydanticAI/SDK/LangGraph role assignments under ALLOW, separate exact principal approvals with reopen/future-profile mutation, and DENY. Actual SDK wire and durable model selection/usage/Gateway/artifact assertions pass; target stays unchanged and no leases remain outstanding. Scoped Ruff/format and mypy176 passed. Initial static invocation omitted src and also found an unannotated invariant dict tuple; both corrected before test execution, no validator changed. Independent overlay review remains pending. These are9 simulated workflow cases, not nine live tasks or the3-task mixed-Harness KR.
- [x] (2026-09-09, after15:35 UTC) LangGraph root shared regression717/47.58s passed, with one value-free Google Python3.14 deprecation warning. Selected CLI version/doctor1/.34s,108 schema check and offline lock99/22ms passed. Earlier shared run619passed/1failed34.35s exposed the missing RuntimeSpec Literal; correction preserved strict config validation. Writer5-file c75ee6a5 has87 unique passes/12.70s, scoped format/lint/mypy5. Independent production review remains pending; no live request or whole-checkout acceptance.
- [ ] (2026-09-09 15:25:15 UTC) S2.4 independent candidate720d /549-file90918eeb FAILED. Fresh17-module replay275/603.53s and10 extra passes do not override the late-resource injection failure (extra11-case gate22.96s). A real worktree created after the final review snapshot was included in cleanup; original turn revision and full lease payloads were not carried atomically through fencing. Receipt SHA6459116d8ac4e2f2558a0d40fb7abcd7907c2895d661e1b18b2e7d3742b898d5. New single Writer owns the explicit same-transaction review/fixed cleanup-plan repair contract above; root only wires graphs=graphs to its constructor. No replay or relaxed ownership criterion is authorized.
- [ ] (2026-09-09, native qualification completed before15:35 UTC) Original-DB observer write admission remains NOT_GO: private40-case gate35passed/5failed. APSW's distinct SQLite engine can bypass same-process stdlib locks, native NOFOLLOW does not bind parent paths or auxiliary WAL/SHM opens, and parent raw descriptor close can release POSIX locks. Separate-child descriptor capture into private DB+WAL staging qualifies only a read prerequisite, with production-enforced streaming IPC/timeout/reaping still required. Native relative-path and /dev/fd workarounds are rejected. No APSW dependency was added. Qualification verdict SHAe60fa72357e975cd48a5a8fc4138bf77b89da1dcc698b9f0d4067c741fd3c1a7. A read-only design review is assessing immutable historical receipts; no storage redesign or observer public admission is yet authorized by that assessment.
- [x] (2026-09-09 15:11 UTC) Root raw-response factory seam passed26 actual-SDK checks/.58s and scoped Ruff/format/mypy2. Default path remains closed to raw headers; new trusted flag requires exactTrue plus SingleSend ticket and Responses-only URL, preserving uncoerced wire JSON for LangGraph. No provider call occurred; this successor factory requires shared regression/fresh adapter audit before admission.
- [ ] (2026-09-09 15:11 UTC) S2.4 frozen8-file inventory720d7a875a782eda2b8dbb3a0a9cd1b8a12218fbbbb71e2fcaa47eb8caf3beff passed62 focused/43.44s. Scoped Ruff/format7,mypy9 passed; earlier ASYNC240 test-only path assertions moved to asyncio.to_thread and re-executed. Independent549-file snapshot90918eeb has been captured and17-module replay started. Root earlier broad gate started before those five assertion changes; its result is historical until identity reconciliation, not a fresh-all claim.
- [x] (2026-09-09 15:10 UTC) S2.3 bundles independently accepted on15-file a9d2d609 snapshot:55focused/87.59s +43compatibility/91.74s +20additional/16.55s;12-file static checks,165 artifacts,38 terminal leases,11 physical paths absent and8 explicit apply/rollback operations passed. Distinct verifier snapshot/dependency9577 hashes stable;5 child imports snapshot-only. A private launcher -u fixture failure is retained before corrected full43 replay. All four workflow results remain simulated/not verified_complete; later bootstrap/Session successor bytes excluded.

- [ ] (2026-09-09 14:58 UTC) S1.1c independent observer candidate6f058497 FAILED security acceptance despite323 ordinary passes/216.52s and static9/schema108 passes. Actual read-only inspect creates empty WAL/SHM after old handles close. Two adversarial ABA interleavings bypass pre/post path identity checks: an Artifact read accepts same-byte symlinked outside-root content; sqlite3.connect accepts a substituted DB with a different terminal error and then reports the restored original identity. Evidence retained at observer-verifier.i3QF1s adversarial.xml (2failed/5passed25.66s) and database-probe.xml (1failed3.79s). No secret/network used. Do not expose evaluation CLI or claim this source accepted. Descriptor-bound physical reads and a coherent read-only SQLite/WAL snapshot need a new repair contract; adding more lstat checks or immutable=1 while ignoring WAL is not a repair.

- [x] (2026-09-09 14:47:37 UTC) Google Provider and root integration independently accepted on12-file b16750cf and544-file bf83e3d7 snapshot:593/34.49s plus9 extra/.58s,53 physical artifact hashes/3 conservative product gate replays,34released leases/12paths absent,521 wheel files/9033 dependency files unchanged. Ruff/mypy10 and108 schemas passed. Receipt SHA f94bd1e60e38cf2b7461b1e72db18f8ab0e3d1e2ce48d163406c80775b5d25de. DENY retained pre-cleanup bundle still reports cleanup-unproven although physical cleanup passed; no live Google, full-E2E or whole-checkout claim.
- [ ] (2026-09-09 14:56 UTC) S2.4 first targeted47/12.87s and2actualCLI/14.33s passed. Expanded one-use/restart/history/local-owner tests60/29.96s passed; graph multiple-request denial15/18.99s passed. Corrected historical fenced_at incorrectly permitting redundant no-work recovery; fixture invalid Run error_message mutation and old parser assumption failures retained. New frozen tests/fixtures/session-journeys.json maps ten logical journeys to seven existing/new real-process test functions; final unique collection, broad regression and independent audit pending.
- [x] (2026-09-09 14:56 UTC) LangGraph isolated prerequisite29/2.533s and4private-script format/lint passed,15 additive exact packages with zero existing version changes and761 wheel files matched. Actual negative control proved cancelled graph exit can outlive a child; independent owner draining corrected this in the probe. Retained initial thread/router/logger fixture failures and17 value-free deprecation warnings. Production adapter contract is now frozen; runtime/live admission remains pending.

- [x] (2026-09-09 14:32:26 UTC) S1.1b2 independently accepted on851b inventory and532-file bc1021a5 snapshot:182focused/116.67s +242legacy/358.43s =424 unique,8 adversarial/15.35s,89 artifact hash checks,3 non-success completion replays.30 focused leases released/8 physical paths absent; extra cancelled Engineer released2 more.21-file static gates and106 schemas passed;8135 private dependencies unchanged. Receipt SHA c7d51601c323e8c0c0a18e014ba125386c3b87544290f1bd1d9be09b377f405d. Later authorized S1.1c persistence changes and2 schema integration files are excluded from this snapshot acceptance; root notified verifier after his live-drift check stopped, preserving that coordination gap. Deliberate legacy fixtures retain8 active/2 creating metadata rows and2 paused Fake worktrees; do not claim blanket cleanup. No external oracle, real campaign or live call.
- [ ] (2026-09-09 14:31 UTC) Root Google12-file b16750cf freeze passed593 unique tests/34.79s (Google108 +SDK105 +shared380),10-file Ruff/format,12-file mypy and offline lock84. One value-free Google Python3.14 deprecation warning retained. Independent Google review started. Bundles15-file a9d2d609 passed55focused/90.90s plus43compatibility/95.76s; independent review queued. New LangGraph1.2.11 wheel source is being qualified without installation; exact SDK0.4.4 permits current websockets16.1.1, unlike minimum0.4.2. No dependency mutation or admission is inferred from qualification.
- [ ] (2026-09-09 14:27 UTC) Root S2.3 candidate has55 focused passes/90.90s across31 unit,4 real new-CoS proposal/review/apply/custom-role/rollback,10 subprocess CLI and10 schema cases. Static10-module mypy and scoped Ruff pass; compatibility and fresh independent review remain pending. Retained failures: initial4 SQLite-GC byte assertions, two4-case test API keyword mistakes,1 CLI JSON-selection loss because Click mutates args; fixed the parser by capturing --json before parsing and rejecting unknown group commands safely. New integration filename test_role_bundle_workflow.py avoids a duplicate pytest basename. No product validator weakened.
- [ ] (2026-09-09 14:25 UTC) Google root registration matches written google:<model> contract, not the initial mistaken google-gla prefix. Added exact google-genai2.18.0/PydanticAI google extra: lock76→84,8 dependencies added with no existing version upgrade; canonical sync followed campaign snapshot release and retained editable install. Offline lock initially failed because index metadata was absent from cache; normal exact resolution succeeded. New Google/Anthropic/OpenAI role-profile transport + model-profile tests46/1.81s passed, with one value-free Google Python3.14 deprecation warning. New Google adapter and current shared closure remain under review; no Google live request.
- [x] (2026-09-09 14:05:57 UTC) S3.2 SDK and root shared integration independently accepted on immutable521-file snapshot7ea80a0d75dcd556a9c8a4dbb70dda943532af1b7d540af126a6d18e70ae6c49, SDK4-file e139b3d0. Fresh105 SDK/13.67s plus375 shared/9.07s =480 unique passes and7 independent raw-usage/cancellation/tracing probes. All import origins were snapshot-only,8135 private dependency files unchanged;31-file Ruff/format,15-module mypy and106 schema comparisons passed.66 databases,20 released leases,7 leased paths physically absent;5 worktree registries contained only targets. Final receipt SHA5e40e882300aedc298eb7e2bfc3d3c0239660c82de1b10528f946aecc4e3ae31 and11 linked hashes rechecked. Initial verifier plugin-selection failure and nonsecret SQLite GC ResourceWarnings retained. No whole mutable checkout/live/Docker/distribution/GitHub acceptance.
- [ ] (2026-09-09 14:16 UTC) Root S2.3 domain/assets/preview implementation passed20 unit tests/13.52s after retained first-run4 failures/16 passes: legacy harness SQLite connections were garbage-collected during byte inventory, checkpointing existing WAL. The test now finishes fixture collection before measurement; service still opens no store. CLI, actual new-CoS proposal lifecycle and independent acceptance remain pending. Google actual-SDK contracts are under development in an isolated Python3.14 environment; no Google credential or request.
- [x] (2026-09-09 13:46 UTC) Shared provider/client/config/onboarding/admission/lifecycle regression375passed/8.16s after the ordinary S1 dependency path became coherent. S1 execution service is wired into ApplicationContainer.evaluation_execution and the same Workflow; composition probe passed. These in-development dependency runs are not immutable whole-candidate acceptance.
- [ ] (2026-09-09 13:49 UTC) SDK writer froze4 new files on e139b3d0f2ea5f4d84e3c052ede2bcf6112434ab0501603341253dbb80196bfb:105passed/12.34s, Ruff/format4/mypy5 passed. Nested usage warning and atomic tracing-install findings corrected;2MiB remains explicitly a post-read acceptance bound. Independent review is next, using a stable captured source closure while S1 development continues, not claiming the whole mutable checkout accepted.

- [x] (2026-09-09 13:43 UTC) Root shared transport/profile subset178passed/2.90s, scoped mypy7passed after explicitly including the existing fixture import module. First type invocation failed only because that fixture module was omitted. Second combined pytest retained223passes/15failures/5.38s:3 Anthropic URL test expectations omitted the already permitted ?beta=true;12 DB-backed cases hit the concurrent S1 writer's then-missing execution-store import. Corrected URL and pure/transport subset passed; the concurrent DB run is not acceptance. README and USER_GUIDE now describe accepted S2 management and separate provider/Harness review limits.

- [x] (2026-09-09 13:27:02 UTC) S2.2 independently accepted on11-file efda1d9c2633533c39ed0f4e789ae03f6c006c5acce59eb2f0a34230d47104ba:65 focused/51.72s plus144 compatibility/391.41s,209 unique cases, stable held dependency closure. Six read-only views preserved43 tables; actual Unicode Session wire1047212bytes with78 explicit omissions. Ruff/format/mypy/schema/diff passed. Audit receipt SHA24b5bd245c4d8b6da119c172fbf468d5070d1ae27c2d250434db8ad9a7b7e4eb. Source hold released13:24:17.870919Z. Generic pre-existing text bidi rendering remains a separate limitation; new JSON views escape it.
- [ ] (2026-09-09 13:34 UTC) Root shared-client extraction and closed provider/SDK registry integration proceed after both accepted dependency holds. S1.1b2 contract frozen before Noether implementation. SDK writer reports81 actual-SDK offline contracts passing; integration still correctly rejects unregistered runtime until root wiring. No new live requests.

- [ ] (2026-09-09 13:17 UTC) Agents SDK lock resolution added19 packages,57to76, without upgrading an existing version. To preserve the active Session audit's installed dependency closure, no repository .venv sync occurred. A new private UV_PROJECT_ENVIRONMENT first selected Python3.13.15 automatically; a separate explicitly pinned sibling environment uses the primary Python3.14.6 and installed73 platform-applicable packages. Agents writer uses only that private3.14 environment. Existing .venv/editable remains held. Shared OpenAI factory12 actual-SDK offline tests passed/0.27s plus scoped format/lint/mypy; PydanticAI extraction and registry wiring wait for Session dependency release.
- [x] (2026-09-09 13:14:15 UTC) Anthropic direct RuntimeConfiguration path independently accepted on14-file ff390b94dfca22c49e7cabda86c38f01a59a42b8652a2c7f9a698426f957af74. Fresh233/8.14s plus5 actual-SDK lifecycle faults passed; exact durable client_cleanup event and zero-effects failure verified. Source/SDK closure held, static passed and6 normal-workflow leases/worktree paths were physically terminal. Prior ef721 double-cancel FAIL and c15ab diagnostic gap retained. Root's prior c15ab closure was interrupted by diagnostic edits, so it is intermediate evidence only. Direct runtime support does not yet include per-role Anthropic ModelProfiles or live calls.
- [ ] (2026-09-09 13:15 UTC) Anthropic dependency audit released. Root will add only pinned openai-agents0.22.1 and its required transitive dependencies, preserving existing versions, then perform locked sync with editable project retained. No SDK/live acceptance is inferred from installation. S2.2 independent audit was previously queued to an idle verifier; it is now explicitly started with followup_task, not claimed retrospectively running or completed. Hold its source files until its actual closure.
- [ ] (2026-09-09 12:56 UTC) Anthropic ef721 first freeze failed independent repeated-cancellation cleanup despite193 replay passes/7.76s. Its actual transport could remain unclosed behind a true is_closed flag. Correct under the written lifecycle contract before acceptance. Root52 affected workflow tests passed/209.51s on the same frozen provider/runtime and current frozen Session dependencies; these do not dismiss the new physical-cleanup failure.
- [x] (2026-09-09 12:31:41 UTC) S1.1b1 non-executing durable ledger independently accepted on19-file inventory39b9548cf3416b64da2fcb8ff5992589d0f352c720ddfc76d08ef5c50873e33c. Authoritative stable-dependency replay143/6.90s plus38 adversarial checks; schema/migration/atomic-budget/resource checks passed. Prior a442 candidate failed exact-False typing because integer0 was accepted; all three new models now reject coercion at every boundary. The earlier195-case mixed-dependency replay is retained but not counted as frozen old-store acceptance. No campaign dispatch is admitted.
- [ ] (2026-09-09 12:50 UTC) Root Anthropic actual-SDK offline candidate passed192 focused/runtime/workflow tests in7.21s; scoped Ruff/mypy passed. The real SDK workflow uses FakeSandbox and explicitly remains SIMULATED_EVIDENCE_ONLY. Independent security review and freeze are pending; no Anthropic live request. Retained iterations include missing SDK metadata-header allowance, wrong test-only provider field/oracles, missing-usage fail-closed expectation and a raw ExceptionGroup context on an otherwise safe error. No budget/permission/output validator was weakened.
- [ ] (2026-09-09 12:50 UTC) S2.2 writer freeze efda1d9c2633533c39ed0f4e789ae03f6c006c5acce59eb2f0a34230d47104ba covers11 files;65 focused tests passed/56.37s, format/lint/scoped types passed. Independent acceptance pending. A prior subprocess oracle used the wrong existing plan field; failed result retained and corrected subprocess passed1/15.04s. Session readiness measures its actual redacted, escaped pretty-JSON plus newline, with no frozen readiness-service change.
- [x] (2026-09-09 12:17:38 UTC) Corrected S2.1a independently accepted on14-file inventory7ab4f93e95f6834a04ef9592ebfa41a84de393390a0db018af5836b65e573fd4. Independent76/8.24s and same76/6.99s post-environment-restoration replay are not additive. Original Unicode counterexample now1047265 actual CLI bytes<=1MiB with309 explicit omissions/exit1;110 legacy-profile comparisons and existing state/WAL/SHM/index/target byte checks passed. Prior d5cdFAIL retained. S2.2 writer released under its separate contract.
- [ ] (2026-09-09 12:22 UTC) Root Anthropic implementation begun after its12:14 contract. Lock resolution added only anthropic1.3.0/docstring-parser0.18.0 (55to57 packages). SDK offline transport tests underway; no Anthropic credential or live call. Initial --no-install-project sync temporarily removed the editable package; --no-build-isolation restoration failed for missing build-only editables, then normal locked offline sync restored it successfully. Independent tests reported no affected failure and replayed readiness after restoration. Preserve these environment findings, do not claim the first sync left the editable install intact.
- [ ] (2026-09-09 12:08 UTC) S2.1a first freeze d5cdff has82 writer passes and75 independent passes plus46 legacy-profile byte comparisons, but independent audit correctly rejected its public Unicode JSON byte bound. Retain the failed freeze and correct only readiness serialization/accounting, then replay before acceptance. S1.1b1 new ledger56 tests and historical profile/plan40 tests passed so far; it is not frozen or independently accepted.
- [x] (2026-09-09 12:08 UTC) Independent bounded review of Coding Harness feasibility found no material unsupported admission or impossibility claim. Clarified environments=[] applies when no turn override is provided. Review matched the local binary/schema hashes and416 generated schemas, but did not start a server or model; this remains interface feasibility only.
- [x] (2026-09-09 11:53:15 UTC) Independent PASS for root S3.1a guard-only five-file inventory8ad3fdeac9367acfd8f08fb9528163b01715b80de71d0086b23f6be0b3f6f230:159 focused passes/3.32s plus26 independent entry/order adversarial checks; root separately ran52 relevant workflow/approval/budget/custom-role/model-binding tests/207.83s, exact JUnit independently reconciled. No invocation authority/wire/capability expansion. This is not complete S3.1 or new-Harness qualification. S1.1b1 and S2.1a remain in progress under disjoint writer scopes.
- [x] (2026-09-09 11:39:48 UTC) Independent PASS for corrected S1.1a334c:123 focused passes/0.42s plus16 independent corrections, actual earlier CoS failures represented without fabricated Task,411-file inventory retained and independently matched. Against reconstructed7af,399 files unchanged,2 existing files changed and10 added;92 old schema bytes/config unchanged. Prior a37FAIL preserved; no unavailable per-file intermediate comparison claimed. This accepts the pure structural slice only. S2.1a writer released after the audit; root separately owns frozen S3.1a guard-only scope.
- [x] (2026-09-09 11:35 UTC) Independent review rejected a37 despite113 focused passes: a real CoS failure can retain a root Run before any TaskSpec is bound, but OutcomeRecord required both identities together. Writer corrected only the outcome model and two regression modules, freezing334c089e01b380b167d0950af8e6d11a564275f0ff33ad3e9f85d5853bc13092;123 focused tests passed/0.47s, scoped static/schema checks passed and schema bytes were unchanged. Independent corrected-candidate acceptance remains pending; S2 source edits remain held. Preserve the a37 FAIL and root132-pass result as earlier-candidate evidence, not corrected-candidate proof. The a37 collection was2593 tests; this is collection only, not full execution.
- [x] (2026-09-09 11:27 UTC) S1.1a frozen a37b858ba6a00d875e5f811a2164dc533c287b6c4b16adaa9d71863ebbc5dca8:writer113 focused passes/0.43s; root expanded selection132/20.22s includes archive and budget CLI. Whole-dot format348,linter,mypy284,schema95/offline lock55 packages22ms,whitespace passed. Initial97/1 focused result retained: JSON serialization coerced a copied bool repetition to integer,so boundary now strictly revalidates original instances before serialization. New UTC/not_run/time/identity/coverage/report consistency checks included. Fresh independent acceptance is running; this is not a full current default/live campaign gate. S2.1a contract written before any S2 source edits.
- [x] (2026-09-09 11:08 UTC) Canary post-result package closure accepted; S1.1a exact field map and rate semantics frozen and writer released. Read-only GitHub check: remote main equals3fb0971 and reports protected=false; ruleset endpoint403 feature-unavailable, connector itself404 due unavailable repository access. No remote mutation or Actions run. Recheck protection immediately before delivery.
- [x] (2026-09-09 10:37 UTC) Bounded live prerequisite independently accepted; S1–S3 implementation gate unlocked. This is not S1 task-campaign acceptance.
- [x] (2026-09-09 11:05 UTC) Read-only source/roadmap contract mapping complete; this living plan and S1.1a writer boundary written before new source edits.
- [x] S1.1a immutable models and pure reports, focused tests and independent review.
- [ ] S1.1b durable campaign/evidence accounting and S2.1 readiness.
- [ ] S1.1c measured existing-provider baseline; S2 Session/bundles/strategy/cold-start acceptance.
- [ ] S1.2–S1.4 Provider qualification and live combinations.
- [ ] S3.1–S3.4 shared conformance, new Harnesses and feasibility.
- [ ] Full candidate gates, updated support documentation and verified small-commit GitHub merge.

## Discoveries

- Observation: the existing Bootstrap canary uses a disposable fixture, while Workflow always invokes CoS and command authorization requires a code-change TaskSpec. Consequence: it cannot honestly measure the target's preexisting test failures without a new explicit model-free baseline purpose, exact reviewed command binding and durable no-replay ownership. A read-only mapping identified existing Gateway/Broker/resources seams; no baseline code is implemented. The six evaluation fixture repository identities are synthetic, not real-target proof, and no qualified Node image/dependency environment is available. Do not fabricate an empty patch or call a missing-image diagnostic a completed Node baseline.

- Observation: independent Session late-resource injection disproves review scope despite275 ordinary passes; rereading lease IDs/payloads during cleanup expands authority. Consequence: preserve the original review's turn/claim/graph/full-lease identities in one transaction and consume only its fixed cleanup plan, with pre-effect and terminal compare-and-swap checks.
- Observation: SQLite mode=ro can create WAL/SHM and pre/post path checks cannot detect transient path substitution. The native qualification also found cross-engine and descriptor-close locking hazards. Consequence: do not expose the observer; original-DB terminal CAS writes remain unqualified. Read snapshots must use a clean separate process, descriptor-bound capture and SQLite interpretation of captured committed WAL, not ignore WAL or rely on assertions-disabled native behavior.
- Observation (2026-09-09 12:50 UTC): Anthropic1.3.0 uses httpx2/httpcore2 logging; HTTP INFO can expose reason/version before response hooks and child loggers can override parent levels. Consequence: reject enabled INFO logging throughout those and anthropic namespaces before credential access. SDK response model identity is checked against the selected model; aliases are not silently accepted. PydanticAI can attach a raw graph ExceptionGroup to a safe FleetError, so the public boundary removes its raw chain while preserving the domain subtype.
- Observation (2026-09-09 12:50 UTC): Agents SDK deduplicates identical call IDs before interruptions, and tracing_disabled alone may initialize a default exporter. Consequence: validate raw output before SDK planning, and install an explicit no-processor disabled trace provider before lazy initialization. The bounded S3.2 contract above records these independently source-qualified conditions before implementation.
- Observation (2026-09-09 12:08 UTC): readiness measured UTF8 JSON with ensure_ascii=False, while its public CLI used the default escaped encoding. An independent reachable Unicode-path case was1040327 bytes in the model and2021395 bytes on the wire, exceeding1MiB. Consequence: qualify the exact readiness wire format with a public CliRunner regression, without changing unrelated CLI serializers. Earlier pre-review also required capture failures not to alter legacy profiling, secret-safe errors without retained raw exception contexts, and preserving admitted dependency-name spelling so redaction is not bypassed by normalization. All failed iterations remain in private handoff evidence.
- Observation (2026-09-09 12:08 UTC): exact minimum-compatible Anthropic1.3.0 and google-genai2.18.0 wheels were downloaded without dependencies into an external qualification cache, not installed or imported. Their client boundaries differ materially: Anthropic uses httpx2 and ambient custom headers; Gemini uses httpx, can consult ambient cloud/API-key settings, and needs attempts=1 rather than0 to disable its retry loop. Consequence: inspect actual pinned SDK paths before designing provider admission; never copy OpenAI constructor flags blindly. Wheel hashes are e7e7dbebf9f3c84a23954ab989378af6ae10a4d1804c81e9fea4b5ced695ce75 and4c5e60ccaed3ed35ac2ee81e87c5bebf7280cd49b81526d872a526e97ce25f46. No credential, endpoint or dependency-lock mutation occurred.
- Observation (2026-09-09 11:55 UTC): early independent S2 review found Python extras could be silently dropped, tool.uv.sources could mask path/VCS overrides as registry dependencies, and aggregate projection overflow could produce the wrong exit category. Consequence: preserve or explicitly mark unsupported dependency semantics, never retain unsafe override payloads, and truncate every projectable collection into an incomplete bounded report/exit1. Initial duplicate test-basename collection error is corrected by renaming only the new integration module; no global import-mode workaround.
- Observation (2026-09-09 11:55 UTC): official Coding Harness interfaces offer custom tools, but native approvals are not Fleet executor receipts and callback coverage is configuration-dependent. Local Codex0.153.4 help and416 generated experimental protocol schemas were inspected without starting a server or model; Claude findings are documentation-only. Consequence: both remain NOT_ADMITTED pending exact native-effect,credential,per-request-budget and recovery tests. The qualified boundaries and prospective experiment are in docs/CODING_HARNESS_FEASIBILITY.zh-CN.md; this is not new-Harness live acceptance.
- Observation (2026-09-09 11:35 UTC): Workflow persists Run before CoS output is accepted and TaskSpec/run.task_bound is saved. A provider/validation failure therefore legitimately has root_run_id with task_id=null. Consequence: OutcomeRecord allows root-without-Task for non-success outcomes, rejects Task-without-root, requires both for verified_success, and still forbids a Run for not_run. Never fabricate a provisional Task ID to satisfy an evaluator schema. Both root inspection and independent reproduction established this failure; corrected regression includes reported CoS usage and the frozen denominator.
- Observation (2026-09-09 11:35 UTC): read-only source qualification of openai-agents0.22.1 wheel SHA41e09c74ac8a1de4735a16f687b544a9c4a611602bc83a83dccad0e28b955615 confirms explicit model/client construction, tracing_disabled, per-tool interruptions and preserve_raw_usage. SDK Usage otherwise substitutes zero for some absent fields; its debug/error logging may expose response/exception data. Consequence: eventual admission must verify raw usage and logging as well as transport, batch authorization and cancellation. The wheel was downloaded without dependencies into a private external cache; nothing was installed/imported/executed or changed in the project lock. Source inspection is not adapter qualification.
- Observation (2026-09-09 11:16 UTC): official Agents SDK guide pages establish explicit model selection and default tracing, but defer exact transport/lifecycle hooks to the language SDK. An isolated no-cache package-index query reports openai-agents0.22.1. Consequence: inspect that exact wheel outside the checkout before designing the adapter; this is dependency qualification only, not installing into the project, invoking a model or opening admission. Use a private unique cache, official PyPI binary wheel, no dependencies, and retain its hash. No change to the existing lock/environment in this preparation.
- Observation: accepted canary fixes did not require relaxing schemas, permissions, completion mapping or budget limits. Evidence: prior living plan and independently accepted7af attempt6. Consequence: preserve strict acceptance; the external baseline must measure failures rather than repair outcome records.
- Observation: only OpenAI credentials are presently authorized/available; other SDK dependencies are not yet installed. Consequence: safe implementation may continue, but new-provider live acceptance cannot be fabricated.
- Observation: frozen existing models can contain mutable dictionaries/lists; readiness's existing doctor can migrate. Consequence: use deeply immutable new contracts and a genuinely read-only readiness path.

## Decision Log

- Decision: start with pure evaluation contracts, not a broad new orchestrator. Rationale: fixed honest denominators and evidence identity are prerequisites to useful paid measurement; preserve existing runtime/budget authority. Alternatives: ad-hoc test totals would hide missing and repeated attempts. Date:2026-09-09UTC.
- Decision: no first-version exclusions or automatic KR PASS. Rationale: exclusion and source-authenticity protocols are not yet implemented; strict accounting avoids post-result selection. Date:2026-09-09UTC.
- Decision: retain unknown costs and separate product verdict from external result. Rationale: reported tokens and a Verifier verdict are not invoices or an independent oracle. Date:2026-09-09UTC.
- Decision: missing external credentials/environment is a bounded acceptance gap, not permission to skip all safe S1–S3 development. No new licensing/branding/provider-choice questions. Date:2026-09-09UTC.

## Outcomes

The current21700932 checkpoint accepts implemented local foundations, not all S1–S3 OKRs. Its exact default reconciliation is3591 passed/23 optional skips over3614 unique identities, combining870 fresh successor cases with2744 byte-identical carried cases; it is not3614 fresh executions. Named adversarial737,format429,lint,mypy363,schema108 and offline99-lock checks pass. The unchanged production/dependency predecessor's real Docker29 and fresh-install3 journeys have independent physical/artifact readback; the corrected installed entry has separate positive/negative controls. Final live-result documentation/archive and GitHub delivery remain separate gates.

Pure evaluation, durable reservations and reserved execution are locally accepted, but terminal outcome writes remain NOT_GO and disabled before state access. The separate-process read repair is now independently accepted79 unique tests; it is not publicly wired or write acceptance. Session management/recovery and four reviewed role bundles are accepted, including376 fresh recovery cases and the corrected late-resource counterexample. PydanticAI/Anthropic/Google, OpenAI Agents SDK and LangGraph have the precise offline boundaries recorded above; mixed Harness routing has nine offline cases, not live reliability proof. Component counts overlap and are not additive full-suite coverage.

Historical nano canary attempt6 passed; the latest21700932 regression instead FAILED after Verifier command execution and strict output validation, with49687 reported tokens and no automatic retry or target apply. Both results remain visible. Seven scoped foundation commits are local; final documentation commit and remote delivery are pending. No Anthropic/Google credentials or requests,real24-task campaign,new-Harness six-task live qualification,business baseline/cold-start acceptance,push or merge has occurred. Keep the goal active until the remaining objectives are genuinely verified; do not replace them with mock outcomes or relabel this checkpoint as whole S1–S3 completion.
