# Phase 1.5 North-Star Alignment

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

Turn the verified Phase 0/1 skeleton into an honest foundation for the product's six differentiators before any real model harness or Docker execution is introduced. Agent Fleet is not a generic multi-agent framework. It is a local-first, BYOK Chief-of-Staff CLI that converts a software repository into a secured, adaptive project-specific agent organization and delivers work through verifiable evidence.

At the end of this plan, the offline CLI will expose repository facts instead of only copying generic prompts, persist a validated `FleetPlan` instead of assuming a permanent three-agent roster, route every runtime-requested action through an injected `PermissionBroker`, describe the fake sandbox through an explicit capability contract, and produce a structured `EvidenceBundle` whose completion decision cannot mistake simulated output for executed proof.

A representative offline flow remains:

```bash
AGENT_FLEET_HOME="$temporary_state" uv run fleet init "$temporary_repo" --runtime fake --sandbox fake --yes --json
AGENT_FLEET_HOME="$temporary_state" uv run fleet run "Fix the canary behavior" --project "$temporary_repo" --fake-scenario success --json
AGENT_FLEET_HOME="$temporary_state" uv run fleet artifacts <run-id> --json
```

The init result will include a structured repository profile and Project Knowledge artifact references. The run artifacts will include a `FleetPlan` and `EvidenceBundle`. Because the sandbox remains fake, the bundle must report simulated command evidence and a proof gap rather than verified execution.

## Scope

### In scope

- Make the North-Star positioning and six differentiators normative in README, product/architecture/security/schema documentation, one ADR, and the roadmap.
- Add safe, deterministic repository profiling for common Python, Node, Go, Rust, Maven, Gradle, Make, and CI signals without executing repository code, hooks, package lifecycle scripts, or detected commands.
- Persist repository profile and Project Knowledge as content-addressed artifacts and use detected commands when proposing the repository verification profile.
- Replace security-irrelevant closed role/workflow literals with validated extensible identifiers.
- Add typed `FleetPlan`/node/DAG/budget/verification contracts, a deterministic plan validator, and a persisted FleetPlan artifact used by the existing offline vertical slice.
- Demonstrate offline `direct`, `single_engineer`, and `engineer_verifier` plans with only the planned role instances created. Code-change plans remain bounded and the existing repair workflow remains supported.
- Extract Phase 1 authorization from `ToolGateway` into an injected project-owned `PermissionBroker` contract with decision explanations; keep only `allow once` persistence while reserving run/exact-persistent grants for Phase 4.
- Remove host paths and sandbox handles from runtime input. A runtime may return typed intents but cannot mutate a workspace or call a sandbox directly.
- Add an explicit sandbox capability descriptor and common fake-provider contract tests. Unsupported providers continue to fail closed with no fallback.
- Add typed command/criterion/risk/proof-gap evidence, a content-addressed `EvidenceBundle`, and a deterministic `CompletionGate` that distinguishes workflow completion from verified completion.
- Add a validated `FleetPatch` domain/schema foundation and protected-path validation, without implementing conversational proposal, persistence, apply, or rollback commands.
- Add contract coverage for every Phase 1 concrete adapter, plus repository-analysis, adaptive-plan, permission, sandbox, evidence, and schema security tests.
- Keep all ordinary tests offline with no API key, network, Docker daemon, or project-code execution by FakeSandbox.

### Out of scope

- PydanticAI, any live model/provider call, provider SDK, credential resolution, keyring, usage billing, or model selection.
- Docker, Modal, hosted sandbox execution, or a local unsafe executor. No placeholder providers that appear functional.
- Parallel Engineer scheduling, merge/join conflict resolution, or real Researcher/Architect execution. Their topology is a later adaptive scheduler increment.
- Full Phase 4 policy: allow-for-run, persistent exact project trust, revoke/explain CLI, trust-store migration, and protected action registry.
- Full Phase 6 FleetPatch persistence, CLI diff/apply/rollback, natural-language proposal, or behavioral evolution loop.
- Real project test/build execution, network access, external writes, commits, pushes, pull requests, deployments, or release publication.

## Starting repository state (historical)

At the start of this plan, commit `b2516425a71a03eb25ed9785b335c79968187ecd` on `main` was synchronized with private `origin/main`. Phase 0/1 contained an installable Python 3.12-3.14 package, Typer/Rich CLI, strict Pydantic/YAML models, SQLite migration `0001`, content-addressed artifacts, real hardened Git worktrees, fake runtime/sandbox adapters, durable allow-once approval, guarded patch apply, recovery/cancellation, and 46 passing tests. This paragraph is retained as the implementation baseline, not as a claim about the final working tree.

Important components at plan start:

- `src/agent_fleet/bootstrap.py::build_container` is the composition root.
- `src/agent_fleet/application/projects.py::ProjectService` registers a repository, writes generic `.fleet/` files, and creates but does not run a disposable canary.
- `src/agent_fleet/adapters/config/yaml.py::default_fleet_files` currently proposes the same role and verification files for every repository.
- `src/agent_fleet/application/workflow.py::WorkflowEngine` hard-codes CoS, Engineer, and Verifier sequencing.
- `src/agent_fleet/application/gateway.py::ToolGateway._evaluate` contains the narrow Phase 1 policy inline.
- `src/agent_fleet/adapters/runtime/fake.py::FakeRuntimeAdapter` receives a verification host path and directly mutates it for one adversarial scenario. That simulation demonstrates a real architecture bypass that this plan must remove.
- `src/agent_fleet/ports/sandbox.py::SandboxProvider` has lifecycle methods but no capability or evidence-strength descriptor.
- `TaskSpec.required_evidence` is stored but not evaluated. Fake command output can accompany a PASS verdict even though no project code ran.
- FleetPatch exists only in specifications.

