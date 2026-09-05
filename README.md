# Agent Fleet

Agent Fleet is a **local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization**. A user gives goals to one Chief of Staff (CoS); the control plane assembles the smallest valid team, constrains its authority and execution boundary, and delivers reviewable changes with evidence.

It is deliberately not a generic multi-agent chat framework or a permanent roster of named bots. Models propose scope, plans, actions, and organizational changes. Deterministic application code validates those proposals, owns permissions and sandbox selection, computes the canonical patch, and decides what the available evidence can prove.

This repository implements **Phase 0 through Phase 3**: deterministic repository profiling, adaptive FleetPlans, an independent baseline PermissionBroker, content-addressed evidence, real Git worktrees, guarded patch review/application, explicit BYOK PydanticAI, and a hardened local Docker execution boundary. The deterministic fake runtime remains available for offline development and tests; no live model-provider call is required for the Phase 3 bootstrap canary.

Three sandbox providers are registered. `DockerSandboxProvider` is the isolated path and creates one inspected, resource-bounded, network-disabled container per reviewed command from an already-local immutable image. `FakeSandboxProvider` records commands without executing them. `LocalUnsafeSandboxProvider` executes directly on the host only after a separate `--allow-unsafe-local` confirmation and can never count as isolated evidence. Provider selection is exact and immutable for a project/run; Docker failure never falls back to host execution.

## Product north star

Six capabilities determine whether Agent Fleet provides differentiated value:

| Capability | Current implementation boundary | Remaining target |
|---|---|---|
| Repository-aware bootstrap | **Enforced:** bounded static inspection finds supported ecosystems, build systems, boundaries, exact candidate commands, provenance, confidence, and ambiguities; preview is read-only; init stages the proposal, runs a disposable canary through the normal Docker workflow, validates a hash-linked `BootstrapReport`, proves cleanup, and only then publishes `.fleet/`. | The canary is a deterministic Fleet-owned fixture; executing arbitrary target-repository setup or networked commands remains out of scope. |
| Adaptive Fleet | **Enforced subset:** every fake or PydanticAI run persists a validated `FleetPlan`; repository scopes use canonical, case-insensitive conflict checks; `direct`, `single_engineer`, and `engineer_verifier` create only their planned role instances. | Parallel and Researcher/Architect scheduling remain unimplemented and fail closed, although their domain shapes are validated. |
| Independent permission control plane | **Enforced baseline:** ToolGateway injects an independent `PermissionBroker`; canonical actions receive `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`, with default deny, decision events, and exact allow-once persistence. | Allow-for-run, exact persistent project trust, revoke/explain, and an independently reviewed user-scope ceiling remain Phase 4. |
| Independent sandbox abstraction | **Enforced local slice:** strict `SandboxRequirements` matching dispatches exact fake, Docker, or separately confirmed local-unsafe providers. Docker pins a local Unix daemon and image ID, inspects effective configuration before start, bounds execution, and recovers exact labeled resources. | Modal and hosted providers, approved network modes, and a multi-user/remote-daemon trust model remain unimplemented. |
| Evidence-first delivery | **Enforced:** exact ConfigSnapshot, TaskSpec, FleetPlan, patch, command inspection/transcript, verdict, cleanup, BootstrapReport, risk, and proof-gap links form content-addressed evidence. Only fresh non-mutating Docker verifier evidence can become independently verified; fake/local-unsafe remain non-verifying. | General criterion-by-criterion model mapping and broader project command/tool coverage remain bounded future work. |
| Versioned Fleet evolution | **Contract only:** FleetPatch has dedicated ID prefixes, case-insensitive unique paths, base-hash/protected-path checks, exact content hashes, and required pre-parse plus typed whole-proposal registered-secret scanning. | Proposal persistence, semantic/text diff commands, apply, audit, and rollback remain Phase 6; there is no operational FleetPatch CLI. |

“Enforced” means a property is checked by code and tests at the named boundary. “Partial” means a real subset exists but does not yet satisfy the complete product claim. “Roadmap” means documentation or schema direction only; it must not be presented as executable behavior. See [ADR 0001](docs/adr/0001-product-north-star.md) for the decision and tradeoffs.

## Development setup

Python 3.12–3.14 and Git 2.45 or newer are required. The Git floor is needed for the hardened `--no-lazy-fetch` execution ceiling. `uv` is the preferred contributor tool.

```bash
uv sync --all-extras
uv run fleet version
uv run fleet doctor --json
```

