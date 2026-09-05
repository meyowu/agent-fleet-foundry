# Phase 3 Docker Sandbox and Evidence-Bound Bootstrap

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

Add the first real code-execution boundary without allowing a model, runtime adapter, repository, or harness to choose or weaken that boundary. A user will be able to select an exact project sandbox, run reviewed verification commands through a bounded gateway, inspect Docker readiness, and bootstrap a repository only after a disposable canary has produced independently verifiable evidence.

A representative offline-provider flow is:

```bash
fleet doctor --path ./demo --sandbox docker --json
fleet init ./demo --runtime fake --sandbox docker --yes --json
fleet status <canary-run-id> --json
fleet artifacts <canary-run-id> --json
fleet patch show <canary-run-id>
```

`fleet init` must stage the proposed `.fleet/` tree, create a disposable canary repository in Fleet-owned state, run the normal CoS -> Engineer -> Verifier workflow with the fake runtime and real Docker execution, persist a `BootstrapReport`, and only then publish `.fleet/` into the target repository. Docker unavailability, image absence, security-inspection mismatch, canary failure, or cleanup failure must fail closed without executing on the host and without silently falling back to fake or local-unsafe.

Phase 3 continues to support the deterministic `fake` sandbox for ordinary tests and explicitly exposes `local-unsafe` for development diagnostics, but neither can claim isolated or independently verified execution. No live model-provider call is required for Phase 3 acceptance.

## Scope

### In scope

- Add strict, provider-neutral sandbox requirements, immutable capability snapshots, structured command specifications, sandbox inspection, lifecycle state, and bootstrap-report contracts.
- Persist the selected sandbox and security-relevant configuration on Project and Run aggregates while retaining backward compatibility for Phase 2 fake projects.
- Add an exact-name sandbox registry. A requested provider must either satisfy the reviewed requirements or return a typed failure; there is no fallback.
- Add `DockerSandboxProvider` using a trusted absolute Docker CLI, direct argv only, a locally present immutable image identity, non-root execution, capability removal, no-new-privileges, read-only root, `network=none`, bounded CPU/memory/PIDs/tmpfs/output/time, exact mounts, inspection before start, labels, and deterministic cleanup.
- Use one short-lived labeled container per command. Persist the logical sandbox lease and command-attempt event before Docker resource creation so recovery can reconcile rather than blindly replay an ambiguous command.
- Add an explicit `LocalUnsafeSandboxProvider` with a second high-risk opt-in gate, prominent warnings, honest `unsafe_host` evidence, and no ability to satisfy isolation requirements.
- Expand `ToolGateway` with bounded list/read/search/write/edit/delete/diff/command operations. Trusted control-plane context supplies run, task, agent, stage, workspace, command identity, and provider; model arguments never contain host paths, sandbox handles, grants, or Docker flags.
- Replace path-based authorization with a descriptor-relative secure workspace primitive for side-effecting file operations. Refuse unsupported platforms or unsafe path components rather than falling back to `Path.resolve()` authorization.
- Resolve command execution server-side from an immutable reviewed `VerificationProfile`; never accept shell strings or arbitrary model-selected host commands. Start with `network=none` commands only.
- Persist bounded, redacted command transcripts and effective sandbox inspection evidence. Classify fake execution as `simulated`, Docker Engineer execution as `observed`, and only a fresh verifier sandbox bound to the final patch as `independently_verified`.
- Refactor bootstrap ordering so disposable canary execution and `BootstrapReport` creation precede target `.fleet/` publication.
- Extend `fleet init`, `fleet run`, `fleet doctor`, `fleet version`, JSON/human presentation, schemas, package contents, docs, and test fixtures for the three sandbox names.
- Add ordinary offline tests using an injected Docker command runner and separately gated real-Docker integration/security tests. Ordinary tests must never discover or use Docker implicitly.
- Complete one fake-runtime real-Docker bootstrap canary that proves the code change, final patch, fresh verifier result, registered provider-secret non-injection, mount-external host-sentinel inaccessibility, effective restrictions, and complete cleanup.

### Out of scope

- PydanticAI changes, new live provider calls, provider-specific credentials, or network-dependent model tests.
- Persistent `allow for run`, `always allow`, revoke/explain policy management, repository-controlled grants, or broad trusted command lists. Those remain Phase 4.
- Chat UX, multi-Engineer scheduling, Researcher/Architect execution, parallel joins, or multi-node orchestration. Those remain Phase 5.
- Operational FleetPatch propose/diff/apply/rollback. Those remain Phase 6.
- Modal, hosted execution, Kubernetes, remote Docker daemons, Docker-over-TCP/SSH, rootful host execution, domain allowlisting, egress proxies, image pull/build during a run, arbitrary shell, interactive TTY, ports, devices, Docker socket mounts, host namespaces, or nested container control.
- Claiming VM-strength isolation, portable disk quotas for the writable bind mount, secret discovery inside an arbitrary repository, a tamper-proof audit log, or that `network=none` removes loopback.
- Starting Phase 4 work before every Phase 3 acceptance item, including the real-Docker canary, passes.

## Baseline repository state before Phase 3 implementation

Phase 2 is merged on GitHub as PR #2. Local and remote `main` point to merge commit `6fcc54a2b5ccaff652d05918a981dcb41c2dc243`, whose tree `85929bdcb7788ad92c4731f6538b9590a67302fb` matches reviewed Phase 2 commit `4b395cd1b7bdeb427677607841bc8093f69b9d53`. This branch, `codex/phase-3-docker-sandbox`, started clean from that merge.

At branch creation, the implementation was intentionally Phase 2/fake-only:

- `src/agent_fleet/domain/config.py::SandboxRequest` and `src/agent_fleet/domain/models.py::Run.sandbox_name` accept only `fake`. Project does not persist a sandbox selection or immutable capability snapshot.
- `src/agent_fleet/domain/models.py::SandboxSpec`, `SandboxHandle`, `ExecRequest`, and `ExecResult` carry only the fields needed by `FakeSandboxProvider`.
- `src/agent_fleet/ports/sandbox.py::SandboxProvider` exposes `capabilities`, `security_level`, `create`, `exec`, and `terminate`, but no inspection/reconciliation contract.
- `src/agent_fleet/bootstrap.py::build_container` wires a singleton `FakeSandboxProvider` into `WorkflowEngine`, `ResourceService`, and `ToolGateway`; `ProjectService` and `WorkflowEngine` reject non-fake selections.
- `src/agent_fleet/application/gateway.py::ToolGateway` supports a candidate write and a fake command. Its current `resolve -> mkdir/mkstemp -> replace` write sequence is not a safe authorization boundary under a parent-directory symlink swap.
- `src/agent_fleet/application/runtime_tools.py::GatewayRuntimeToolCatalog` hard-codes `python -m pytest -q`, while `BaselinePermissionBroker` recognizes only the fake-command resource.
- `src/agent_fleet/application/resources.py::ResourceService` creates a provider resource before persisting a lease, leaving a crash window. Lease recovery currently recognizes only the fake lifecycle.
- `src/agent_fleet/application/projects.py::ProjectService.initialize` stages and applies `.fleet/`, creates a canary fixture, but does not run it or produce a `BootstrapReport`; publication currently precedes the intended canary gate.
- `src/agent_fleet/application/evidence.py::EvidenceAssembler`, status output, summaries, and warnings contain fake-specific assumptions. Execution evidence is not yet bound to effective sandbox restrictions or a fresh verifier workspace.
- `src/agent_fleet/application/doctor.py::DoctorService` checks only `docker --version`; it does not prove daemon reachability, local endpoint use, image availability, or inspect effective isolation.

The host initially had no `docker`, `podman`, `colima`, `orbctl`, `lima`, or `nerdctl` executable. Therefore the mandatory real-Docker suite and manual canary began as `NOT RUN`, not PASS. All offline contracts and injected-runner tests were completed first; after the user explicitly approved local Docker/Colima installation, the hard real-daemon path became available and was run rather than waived. Phase 3 still will not be committed, pushed, merged, or called complete until the final repeated hard acceptance path passes.

## Security impact

Phase 3 introduces an intentional untrusted-code execution boundary and therefore affects the most sensitive trust boundaries in `docs/SECURITY_MODEL.md`.