The current implementation and validation results are recorded in `Progress` and `Outcomes` below.

## Security impact

This plan changes repository inspection, runtime context, tool authorization, evidence claims, persistent model schemas, and configuration generation.

- Repository profiling treats every repository file as untrusted data, reads only bounded regular files beneath the canonical repository root, rejects symlink escapes, and never imports modules or executes manifests, hooks, scripts, Make targets, or detected commands.
- Detected commands are evidence-backed candidates with source and confidence. Detection is never authorization.
- Runtime requests contain logical identifiers and content, never host paths, sandbox handles, secrets, or trusted authorization context.
- `PermissionBroker` evaluates a canonical `ToolIntent` constructed by the control plane. Repository configuration and runtime output cannot grant authority.
- `ToolGateway` remains the only application path from runtime intent to candidate write or sandbox execution. Static architecture tests reject runtime imports of concrete sandbox/repository/subprocess execution modules.
- Fake sandbox evidence is explicitly `simulated`, with `executes_code=false` and `isolation_enforced=false`. It cannot satisfy a criterion requiring executed or independently verified evidence.
- Evidence is assembled from authoritative state, canonical Git patch metadata, and control-plane-created artifacts, not from agent-provided artifact IDs or claims.
- FleetPatch validation permits only approved `.fleet/` organization paths and rejects trust, secret, state, audit, hard-deny, and sandbox-hard-limit paths.
- Existing redaction, path containment, symlink defense, no-shell Git execution, exact approval binding, transactional state/event behavior, and guarded patch apply remain mandatory.

No migration is required unless implementation proves JSON-in-row compatibility insufficient. New optional fields must have backward-compatible defaults so migration `0001` databases reopen safely. If a new table becomes necessary, add transactional migration `0002` and a migration-upgrade test rather than editing `0001`.

## Proposed design

The aligned dependency flow is:

```text
Repository -> StaticRepositoryProfiler -> RepositoryProfile
                                      |-> ProjectKnowledge
                                      |-> FleetSpec proposal

User goal -> RuntimeAdapter proposes bounded scope + strategy
                                      |
                                      v
                         FleetPlanner -> FleetPlanValidator
                                      |
                           WorkflowEngine / Scheduler
                                      |
Runtime action -> ToolGateway -> PermissionBroker -> Authorized execution
                                      |                  |
                                      v                  v
                                 audit event      SandboxProvider

Task + plan + canonical patch + command records + verdict
                                      |
                                      v
                              EvidenceAssembler
                                      |
                                      v
                               CompletionGate
```

### Repository intelligence

`RepositoryProfile` will contain stable repository-relative facts: ecosystems/languages, build/package systems, repository/subproject boundaries, detected commands, evidence sources, confidence, and ambiguities. `StaticRepositoryProfiler` will recognize authoritative metadata conservatively. For example, `pyproject.toml` plus `uv.lock` and a `tests/` directory can support a Python/uv profile; a declared script in `package.json` can support an exact package-manager command. A missing script must not be invented.

`ProjectKnowledge` will record factual summaries and unknowns, not model-generated prose presented as truth. Both structures are serialized into artifacts during `fleet init`, and their hashes/IDs are bound to the `Project` record.

### Adaptive plan foundation

`RoleId` and `WorkflowId` become validated strings rather than closed role lists. `FleetPlan` contains a strategy, nodes, dependency edges, scopes, workspace ownership, required verification, limits, and rationale. A deterministic validator rejects cycles, missing dependencies, duplicate IDs, excessive concurrency, direct plans with side effects, and code-change plans whose declared assurance exceeds their verifier/evidence topology.

The fake CoS returns a bounded scope/strategy record. The application-owned `FleetPlanner` constructs and validates the immutable plan. The existing success/fail/repair/approval/inconclusive paths use `engineer_verifier`. Two additional offline scenarios demonstrate `direct` and `single_engineer`; neither may claim independent verification. Parallel topology is representable and validated but not scheduled in this phase.

### Permission separation

Add a `PermissionBroker` protocol and a `BaselinePermissionBroker` application implementation. `ToolGateway` canonicalizes and persists intents, delegates the decision, and executes only allowed or exact-grant-reserved intents. Decision events include a stable decision code and explanation. The baseline retains the existing narrow rules and default deny; broader trust persistence remains Phase 4.

### Runtime isolation

`AgentInvocation` contains only logical repository/workspace identity and artifact references needed for a role. The verifier-mutation scenario becomes a normal forbidden `workspace.write_file` intent from the Verifier; `PermissionBroker` denies it, proving the attempted bypass never reaches the filesystem. Runtime adapter code must not import `pathlib.Path` for workspace mutation, repository adapters, sandbox implementations, or subprocess execution.

### Evidence and completion

`CommandEvidence` records exact executable/argv/cwd, transcript artifact, sandbox provider/security level, evidence strength, exit/timing/truncation, and the patch/config identity it applies to. `CriterionAssessment` maps each acceptance criterion to authoritative evidence references and records PASS/FAIL/INCONCLUSIVE. `EvidenceBundle` binds the exact ConfigSnapshot and TaskSpec artifacts, FleetPlan, base revision, patch hash, changed paths, verifier identity/verdict, risks, proof gaps, and the completion decision. Phase 1.5 deliberately returns `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE` for multi-criterion scripted tasks instead of pretending one overall verdict proves each criterion.