Use `AGENT_FLEET_HOME` to place local state somewhere explicit. Tests always point it at a temporary directory.

## Docker sandbox and verified bootstrap

Docker mode requires a local Linux Docker daemon reachable through a local Unix socket and an image that already exists locally. Fleet never pulls or builds an image, accepts a remote/TCP daemon, or falls back to another provider. The supplied test runner image can be built explicitly by the operator:

```bash
docker build --pull \
  -t agent-fleet-runner:phase3 \
  -f tests/docker/Dockerfile.runner .

export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet doctor \
  --path /path/to/repo \
  --sandbox docker \
  --docker-image agent-fleet-runner:phase3 \
  --json

uv run fleet init /path/to/repo \
  --runtime fake \
  --sandbox docker \
  --docker-image agent-fleet-runner:phase3 \
  --preview --json

uv run fleet init /path/to/repo \
  --runtime fake \
  --sandbox docker \
  --docker-image agent-fleet-runner:phase3 \
  --yes
```

The final init command first runs a disposable fake-runtime/real-Docker canary through the ordinary workflow. It publishes `.fleet/` only after the final patch, independent verifier command, terminal container inspection, cleanup receipt, completion decision, and `BootstrapReport` hashes all validate. A fake or local-unsafe sandbox can preview the proposal but cannot satisfy this publication gate.

The opt-in real-Docker suite never runs implicitly:

```bash
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:phase3 \
uv run pytest -q -m docker_integration tests/docker/test_real_docker.py
```

On macOS with Colima, pytest's temporary root must be under a host path shared into the VM; pass `--basetemp="${HOME}/.cache/agent-fleet-docker-tests"` when the system temp directory resolves beneath `/private/var`.

## Runtime selection and BYOK

The two registered runtimes are `fake` and `pydantic-ai`. The real adapter accepts only explicit `openai:<model>` and `openai-chat:<model>` identifiers. There is no provider inference or fallback: every other prefix fails closed before credential resolution or network access.

BYOK configuration uses a strict `env:NAME` reference. The reference comes from the user's `fleet init` command and is persisted only in Fleet-owned local state; `.fleet/fleet.yaml` records the runtime and opaque provider/model ID, never the credential reference or value. Resolved values must be 8–16384 bytes of visible ASCII, which rejects control characters before HTTP-header construction. The raw value remains in trusted control-plane memory, is registered with the shared redactor, and is passed explicitly to the provider client. It is not put in repository configuration, prompts, artifacts, events, worker input, or the process environment by Agent Fleet.

Preview validates the runtime/model/reference shape and the complete proposed `.fleet/` patch, but does not read the referenced environment variable, migrate or write Fleet state, write the repository, construct a provider client, or use the network. Initialization resolves the environment reference before any project state or `.fleet/` write; it does not make a model request. `fleet run` revalidates the exact registered runtime/model/reference, resolves the credential, and only then may cross the trusted control-plane HTTPS boundary to the selected provider.

Initialization is fail-closed rather than an in-place `.fleet/` reconfiguration command. Repeating the same generated tree is safe, and changing only the Fleet-owned credential reference can succeed because it does not change repository files. If a new runtime, provider/model, or sandbox would change an existing generated `.fleet/` tree, init returns a stable error before Project/artifact state or repository mutation. Review the new `--preview`, move the entire conflicting generated `.fleet/` tree aside, and rerun explicit init; Fleet will not overwrite a mixed or partially changed tree.

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
# Set OPENAI_API_KEY through your normal secure environment mechanism.

uv run fleet init /path/to/repo \
  --runtime pydantic-ai \
  --provider-model openai:gpt-5-mini \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker \
  --docker-image agent-fleet-runner:phase3 \
  --preview --json

uv run fleet init /path/to/repo \
  --runtime pydantic-ai \
  --provider-model openai:gpt-5-mini \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker \
  --docker-image agent-fleet-runner:phase3 \
  --yes