- The trusted control plane alone selects the provider, image identity, network mode, UID/GID, mounts, limits, command, working directory, environment, labels, and logical identities. Runtime/model output can request a registered logical tool and bounded arguments only.
- Docker CLI and daemon are trusted computing base components. Only a local Unix endpoint is supported. Ambient `DOCKER_HOST`, contexts that resolve remotely, TCP/SSH endpoints, and repository-supplied daemon configuration are rejected.
- Docker images must already exist locally and resolve to an immutable local image ID/digest. The adapter uses `--pull=never`; it does not build or pull. Image-declared volumes, unsafe environment defaults, or incompatible platform metadata fail preflight.
- Every command container must run as a nonzero UID/GID with all Linux capabilities dropped, no-new-privileges, builtin/default seccomp, read-only root, private IPC/cgroup namespaces, no restart, no health check, `network=none`, bounded PIDs/CPU/memory/swap/shm/tmp/cache, and no device/port/host namespace/socket access.
- The only repository bind is the exact Fleet-created candidate workspace. A Fleet-owned inert read-only file shadows `/workspace/.git` so the worktree pointer and control-plane Git metadata are not visible. This second bind carries no user or credential content. Container inspection must reject every unrecognized mount.
- No host environment is inherited. The command environment is constructed from a tiny fixed non-secret allowlist and command-profile values. Provider, SSH, cloud, browser, Docker, Kubernetes, token/key/secret/password-like names or registered secret values are rejected. Events and artifacts retain environment names and safe hashes only, never values.
- File operations are trusted control-plane primitives over the isolated candidate worktree. They use a pinned root descriptor, per-component no-follow traversal, regular-file checks, bounded I/O, descriptor-relative atomic replacement/deletion, and post-operation binding checks. Untrusted repository commands run only through a sandbox provider.
- A command timeout or combined-output overflow kills and removes the whole one-shot container; terminating only the Docker client is insufficient. Output is bounded before persistence and redacted through the shared `Redactor`.
- Permission decisions bind action, role, stage, task, canonical relative path or reviewed command ID, sandbox provider, requirements, and network mode. Phase 3 permits only exact config-bound `network=none` verification commands; it does not add persistent grants.
- A `RESERVED` command intent with no recorded terminal outcome is ambiguous. Recovery reconciles its deterministic execution label/container and reports repair-required if no authoritative result exists; it must never automatically rerun the command.
- Fake execution is always `simulated`. Local-unsafe execution is at most `observed`, permanently carries `unsafe_host`, and cannot meet an isolation criterion. A Docker verifier result is independently verified only when it is from a fresh verifier-owned sandbox/worktree, binds the final patch/config/capability hashes, exits zero without truncation, and the verifier workspace remains unchanged.
- Resource recovery uses installation nonce plus full logical labels plus the persisted lease and exact full Docker resource ID. It never prunes, uses wildcards, trusts a name alone, or removes a resource that fails re-inspection.
- A target repository remains unchanged until canary success. Failure, timeout, cancellation, and partial cleanup preserve bounded reports/events while leaving no active container and no false completion claim.

The applicable security invariants are deny-by-default authorization, control-plane identity binding, untrusted-repository containment, no ambient secret flow, no-shell execution, bounded input/output/resource use, honest sandbox capability reporting, immutable evidence linkage, verifier independence, fail-closed provider selection, and explicit external side effects.

## Proposed design

The execution and bootstrap flow is:

```text
explicit Project sandbox config -> SandboxRegistry -> capability match
                                                -> persisted CREATING lease
reviewed command ID -> ToolGateway -> PermissionBroker -> CommandSpec resolver
                                                -> DockerSandboxProvider
                                                -> create + inspect + start/attach
                                                -> bounded transcript + cleanup
                                                -> command evidence

staged .fleet proposal -> disposable canary repo -> normal WorkflowEngine
        -> Engineer write -> Docker observed test -> control-plane final patch
        -> fresh Verifier worktree + Docker independently verified test
        -> EvidenceBundle -> CompletionGate -> BootstrapReport
        -> cleanup verified -> publish target .fleet -> persist Project
```

### Domain contracts and selection

Add strict `SandboxName`, `SandboxSecurityLevel`, `SandboxNetworkMode`, `SandboxRequirements`, `SandboxCapabilities`, `SandboxConfiguration`, `CommandSpec`, `SandboxInspection`, `SandboxExecutionMetadata`, and `BootstrapReport` models. `SandboxConfiguration` is a discriminated union for fake, docker, and local-unsafe. Docker configuration names a locally installed image reference and bounded resource limits; resolved image identity and effective capabilities are captured on Run, not trusted from project text.

Project persists the reviewed sandbox configuration. Run copies that exact configuration plus an immutable capability snapshot and hash. `fleet run --sandbox` becomes optional for an existing Project; an explicit value must equal the persisted selection. Existing rows with no field reopen as fake. Unknown providers and requirement mismatches fail before Run creation or sandbox side effects.

`SandboxRegistry` performs exact-name lookup and no fallback. `SandboxProvider.create` accepts a control-plane-generated logical sandbox ID. The port gains `inspect` and an explicit reconciliation/cleanup result. Provider adapters do not know about SQLite or artifact storage.

### Docker provider and lifecycle

Use an injected `DockerCommandRunner` port-like collaborator so ordinary unit tests can assert exact argv, stdin, timeout, output bounds, error classification, and state transitions without a daemon. Production resolves the Docker executable from a fixed trusted path set, verifies a local Unix endpoint/context, and executes direct argv with a scrubbed environment.

The provider models a logical sandbox handle but creates one one-shot container for each `ExecRequest`. Before create, the control plane has persisted a `CREATING` lease and `sandbox.exec_started` event containing a deterministic execution ID. The provider runs `docker container create`, immediately inspects the returned full ID, compares every effective field against the requested spec, then starts/attaches. On success, nonzero exit, timeout, output overflow, cancellation, or inspection mismatch, it kills if necessary and removes that exact inspected ID. Logical termination repeats exact-label reconciliation and is idempotent.

Lease states are `CREATING`, `ACTIVE`, `RELEASING`, `RELEASED`, `RECOVERED`, and `FAILED`. Recovery is an explicit exact-run operation, not an automatic startup sweep: `fleet recover <run-id> --confirm-owner-stopped` first marks only an interrupted `RUNNING`/`APPLYING` Run failed, then considers every outstanding lease for that Run. Docker ambiguity discovery uses the minimal unique installation/execution label pair, then cross-checks the exact generated name, full ID, and complete persisted label binding before any destructive action. It refuses deletion on every mismatch. Durable paused/review states keep their normal commands.

### Workspace and command gateway

Introduce `SecureWorkspace` as the sole implementation of bounded repository file operations. Paths are portable POSIX-relative logical paths with bounded depth/components/bytes. Traversal rejects absolute paths, empty/dot/dot-dot components, NUL/control characters, case-fold collisions where applicable, symlinked parents/targets, directories where a regular file is expected, FIFOs/sockets/devices, oversized content/results, and inode instability. Directory-FD operations are required; unsupported primitives fail closed.

The public logical tool set is:

- `repo.list_files`, `repo.read_file`, and `repo.search_text` for bounded reads;
- `workspace.write_file`, `workspace.apply_edit`, and `workspace.delete_path` for Engineer-only candidate changes;
- `workspace.get_diff` for control-plane Git diff retrieval;
- `command.run` for an exact reviewed command profile.

CoS gets no side-effect tools. Engineer gets bounded reads, writes, diff, and exact commands. Verifier gets reads, diff, and exact commands but no write/edit/delete. The control plane injects identity and resolves a model-visible command ID to the immutable `VerificationProfile`; the model never supplies executable, raw cwd, environment, timeout, or network mode. `CommandSpec` remains a public auditable contract and uses direct executable plus argv, logical cwd, allowlisted environment, timeout/output limits, and `none|required` network requirement.

### Evidence and independent verification

`ExecResult` carries bounded stdout/stderr, exit/truncation/timeout data, and provider-neutral execution metadata. `ToolGateway` redacts and persists a command-transcript artifact plus `CommandEvidence` bound to Run, TaskSpec, AgentInstance, stage, base revision, final patch hash when known, config/proposal hash, command-spec hash, sandbox name/security/capabilities hash, logical cwd, and execution ID.

Engineer command evidence is `observed` under Docker. Verification runs in a new verifier worktree and logical sandbox after the final patch identity is frozen. The verifier command output is `independently_verified` only after the control plane proves verifier ownership, exact final patch binding, exit zero, no truncation/timeout, unchanged verifier worktree, and successful cleanup. `CompletionGate` refuses isolated completion for fake/local-unsafe or for missing bindings and reports concrete proof gaps.

### Bootstrap and report

Split Project initialization into proposal staging, canary orchestration, and atomic publication. `BootstrapService` owns the application workflow but reuses `WorkflowEngine`, `ToolGateway`, `PermissionBroker`, `ArtifactService`, and `CompletionGate`; it must not create a bypass path. The deterministic calculator canary uses only Python standard-library `unittest`, so a preloaded base Python image needs no package installation or network.

