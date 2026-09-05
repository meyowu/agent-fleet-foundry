# Implementation roadmap — Agent Fleet

## How to execute this roadmap

Implement phases in order. Every phase must leave a runnable, tested repository and produce an updated ExecPlan outcome. Do not begin a later phase by creating empty placeholder abstractions across the whole system. Add only the contracts required by the current vertical slice, while preserving the specified architectural boundaries.

Current boundary as of 2026-09-05: Phase 0–6 is implemented and locally accepted. Checkpoints before Phase 6 extend through `a46b68800fb9725274db869f8c360b97a70c24ef` on `codex/mvp-completion`; remote main remains `c700de1`. E6 records1973 default passes15 explicit skips and fourteen separately enabled real-Docker passes, with82 schemas and migration8. Whole-phase metadata is6 after the successful behavioral freeze; metadata/package/checkpoint refresh is recorded separately in the evolution plan. Phase 7 guide/hardening, fresh-user/Linux platform release proof, live-provider acceptance and the owner license decision remain open. Local acceptance is not a complete release or final GitHub merge.

For each phase:

1. create or update the active ExecPlan;
2. inspect existing code and tests;
3. implement the smallest end-to-end behavior;
4. add focused, negative, and persistence/recovery tests;
5. run formatting, lint, type checking, and full tests;
6. update README and specs to distinguish implemented from roadmap;
7. record known limitations and the exact next phase.

## Phase 0 — Repository foundation and executable skeleton

### Goal

Create a high-quality Python project that can be installed and whose CLI, domain types, configuration loading, and deterministic test infrastructure are real—not placeholders.

### Deliverables

- `pyproject.toml` with Python support range, package metadata, CLI entry point `fleet`, dev/test dependencies, Ruff, mypy, pytest, and coverage configuration.
- `src/agent_fleet` package using the architecture layout.
- `fleet version` and `fleet doctor` with real behavior.
- Project-owned protocols for clock, ID generation, state store, artifact store, runtime, sandbox, repository, secret store, and event sink, but only methods needed by Phase 0/1.
- Core Pydantic models:
  - IDs;
  - FleetSpec subset;
  - Project;
  - Run and states;
  - FleetEvent;
  - Artifact metadata;
  - basic errors.
- Safe YAML loader for the Phase 0 FleetSpec subset.
- JSON Schema generation command/test.
- In-memory fakes for nondeterministic ports.
- SQLite database bootstrap and migration `0001` for the Phase 1 records.
- `README.md`, contributor setup, architecture summary, security limitations.
- CI workflow only if appropriate and fully runnable without secrets/network beyond dependency installation.

### `fleet doctor` checks

At Phase 0:

- Python/package version;
- Git executable/version and whether current path is in a repository;
- state/config directory writability;
- SQLite open/migration status;
- Docker presence/version as optional, not required for Phase 0 tests;
- configured provider credential reference existence without revealing value;
- effective warnings for missing future components.

It must support human output and `--json`.

### Acceptance criteria

```bash
uv sync --all-extras
uv run fleet version
uv run fleet doctor --json
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
```

All succeed in a clean environment without a model API key or Docker daemon. `doctor` may report unavailable optional capabilities but exits according to documented severity.

No command claims multi-agent execution yet.

## Phase 1 — Deterministic vertical slice with fake adapters

### Goal

Prove the control-plane workflow, durable events, artifacts, approval pause/resume, and candidate-patch lifecycle without a real model or Docker.

### User-visible flow

```bash
fleet init /path/to/fixture --runtime fake --sandbox fake --yes
fleet run "Fix the canary behavior" --runtime fake --sandbox fake
fleet status <run-id>
fleet artifacts <run-id>
fleet patch show <run-id>
```

### Deliverables