uv run fleet doctor --path /path/to/repo --json
uv run fleet run "Fix the canary behavior" --project /path/to/repo --sandbox docker
```

Use `openai-chat:<model>` only when the OpenAI Chat Completions model path is intended; `openai:<model>` uses the Responses model path. Run-time provider flags are optional when they match the reviewed project registration; if supplied, they must match exactly. `--fake-scenario` is rejected for `pydantic-ai`.

`fleet doctor` inspects whether the selected environment reference is configured and valid without resolving/returning its value and without contacting a provider. The Phase 2 OpenAI client pins `https://api.openai.com/v1`, disables SDK redirects, retries, and ambient proxy/CA discovery, clears ambient OpenAI organization/project/admin/webhook selections, and supplies the explicitly resolved authorization value. A final request hook validates the SDK-merged method, endpoint, headers, content length, and serialized body before send; a response hook rejects registered-secret material and removes provider-controlled headers before OpenAI SDK parsing/logging. `OPENAI_BASE_URL`, proxy variables, and unrelated OpenAI identity variables cannot redirect the selected BYOK credential. A generated doctor report exits zero even when `data.healthy` is false: exit zero means diagnostics completed, while readiness is expressed by `data.healthy` and the individual required checks. A missing PydanticAI credential is a failed required check; the fake runtime reports `not_selected` and does not require a provider credential. A command-level Fleet error still returns its documented nonzero category.

The live smoke test is deliberately opt-in and destructive only to its generated disposable fixture. Configure the referenced variable through a secure environment mechanism, then run:

```bash
export AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=1
export AGENT_FLEET_LIVE_PROVIDER_MODEL='openai:gpt-5-mini'
export AGENT_FLEET_LIVE_PROVIDER_CREDENTIAL_REF='env:OPENAI_API_KEY'
uv run pytest -q -m live_provider tests/live/test_provider_smoke.py
```

Without all explicit opt-in inputs, pytest skips the live case. The Phase 2 acceptance recorded here did **not** run it because no explicit test credential was supplied.

## Offline preview and fake test mode