`BootstrapReport` references rather than duplicates the authoritative evidence graph. It binds project profile, ProjectKnowledge, staged proposal, semantic config hash, selected provider and immutable capabilities, canary project/run/plan, final patch, command transcripts/evidence, verifier verdict, EvidenceBundle, CompletionDecision, cleanup result, remaining risks, proof gaps, schema/API version, and timestamps. Every referenced artifact ID/content hash is revalidated when reading the report. Only a successful, independently verified, fully cleaned report permits target `.fleet/` publication.

## Public contracts

- CLI:
  - `fleet init PATH --sandbox {fake,docker,local-unsafe} [--docker-image REF] [--allow-unsafe-local] ...`
  - `fleet run GOAL --project PATH [--sandbox ...]`; omitted sandbox uses Project selection, supplied selection must match it.
  - `fleet doctor --path PATH [--sandbox ...] --json` reports CLI, daemon, local endpoint, platform, configured image identity, and readiness. Docker checks are required only when Docker is selected.
  - `fleet version --json` reports `phase: 3` and `sandboxes: ["fake", "docker", "local-unsafe"]`.
- Models/configuration:
  - add sandbox requirements/configuration/capabilities, structured command, inspection/execution metadata, bootstrap report, and cleanup result contracts;
  - add `ArtifactKind.BOOTSTRAP_REPORT` and any required sandbox-inspection/transcript kind;
  - Project and Run receive backward-compatible sandbox fields and hashes.
- Ports:
  - `SandboxProvider` adds trusted-name selection, `inspect`, deterministic logical IDs, and idempotent termination/reconciliation semantics;
  - `SandboxRegistry` performs exact selection;
  - repository commands remain control-plane Git operations; no `.git` metadata is exposed in a worker.
- Persistence/events:
  - lease lifecycle expands to creating/active/releasing/released/recovered/failed;
  - append bounded `sandbox.create_started`, `sandbox.created`, `sandbox.inspected`, `sandbox.exec_started`, `sandbox.exec_finished`, `sandbox.cleanup_started`, `sandbox.cleaned`, and failure/recovery events;
  - command attempts and deterministic execution IDs make ambiguous outcomes visible and non-replayable.
- Errors and exit behavior:
  - stable errors distinguish unavailable CLI/daemon/image, remote daemon refusal, capability mismatch, sandbox create/inspection/exec/timeout/output/cleanup failures, unsafe-local confirmation missing, command not reviewed, command outcome ambiguous, and bootstrap canary/report failure;
  - Docker failure never changes provider or executes a host command.
- Compatibility:
  - old Project/Run/lease JSON loads as fake with conservative capabilities;
  - existing fake CLI/test behavior remains deterministic;
  - local-unsafe requires both explicit selection and `--allow-unsafe-local`; generic `--yes` is insufficient.

## Milestones

### Milestone 1: Provider-neutral sandbox and persistence contracts

Add the strict models, schemas, registry, additive aggregate fields, lease lifecycle, capability matching, stable errors/events, and migrate FakeSandbox to the expanded port.

Acceptance:

- Existing Phase 2 databases, fake Projects/Runs, and CLI fixtures reopen unchanged.
- Exact provider selection and capability mismatch fail closed before Run/resource creation.
- CREATING is persisted before provider create; all nonterminal leases are discoverable for recovery.
- Generated schemas are deterministic and package/archive tests include every new public contract.

### Milestone 2: Hardened providers and bounded gateway

Implement injected-runner-tested Docker behavior, explicit local-unsafe behavior, descriptor-relative workspace operations, exact reviewed commands, environment filtering, output/timeout handling, redacted transcripts, and ambiguous-command recovery.

Acceptance:

- Offline tests prove exact Docker create/inspect/start/kill/remove ordering and flags, immutable local image use, mount allowlist, empty environment construction, full-ID reconciliation, and no fallback.
- Adversarial path/race/special-file/case-fold tests cannot escape the candidate workspace.
- Shell metacharacters remain literal argv; unreviewed command/cwd/env/network changes are rejected.
- CoS and Verifier cannot mutate; all allowed actions bind trusted role/stage/task/workspace context.
- Timeout, cancellation, output flood, every lifecycle failure point, and ambiguous RESERVED intent leave bounded evidence and no blind replay.

### Milestone 3: Workflow, evidence, CLI, doctor, and bootstrap

Dispatch sandboxes from immutable Project/Run state, create fresh verifier resources, derive evidence from actual capabilities, add doctor/preflight and user-facing options, refactor canary-before-apply bootstrap, and persist/verify `BootstrapReport`.

Acceptance:

- Fake workflow stays simulated and cannot become verified complete.
- Docker Engineer evidence is observed; a fresh Docker verifier can reach independently verified only with every final-patch/config/capability/cleanup binding.
- Docker-selected init/run fails safely when CLI, daemon, image, capability, or cleanup is unavailable and never touches target `.fleet/` before canary success.
- Fake/local doctor does not require Docker; Docker doctor performs inspect-only checks and never starts a container, resolves a credential, runs repository code, or contacts a provider.
- `BootstrapReport` tamper tests reject changed referenced artifacts/hashes.

### Milestone 4: Real Docker acceptance and delivery

Run opt-in real-Docker integration/security tests and the complete fake-runtime bootstrap canary, update README/spec status and this plan with exact evidence, freeze the candidate identity, obtain independent review, commit Phase 3 once, push its branch, merge the GitHub PR, and repeat critical checks on merged `main`.

Acceptance:

- Real inspection proves non-root UID, `CapDrop=ALL`, no-new-privileges/seccomp, read-only root, network none, exact mounts, immutable image, CPU/memory/swap/PID/shm limits, no restart/healthcheck, and no privileged/host namespace/socket/device/port access.
- Registered provider-secret values and a host sentinel outside the mount are inaccessible; `.git` metadata is masked; root filesystem writes and network/DNS fail while bounded workspace writes succeed.
- Argv injection, output flood, timeout descendant killing, failure/cancel/crash cleanup, and orphan reconciliation pass against the real daemon.
- The bootstrap canary produces a nonempty final patch, independently verified zero-exit evidence, `verified_complete=true`, a hash-valid `BootstrapReport`, no target mutation before success, and no remaining managed containers/nonterminal leases.
- Formatting, lint, strict type checking, unit, contract, integration, offline E2E, full suite, schema drift, build/archive, diff hygiene, and secret scans all pass with exact recorded results.
- GitHub records one Phase 3 commit/PR merge; remote `main` exactly matches the reviewed implementation tree, and post-merge validation is clean.

## Detailed implementation steps

1. Add and maintain this ExecPlan before implementation. Incorporate architecture, security, persistence, gateway, and bootstrap discoveries without erasing failed approaches.
2. Extend `src/agent_fleet/domain/models.py`, `domain/config.py`, `domain/evidence.py`, `domain/enums.py`, `domain/errors.py`, and `schemas/generate.py` with strict sandbox/command/report contracts, backwards-compatible Project/Run fields, stable codes, hashes, limits, and schema output.
3. Extend `ports/sandbox.py`; add `application/sandboxes.py::SandboxRegistry` and requirement matching; migrate `adapters/sandbox/fake.py` and common provider contract tests first.
4. Change lease persistence/recovery in `application/resources.py` and SQLite state adapters so a control-plane ID and CREATING record precede provider work, all nonterminal states are queryable, transitions are validated, and exact metadata supports safe reconciliation.
5. Add `adapters/sandbox/docker.py` plus a subprocess command runner. Implement fixed-path/local-endpoint preflight, immutable image inspection, safe argv construction, one-shot container lifecycle, effective-config inspection, bounded attach output, whole-container timeout/overflow termination, full-ID cleanup, and exact-label recovery.
6. Add `adapters/sandbox/local_unsafe.py` as an explicit, separately confirmed diagnostic provider. Reuse structured no-shell command execution and bounds, but advertise `unsafe_host` honestly and never enter it through fallback.
7. Add `adapters/workspace/secure.py` and route bounded read/list/search/write/edit/delete through pinned descriptor-relative operations. Keep Git diff/base/patch computation in the existing trusted repository adapter.
8. Expand `application/gateway.py`, `application/runtime_tools.py`, and `application/permissions.py` with the role-specific logical tool set, reviewed command-ID resolution, environment/name/value checks, transcript artifacts, evidence binding, and non-replay handling for ambiguous commands.
9. Refactor `application/workflow.py` and `application/evidence.py` to select from the persisted sandbox registry, copy capability/config hashes into Run, use fresh verifier worktree/sandbox resources, classify evidence by actual security/execution provenance, and clean every resource path.
10. Add a `BootstrapService` and refactor `ProjectService.initialize` so proposal staging is read-only toward the target, the deterministic canary runs through normal application boundaries, a hash-linked `BootstrapReport` is stored and validated, and only success publishes `.fleet/` and Project state.
11. Wire providers/registries/services in `bootstrap.py`; extend `cli/app.py`, CLI models/presenters, doctor diagnostics, version output, config generation, warnings, and status/artifact output. Add local-unsafe double confirmation and no-fallback tests.
12. Add unit, contract, integration, E2E, migration, schema, packaging, architecture, redaction, adversarial path/race, Docker-command-runner, recovery, bootstrap report, and negative tests. Mark real Docker tests `docker_integration` and require both `AGENT_FLEET_ENABLE_DOCKER_TESTS=1` and `AGENT_FLEET_DOCKER_TEST_IMAGE=<local-ref>`.
13. Update README and normative docs with exact Phase 3 behavior, threat-model limitations, prerequisites, preloaded-image policy, doctor/init examples, opt-in commands, cleanup/recovery semantics, and test results.
14. Run all offline gates. When a local daemon and preloaded image are available, run every real-Docker gate and manual canary, repair all findings, and repeat the full suite.
15. Freeze the candidate tree/diff identity, commission fresh independent read-only verification, update this plan's Outcomes, make one Phase 3 commit, push `codex/phase-3-docker-sandbox`, open/merge a GitHub PR, verify remote tree identity, and rerun post-merge checks before Phase 4.