- Project registration and stable local project ID.
- Minimal `.fleet/` proposal generation and apply behavior.
- Deterministic `FakeRuntimeAdapter` with scripted role outputs.
- `FakeSandboxProvider` that records canonical executions and returns fixture outputs.
- Explicit code-change workflow state machine:
  - intake;
  - scoping;
  - workspace preparation;
  - implementation;
  - verification;
  - presentation;
  - ready for review;
  - optional apply in fixture repository.
- Fake CoS, Engineer, and Verifier invocations use the same application path intended for real adapters.
- SQLite persistence for projects, runs, tasks, agent instances, events, artifacts, and resource leases.
- Local content-addressed ArtifactStore.
- Generated Git fixture repository for tests.
- Repository adapter using structured Git subprocess calls.
- Candidate worktree creation, canonical patch extraction, separate verification workspace, and cleanup.
- Apply guard checking target state before applying.
- Cancellation and explicit exact-run recovery for fake resources.
- `fleet status`, `fleet logs`, `fleet artifacts`, `fleet patch show`, and `fleet patch apply` as real commands.

### Approval scenario

Add a scripted fake tool intent that requires approval. The run must persist as paused. A separate CLI invocation resolves the request and resumes without duplicate execution.

Initial approval commands:

```bash
fleet approve <request-id> --once
fleet deny <request-id>
fleet resume <run-id>
```

Persistent always-allow comes in Phase 4, but the domain shape may be introduced now when necessary.

### Required tests

- complete successful run with ordered events and artifacts;
- verifier rejection and terminal rejected state;
- one bounded repair iteration;
- approval pause, process recreation, resolution, and resume;
- duplicate resume does not duplicate side effect/event;
- cancellation cleanup;
- crash-recovery simulation for leased worktree;
- patch hash verification;
- dirty/diverged target refuses apply;
- verifier changes discarded;
- JSON CLI envelope tests;
- migration from empty database;
- no API key/Docker/network dependency.

### Acceptance criteria

A clean subprocess-level E2E test installs/runs the CLI against a temporary Git fixture and verifies the resulting patch behavior. README clearly labels runtime and sandbox as fake in this phase.

## Phase 1.5 — North-Star alignment

### Goal

Correct the foundational abstractions around the six product differentiators before introducing a real model harness or execution sandbox. The result remains completely offline, but repository intelligence, adaptive planning, permission separation, sandbox capability claims, evidence assurance, and FleetPatch boundaries become real typed contracts with an observable vertical slice.

### Deliverables

- Normative product positioning and ADR: a local-first, BYOK Chief-of-Staff CLI for a project-specific agent organization, not a generic multi-agent framework.
- A deterministic `RepositoryProfiler` for common Python, Node, Go, Rust, Maven, Gradle, Make, and CI signals that never executes repository code.
- Content-addressed `RepositoryProfile` and factual `ProjectKnowledge` artifacts with provenance, confidence, ambiguities, an independently checked source-profile semantic hash, and distinct serialized artifact hashes.
- Exact content-addressed `ConfigSnapshot` and `TaskSpec` artifacts bound to Project/Run/EvidenceBundle, covering every referenced `.fleet/` file rather than only the top-level parsed FleetSpec.
- Repository-specific verification-command proposals; missing or ambiguous commands are not invented.
- Extensible validated RoleId/WorkflowId values instead of a security-irrelevant closed role roster.
- An immutable `FleetPlan` with nodes, dependencies, scopes, workspace ownership, budgets, concurrency, verification requirements, and deterministic validation.
- Offline scheduling for `direct`, `single_engineer`, and `engineer_verifier`, creating only planned AgentInstances. Parallel and specialist DAGs are representable but not executed in this phase.
- A separately injected project-owned `PermissionBroker`; ToolGateway retains canonicalization/execution and all unplanned actions default deny.
- Runtime invocations contain no host paths, sandbox handles, credentials, grants, or direct executor objects. Verifier mutation is expressed as a denied intent.
- Immutable `SandboxCapabilities` plus fail-closed provider capability matching. FakeSandbox explicitly declares no isolation, no code execution, and simulated evidence.
- Authoritative command/criterion/risk/proof-gap models, `EvidenceBundle`, and `CompletionGate`, with workflow completion distinct from verified completion.
- Evidence-aware `fleet run/status` output that exposes changed paths, command results, verdicts, risks, proof gaps, and deterministic completion reason codes while rejecting a corrupt bundle binding.
- Strict FleetPatch schema and protected-path/base-hash validation for the minimum `agents/**`, `workflows/**`, named project files, and `.fleet/README.md` set only; `.fleet/skills/**`, persistence, and operational commands remain Phase 6.
- Contract tests for every concrete Phase 1 adapter plus repository-profile, plan, permission, evidence, sandbox, and FleetPatch security tests.