Start from a Git repository with at least one commit. Preview performs repository-aware discovery without executing repository code or writing Fleet state:

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet init /path/to/canary-repo --preview --json
```

`fleet init --preview --json` returns RepositoryProfile, ProjectKnowledge, every proposed `.fleet/` file, and a unified diff without creating `.fleet/` or `AGENT_FLEET_HOME`. Semantic profile hashes and serialized artifact hashes use explicitly different fields. Registered secrets in repository-derived profile/configuration data are rejected before parsing, output, or any Fleet write; malformed YAML errors do not retain registered values in their exception chain.

Fake mode remains deterministic test infrastructure and supports legacy Phase 0–2 project registrations, but it cannot prove an isolated bootstrap. A public `fleet init --runtime fake --sandbox fake --yes` therefore runs the canary, returns `BOOTSTRAP_CANARY_FAILED`, and leaves the target `.fleet/` unpublished. Use the Docker quickstart above for a new verified registration.

The init/run path safely tolerates only the exact unchanged `.fleet/` status and referenced configuration contents produced by initialization. Configuration loading accepts only bounded regular non-symlink files. A changed referenced file is rejected before run creation even when Git's untracked-file status is textually unchanged, and explicit patch apply rechecks the run-bound ConfigSnapshot as well as repository/base/status identity. Differing `.fleet/` reinitialization also fails before Fleet state changes rather than overwriting the existing tree. Repository and Fleet-state roots must be disjoint in both directions. Real and fake runtimes use the same workflow, artifacts, gateway, permission broker, and completion gate.

The code-change scripted workflow expects `src/canary_calc/core.py` in the target repository. It changes `divide(a, b)` so division by zero raises `ValueError("division by zero is not allowed")`. `--fake-scenario direct` creates no specialist workspace, `single_engineer` creates one Engineer, and the default creates Engineer plus fresh Verifier. `repair`, `fail`, `approval`, `inconclusive`, and `verifier_mutation` exercise bounded negative paths. The mutation scenario is denied by PermissionBroker before a write. These are test/demonstration scripts, not model judgments.

For an existing fake registration or the test harness, the approval scenario is:

```bash
uv run fleet run "Fix the canary behavior" --project /path/to/canary-repo --fake-scenario approval
uv run fleet approve <request-id> --once
uv run fleet resume <run-id>
```

`fleet deny <request-id>` followed by `fleet resume <run-id>` rejects the run. Repeated resume does not repeat the recorded logical side effect.

After a control-plane crash, recovery is deliberately scoped to one known Run and is not
performed as a blanket startup sweep. First confirm that no other Fleet process still owns the
Run, then invoke:

```bash
uv run fleet recover <run-id> --confirm-owner-stopped --json
```

The command marks an interrupted `RUNNING`/`APPLYING` Run failed and reconciles only its
persisted leases. It is idempotent for an already terminal, fully cleaned Run and refuses durable
states such as `PAUSED_FOR_APPROVAL`, which must use `resume` or `cancel` instead.

## What is enforced now

- strict Pydantic v2 persistent/external models and safe YAML loading;
- type-specific stable ID prefixes for persistent and public identity fields, including project, run, task, agent, event, approval, grant, artifact, intent, lease, workspace, sandbox, plan, and FleetPatch IDs;
- explicit workflow transitions with transactional per-run events;
- SQLite migrations `0001`–`0003`, durable approvals, exact one-use grants, provider/image/daemon-bound Projects and Runs, and recoverable worktree/sandbox/execution leases;
- repository-aware no-execution profiling with provenance, ambiguity, read/entry/depth limits, and symlink defenses;
- repository-specific FleetSpec/verification proposals plus immutable profile/knowledge artifacts;
- exact content-addressed ConfigSnapshot and TaskSpec bindings for each run, status inspection, and patch apply;
- validated per-run FleetPlans and dynamic direct/single/pair role instantiation;
- model-style writes routed through ToolGateway and an independently injected PermissionBroker;
- permission-decision events and exact role/stage/action/resource/sandbox matching;
- intrinsically coherent sandbox capability reporting and exact requirement matching across fake, Docker, and separately confirmed local-unsafe providers, with no fallback;
- fixed-path Docker CLI resolution; local-Unix/Linux-daemon, API/capability, immutable-image, and image-environment preflight; one container per command with non-root identity, dropped capabilities, no-new-privileges/seccomp, read-only root, network none, private namespaces, exact mounts/tmpfs/environment, and CPU/memory/no-swap/PID/shm/file-descriptor bounds;
- effective Docker inspection before start, direct argv only, bounded output and process-group timeout/cancellation handling, exact full-ID/11-label cleanup, installation-scoped recovery, and a durable pre-dispatch checkpoint that prevents command replay after crashes;
- descriptor-relative, no-follow workspace reads/searches/writes/deletes with inode/type/size/path ceilings; `.git` is shadowed from containers and remains control-plane-only;
- canonical repository-relative path checks with traversal, symlink, filesystem-identity, case-folded protected-path, and bidirectional state/repository containment defenses;
- structured Git subprocess argv with no shell, reset, clean, stash, push, or implicit commit;
- separate candidate and verification worktrees; verifier mutation intents are denied;
- control-plane-computed patch/hash and explicit apply with repository/base/status guards;
- content-addressed artifacts with read-time integrity checks;
- canary-before-publication bootstrap staging with a hash-linked `BootstrapReport`; target `.fleet/` publication requires independently verified Docker evidence plus complete cleanup and never accepts fake/local-unsafe claims;
- structured command evidence and EvidenceBundle/CompletionGate assurance, expanded in `fleet run/status` as changed paths, command results, verdicts, risks, proof gaps, and reason codes;
- recursive registered-secret rejection across mapping keys and values before bootstrap preview/configuration, package prompt/tool/output-schema model input, provider response/tool execution, final serialized provider request, ToolIntent, task, event, approval, or artifact persistence, plus redaction for trusted user-authored diagnostics;
- exact runtime selection with typed capability preflight and no implicit fallback;
- strict `env:NAME` BYOK references, environment-backed inspection/resolution, opaque secret values, and dynamic redaction of raw and common encoded forms;
- strict PydanticAI `ScopeDecision`, `ImplementationReport`, and `VerifierVerdict` outputs plus provider-neutral usage records and bounded provider metadata;
- role- and stage-bound PydanticAI tools whose execution always crosses `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`; whole deferred batches receive side-effect-free catalog schema validation first, then authorized candidate writes use the Fleet-owned candidate-worktree primitive while fake command/approval fixtures use `FakeSandboxProvider`;
- provider errors, timeouts, invalid output, and budget/retry exhaustion mapped to stable Fleet errors without persisting raw provider responses or SDK objects;
- ordinary adapter, integration, CLI, and E2E coverage with live model requests and sockets denied.

## Honest security limitations

`FakeSandboxProvider` is a recorder with `security_level=fake`, `isolation_enforced=false`, and `executes_code=false`; it is not a security boundary. `LocalUnsafeSandboxProvider` executes with the Fleet process's host authority and is also not isolation. Neither can publish a verified bootstrap or turn a model Verifier PASS into `verified_complete=true`.

Docker isolation assumes the local OS account, Docker CLI/configuration, daemon, kernel/VM, and preloaded runner image are trusted. Docker daemon access is itself highly privileged. Fleet accepts only a pinned local Unix endpoint and Linux daemon, but it does not isolate against another process running as the same host user. Workspace and `.git` shadow inode identities are checked at logical sandbox creation, before command preparation, and again after the final daemon probe immediately before dispatch; there remains an unavoidable same-user bind-source replacement window before the daemon consumes the mount request. The Phase 3 real gate was run on one macOS arm64/Colima Linux configuration, not every Docker/kernel/filesystem combination.

Only `network=none` is accepted by the isolated Phase 3 path. Images must already exist locally and may expose only the allowlisted environment defaults; Fleet does not build, pull, patch, or attest their supply chain. Cgroup-v2 daemons may report `MemorySwappiness=null`; Fleet accepts that only while the inspected memory and memory-swap hard limits are equal, which proves no container swap allocation. A crash after the durable create-dispatch checkpoint but before an exact Docker ID is persisted is intentionally conservative: zero label matches remain `FAILED`, parent resources stay intact, and no command is replayed. If the resource appears later, the operator reruns exact-run recovery after confirming the old owner stopped; a permanent zero remains outstanding for diagnosis rather than becoming an unsafe absence claim. Phase 3 has no cross-process owner-liveness lock, so it intentionally does not run destructive recovery automatically on every CLI startup.

Phase 3 still cannot map one overall model verdict independently to multiple acceptance criteria: a multi-criterion task is reported as inconclusive with `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`. The current policy surface covers bounded candidate operations, exact reviewed verification commands, and one approval fixture. CoS-proposed `allowed_paths` are canonicalized and conflict-checked, but there is no separately reviewed natural-language user path ceiling; target-checkout mutation still requires explicit patch review/apply. A complete allow-for-run/always-allow/revoke/explain trust store belongs to Phase 4. There is no approved worker networking, remote/hosted sandbox, arbitrary shell surface, external write, persistent CoS chat, parallel specialist scheduler, keyring/second-provider integration, or operational FleetPatch apply/rollback workflow.

The BYOK external boundary is provider HTTPS from the trusted control-plane process. Model prompts and selected project/task context are therefore disclosed to that provider according to its terms. `max_total_tokens` is enforced from provider-reported usage after each response and before continuations/tools; it is not a pre-spend billing ceiling, so a first or final request can report more total tokens than remained. `max_tokens` still bounds requested output. The response hook runs before OpenAI SDK response handling, but Fleet does not install global logging filters: a caller that programmatically enables low-level transport (`httpx2`/`httpcore2`) DEBUG logging may log transport metadata before that hook. Normal Fleet CLI operation and `OPENAI_LOG` do not enable those low-level loggers. Provider-native shell, filesystem, MCP, hosted tools, and arbitrary model-selected network tools are disabled. Installed adapter code shares the control-plane process's OS authority; isolation from arbitrary third-party adapter code is not claimed.

Local SQLite/events are append-only through the application API but are not tamper-proof against the local OS user. Git worktree cleanup force-removes only Fleet-owned paths beneath `AGENT_FLEET_HOME`; it never resets, cleans, stashes, or discards the target checkout.

Git subprocesses resolve an absolute executable outside repository/Fleet-state-controlled `PATH` entries using lexical, canonical, and filesystem-identity containment; require stable top-level/git-dir/common-dir identity; ignore global/system config; disable hooks, fsmonitor, replacements, lazy fetching, credentials, signing, and external diffs; reject any repository-local executable filter/diff/hook/include surface without copying its name into a later argv; and use only an explicit subcommand allow-list. Invalid repository errors omit unresolved canonical paths and underlying untrusted exception chains. This is a strong Phase 1.5 ceiling, not a multi-user isolation boundary: a same-OS-user process can still race repository-local config between the non-executing config probe and a later Git command. Git output is not yet byte-capped, and a parent-process timeout does not prove that malicious descendants were reaped. A future shadow Git metadata/index boundary plus process-group/output enforcement is required before hostile multi-user repositories are in scope.

Patch application updates the original working tree only. It does not stage, commit, merge, push, or create a pull request.

## Roadmap boundary

- Phase 1.5: completed offline foundation—repository profiling, validated adaptive FleetPlan, independent PermissionBroker, sandbox capabilities, EvidenceBundle/CompletionGate, and FleetPatch schema validation.
- Phase 2: implemented explicit BYOK `env:NAME` references and the PydanticAI runtime behind the project-owned runtime/tool contracts.
- Phase 3: completed local Docker sandbox, bounded file/command tools, deterministic recovery, and evidence-gated bootstrap.
- Phase 4: complete three-state policy and exact project-scoped persistent trust.
- Phase 5: persistent CoS chat and full real role workflow.
- Phase 6: reviewable FleetPatch organization updates.
- Phase 7: release hardening, cross-platform evidence, and owner license decision.

Phase 0–3 establishes the local isolated execution and evidence foundation, but the broader security-ready MVP still depends on the Phase 4 permission lifecycle and later product gates.

## Quality gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python -m agent_fleet.schemas.generate --check
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:phase3 \
uv run pytest -q -m docker_integration tests/docker/test_real_docker.py
```