## Validation plan

Required offline gates:

```bash
uv lock --check
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q tests/unit
uv run pytest -q tests/contract
uv run pytest -q tests/integration -m integration
uv run pytest -q tests/e2e -m e2e
uv run pytest -q
uv run python -m agent_fleet.schemas.generate --check
uv build --offline
git diff --check
```

Additional offline evidence:

- Run common provider contracts for fake, Docker-with-injected-runner, and local-unsafe without executing a host project command.
- Inspect generated Docker argv and synthetic post-create inspection for every positive/negative invariant; include missing CLI/daemon/image, remote endpoint, malformed output, inspect mismatch, create/start/attach/kill/remove failure, timeout, cancellation, and output overflow.
- Exercise all bounded tool schemas and role/stage/task/path rules. Include traversal, absolute path, symlinked parent/target, race swaps, case-fold collision, FIFO/socket/device, oversized paths/files/search/output/artifacts, hostile argv, secret environment, and verifier mutation cases.
- Prove raw and encoded registered secret sentinels do not appear in Docker argv, runner environment, SQLite/WAL, events, artifacts, JSON/human output, exception strings, tracebacks, or sandbox inspection.
- Prove Project/Run sandbox persistence, old-row compatibility, capability/hash tamper rejection, mismatch failure before resource creation, exact lifecycle recovery, and no local-unsafe fallback.
- Exercise BootstrapReport reference/hash verification and target-before-canary ordering using deterministic fake providers.
- Inspect wheel and sdist for schemas and runtime assets and absence of local paths/secrets/test-only fixtures.

Required real-Docker gate, never implicit:

```bash
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE='<preloaded-local-image-ref>' \
uv run pytest -q -m docker_integration
```

Required manual acceptance uses a disposable generated Git repository, fake runtime, selected real Docker provider, a registered provider-secret sentinel, and a host sentinel outside every mount. It must retain the `BootstrapReport` but remove all command containers, logical sandbox resources, and disposable worktrees. Before declaring Phase 3 complete, record:

- exact Docker client/server versions, context/endpoint classification, resolved image ID/digest, and test command;
- full test counts/durations, explicit skips, and any platform-limited proof gaps;
- canary Run/Task/Agent/artifact IDs and content hashes, final patch hash, command-spec/capability hashes, verifier verdict, completion decision, cleanup result, and secret/sentinel assertions;
- candidate diff/tree hash, independent reviewer verdict, Phase 3 commit, PR URL/number, merge commit, remote main tree hash, and post-merge results.

## Rollback and recovery

Sandbox selection is immutable for a Project initialization and copied to each Run. Docker failure never falls back; users fix doctor findings or explicitly initialize a different disposable Project. Existing fake rows remain readable through defaults. If a persistence migration is required, it is additive/forward-only and retains Phase 2 JSON; older binaries must reject a newer schema rather than misread weakened security state.

The control plane generates deterministic logical sandbox/execution IDs and persists a CREATING lease/attempt before Docker create. After confirming the previous owner stopped, the operator scopes recovery to one persisted Run. Recovery queries every outstanding lease for only that Run. For an ambiguous create it discovers by the minimal unique installation/execution label pair, then cross-validates the exact generated name, full inspected ID, and complete label binding. A known resource is killed/removed idempotently and the lease becomes RECOVERED. An unknown or mismatched resource is not deleted and produces a manual-repair diagnostic. No cleanup code uses prune, wildcards, repository-derived names, or a partial ID. Automatic startup recovery is intentionally absent until a cross-process owner-liveness/locking protocol can prevent interference with a still-active Run.

A command with an authoritative terminal result may be replayed from persisted result metadata. A command left RESERVED/started without a terminal result is outcome-ambiguous and is never automatically executed again; the Run moves to a repair-required/failed boundary and a future user retry creates a new Run or fresh verifier attempt.

Bootstrap proposal files remain in Fleet-owned staging until the canary report is verified. Failure before publication leaves the target untouched and cleanup is retryable. Publication retains the existing no-follow/no-overwrite snapshot protocol. If publication finishes but Project persistence fails, the exact generated target snapshot allows an idempotent retry; a differing target tree fails without overwrite. Report/artifact records survive a failed canary for diagnosis but cannot authorize publication or completion.

Local-unsafe has no automatic recovery-to-Docker or Docker-to-local transition. Its warnings and `unsafe_host` risk survive restarts and appear in every relevant completion artifact.

## Progress