### Required tests

- Python/uv and Node/package-script fixtures yield distinct deterministic profiles and exact evidence-backed candidate commands.
- Profiling does not execute malicious Git hooks, package scripts, Make targets, manifest payloads, or escaping symlinks.
- FleetPlan rejects cycles, unknown roles, excessive concurrency, conflicting writers, direct side effects, and unsupported assurance claims.
- Direct, single-Engineer, and Engineer+Verifier paths create only planned role instances and preserve bounded repair/approval behavior.
- Every runtime action has a canonical intent, PermissionDecision, and audit event; verifier writes are denied before mutation.
- Runtime payloads contain no absolute host path or sandbox handle.
- Fake command PASS remains simulated and cannot set `verified_complete=true`.
- Evidence requirements map to content-addressed authoritative artifacts and reject stale/tampered identities.
- Referenced configuration drift is rejected before run creation even when Git's untracked status text is unchanged; missing/foreign/corrupt TaskSpec and ConfigSnapshot bindings fail closed.
- Case-insensitive filesystem aliases cannot place Fleet state inside a repository or supply a repository-controlled host executable.
- FleetPatch rejects protected and escaping paths plus base-hash conflicts.
- Existing Phase 0/1 tests, migration data, patch guards, redaction, recovery, and subprocess E2E remain green.

### Acceptance criteria

`fleet init --json` exposes repository profile, Project Knowledge, sandbox capabilities, and artifact references. An offline run persists a validated FleetPlan and EvidenceBundle. The fake path may reach review, but reports `verified_complete=false` with a simulated-evidence proof gap. All formatting, lint, strict type checking, unit/contract/integration/E2E, schema-drift, and build checks pass without network, API keys, Docker, or project-code execution by FakeSandbox.

Phase 1.5 is a hard gate: Phase 2 and Phase 3 must not begin until these acceptance criteria pass.

## Phase 2 — BYOK provider configuration and PydanticAI runtime adapter

**Implementation status:** implementation present; the Phase 2 ExecPlan is authoritative for final acceptance evidence and must be complete before merge. The optional live-provider smoke was **not run** because no explicit test credential was supplied. Ordinary acceptance does not discover or reuse ambient credentials.

### Goal

Replace scripted role output with a real model/harness adapter while preserving deterministic tests and system-owned orchestration.

Prerequisite: Phase 1.5 is complete. The adapter consumes validated RepositoryProfile/ProjectKnowledge/TaskSpec/FleetPlan context, exposes only ToolGateway-backed tools, and never receives a host path, sandbox handle, credential value, grant, or alternate executor.

### Deliverables

- `PydanticAIRuntimeAdapter` implementing the project `RuntimeAdapter` port.
- Runtime capability declaration and preflight validation.
- Provider/model strings treated as opaque domain/configuration values, with an explicit live-adapter allowlist of `openai:<model>` and `openai-chat:<model>` and no fallback.
- Secret references:
  - `env:NAME` required;
  - reference selected by explicit user input and persisted only in Fleet-owned state;
  - OS keyring remains future work.