## Verification snapshot (Phase 1.5 baseline, 2026-09-04)

The Phase 0/1.5 acceptance suite passed offline on Python 3.14.6, Git 2.50.1 (Apple Git-155), `uv` 0.12.9, Ruff 0.16.6, mypy 1.20.2, and pytest 9.1.1:

- dependency reconciliation: `uv sync --all-extras` passed with 29 packages resolved and 28 checked;
- formatting: `ruff format --check .` passed across 107 files;
- lint: `ruff check .` passed;
- type checking: `mypy src tests` passed across 91 source files;
- tests: an independent read-only acceptance run reported unit `188 passed in 1.41s`, contract `18 passed in 1.52s`, integration `95 passed in 85.02s`, offline subprocess E2E `3 passed in 8.41s`, and the combined suite `304 passed in 99.23s`;
- schema drift: `python -m agent_fleet.schemas.generate --check` passed;
- packaging: `uv build` produced `dist/agent_fleet-0.1.0.tar.gz` and `dist/agent_fleet-0.1.0-py3-none-any.whl`; archive inspection confirmed the CLI, migration, and new ConfigSnapshot/TaskSpec/FleetPlan/sandbox/command/evidence/FleetPatch schemas are included;
- patch hygiene: `git diff --check` passed.

The independent verifier also reran the UTF-8 output-boundary attack, Git/YAML/FleetPatch security probes, package archive inspection, and implementation/path/credential scans. It returned PASS with candidate identity `8be5e049a0af0220202b2ca6472e316718a436ee9e3f00a23f7640f2e0f03e21` unchanged from the start through the end of the review.