- [x] (2026-09-04) Phase 2 PR #2 merged; local/remote main tree identity and full post-merge suite verified.
- [x] (2026-09-04) Read Phase 3 roadmap and normative product, architecture, configuration, security, repository-agent, and ExecPlan instructions.
- [x] (2026-09-04) Completed independent read-only architecture, security, and acceptance-gap audits.
- [x] (2026-09-04) Created this Phase 3 living ExecPlan before implementation.
- [x] (2026-09-04) Implemented Milestone 1 contracts, generated schemas, additive SQLite migration `0003`, immutable Project/Run sandbox bindings, and recoverable sandbox/execution leases.
- [x] (2026-09-04) Implemented Milestone 2 fake/Docker/local-unsafe providers, descriptor-relative workspace operations, reviewed command resolution, bounded subprocess handling, exact inspection, and fail-closed cleanup/recovery.
- [x] (2026-09-04) Added public exact-run crash recovery with explicit owner-stopped confirmation, no-lease interruption handling, durable-pause refusal, CLI/E2E coverage, and no unsafe global startup sweep.
- [x] (2026-09-04) Implemented Milestone 3 workflow/evidence/bootstrap/CLI/doctor integration, fresh verifier resources, canary-before-publication, and hash-linked BootstrapReport validation.
- [x] (2026-09-04) A fresh verifier rejected candidate identity `158f81458804474faaad06556a1d5574330523c69f38605a47d53bf87da28011` for an application-to-adapter dependency violation; repaired it by mandatory port injection at the composition root and added an AST architecture regression.
- [x] (2026-09-04) Repeated every offline validation gate after that repair: unit `330 passed`, contract `250 passed`, integration `87 passed, 47 deselected`, E2E `4 passed`, and combined `719 passed, 7 skipped`; formatting, lint, mypy, schema drift, lock/sync, and diff hygiene passed.
- [x] (2026-09-04) Repeated the six-test real-Docker suite on the repaired implementation/test tree: `6 passed in 12.72s`, with zero Fleet-managed containers afterward.
- [x] (2026-09-04) Repeated a disposable real-Docker manual bootstrap canary through the repaired composition root with read-only preview, independently verified Engineer/Verifier executions, hash-valid BootstrapReport, zero proof gaps, secret/sentinel assertions, and complete resource cleanup.
- [x] (2026-09-04) Rebuilt and inspected the final documentation-bearing wheel and sdist; both contain the repaired gateway bytes and the exact expected runtime assets with no excluded/local/sentinel content.
- [x] (2026-09-04) Froze replacement candidate identity `8ea5a9f4da9d746c19a01df72a6e96ddd4f9471711fe48dccae9e07e112de684` across 182 entries, excluding only this living plan to avoid self-reference.
- [x] (2026-09-04) A new independent read-only verifier recomputed that identity unchanged at start/end, ran 372 focused tests plus all static/package checks, found no P0/P1/P2, and returned `PASS — FREEZE: YES`.
- [x] (2026-09-05) Created Phase 3 feature commit `a15cb01621d99d0e3e22e72f5f55f4d8ac1ad9c6`, pushed `codex/phase-3-docker-sandbox`, and merged GitHub PR #3 as `12bee8e206735c65eb905f94bef9b10b41d0b30c`; feature and merge trees both equal `de12d3ac016abd4ebb924c643e6a0479dfbac5a7`.
- [x] (2026-09-05) Repeated post-merge static/package checks, the combined suite (`719 passed, 7 skipped in 169.63s`), and the six-test real-Docker gate (`6 passed in 12.55s`) with zero managed containers.
- [x] (2026-09-05) A later completion audit exposed a real cancellation race: the real-Docker gate failed once with `1 failed, 5 passed in 11.92s`, despite exact container cleanup succeeding. Two read-only diagnostics independently reproduced and classified it as a P1 Phase 3 acceptance defect rather than accepting a passing rerun.
- [x] (2026-09-05) Implemented a bounded subprocess cancellation repair on `codex/phase-3-cancellation-race-fix`: one waiter per child, typed invocation/termination failures, immediate process-group termination before bounded reap, fail-closed group-absence proof, repeat-cancel-resistant runner/provider cleanup, exact Docker error mapping, and deterministic unit/contract coverage.
- [x] (2026-09-05) An initial focused slice of 198 runner/Docker/local-unsafe tests and 25 real-Docker race repetitions passed. Later adversarial review deliberately superseded that evidence after finding cancellation could still restart an in-flight timeout cleanup or interrupt higher-level resource cleanup.
- [x] (2026-09-05) Hardened the complete cancellation chain: one retained process termination task across timeout/overflow/pipe/cancel paths; repeat-cancel-resistant auxiliary finalization; cleanup-error precedence; typed process failure mapping; strong Docker, gateway, sandbox-creation, whole-run, and direct-lease cleanup; execution -> sandbox -> worktree ordering; same-target coalescing; public cancel retry; and fail-closed conflicting `RELEASED`/`RECOVERED` targets including the completed-task registry window.
- [x] (2026-09-05) Added deterministic regressions for every discovered race. The final focused suite passed `226 passed`; the 12 highest-risk cases passed 25 consecutive runs (`300/300`), and `tests/unit/test_process_runner.py` passed all 13 tests on Python 3.12.14, 3.13.15, and 3.14.6.
- [x] (2026-09-05) Ran the complete final offline matrix: unit `341 passed`, contract `257 passed`, marked integration `93 passed, 49 deselected`, E2E `4 passed`, and combined `745 passed, 7 skipped`; lock/sync, Ruff, mypy, schema drift, and diff hygiene all passed.
- [x] (2026-09-05) Ran the exact final real-Docker tree: all six tests passed in 14.21s, the original timeout/output/cancellation/orphan scenario passed 25 consecutive repetitions, and the final global managed-container query was empty.
- [x] (2026-09-05) Ran a new standalone fake-runtime/real-Docker bootstrap acceptance with read-only preview, random registered secret, external host sentinel, fresh Engineer/Verifier containers, hash-valid evidence graph, verified publication, 72 contiguous events, 16 artifacts, and zero leases/worktrees/containers or secret persistence.
- [x] (2026-09-05) Rebuilt and inspected the documentation-bearing wheel/sdist. Both contain 118 files, 28 schemas, migrations `0001`-`0003`, three prompts, exact repaired source bytes, and no excluded/local/sentinel content; direct wheel import/CLI smoke passed. Dependency-cold offline installation remained unclaimed because the uv cache lacks an installable PyYAML distribution.
- [x] (2026-09-05) Two fresh independent read-only reviews found no P0/P1/P2 implementation or test issue and returned `FREEZE: YES`; documentation evidence was refreshed afterward without changing implementation/tests.
- [ ] Commit and push the frozen follow-up repair, merge its GitHub PR, verify local/remote main identity, repeat post-merge gates, and record the external Git identities in the delivery report.

## Discoveries

- Observation: The host initially had no Docker-compatible CLI/runtime executable in `PATH`.
  Evidence: `command -v docker podman colima orbctl lima nerdctl` found none on 2026-09-04. The user then explicitly approved installation; Homebrew Docker CLI 29.8.0 plus Colima were installed and a local Linux/arm64 daemon was started.
  Consequence: The hard gate became runnable rather than being waived. Acceptance pins context `colima`, local endpoint `unix:///Users/blackswan/.colima/default/docker.sock`, server 29.5.2, canonical daemon identity `815f9bce2b2930154aaaf49cf86667332a3b576d6b85a92ed070ff9d1a0971fb`, and immutable image `sha256:08a5a9124f184f29018f59c1abbe7015a0498a447d5aecd60b18029316465379`.
- Observation: Baseline provider creation preceded lease persistence.
  Evidence: before Phase 3, `ResourceService` called `sandbox.create()` before `save_lease()`.
  Consequence: The lifecycle contract must be changed before any real external resource is created.
- Observation: Current candidate worktrees contain a `.git` file with an absolute control-plane metadata path.
  Evidence: `GitRepositoryAdapter` uses Git worktrees and whole-workspace Docker mounting is the planned execution shape.
  Consequence: Docker mounts need a Fleet-owned inert `.git` shadow and effective-mount inspection; Git remains control-plane-only.
- Observation: `Path.resolve()` followed by path-based mutation is vulnerable to parent replacement between validation and use.
  Evidence: `_atomic_workspace_write` resolves first and later calls path-based directory/temp/replace operations.
  Consequence: Phase 3 file writes and deletes require descriptor-relative no-follow primitives; no insecure compatibility fallback is allowed.
- Observation: Current RESERVED intent recovery is acceptable for a reconciled deterministic write but unsafe for an arbitrary command.
  Evidence: gateway recovery can execute a RESERVED intent again without a terminal command outcome.
  Consequence: Command attempts need a persisted execution identity and ambiguous outcomes must not be blindly replayed.
- Observation: The product bootstrap order conflicts with the current `ProjectService.initialize` order.
  Evidence: normative bootstrap flow requires canary/report before target apply, while current code applies `.fleet/` before any canary execution.
  Consequence: Bootstrap orchestration must be split and reordered rather than adding a post-publication canary.
- Observation: Colima does not share pytest's macOS `/private/var/...` temporary root into its VM by default.
  Evidence: the first real-Docker fixture mount under the system pytest temp root was unavailable to the daemon, while an identical fixture beneath the shared project parent mounted successfully.
  Consequence: real-Docker tests use an explicit `--basetemp` beneath `/Users/...`; this is a host-runner requirement, not a sandbox relaxation.
- Observation: a cgroup-v2 daemon may report `HostConfig.MemorySwappiness=null` even when `--memory-swap` exactly equals `--memory` and no container swap allocation exists.
  Evidence: Colima/Docker 29.5.2 effective inspection returned null for that field while retaining the exact equal hard limits.
  Consequence: Phase 3 accepts only explicit zero or null coupled with exact equal memory/swap bounds; wrong types and nonzero values fail closed.
- Observation: stopping reads as soon as the output cap was reached could deadlock a child blocked on a full pipe.
  Evidence: the adversarial 2 MiB output test hung until timeout when the capped consumer returned without draining the remaining bytes.
  Consequence: capped stdout/stderr readers continue discard-draining until process termination while persisting only the bounded prefix and truncation flag.
- Observation: daemon identity is not safely established by one preflight check when the local socket may be rebound between lifecycle calls.
  Evidence: injected daemon replacement after image inspect, create, effective inspect, attach, list, kill, and remove exposed operations that otherwise could cross daemon identities.
  Consequence: endpoint, daemon ID, OS, architecture, and server version form a canonical pinned identity; every discovery/destructive sequence has adjacent pre/post checks, and cleanup never continues on a replacement daemon.
- Observation: a Docker CLI nonzero or signal return after dispatch does not prove the daemon rejected container creation.
  Evidence: the CLI can lose its response after the daemon accepts create, and a first exact-label query can race a delayed resource.
  Consequence: any dispatched create without a valid full ID stays ambiguous even for return code 125 or `-9`; zero matches leave a FAILED/outstanding lease, prohibit replay, and later exact-label recovery removes a delayed resource.
- Observation: the implemented recovery service initially had no production caller, while invoking it automatically on every CLI startup could destroy resources owned by another still-running process.
  Evidence: only tests called the original all-run recovery method, and Phase 3 persists no cross-process owner-liveness lease or mutex.
  Consequence: Phase 3 exposes only `fleet recover <run-id> --confirm-owner-stopped`; it handles interrupted Runs even before their first lease, scopes cleanup to that exact Run, and refuses durable paused/review states.