- Secret redactor registry.
- Typed PydanticAI outputs for:
  - `ScopeDecision`;
  - `ImplementationReport`;
  - `VerifierVerdict`.
- Project-owned prompt files for CoS, Engineer, and Verifier.
- Model-visible tools are wrappers around ToolGateway; no PydanticAI-native shell/filesystem bypass.
- Usage metadata mapping when available, without assuming every provider exposes price.
- Provider failures, invalid structured output, timeouts, and retry behavior mapped to typed errors.
- `fleet init` interactive/provider flags and credential preflight.
- Fail-closed reinitialization: differing generated `.fleet/` content is never merged or overwritten and fails before Project/artifact state mutation. The original reference-only update support applies only before organization admission; Phase 6 rejects all headed reinitialization, including reference-only changes. A protected setup change requires separate registration with old state preserved.
- `fleet run` exact registration matching and provider preflight; explicit mismatched overrides fail before Run creation.
- `fleet doctor` inspect-only credential status. A successfully emitted report uses `healthy`/required checks for readiness even when the command exit is zero.
- Optional manual live-model smoke test excluded from normal CI.

Phase 2's provider HTTPS request originates in the trusted control plane. Preview validates shape only and performs no credential read, state/repository write, provider construction, or network. Init resolves the selected reference before writes but makes no model request. A run resolves it before provider construction, registers dynamic redaction, and passes the value explicitly without mutating global environment state.

Every model-visible tool is a role/stage-bound wrapper around `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`. The complete deferred batch is schema-validated before execution. Authorized candidate writes then use a narrow Fleet-owned candidate-worktree primitive; fake commands and approval fixtures use `FakeSandboxProvider`. PydanticAI-native shell, filesystem, code execution, MCP, provider-hosted tools, and arbitrary network tools are not exposed. FakeSandbox still executes no code, so a real Verifier output cannot set `verified_complete=true`.

### Test strategy

- Use PydanticAI test/fake model facilities.
- Assert the adapter registers only expected tools.
- Assert structured outputs validate and provider-internal objects do not escape.
- Assert raw secret is absent from events, logs, exceptions, tool contexts, and worker configuration.
- Assert no live network/API call occurs in ordinary tests.
- Deny socket creation in ordinary tests and keep PydanticAI's live-model request guard disabled.
- Contract-test fake and PydanticAI adapters against common semantics.

### Acceptance criteria

Offline TestModel/FunctionModel contract, integration, and CLI tests must obtain strict CoS/Engineer/Verifier outputs through the real adapter code, exercise gateway/evidence/usage persistence, and prove no network, API key, or Docker dependency. Without a credential, diagnostics remain actionable and no Run is created. When an explicit disposable credential is supplied, the optional manual smoke may additionally demonstrate provider HTTPS; if it is not supplied, record **NOT RUN** rather than reusing ambient credentials or weakening the offline gate.

Do not add multiple real harnesses yet.

## Phase 3 — Real Docker sandbox and command/file ToolGateway

**Implementation status:** implementation present; the Phase 3 living ExecPlan is authoritative for the exact offline, real-Docker, manual-canary, independent-review, commit, PR, merge, and post-merge evidence. The optional live-provider smoke remains separately gated and is not required for the deterministic Phase 3 bootstrap acceptance path.

### Goal

Execute worker file changes and commands within an enforced Docker boundary while model credentials and Git control remain outside.

### Deliverables

- `DockerSandboxProvider` with:
  - non-root execution;
  - capability drop;
  - no-new-privileges;
  - read-only root filesystem where supported;
  - candidate-workspace bind mount only;
  - bounded temp/cache mounts;
  - no Docker socket/home/credential mounts;
  - network `none` default;
  - CPU/memory/PID/time/output limits;
  - labels and resource leases;
  - inspection and cleanup.