The Phase 1 fake path may reach `READY_FOR_REVIEW`, but `verified_complete` must be false because command evidence is simulated. `RunStatus.COMPLETED` after explicit patch apply remains an operational lifecycle result and is not synonymous with verified completion.

### FleetPatch foundation

Add a strict `FleetPatch` model and deterministic path/base-hash validator used by unit tests and JSON Schema generation. The foundation is intentionally not exposed as an operational CLI until Phase 6 can implement staging, persistence, atomic apply, rollback-as-new-event, and behavior-before/after proof.

## Public contracts

- Existing CLI commands and Phase 0/1 JSON envelope remain compatible.
- `fleet init --json` adds repository profile, Project Knowledge, and sandbox capability summaries plus artifact IDs.
- `fleet run/status/artifacts --json` expose FleetPlan and EvidenceBundle references and `verified_complete`/proof-gap information.
- New strict Pydantic types: repository signals/profile/knowledge, extensible identifiers, FleetPlan/nodes/strategy, sandbox capabilities, command evidence, criterion assessment, completion decision, EvidenceBundle, and FleetPatch validation foundation.
- `Project` gains optional profile/knowledge/config-snapshot artifact IDs and hashes; `Run` gains optional config-snapshot, TaskSpec, plan, and evidence artifact IDs/hashes plus assurance fields with backward-compatible defaults.
- `ConfigurationPort` proposal generation accepts a `RepositoryProfile`.
- New `RepositoryProfiler` and `PermissionBroker` protocols. `SandboxProvider` gains immutable capabilities.
- New artifact kinds include repository profile, project knowledge, config snapshot, TaskSpec, fleet plan, command evidence/transcript, verifier verdict, and evidence bundle.
- Schema generation/check covers repository-profile, project-knowledge, config-snapshot, task-spec, fleet-plan, sandbox-capabilities, command-evidence, evidence-bundle, and fleet-patch schemas.
- Existing fake/runtime/sandbox selection remains the only supported runtime execution path; any later provider value fails closed.

## Milestones

### Milestone 1: Normative contracts and positioning

Update product/architecture/security/schema/roadmap documentation and ADR; add strict domain models, extensible IDs, FleetPlan validation, sandbox capabilities, EvidenceBundle/CompletionGate, FleetPatch validation, and generated schemas without breaking existing tests.

Acceptance:

- README and specifications use the Chief-of-Staff CLI / project-specific organization-runtime positioning and label each differentiator as enforced, partial, or roadmap.
- Models reject invalid identifiers, FleetPlan cycles/ownership/assurance claims, forged evidence strength, and protected FleetPatch targets.
- Existing migration data validates through backward-compatible defaults.

### Milestone 2: Repository-aware offline bootstrap

Implement and inject the static repository profiler; generate repository-specific verification proposals and Project Knowledge; persist and expose their artifacts during init.

Acceptance:

- Python/uv and Node/package-script fixtures produce different evidence-backed profiles and verification commands.
- Removing or changing an input manifest changes the profile deterministically; an absent command is not claimed.
- Malicious hooks, package scripts, Make targets, and symlink escapes are never executed/followed.
- Repeated profiling of identical content produces identical canonical hashes.

### Milestone 3: Adaptive plan, permission, and evidence vertical slice

Use validated FleetPlan artifacts in the fake workflow, extract PermissionBroker, remove runtime host paths, add sandbox capabilities, assemble EvidenceBundle, and run CompletionGate.

Acceptance:

- Direct, single-Engineer, and Engineer+Verifier fake plans create only their planned instances and produce honest assurance outcomes.
- A verifier mutation request is denied before filesystem mutation; the verifier workspace fingerprint stays unchanged.
- Every executed/denied action has canonical intent, permission decision, and event evidence.
- Fake command PASS remains simulated and cannot set `verified_complete=true`.
- Existing approval reconstruction, repair, rejection, guarded apply, and redaction behavior remains green.

### Milestone 4: Contract matrix and final proof

Add per-adapter contracts, CLI/integration/E2E assertions, documentation snapshots, final security/import audit, package build, and exact outcomes.

Acceptance:

- Every concrete Phase 1 adapter has a contract test or a documented reason that an existing shared contract covers it.
- Full offline quality suite and schema drift check pass with network, live providers, and Docker unused.
- Manual init/run/inspect/apply demonstrates repository profile, FleetPlan, EvidenceBundle, and explicit simulated-evidence warning.
- README and this plan contain exact results and remaining Phase 2-7 limitations.

## Detailed implementation steps

1. Add the North-Star ADR and update `README.md`, `docs/PRODUCT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_MODEL.md`, `docs/CONFIG_AND_SCHEMAS.md`, and `docs/IMPLEMENTATION_ROADMAP.md` with normative positioning and the Phase 1.5 gate.
2. Add repository profile, project knowledge, dynamic role/workflow identifier, FleetPlan, sandbox capability, evidence/completion, and FleetPatch models under `src/agent_fleet/domain/`; register generated schemas.
3. Add pure validation modules for FleetPlan, CompletionGate, and FleetPatch protected paths/base hash.
4. Add `RepositoryProfiler` and `PermissionBroker` ports; expand `SandboxProvider` capabilities; update `RuntimeAdapter` inputs so no host path is exposed.
5. Implement `StaticRepositoryProfiler` with bounded, no-execution parsing and evidence provenance for common manifests/lockfiles/CI signals.
6. Inject profiling into `ProjectService` and repository-specific proposal generation into `YamlConfigurationAdapter`; persist profile and knowledge artifacts.
7. Implement `BaselinePermissionBroker`, inject it into `ToolGateway`, persist decision events, and express verifier mutation as a denied typed intent.
8. Make fake CoS output a bounded scope/strategy record; construct, validate, and persist FleetPlan in the application; adapt `WorkflowEngine` to the three supported offline strategies while retaining bounded repair and approval reconstruction.
9. Capture authoritative command evidence, verifier identity, patch identity, risks, and proof gaps; assemble/persist EvidenceBundle and evaluate CompletionGate before presentation.
10. Add unit/security/contract/integration/E2E tests and fixture repositories; update previous tests for new honest artifact counts and assurance fields.
11. Generate schemas, run focused suites, then run sync, formatting, lint, strict mypy, full pytest, schema check, build, manual CLI demo, and security/import/path audits.
12. Update this plan's Progress, Discoveries, Decision Log, and Outcomes with exact evidence and no overstated claims.