- Observation: the first frozen candidate let `application/gateway.py` import and lazily construct the concrete workspace filesystem adapter.
  Evidence: the first fresh verifier traced the active fallback from `ToolGateway.__init__` and confirmed that the composition root omitted the port binding; the existing architecture test covered only the PydanticAI adapter.
  Consequence: that candidate was rejected. `ToolGateway` now requires the `WorkspaceFileSystem` port, only `bootstrap.py` constructs `BoundedWorkspaceFileSystem`, and an AST regression rejects every future `application/** -> adapters/**` import.
- Observation: `GitRepositoryAdapter.create_canary_fixture` deliberately creates only beneath its own state root.
  Evidence: the first repaired-tree manual-acceptance setup attempted a sibling target and failed before Docker or project state with the adapter's containment check.
  Consequence: the successful retry used a Fleet-owned factory-state target and a separate sibling acceptance state; no containment rule was weakened.
- Observation: an existence-only real-Docker cancellation fixture can cancel during a short post-create daemon-identity check rather than during the intended attached workload.
  Evidence: a completion-audit run failed at `DockerSandboxProvider.exec -> _require_labels_daemon -> docker info`; diagnostic instrumentation reproduced `os.killpg(..., SIGKILL)` raising `PermissionError(EPERM)` while that short-lived CLI process exited. The adapter then mislabeled the raw `OSError` as `SANDBOX_UNAVAILABLE`, replacing `CancelledError`. Exact-label compensation still removed the container and every final global managed-container query was empty, but CLI process-group termination had not been proven.
  Consequence: Phase 3 remained incomplete after PR #3. Cancellation cleanup now reuses the original waiter, signals the still-owned process group before bounded reap, tolerates EPERM only after leader reap plus an `ESRCH` group probe, and otherwise returns a typed cleanup failure. The real test now waits for `State.Running=true`, while an offline contract preserves the post-create control-call cancellation case.
- Observation: the subprocess runner created one `wait_task` but its cancellation path invoked `process.wait()` a second time.
  Evidence: an independent synthetic probe counted two wait calls and demonstrated that a second-waiter failure could replace the original cancellation even though CPython currently permits multiple waiters.
  Consequence: all normal, timeout, overflow, and cancellation paths now await the single original waiter; deterministic regression asserts one call under an injected EPERM exit race and repeated cancellation.
- Observation: cancellation during an already-started timeout/output termination could start a second process-group cleanup, and continued cancellation during auxiliary-task finalization could replace a typed termination failure.
  Evidence: independent deterministic probes paused group-absence proof after the first destructive signal, observed two signal attempts on the pre-fix tree, and reproduced `CancelledError` 50/50 while the shielded cleanup future held an unobserved `ProcessTerminationError`.
  Consequence: every abnormal exit lazily creates at most one retained termination task. Timeout, overflow, pipe drain, and cancellation join that task; auxiliary-task finalization is itself retained; task failures are retrieved before an ordinary caller cancellation can be propagated. Final probes returned `ProcessTerminationError` 10/10 with no unobserved-future warning.
- Observation: protecting only provider cleanup did not protect the entire application cleanup transaction.
  Evidence: repeated cancellation of `ToolGateway`, sandbox creation, public cancellation/recovery, or direct verifier cleanup could detach a later cleanup tier, mark a lease `FAILED`, or return before execution -> sandbox -> worktree cleanup completed. A second public `cancel()` also returned early once the Run was durably `CANCELLED`, even while leases remained outstanding.
  Consequence: gateway and sandbox-creation cleanup use strong retained tasks; ResourceService retains one whole dependency-ordered run task and one exact lease task; cleanup failure takes precedence over cancellation; and a cancelled Run retries while any lease remains outstanding.
- Observation: cleanup-task coalescing needs the requested terminal audit state as part of its identity, including after the task is done but before its owner removes the registry entry.
  Evidence: same-ID `RELEASED` and `RECOVERED` callers could otherwise share one destructive operation but report success for the wrong terminal status in a completion-window probe.
  Consequence: the process-local registries store `(target_status, task)`. Same-target callers join; every stored target mismatch fails closed without starting duplicate cleanup, and deterministic tests cover both live and completed-task windows at run and lease scope.

## Decision Log

- Decision: Preserve omitted/legacy sandbox as `fake`, while recommending explicit Docker for isolated work.
  Rationale: The roadmap calls Docker the recommended path but does not authorize a backwards-incompatible default change; silent migration could unexpectedly execute code.
  Alternatives: Make Docker the default immediately; auto-select Docker when present. Both were rejected because selection must be reviewed and exact.
  Date: 2026-09-04
- Decision: Implement one one-shot Docker container per command behind a logical sandbox lease.
  Rationale: Timeout/output overflow can terminate the entire execution boundary, fresh verifier execution is easy to prove, and no idle worker process needs a command RPC protocol.
  Alternatives: Long-lived container plus `docker exec`; rejected because terminating the client does not reliably terminate descendants and lifecycle recovery is more ambiguous.
  Date: 2026-09-04
- Decision: Resolve exact command specifications from immutable reviewed VerificationProfile command IDs in the control plane.
  Rationale: Repository detection yields candidates, not authority, and model-supplied argv/env/cwd would bypass the permission boundary.
  Alternatives: Permit arbitrary structured argv after generic validation; deferred because Phase 3 needs a minimal secure verification surface.
  Date: 2026-09-04
- Decision: Support `network=none` in the acceptance slice and retain `required` only as a request shape that fails without exact approval.
  Rationale: Domain allowlisting is unavailable and persistent permission semantics belong to Phase 4. The bootstrap canary needs no network.
  Alternatives: Implement approved-unrestricted immediately; deferred until the exact approval lifecycle is present and tested.
  Date: 2026-09-04
- Decision: Shadow the worktree `.git` pointer with a Fleet-owned inert read-only file and inspect the exact mount set.
  Rationale: The worker needs the candidate bytes but not Git control-plane metadata or host paths. This is the smallest auditable execution view compatible with direct candidate writes.
  Alternatives: Copy/synchronize a second sanitized workspace; stronger separation but materially larger reconciliation and race surface. Mount the unmasked worktree; rejected due host-path disclosure.
  Date: 2026-09-04
- Decision: Add a separate `--allow-unsafe-local` gate that `--yes` cannot satisfy.
  Rationale: Local execution is a qualitatively different high-risk boundary and cannot be enabled by routine noninteractive confirmation or repository configuration.
  Alternatives: Hide local-unsafe or accept `--yes`; hiding conflicts with the roadmap, while generic confirmation is too weak.
  Date: 2026-09-04
- Decision: Bind Docker Project, Run, logical sandbox, execution labels, doctor result, and evidence to the resolved immutable image ID and a canonical local-daemon identity.
  Rationale: a mutable image tag or a replacement daemon would make inspected policy and later execution/cleanup refer to different resources.
  Alternatives: trust the selected context name or tag; rejected because neither is an immutable execution identity.
  Date: 2026-09-04
- Decision: Persist a one-way `creation_dispatched` transition immediately before Docker create and treat every post-dispatch missing-ID result as ambiguous.
  Rationale: a control-plane crash, callback acknowledgement loss, CLI failure, or delayed daemon response must never cause command replay or premature absence proof.
  Alternatives: treat ordinary nonzero create as definitive failure; rejected after security review because daemon acceptance may precede CLI failure.
  Date: 2026-09-04
- Decision: Require terminal Docker inspection to contain an explicit empty-string `State.Error` and exact scalar shapes for all security-relevant fields.
  Rationale: missing, null, collection-shaped, or nonempty error state cannot be interpreted as an authoritative successful terminal execution.
  Alternatives: normalize missing/null to empty; rejected because it turns malformed daemon metadata into success evidence.
  Date: 2026-09-04
- Decision: Make crash recovery an operator-confirmed exact-run command rather than an automatic startup sweep.
  Rationale: exact scoping provides a real public recovery path for delayed resources and lease-free interruptions without guessing whether another Fleet process is still live.
  Alternatives: recover every outstanding lease on every CLI startup; rejected until ownership liveness and cross-process locking can make that destructive action safe.
  Date: 2026-09-04
- Decision: Make the bootstrap fixture emit a Fleet-owned boundary marker from both Engineer and fresh Verifier commands.
  Rationale: a generic passing test could not prove that the sandbox-hidden host sentinel, environment allowlist, and ordinary verification behavior were all exercised through each role's real command path.
  Alternatives: rely on container inspection alone; rejected because inspection and behavioral boundary evidence answer different questions.
  Date: 2026-09-04
- Decision: Require every application-layer concrete adapter through a project-owned port and instantiate it only in the composition root.
  Rationale: an optional application fallback silently reverses the documented dependency direction even if its behavior is otherwise secure.
  Alternatives: retain an optional convenience default; rejected because it makes the forbidden dependency active and recurrence invisible without the new AST test.
  Date: 2026-09-04