- Explicit `LocalUnsafeSandboxProvider`, gated by configuration/flag and warning. No silent fallback.
- ToolGateway implementations for bounded read/list/search/write/edit/delete/diff/command operations.
- Trusted-context identity injection.
- Canonical path resolver with symlink defense.
- Structured `CommandSpec` and no-shell executor.
- Environment allowlist and secret redaction.
- Output-size handling and command transcript artifacts.
- Docker `doctor` checks and clear remediation.
- Bootstrap canary uses Docker in the recommended path.
- Git/worktree lifecycle remains in the control plane.

### Honest network scope

Implement only:

- `none`;
- `approved-unrestricted` after explicit approval/policy.

Do not claim domain allowlisting until an enforcing egress proxy exists.

### Required tests

Unit/security tests do not require Docker. Add opt-in Docker integration tests that inspect effective:

- user ID;
- mounts;
- absent secret environment;
- disabled network in `none` mode;
- resource settings;
- capabilities/no-new-privileges;
- inability to read a host sentinel outside the mount;
- timeout and cleanup behavior;
- no local-unsafe fallback.

### Acceptance criteria

A manual canary with a real or fake runtime modifies and tests code inside Docker, produces a control-plane patch, and demonstrates that a provider secret and host sentinel are inaccessible from the worker.

## Phase 4 — PermissionBroker, approvals, and exact always-allow

**Status: accepted, 2026-09-05.** Final gates: default suite `1001 passed, 10 skipped in 431.79s` (nine opt-in Docker and one live-provider skip); unit `510/53.30s`, contract `281/4.47s`, marked integration `156 passed, 49 deselected/311.72s`, E2E `4/44.40s`; Ruff formatting/lint (165 files), mypy (141 source files), schema/diff checks; real Docker `9 passed in 42.32s` with zero managed-container residue; offline wheel/sdist inspection of 129 package files, 37 schemas, four migrations and three prompts each. These are local working-tree results, not a frozen Git commit or installed-user release proof.

Accepted hardening includes exact current-policy revalidation, reviewed init paths/revision, prepared→publish→completion audit, dormant always-rule activation, reset cutoff, source-rule receipts without fabricated approvals, permanent single-winner dispatch, exact Engineer/Verifier checkpoints and legacy once-agent restoration. Logical retries preserve original explanatory prose without relaxing execution-bearing identity checks. Safe prompts supported commands; Balanced and Autonomous Sandbox deliberately share the supported reviewed-command ceiling, without arbitrary command/network expansion. Aggregate usage/budgets across pauses and bounded conversation context were subsequently accepted under Phase 5; raw provider history is not persisted and no live provider was run. The deliverables below remain the contract for regression, not unfinished Phase 4 work.

### Goal

Implement the full three-state authorization system and user-controlled persistent scoped trust rules.

### Deliverables

- Canonical ToolIntent and resource types.
- Permission evaluation engine with:
  - `ALLOW`;
  - `DENY`;
  - `REQUIRE_APPROVAL`;
  - hard denies;
  - trust-mode defaults;
  - project/role/workflow/task intersection;
  - exact capability grants;
  - expiration, use count, revocation;
  - explanation/matched rules.
- Persistent user trust store outside repository with atomic validated writes.
- Approval request binds to intent hash.
- CLI:
  - `fleet approve --once`;
  - `fleet approve --run`;
  - `fleet approve --always --scope project`;
  - `fleet deny`;
  - `fleet permissions list`;
  - `fleet permissions explain`;
  - `fleet permissions revoke`;
  - `fleet permissions reset --project`.
- Safe/Balanced/Autonomous Sandbox trust modes.
- Audit events for decision, request, resolution, grant, consumption, and revocation.
- Resume semantics after approval.
- Protected action registry.

### Always-allow rules

Persistent allow must include canonical action/resource, project, role, sandbox conditions, and command/path/network conditions. No generic “all shell,” “all network,” “all files,” or “all projects” UI in the ordinary flow.

### Required security tests

Implement every relevant test listed in `docs/SECURITY_MODEL.md`, especially:

- command compound-injection mismatch;
- path/symlink escape;
- wrong project/run/stage;
- expired/exhausted/revoked grants;
- self-approval;
- repository config self-grant;
- protected action denial;
- changed intent after approval;
- secret redaction;
- isolated-only grant not matching local-unsafe.

### Acceptance criteria

A user can approve a test command once, for the run, or persist an exact project rule; inspect why it matched; revoke it; and observe that broader/different actions still prompt or fail.

## Phase 5 — Complete real adaptive CoS workflow and chat

### Goal

Deliver the core user experience with a persistent CoS interface and bounded specialist execution.

Acceptance status: the complete Phase 5 passed on 2026-09-05 and was committed/pushed as `a46b688`. M3 adds atomic conversation/Run registration, bounded summaries and references, shared resume ownership, event progress, exact approval controls and responsive cancellation. The proving surface is `tests/unit/test_chat_cli.py`, `tests/unit/test_conversation_models.py`, `tests/unit/test_conversation_state.py`, `tests/contract/test_conversation_store.py`, `tests/integration/test_conversations.py`, `tests/integration/test_conversation_safety.py`, `tests/e2e/test_persistent_chat_cli.py` and the separately gated `tests/docker/test_conversation_journey.py`. E5.3 and the persistent-chat plan retain exact full/focused/static results and failed attempts. Whole-phase metadata is 5; acceptance does not extend to Phase 6/7 or release prerequisites.

### Deliverables

- `fleet chat` line-oriented REPL with durable thread/run references.
- CoS turns user messages into validated TaskSpec drafts.
- Validated adaptive planning chooses the smallest supported team; direct, single-Engineer, Engineer+Verifier, parallel Engineer, and declared specialist DAG paths have explicit assurance and join semantics.
- The verified code-change workflow uses:
  - a fresh Engineer invocation per iteration;
  - separate candidate workspace;
  - actual patch extraction by control plane;
  - fresh Verifier context;
  - independent verification workspace;
  - at most configured repair iterations;
  - evidence mapping and final summary.