A separate disposable manual run exercised Python and Node repository previews, `doctor`, `init`, `run`, `status`, `logs`, `artifacts`, `patch show`, and `patch apply`. Both previews identified the correct ecosystem and wrote no repository or state files. Doctor reported healthy. The fake run reached `READY_FOR_REVIEW` with `engineer_verifier`, persisted 48 ordered events and 12 run artifacts, reported `verified_complete=false` with `PROOF_GAPS_PRESENT` and `SIMULATED_EVIDENCE_ONLY`, and produced patch SHA-256 `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`. Applying it changed only `src/canary_calc/core.py`; independent behavioral assertions and `git diff --check` passed.

## Verification snapshot (Phase 2 local candidate, 2026-09-04)

The Phase 2 candidate passed the required offline matrix on Python 3.14.6, Pydantic 2.13.5, PydanticAI 2.39.0, OpenAI SDK 3.8.0, Git 2.50.1 (Apple Git-155), `uv` 0.12.9, Ruff 0.16.6, mypy 1.20.2, and pytest 9.1.1:

- `uv lock --check` and `uv sync --all-extras`: passed; 51 packages resolved and 49 checked;
- `uv run ruff format --check .`: 129 files already formatted; `uv run ruff check .`: passed;
- `uv run mypy src tests`: passed across 108 source files;
- unit: `279 passed in 8.70s`; contract: `68 passed in 2.40s`; marked integration: `84 passed, 38 deselected in 87.89s`; offline subprocess E2E: `3 passed in 17.90s`;
- combined `uv run pytest -q`: `473 passed, 1 skipped in 133.23s`; the one skip was the explicitly gated live-provider canary;
- schema drift and `git diff --check`: passed;
- `uv build --offline`: passed; wheel and sdist each contain 97 files, including 3 runtime prompts, 17 JSON Schemas, and migrations `0001`/`0002`, with no tests or `.agent` plan files;
- the newly built wheel imported directly and `fleet version --json` returned `0.1.0` against the locked dependency environment; a dependency-cold, network-disabled venv install was not claimed because the local uv cache lacked PyYAML.