## Validation plan

Focused commands:

```bash
uv run pytest -q tests/unit/test_repository_profile.py
uv run pytest -q tests/unit/test_fleet_plan.py
uv run pytest -q tests/unit/test_permission_broker.py
uv run pytest -q tests/unit/test_evidence_gate.py
uv run pytest -q tests/unit/test_fleet_patch.py
uv run pytest -q tests/contract
uv run pytest -q tests/integration
uv run pytest -q tests/e2e
uv run python -m agent_fleet.schemas.generate --check
```

Security/negative cases include malformed and oversized manifests/configuration; conflicting lockfiles; missing scripts; symlink, traversal, case-folded, and filesystem-identity escapes; malicious Git hooks/includes/configured executables/promisor lazy-fetch behavior/package lifecycle/Make content; FleetPlan cycles, missing dependencies, duplicate workspace writers, direct side effects, and unavailable roles; runtime host-path leakage; verifier mutation and contradictory PASS semantics; default deny; approval hash mismatch; fake evidence strength escalation; missing/foreign/wrong-kind/corrupt/hash-mismatched ConfigSnapshot and TaskSpec artifacts; stale patch/config evidence; multi-criterion mapping gaps; status-bundle corruption; protected FleetPatch paths; base hash conflicts; dirty/diverged apply; and secret sentinel persistence.