- Decision: Treat subprocess invocation failure and verified-termination failure as separate typed adapter outcomes.
  Rationale: catching arbitrary `OSError`/`RuntimeError` at the Docker boundary hid a cancellation cleanup defect as CLI unavailability. A termination error must instead fail closed as `SANDBOX_CLEANUP_FAILED`; unrelated runtime invariants must not be relabeled.
  Alternatives: ignore `EPERM`, or continue catching all runtime errors. Both were rejected because neither proves that the launched process group is gone.
  Date: 2026-09-05
- Decision: Signal the process group immediately on bounded cleanup, then tolerate a cancellation-time `killpg` permission race only after bounded leader reap and non-destructive process-group absence proof.
  Rationale: on Darwin, a short-lived child may exit while the watcher has not yet published its return code. Waiting for natural leader exit can strand a same-group descendant; signaling before reap preserves tree cleanup. `EPERM` alone proves neither success nor absence, so only original-`wait_task` completion plus `killpg(pgid, 0) -> ESRCH` restores cancellation in the current same-user threat model.
  Alternatives: blanket-suppress permission errors; add a natural-exit grace; signal again after bounded reap; introduce a supervisor/cgroup/pidfd design. Suppression is unsafe, grace stranded a deterministically reproduced descendant, post-reap destructive signaling widens PGID-reuse risk, and a new process-supervision architecture is beyond the bounded Phase 3 repair.
  Date: 2026-09-05
- Decision: Retain exactly one process-termination task for every abnormal exit and make auxiliary-task finalization cancellation-resistant, with cleanup failures ordered ahead of caller cancellation.
  Rationale: timeout, output overflow, pipe drain, and cancellation are concurrent observations of one subprocess lifecycle, not authorization for multiple destructive signals. Returning `CancelledError` while termination is unproven would turn a safety failure into an ordinary control-flow result.
  Alternatives: restart cleanup after each cancellation; let `finally` use an unshielded gather; always prefer the first cancellation. Each was rejected by deterministic double-signal or error-masking probes.
  Date: 2026-09-05
- Decision: Treat dependency-ordered run cleanup and direct lease cleanup as retained, process-local operations keyed by both resource identity and terminal target.
  Rationale: every caller must wait for the exact execution -> sandbox -> worktree proof, same-target callers must not duplicate destructive work, and `RELEASED` versus `RECOVERED` is audit evidence rather than interchangeable presentation. Cleanup failures must remain visible even when cancellation is pending.
  Alternatives: shield only provider calls; retain only the public cancellation service; key tasks only by resource ID; run conflicting modes concurrently. These alternatives left parent resources, bypassed verifier cleanup, corrupted terminal audit state, or duplicated deletion attempts.
  Date: 2026-09-05

## Outcomes

The Phase 3 vertical slice is implemented and the target behavior is observable end to end. Exact fake/Docker/local-unsafe selection, persistent immutable sandbox bindings, bounded logical filesystem/command tools, one-shot inspected Docker execution, operator-confirmed exact-run recovery, fresh-verifier evidence, and canary-before-publication now share the normal application control plane. Fake and local-unsafe remain honest non-verifying paths; no live model-provider request is needed or made by the bootstrap acceptance flow.

The initial PR #3 disposable manual acceptance used fake runtime plus real Docker and a generated Git repository after the composition-root repair. Preview produced proposal hash `b82322ef1bf9ee67902aac22921b1400d2065b7d35fe46095804fb0053960a48` without creating target `.fleet/` or Fleet state. Confirmed init created target Project `prj_eb7c51224f154b40bf4d981de02fb8f8`, canary Project `prj_ba2b6ac81e2248b5801c38e7c0cc4933`, Run `run_b610d8af67ce4e549534dd37bcd4ed32`, Task `task_edb3db0564f14c4aa6c4c38ec189e08d`, CoS `agent_952dcb7513ad4e399f2eb442859d9152`, Engineer `agent_59504be902bf40adac84dcfe1db0d0fe` with execution `exec_f3e092b89e3f4c1e8da8e9b6e68adaa3`, and fresh Verifier `agent_8a2c125190ea42bbb90799d4df553abb` with execution `exec_c1fcb4780b9f4353b18a2b53a844bae6`. Both commands exited zero and each transcript contained exactly one `AGENT_FLEET_SANDBOX_BOUNDARY_OK` marker. The canonical patch hash was `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`; config snapshot hash `7af3bf2cb757cce7239a3c874c83cf61089cd9d76c46dbdb436cfc6b1eafdd0e`; sandbox config hash `f862ec3f1ebdff12824ba1b3f3ad8fce078557ac566fd2b89104799196a21eb2`; capability hash `7091e20f0d4fdbca15834b94c4d67c132f51ac0b122891b164c6a669a8915853`; command-spec hash `ef810445d282c54d3adb9eb3cd8100287268a496aa547c323ca06f401865cfc1`; Engineer transcript `art_f1d78ff985a44daab7fdc45153048663` hash `376b966a4b60c782590a5201bcb5a3ca791d7892469594cfe6f35fb6efcdd279`; Engineer evidence `art_a35f7d1729c546c58dd7710bbeb9c992` hash `4ffd60397563219b862d2a3ad2bb82aec8d187ac01acafa3287747e94366fd04`; Verifier transcript `art_3dcd251e6feb48739d11271a0620fc4b` hash `02137e13a2cfb882d118c33847f317f4fa5ee0e563f024ad10f5e1c17dce8f52`; Verifier evidence `art_d29806254af543d082aaa668a5ecffa7` hash `125a117f442bc96960a0afb9324972bf883212ce9323a0b0572788ba79a0ab4d`; Verifier verdict `art_cac0c47b95434ee68f56e6eb71479b0b` hash `827d932e1a05a4f946d42504543d1223233f1cf9dc9077aab4f861ea8dcc4a46`; cleanup `art_ac5809b82f1f4ac4b23f926cf1e04bdd` hash `0d5feff45f8931ff31b55f7faf0190c67ea83d9aac61df2431b55b8a41f04fbf`; EvidenceBundle `art_3a9a3ec4507b448fa4ce057374da6d62` hash `c6bb00fc640a41c35170d70f08c41015247cc45090c05178e385cfa6d7505dd3`; and BootstrapReport `art_5fe0d82e02df4fa898bcd63c1767b7ab` hash `2055c34a4e52d54974fd0f2bebce009a4b16f8cd622c000258b804f2533d55b1`. Completion was `verified_complete=true`, verdict `pass`, proof gaps empty, 72 ordered events and 16 run artifacts were persisted, cleanup left zero outstanding leases and zero managed containers, the outside-mount host sentinel remained present, neither the registered random raw sentinel nor its base64 form appeared in target or state bytes, and `.fleet/` was published only after success. This evidence was later superseded for delivery when the post-merge cancellation defect was found.

The initial PR #3 implementation/test tree passed `uv lock --check`, `uv sync --all-extras` (51 resolved, 49 checked), Ruff formatting across 148 files, Ruff lint, mypy across 126 source files, schema drift, and `git diff --check`. Test results were unit `330 passed in 11.10s`, contract `250 passed in 3.20s`, marked integration `87 passed, 47 deselected in 106.02s`, offline E2E `4 passed in 23.17s`, combined `719 passed, 7 skipped in 173.04s`, and the separately enabled real-Docker suite `6 passed in 12.72s`. The combined-suite skips were exactly six opt-in Docker tests and one opt-in live-provider test; the latter was not run and no live credential was used. Final `uv build --offline` produced wheel SHA-256 `5167551a198bf295e6b765b9f70833345ee4dfb9b3b6faf502783619d64d7588` and sdist SHA-256 `4b89a93a65de1ff2ed08c6391988af105a33c472f33c7d9affd7eb23825cba43`. Each archive contains 118 files, 28 public schemas, migrations `0001`–`0003`, and three runtime prompts; neither contains tests, `.agent`, a local project/acceptance path, or a known raw/encoded sentinel. The source, wheel, and sdist copies of `application/gateway.py` all hash to `8bfbbb63b360d9508531c8ed122bffbe5f1e364605cc5d3a5587a888011fb85e`. This matrix is historical rather than final repair evidence.