The opt-in live-provider smoke was **NOT RUN: no explicitly supplied credential**. Fleet did not discover or reuse an ambient credential. These results establish the adapter, control-plane, persistence, security, packaging, and offline workflow behavior—not live model quality, provider availability, Docker isolation, real project-test execution, a pre-spend token ceiling, hostile low-level transport logging protection, deterministic natural-language path intent, or cross-platform release coverage. The living Phase 2 ExecPlan records the final frozen identity and independent-verifier result before delivery.

## Verification snapshot (Phase 3 candidate, 2026-09-04)

The Phase 3 candidate passed its final offline matrix on the frozen implementation and test tree:

- `uv lock --check` and `uv sync --all-extras`: passed; 51 packages resolved and 49 checked;
- `uv run ruff format --check .`: 148 files already formatted; `uv run ruff check .`: passed;
- `uv run mypy src tests`: passed across 126 source files;
- unit: `330 passed in 11.10s`; contract: `250 passed in 3.20s`; marked integration: `87 passed, 47 deselected in 106.02s`; offline subprocess E2E: `4 passed in 23.17s`;
- combined `uv run pytest -q`: `719 passed, 7 skipped in 173.04s`; six skips were the separately gated real-Docker cases and one was the explicitly gated live-provider canary;
- schema drift and `git diff --check`: passed;
- `uv build --offline`: passed; wheel and sdist each contain 118 files, including 28 JSON Schemas, migrations `0001`–`0003`, and all three runtime prompts, with no tests, `.agent` plan files, local project path, or registered acceptance-secret sentinel.

The opt-in real-Docker suite then passed `6 passed in 12.72s` against Docker CLI 29.8.0, Docker server 29.5.2, Colima's local Unix endpoint, Linux/arm64 daemon identity `815f9bce2b2930154aaaf49cf86667332a3b576d6b85a92ed070ff9d1a0971fb`, and immutable image `sha256:08a5a9124f184f29018f59c1abbe7015a0498a447d5aecd60b18029316465379`. A post-suite exact-label query found zero Fleet-managed containers.

A disposable fake-runtime/real-Docker bootstrap acceptance on the repaired composition root produced read-only proposal hash `b82322ef1bf9ee67902aac22921b1400d2065b7d35fe46095804fb0053960a48`, canary Run `run_b610d8af67ce4e549534dd37bcd4ed32`, final patch hash `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`, capability hash `7091e20f0d4fdbca15834b94c4d67c132f51ac0b122891b164c6a669a8915853`, and command-spec hash `ef810445d282c54d3adb9eb3cd8100287268a496aa547c323ca06f401865cfc1`. Fresh Engineer execution `exec_f3e092b89e3f4c1e8da8e9b6e68adaa3` and Verifier execution `exec_c1fcb4780b9f4353b18a2b53a844bae6` both exited zero and each emitted exactly one Fleet-owned boundary marker. EvidenceBundle `art_3a9a3ec4507b448fa4ce057374da6d62` had hash `c6bb00fc640a41c35170d70f08c41015247cc45090c05178e385cfa6d7505dd3`; BootstrapReport `art_5fe0d82e02df4fa898bcd63c1767b7ab` had hash `2055c34a4e52d54974fd0f2bebce009a4b16f8cd622c000258b804f2533d55b1`. The result was `verified_complete=true`, verdict `pass`, zero proof gaps, 72 ordered events, 16 run artifacts, zero outstanding leases, zero remaining managed containers, target `.fleet/` publication only after success, an intact outside-mount host sentinel, and no raw or base64-encoded registered-secret sentinel in target or state bytes.

This establishes the Phase 3 local Docker boundary on the tested macOS arm64/Colima configuration, not every Docker/kernel/filesystem combination. Docker still shares the host kernel rather than providing a VM boundary, Fleet has no portable disk quota for the writable workspace bind, and `network=none` retains container loopback. Exact-run crash recovery is deliberately operator-confirmed because Phase 3 has no cross-process owner-liveness lock. The opt-in live-model-provider smoke was **NOT RUN** and no live credential was used; Phase 3 acceptance used the deterministic fake runtime to test the real sandbox and evidence path.

See `AGENTS.md`, `docs/`, and the active plan under `.agent/plans/` for architecture and security contracts.