Final commands:

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python -m agent_fleet.schemas.generate --check
uv build
```

The manual demo will use generated temporary Python and Node Git repositories, an external temporary `AGENT_FLEET_HOME`, and fake runtime/sandbox only. No detected command or project code will execute during init. The code-change canary's applied behavior may be independently tested by the demo harness after explicit apply; that external assertion must not be recorded as FakeSandbox evidence.

## Rollback and recovery

Repository profiling and plan/evidence generation write only content-addressed state artifacts until the already-confirmed `.fleet/` init application or explicit patch apply boundary. Profile failure must leave `.fleet/` and project state unmodified where possible; if project registration exists before a later init failure, rerun remains idempotent and no false profile hash is stored.

New optional JSON fields default safely when reopening Phase 0/1 rows. If migration `0002` is introduced, it must be transactional, forward-only, idempotent, and tested from both empty and migration-0001 databases. Never edit an already-applied migration.

ConfigSnapshot, TaskSpec, FleetPlan, and EvidenceBundle are immutable content-addressed artifacts. Resume uses the persisted plan identity; it must not silently regenerate a different topology or configuration/task contract. Permission decisions and grant consumption preserve existing transaction/idempotency behavior. A process interruption before intent completion leaves a reserved intent for explicit recovery rather than blind duplicate execution.

Candidate/verifier worktrees and fake sandbox leases retain the existing idempotent cleanup rules. Only Fleet-owned resources beneath the state root may be removed. No rollback path resets, cleans, stashes, or overwrites the user's target checkout. FleetPatch operational rollback is outside this phase.

## Progress

- [x] (2026-09-04 00:12 PDT) User confirmed the North-Star alignment direction and the six product differentiators.
- [x] (2026-09-04 00:12 PDT) Re-read repository instructions, ExecPlan rules, roadmap, current Git state, and the original product discussion; inspected current implementation gaps.
- [x] (2026-09-04 00:12 PDT) Created this living ExecPlan before substantial implementation.
- [x] (2026-09-04 01:06 PDT) Completed Milestone 1: normative positioning, strict contracts, validators, ADR, and generated schemas are implemented; focused domain/schema tests pass.
- [x] (2026-09-04 01:06 PDT) Completed Milestone 2: bounded static profiling drives preview/config/knowledge artifacts; profiler, config, and CLI preview tests pass without project execution or state writes.
- [x] (2026-09-04 04:12 PDT) Completed Milestone 3: three executable offline FleetPlan topologies, injected PermissionBroker, logical-only runtime input, fake sandbox capability/strength semantics, exact ConfigSnapshot/TaskSpec binding, EvidenceBundle/CompletionGate, verifier-integrity checks, and evidence-expanded status are implemented.
- [x] (2026-09-04 04:12 PDT) Ran dependency sync, formatting, lint, strict mypy, schema drift, all four test layers, the combined suite, package build/archive inspection, repository scans, and a disposable manual Python/Node init/run/inspect/apply demonstration.
- [x] (2026-09-04 04:40 PDT) A read-only adversarial review found six blockers: pre-rejection secret persistence, one-way state/repository separation, incomplete status binding checks, post-read configuration limits/special files, missing apply-time ConfigSnapshot validation, and case-sensitive protected scopes. All six were reproduced or covered by permanent regressions, fixed fail-closed, and the complete local suite was rerun.
- [x] (2026-09-04 05:07 PDT) A follow-up review found that recursive secret handling covered mapping values but not arbitrary mapping keys. Secret detection/redaction now covers both keys and values, the focused 21-test regression passed, and every local quality/test gate was rerun on the repaired candidate.
- [x] (2026-09-04 05:24 PDT) A second read-only review rejected the candidate for case-sensitive FleetPlan writer overlap, incoherent sandbox descriptors/documented requirements overclaim, weak FleetPatch ID/path/secret constraints, ambiguous bootstrap hash labels, and bootstrap secret rejection after generated configuration writes. Each issue now has a permanent regression or narrowed contract, and all repair-focused tests pass.
- [x] (2026-09-04 05:42 PDT) Repair-focused adversarial review found FleetPatch secret scanning was limited to change content. Validation now rejects registered secrets recursively across the full serialized proposal, including rationale and paths, without echoing the sentinel.
- [x] (2026-09-04 05:55 PDT) Contract review found generic FleetPlan ID types, missing escaping-path regressions, schema/semantic-validator ambiguity, and an imprecisely named ProjectKnowledge source hash; security review also found secret-bearing raw/canonical paths and adapter option values plus an unverified profiler-supplied hash. Dedicated IDs, representable wire-schema constraints, mandatory semantic-validation documentation, precise backward-compatible hash naming/binding, and pre-inspection/pre-persistence secret guards are now implemented with regressions.
- [x] (2026-09-04 06:18 PDT) Extended stable prefix validation from FleetPlan/FleetPatch to every typed persistent/public identity field and added the raw FleetPatch pre-parse secret boundary. A narrow read-only audit then found and verified repairs for non-plain Mapping traversal and the remaining ResourceLease/report ID gaps. Regenerated schemas and reran all four layers: unit 185, contract 17, integration 92, E2E 3, combined 297.
- [x] (2026-09-04 06:27 PDT) Re-ran dependency sync, format check, lint, strict mypy, schema drift, package build/archive inspection, diff hygiene, provider/Docker boundary scan, machine-path/temp-identifier scan, and credential-shape scan on the final local candidate; all passed.
- [x] (2026-09-04 06:49 PDT) Fresh acceptance review rejected candidate `c1f7792...` despite 297 passing tests: a repository-local Git driver name could enter secured argv, malformed secret-bearing YAML retained the parser exception, and a canonical secret-named non-Git path entered the repository error. The same review noted recursive raw FleetPatch depth was unbounded. All four findings are now repaired with focused regressions; the prior candidate and its verifier result remain recorded rather than overwritten.
- [x] (2026-09-04 07:06 PDT) Re-ran the repaired layers independently: unit 188, contract 17, integration 95, E2E 3; the combined offline suite passed 303 tests. Final non-test gates and fresh acceptance review remain pending for the new candidate identity.
- [x] (2026-09-04 07:09 PDT) The repaired candidate passed dependency sync, format, lint, strict mypy, schema drift, build, archive inspection, diff hygiene, and all negative implementation/path/credential scans. It is ready for a brand-new independent verifier.
- [x] (2026-09-04 07:25 PDT) A second fresh acceptance review rejected candidate `937e7042...` on one additional contract gap: FakeSandbox applied `max_output_bytes` as a character limit, so multibyte Unicode could exceed the documented byte ceiling without reporting truncation. All other gates and the newest manual adversarial probes passed. The provider now truncates encoded UTF-8 without returning a partial code point, and a permanent emoji regression covers both streams and the truncation flag.
- [x] (2026-09-04 07:30 PDT) Re-ran the repaired layers independently: unit 188, contract 18, integration 95, E2E 3; the combined offline suite passed 304 tests. Dependency sync, format, lint, strict mypy, schema drift, package build/archive inspection, and diff hygiene also passed on the repaired local candidate.
- [x] (2026-09-04 07:56 PDT) Completed Milestone 4 after a third fresh, read-only acceptance review returned PASS on frozen candidate `8be5e049...`: unit 188, contract 18, integration 95, E2E 3, combined 304, all static/build/archive gates, and every required UTF-8/Git/YAML/FleetPatch adversarial probe passed; start and end identities matched exactly.

## Discoveries

- Observation: At plan start, `FakeRuntimeAdapter` received `verification_workspace_path` and directly wrote a mutation sentinel for the verifier-mutation scenario.
  Evidence: `WorkflowEngine._verify` adds the absolute path to runtime input, and `FakeRuntimeAdapter.invoke` calls `Path.write_text` when requested.
  Consequence: This was not merely a test detail; it proved a Harness could bypass ToolGateway when given a host path.
  Resolution: Runtime input now contains logical identifiers only; verifier mutation is a typed intent denied by PermissionBroker before any filesystem write, with an unchanged-workspace assertion.
- Observation: At plan start, repository initialization generated static files independent of repository content and only created, rather than executed through the workflow, a canary fixture.
  Evidence: `ProjectService.preview/initialize` calls `config.default_files(repository_name)` and `repository.create_canary_fixture`; `default_fleet_files` hard-codes Python pytest and three roles.
  Consequence: Bootstrap needed static repository profiling and evidence-bound proposals; the canary must remain labeled an offline orchestration fixture until a real sandbox executes it.
  Resolution: Bounded static profiling now drives preview, ProjectKnowledge, and repository-specific verification proposals without executing repository code; canary execution remains explicitly deferred.
- Observation: At plan start, `AgentRole`, FleetSpec agent keys, workflow ID, tool actions, and workflow branches were closed literals.
  Evidence: `domain/models.py`, `domain/config.py`, and `application/workflow.py` encode exactly CoS, Engineer, Verifier, and `code-change`.
  Consequence: Identity literals needed validated extensible IDs and a plan artifact before model integration; security decisions must remain based on capabilities and trusted context, not arbitrary role names alone.
  Resolution: Security-irrelevant role/workflow/action identifiers are extensible and per-run FleetPlans validate the executable subset; built-in fake role behavior remains deliberately bounded.
- Observation: At plan start, content-addressed artifacts existed, but `TaskSpec.required_evidence` and agent-reported evidence IDs did not gate claims.
  Evidence: verifier PASS/INCONCLUSIVE both reach presentation, and the fake command transcript is not distinguished from executed proof.
  Consequence: Evidence needed assembly from authoritative control-plane records with explicit simulated/observed/independently-verified strength.
  Resolution: EvidenceAssembler and CompletionGate now bind authoritative ConfigSnapshot, TaskSpec, plan, patch, command, and verifier records; fake PASS stays simulated and cannot verify completion.
- Observation: an initial profiler contribution placed canonical data models in the port module, which would invert the intended dependency direction.
  Evidence: the profiler adapter imported `RepositoryProfile` and `ProjectKnowledge` from `ports.repository_profile` while other domain contracts lived under `domain/`.
  Consequence: moved the models into `domain.repository_profile`; the port now exposes only the profiling protocol and the adapter depends inward.
- Observation: repository-derived command candidates and the offline orchestration command are separate concepts in Phase 1.5.
  Evidence: static profiling can propose project-specific commands, while FakeRuntime still records one fixed fake canary command and never executes the generated verification profile.
  Consequence: generated configuration contains only evidence-backed detected candidates; the fake workflow is labeled simulated and this remaining integration gap stays explicit until a real sandbox/tool surface exists.
- Observation: Git status text does not fingerprint the contents of untracked `.fleet/` configuration files.
  Evidence: an initialized repository can keep the same `?? .fleet/` porcelain entry after a referenced role or verification file changes.
  Consequence: Project and run creation now bind an exact bounded ConfigSnapshot artifact/hash and reject referenced-content drift before creating a run.
- Observation: lexical and `resolve()` containment alone can accept alternate-case spellings of an existing ancestor on a case-insensitive filesystem.
  Evidence: APFS regression fixtures showed that path spelling can differ while referring to the same inode.
  Consequence: state-root and executable trust checks now combine lexical/canonical containment with ancestor device/inode identity and fail closed when identity cannot be established.
- Observation: storing an EvidenceBundle ID/hash without expanding it in status leaves users unable to audit the basis of completion claims.
  Evidence: the original status result exposed assurance fields and artifact IDs but not changed paths, commands, criterion results, verifier findings, risks, or proof gaps.
  Consequence: status now verifies bundle metadata/content identity and returns a bounded evidence summary; corruption or foreign binding is an integrity error.
- Observation: hardened Git environment variables alone do not neutralize repository-local includes, hook commands, configured executable drivers, or lazy object fetch helpers.
  Evidence: permanent regressions exercise local `include*`, `hook.*`, executable driver, promisor, alternate PATH, fsmonitor, and case-folded containment attacks.
  Consequence: the adapter probes and rejects dangerous local configuration, pins a trusted absolute Git executable, disables lazy fetching and configured execution surfaces, and retains the documented same-user race/output/process-group limitations.
- Observation: checking a runtime action for registered secrets only at the final write boundary is too late when the canonical ToolIntent, approval, or TaskSpec has already been serialized.
  Evidence: adversarial review reproduced raw sentinels in SQLite WAL through an Engineer write intent and CoS `normalized_goal` output.
  Consequence: the workflow recursively rejects registered secrets in every role output, and ToolGateway independently repeats that check before intent lookup, hashing, events, approvals, or persistence.
- Observation: recursively scanning only mapping values still permits a registered secret to become a serialized parameter key.
  Evidence: a follow-up adversarial regression placed a sentinel in an arbitrary ToolIntent parameter key and checked state files plus the SQLite WAL.
  Consequence: shared recursive detection and redaction now cover mapping keys and values before any gateway or workflow persistence boundary.
- Observation: state/repository separation must be symmetric, and configuration identity must remain an apply-time invariant.
  Evidence: initialization previously accepted a repository beneath the Fleet artifact root, and a changed untracked role prompt preserved the same porcelain fingerprint through patch apply.
  Consequence: initialization rejects containment in either direction, and apply reloads bounded configuration and compares the exact Run-bound ConfigSnapshot hash before touching the target.
- Observation: a nominal file byte limit does not bound I/O when code calls `read_bytes()` first, and `fleet status` cannot claim integrity after checking only the EvidenceBundle's outer artifact hash.
  Evidence: the first adversarial review identified oversized/special-file blocking and demonstrated a Run/config hash mismatch accepted by status.
  Consequence: configuration reads now preflight regular-file identity/size, use bounded descriptor reads with post-read stability checks, and status compares every Run/bundle base/config/task/plan/patch/command/verifier/assurance binding.
- Observation: validated individual logical paths can still alias one another on case-insensitive filesystems, while a permissive opaque ID type weakens a versioned-change contract.
  Evidence: the second review constructed parallel writer scopes `SRC`/`src/api`, FleetPatch paths differing only by case, and FleetPatch/Project/rollback IDs with unrelated prefixes.
  Consequence: FleetPlan ancestry and FleetPatch uniqueness are component-wise case-folded; FleetPatch uses dedicated ID types and requires registered-secret scanning across the complete serialized proposal.
- Observation: provider-declared capability fields need internal coherence before they can participate in sandbox selection.
  Evidence: a `provider=fake` descriptor could previously claim isolated security, enforced isolation, unrestricted networking, and resource limits while executing no code.
  Consequence: the capability model rejects contradictory combinations, ProjectService and WorkflowEngine require the exact Phase 1.5 fake descriptor, and documentation defers the not-yet-implemented per-plan requirements matcher to Phase 3.
- Observation: semantic hashes and serialized artifact hashes are different evidence identities, and bootstrap rejection after staging is not a no-write guarantee.
  Evidence: the prior `repository_profile_sha256` output differed from the persisted profile artifact SHA; a registered secret in a package script key reached staged and target verification YAML before ConfigSnapshot rejection.
  Consequence: init exposes explicitly named semantic/artifact hashes, and profile plus generated configuration are recursively secret-checked before preview output, migration, artifact, staging, or target writes.
- Observation: an adapter-returned digest is evidence only after the control plane recomputes it, and raw/canonical paths or adapter option strings can leak secrets before a later output guard.
  Evidence: an injected profiler returned a valid but false 64-hex source hash; separate repros placed registered sentinels in a raw invalid path, canonical path behind a safe alias, and unsupported adapter names.
  Consequence: ProjectService independently hashes RepositoryProfile, uses the precise backward-compatible `source_profile_sha256` field, and scans raw inputs plus canonical RepositoryInfo before exceptions or writes; WorkflowEngine applies the same pre-run option/path guard.
- Observation: a generic syntactically valid opaque ID allows one entity type to impersonate another at a schema boundary, even when the ID generator itself uses the correct prefix.
  Evidence: before the final contract repair, Run, TaskSpec, ToolIntent, CommandEvidence, and EvidenceBundle accepted values such as an `art_` ID in a project field or a `task_` ID in a run field.
  Consequence: persistent and public identity fields now use centralized prefix-specific Pydantic types, generated wire schemas expose those patterns, and only heterogeneous event causation retains the generic opaque-ID grammar.
- Observation: scanning only an already-parsed FleetPatch cannot prevent Pydantic from including an untrusted registered secret in its raw validation error.
  Evidence: a malformed raw proposal can fail path or ID parsing before `validate_fleet_patch` receives a typed object.
  Consequence: `parse_and_validate_fleet_patch` scans the raw object before schema parsing, normalizes schema errors, and the typed validator independently repeats whole-proposal secret scanning.
- Observation: neutralizing repository-local Git drivers by reflecting their names into command-scoped `-c` arguments prevents execution but can disclose an attacker-controlled registered secret through the process list.
  Evidence: the fresh acceptance review configured `filter.<sentinel>.clean` and observed the sentinel in a secured Git argv even though the driver did not execute.
  Consequence: Phase 1.5 now rejects every discovered repository-local executable integration key generically and never copies its name into a later argv; filter/diff support is intentionally deferred to a shadow-metadata design.
- Observation: redacting only at CLI presentation is insufficient when parser or repository-discovery exceptions retain untrusted content in `message`, `__cause__`, `__context__`, or formatted traceback.
  Evidence: malformed secret-bearing YAML retained the PyYAML error, and a safe alias to a secret-named non-Git directory exposed the canonical target before RepositoryInfo existed.
  Consequence: the Redactor is injected into the configuration adapter and scans all loaded/generated bytes before parse/write/snapshot; Git discovery failures discard unresolved paths and subprocess exceptions before raising a generic error.
- Observation: a recursive plain-JSON shape check is itself an availability boundary.
  Evidence: a roughly 2,000-level built-in dict/list FleetPatch proposal raised a bare `RecursionError` before typed validation.
  Consequence: raw FleetPatch validation is iterative, rejects cycles, caps depth at 64 and visited nodes at 10,000, and never descends into object subclasses.

## Decision Log

- Decision: Insert an explicit Phase 1.5 before provider and Docker work.
  Rationale: Correcting the core product abstractions now prevents real harness integration from freezing a fixed three-agent wrapper architecture.
  Alternatives: Proceed directly to PydanticAI and refactor later; rejected because runtime/tool/role coupling would become more expensive and security-sensitive.
  Date: 2026-09-04
- Decision: Deliver real offline behavior for repository profiling, plan artifacts, permission separation, and evidence gating; use contract/schema foundations only for later parallel scheduling and FleetPatch operations.
  Rationale: This makes the alignment observable without violating ordered roadmap boundaries or creating placeholder providers.
  Alternatives: Implement all Phase 4/6 behavior early, or add unused interfaces only; both produce scope/order problems.
  Date: 2026-09-04
- Decision: Keep operational completion and assurance verdict separate.
  Rationale: A user may explicitly apply a patch with known proof gaps, but the system must never translate that lifecycle fact into verified completion.
  Alternatives: Treat patch apply as proof or forbid all inconclusive review; both lose important semantics.
  Date: 2026-09-04
- Decision: Runtime adapters receive no host filesystem path or sandbox handle.
  Rationale: Logical resource identifiers preserve ToolGateway mediation and make Harness bypass structurally harder.
  Alternatives: Rely on role prompts not to use the path; rejected because prompts are not security boundaries.
  Date: 2026-09-04
- Decision: Keep the Phase 1.5 FleetPatch allow-list intentionally smaller than the eventual organization surface.
  Rationale: the schema foundation permits agent/workflow and selected project knowledge files only; `.fleet/skills/**` remains a Phase 6 review and rollback concern.
  Alternatives: permit skill mutation before operational diff/apply/rollback exists; rejected because it expands self-modification risk without a complete user review loop.
  Date: 2026-09-04
- Decision: Bind the exact bytes of every referenced `.fleet/` configuration file at Project, Run, TaskSpec, and EvidenceBundle boundaries.
  Rationale: Git status and a parsed top-level FleetSpec do not detect or preserve the exact role/workflow/project instructions that governed a run.
  Alternatives: bind only the top-level YAML or repository status text; rejected because both permit silent referenced-content drift.
  Date: 2026-09-04
- Decision: Treat filesystem object identity as part of containment on platforms where case or symlink spellings can alias one object.
  Rationale: lexical and canonical string prefixes alone are not a sufficient trust boundary on case-insensitive filesystems.
  Alternatives: normalize case or rely only on `resolve()`; rejected because neither proves the existing ancestor is outside repository/Fleet-controlled storage.
  Date: 2026-09-04
- Decision: Validate semantic ID kind at every persistent and public schema field, not only at ID generation.
  Rationale: stable prefixes are useful integrity domains only when deserialization rejects a correctly shaped ID from the wrong entity type.
  Alternatives: retain one generic `OpaqueId` everywhere and rely on application lookup; rejected because invalid cross-kind references would remain schema-valid and could reach persistence or evidence checks.
  Date: 2026-09-04
- Decision: Reject repository-local executable Git integration keys in Phase 1.5 instead of shadowing each discovered driver by name.
  Rationale: reflecting an attacker-controlled driver name into `git -c` prevents execution but can still disclose secret material in child argv; generic rejection has the smaller auditable surface.
  Alternatives: inject Redactor into Git and selectively shadow safe-looking names; rejected because it preserves an unnecessary dynamic argv surface and still relies on name classification.
  Date: 2026-09-04
- Decision: Make secret rejection an invariant of the configuration adapter, not only ProjectService and CLI presentation.
  Rationale: `.fleet` files are reloaded during run and apply, and parser exceptions occur before application-level post-processing can sanitize them.
  Alternatives: catch/redact only in WorkflowEngine or CLI; rejected because direct adapter callers and exception chains would retain the original value.
  Date: 2026-09-04

## Outcomes

The implementation now includes canonical repository/profile/knowledge contracts, a bounded static profiler, repository-specific configuration proposals, no-write JSON preview with unified diff, exact ConfigSnapshot and TaskSpec artifact binding, extensible role/workflow/action identifiers, FleetPlan validation and three executable offline topologies, an injected PermissionBroker, explicit fake sandbox capabilities, authoritative command evidence, verifier-mutation/contradictory-verdict defenses, evidence-expanded status, CompletionGate, EvidenceBundle persistence, filesystem-identity/Git execution hardening, and the protected FleetPatch schema foundation.

Fresh local validation on Python 3.14.6 and Git 2.50.1 used `uv` 0.12.9, Ruff 0.16.6, mypy 1.20.2, and pytest 9.1.1. `uv sync --all-extras` resolved 29 and checked 28 packages. Formatting across 107 files, lint, strict type checking across 91 source files, and schema drift passed. After the UTF-8 output-bound repair, local layer results were unit `188 passed in 2.51s`, contract `18 passed in 2.51s`, integration `95 passed in 84.96s`, and offline E2E `3 passed in 8.87s`; the combined suite reported `304 passed in 94.24s`. `uv build` produced both sdist and wheel; archive inspection confirmed the CLI, migration, and new schemas. `git diff --check`, provider/Docker implementation scan, machine-path/temp-identifier scan, and credential-pattern scan passed on the repaired candidate.

A third fresh, read-only verifier independently accepted frozen candidate `8be5e049a0af0220202b2ca6472e316718a436ee9e3f00a23f7640f2e0f03e21`, with the same composite identity at review start and end. Its exact results were unit `188 passed in 1.41s`, contract `18 passed in 1.52s`, integration `95 passed in 85.02s`, offline E2E `3 passed in 8.41s`, and combined `304 passed in 99.23s`; dependency, formatting, lint, strict typing, schema, build/archive, diff, implementation/path/credential scans, and all required UTF-8/Git/YAML/FleetPatch hand attacks passed. A prior narrow independent ID/FleetPatch audit additionally passed 127 focused tests and adversarial raw-object checks.

The disposable manual demonstration profiled separate Python and Node repositories with no preview writes, reported a healthy doctor result, initialized an exact configuration snapshot, and completed the fake Engineer+Verifier flow at `READY_FOR_REVIEW`. It persisted 48 events and 12 run artifacts, exposed changed paths/commands/verdicts/risks/proof gaps in status, and correctly reported `verified_complete=false` with `PROOF_GAPS_PRESENT` and `SIMULATED_EVIDENCE_ONLY`. The canonical patch SHA-256 was `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`; explicit apply changed only `src/canary_calc/core.py`, after which independent behavior assertions and `git diff --check` passed.

Remaining limitations are product boundaries rather than hidden proof claims: FakeSandbox executes no code and provides no isolation; multi-criterion scripted tasks remain inconclusive; parallel/specialist scheduling, real project commands, provider/BYOK, Docker, complete permission persistence/explain/revoke, persistent CoS chat, and operational FleetPatch diff/apply/rollback remain Phase 2-6 work. Milestone 4 is complete for the offline Phase 0/1/1.5 boundary; none of those later capabilities is claimed by this acceptance result.