Candidate identity `158f81458804474faaad06556a1d5574330523c69f38605a47d53bf87da28011` was invalidated by the first fresh verifier's architecture finding and is not delivery evidence. Replacement candidate identity `8ea5a9f4da9d746c19a01df72a6e96ddd4f9471711fe48dccae9e07e112de684` covers 182 entries and hashes, in sorted path order, `mode + space + repository-relative path + NUL + SHA-256(file bytes)` for `git ls-files -co --exclude-standard`, excluding only this living plan. A different fresh read-only verifier independently recomputed the replacement identity unchanged at review start and end; ran 278 critical architecture/security/contract/integration tests, 21 recovery/CLI/distribution/migration tests, and 73 doctor/config/legacy/snapshot tests for 372 focused passes; repeated lock, Ruff, mypy, schema, diff, archive, and recurrence-probe checks; found no P0/P1/P2; and returned `PASS — FREEZE: YES`. It explicitly scoped the real Docker six-test suite, repaired-tree manual canary, and combined 719-test suite to primary-run evidence rather than falsely claiming to rerun them. Git commit, PR, and merge IDs cannot be embedded in the commit that creates them without a self-reference; they will be recorded in the GitHub record and final delivery report, while this plan records the pre-commit candidate identity and all reproducible verification evidence.

The post-merge cancellation repair supersedes that PR #3 delivery evidence. The exact final implementation/test tree passed `tests/unit/test_process_runner.py` on Python 3.12.14, 3.13.15, and 3.14.6 with `13 passed` on each version. The final focused cross-layer suite passed `226 passed`; two independent read-only reviews found no P0/P1/P2 and returned `FREEZE: YES`. The 12 most adversarial cancellation cases passed 25 consecutive iterations (`300/300`): timeout and output-overflow cancellation while termination proof was in flight, unproven group termination under continued cancellation, sandbox-creation cleanup success/failure precedence, public same-mode cancel/recovery joins, full execution -> sandbox -> worktree ordering, direct lease cleanup, live/completed conflicting-target rejection, cleanup retry, and ToolGateway ACTIVE/CREATING recovery.

Final repository gates passed `uv lock --check` (51 resolved), `uv sync --all-extras` (51 resolved, 49 checked), Ruff formatting across 148 files, Ruff lint, mypy across 126 source files, schema drift, and `git diff --check`. Test results were unit `341 passed in 13.61s`, contract `257 passed in 3.64s`, marked integration `93 passed, 49 deselected in 131.49s`, offline E2E `4 passed in 26.52s`, and combined `745 passed, 7 skipped in 225.97s`. The seven skips were exactly the six separately gated real-Docker tests plus the explicit live-provider canary. No live-provider call or credential resolution was attempted.

The final real gate used Docker client 29.8.0, server 29.5.2/API 1.54, context `colima`, local Unix endpoint `unix:///Users/blackswan/.colima/default/docker.sock`, Linux/arm64 daemon identity `815f9bce2b2930154aaaf49cf86667332a3b576d6b85a92ed070ff9d1a0971fb`, and immutable image `sha256:08a5a9124f184f29018f59c1abbe7015a0498a447d5aecd60b18029316465379`. The six-test suite passed `6 passed in 14.21s`; the original real timeout/output/cancellation/orphan test then passed 25 consecutive repetitions on the exact final tree. Every repetition verified attached cancellation cleanup evidence and exact-label absence; the final global `agent-fleet.managed=true` inventory was empty.

The final standalone bootstrap acceptance retained its state beneath `/Users/blackswan/Documents/projects/oss_agent_squad/.phase3-manual-acceptance-cancel-fix-final`. Preview produced proposal hash `b82322ef1bf9ee67902aac22921b1400d2065b7d35fe46095804fb0053960a48` without publishing `.fleet/` or registering the target. Verified initialization created target Project `prj_9cfd0dafd47749188e07a3e49c893cda`, canary Project `prj_d96ac8d97c144a1298037a340e19b754`, Run `run_82821c1c885c442fa93c5f80065a1131`, Task `task_3bcd307dc28e4cb48d64d5850896f879`, CoS `agent_baed740dbef34c83a5af46c26de6610f`, Engineer `agent_747893bad02d4521abcc79e500e8c7c3` with execution `exec_cc3c06632e6c4e0cbc7163c8977e06ca`, and fresh Verifier `agent_382cb26765d64936843fe08e801c4353` with execution `exec_b100217ded4048fc96f0e050a5e13898`. Engineer evidence `art_1374b36b52cb46ef9928c195495cf2b6` hash `5752abe2ad4bbe89e3dd298f3742ab9932da62ffea2bcbb0e0f39464b6a37c9b` was `observed`; Verifier evidence `art_de8707f0e8d54fa387391248530d1dfb` hash `bb4910772722c7e48c6393d168b45814ae4c32210bb31ef0be7cb08ef8e8e864` was `independently_verified`. Both exited zero with command-spec hash `ef810445d282c54d3adb9eb3cd8100287268a496aa547c323ca06f401865cfc1`; transcripts `art_6826d04125eb4859bfe311b34e3d7a79` hash `e8f4270ad8f305a3708261d800ce4551ff80c6cb5cb7067aaa37304a2bb4161f` and `art_c20a26acc3fe404182b12a942ddd2581` hash `3a2de24ce7b2c61fca0396091aad800e26848a71253fa38ac415c1b0d8aa4252` each contained exactly one Fleet boundary marker.

The acceptance patch hash was `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`; ConfigSnapshot artifact hash `3a913d627d785bc692f0b63880ac7abef174cd83542e6735cfffabbc8456f65c`; sandbox configuration hash `f862ec3f1ebdff12824ba1b3f3ad8fce078557ac566fd2b89104799196a21eb2`; capability hash `7091e20f0d4fdbca15834b94c4d67c132f51ac0b122891b164c6a669a8915853`; requirements hash `95d17048e7ebea0d8817bc35f4f18a299b900c9421a120f636de81227476518c`; preflight hash `5c865bcb84daca34dff1b0fd79cd65eab11c1138183aa5a64cc37eeaed14fc8b`. Verifier verdict `art_9cddb168962a4f9099c97424178e52d5` hash `581ba27391d78c0e431f8f1e5424f558bd1ded146e4adc1667d767c3aace2a2f`, cleanup receipt `art_efafdc64433c483f936e9b30878b71a3` hash `29a84bb8182f294c5fe939c865ee4b813a9b85aa38bb802310123250f89b809e`, EvidenceBundle `art_d889b4685b634d8f8772847eb6b50aa0` hash `3a0dc52496c4c04b997a1298e4b1b224ce4d20409ff352c8209c28dac46757d1`, and BootstrapReport `art_dc375e971c0f47a486435e231e5783dc` hash `f23d68e8676bef7630f5268831259eef82dccff3f642d4b4bc702284aad27963` all validated. Completion was `verified_complete=true`, verdict `pass`, zero proof gaps, 72 contiguous events, 16 run artifacts, zero outstanding leases/worktree entries/managed containers, target publication only after success, preserved outside-mount sentinel, and no raw or Base64 form of the random registered secret in target or state bytes.

The final documentation-bearing `uv build --offline` produced wheel SHA-256 `d3626070ec6fef4a7a198e13c439fe294d9cbb20ed326bfb301f144f48029e23` and sdist SHA-256 `619f21bd749841c8acc0a4c442fca1c2b0d09cf13c3f6406deaf1d4fea89153e`. Each contains 118 files, 28 public schemas, migrations `0001`-`0003`, and three prompts, with no tests, `.agent`, local acceptance path, or known sentinel. Source/wheel/sdist copies of all five repaired runtime modules match byte-for-byte; direct wheel import and `fleet version --json` passed against the locked environment. A dependency-cold `uv run --isolated --no-project --offline --with <wheel>` attempt failed before installation because the local uv cache lacked an installable PyYAML distribution; this is recorded as a packaging-environment limitation rather than claimed success.

The remaining security boundary is unchanged and explicit: numeric POSIX PGID absence is not an identity-proof mechanism against a hostile same-user process, Docker/Colima is not a VM boundary, the writable bind has no portable disk quota, `network=none` retains loopback, and cleanup coalescing/owner knowledge is process-local. Eliminating the PGID boundary requires a supervisor/cgroup/pidfd-class design. Phase 4 permissions, live provider behavior, hosted sandboxes, and future integrations were not started.

Frozen repair candidate identity `6eae0cbbc7ec8ebf4e875f99d6ecca282eceea71eaf6e36fa4ba32060df9022f` covers 182 entries. It is computed in sorted path order over `mode + space + repository-relative path + NUL + SHA-256(file bytes)` for `git ls-files -co --exclude-standard`, excluding only this living plan to avoid self-reference. Implementation/test review fingerprint `2aeeca5e6e772c8656ecdc0e6b29f66e7e705c885fc049dc8818ee147d382494` was independently reported unchanged at security-review freeze. The follow-up commit/PR/merge identities cannot be embedded in their own commit without self-reference and will be recorded in the GitHub record and final delivery report.