- CoS cannot directly use Engineer write/command tools.
- Verifier changes discarded and mutation reported.
- Compact event-driven progress UI.
- `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, `/exit`.
- Resume after CLI restart and approval pause.
- Budget enforcement and usage summary.
- `INCONCLUSIVE` handling and proof-gap presentation.
- Robust context selection: do not send entire repositories or raw histories by default.

### Required tests

- role tool isolation;
- CoS attempted direct write denied;
- Engineer output claim differs from actual patch; actual patch wins;
- Verifier starts from original goal and detects scripted defect;
- verifier mutation discarded;
- repair succeeds on second iteration;
- repair budget exhausted;
- cancellation from chat;
- restart/resume;
- context/artifact size limits;
- final summary contains exact evidence and limitations.

### Acceptance criteria

A user can initialize a small real repository, ask CoS for a code change, let the fleet work inside Docker, handle a permission request, receive independent verification, and review/apply the patch without manually managing agents.

## Phase 6 — FleetPatch: versioned organizational updates

Status: local behavioral acceptance passed on 2026-09-05:1973 default passes15 explicit skips, fourteen separately enabled real-Docker passes,57 focused compatibility tests and independent integration/delta PASS. The living plan is `.agent/plans/2026-09-05-versioned-fleet-evolution.md`. Normal offline CoS hashing/output, immutable proposals and semantic/text diffs, strict workflow/skill requirements, native whole-tree publication, exact admission/fencing, CLI recovery and current-head inverse rollback are connected. Native cut-point tests and fresh CLI process exits exercise recovery; the real-Docker journey proves newly mandatory integration evidence from Engineer and independent Verifier. This does not change protected FleetSpec, trust or credentials. Metadata6 and archive/checkpoint refresh follow the successful behavioral freeze. Linux, fresh-installed-user, live-provider and public-release gates remain separate. See ADR 0006 and E6 for exact limitations/results.

### Goal

Allow the user to ask CoS to change agent roles/workflows/skills while maintaining a protected policy boundary.

This phase turns the Phase 1.5 FleetPatch schema/path/base-hash validator into an operational, persisted workflow. It must reuse that contract rather than introduce an incompatible mutation format.

### Deliverables

- `FleetPatch` typed model and persistence.
- CoS produces semantic proposed changes and a textual patch under allowed `.fleet/` paths.
- Stage proposed files separately.
- Validate:
  - path boundary;
  - schema;
  - references;
  - runtime capabilities;
  - no protected setting mutation;
  - no secret value;
  - no trust-store/audit/state path.
- Human-readable semantic diff and unified diff.
- CLI:
  - `fleet fleet-patch list`;
  - `show`;
  - `diff`;
  - `apply`;
  - `rollback`;
  - `operation` and explicit `recover --owner-stopped`.
- Atomic application with before/after hashes and conflict detection.
- Rollback produces a new auditable operation rather than erasing history.
- Example: add required integration-test command for backend changes.

### Required tests

- valid role/workflow update;
- invalid schema;
- path traversal/symlink escape;
- attempt to alter trust/hard-deny/secret/audit policy;
- base hash conflict;
- atomic failure leaves original unchanged;
- rollback restores content and records history;
- model cannot directly apply its proposal.

### Acceptance criteria

A natural-language organizational request produces a reviewable FleetPatch; nothing changes until the user applies it; protected policy remains unchanged.

## Phase 7 — Hardening, packaging, documentation, and release candidate

Status on2026-09-05: implemented candidate under `.agent/plans/2026-09-05-release-candidate.md`, following accepted Phase6 checkpoint b42cdf9. Packaged assets/guide, fresh-install/upgrade/scale tests, security tooling and pinned CI now exist; focused installed wheel/sdist/public-Docker proof passed. Final frozen full/platform gates and GitHub merge remain pending. The owner-license and live-provider requirements below remain separate unperformed public-release gates, not waived acceptance.

### Goal

Turn the working MVP into an auditable OSS release candidate.

### Deliverables

- full E2E matrix on Linux/macOS where feasible; Windows limitations documented and tested where available;
- SQLite migration upgrade tests;
- orphaned Docker/worktree recovery;
- stable CLI error codes and JSON schemas;
- reproducible runner image build and versioning strategy;
- security checklist and adversarial test script;
- complete README quickstart and architecture diagrams;
- contribution guide and issue templates if useful;
- changelog/release process;
- generated configuration schemas;
- performance smoke tests for event/artifact scale;
- optional OpenTelemetry-compatible local instrumentation without mandatory external export;
- dependency review and lock strategy;
- explicit data handling/provider disclosure;
- license decision made by repository owner before public release.

### Release gate

- default test suite passes offline after dependencies are installed;
- optional Docker integration suite passes;
- manual live-provider canary recorded;
- all MVP success criteria in `PRODUCT_SPEC.md` demonstrated;
- all security release gates in `SECURITY_MODEL.md` met or clearly documented as blocking gaps;
- README distinguishes enforcement from guidance and isolated from unsafe modes;
- no placeholder commands, fake claims, plaintext secrets, or machine-specific paths;
- a fresh user can follow quickstart successfully.

## Deferred roadmap after MVP

Only after the core path is reliable:

- second harness adapter and conformance matrix;
- remote sandbox providers;
- enforcing domain egress proxy;
- GitHub App with draft-PR-only scoped permission;
- MCP adapter through ToolGateway;
- background daemon/scheduler;
- multiple concurrent repositories;
- cloud control plane;
- richer TUI/web UI;
- skill/plugin packaging;
- signed audit export;
- enterprise policy adapter such as OPA;
- multi-machine agent scheduling;
- evaluation datasets and automated regression scoring.
