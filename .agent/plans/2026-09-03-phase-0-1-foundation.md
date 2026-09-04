# Phase 0 and Phase 1 foundation

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

Build the first runnable Agent Fleet slice: a local, deterministic CLI that registers a Git repository, installs a reviewed minimal `.fleet/` configuration, drives a fake CoS -> Engineer -> Verifier workflow through the real control-plane boundaries, persists inspectable state and artifacts, pauses durably for a one-use approval, and produces a guarded patch that the user may explicitly apply.

A successful disposable flow will be:

```bash
AGENT_FLEET_HOME="$temporary_state" uv run fleet init "$temporary_repo" --runtime fake --sandbox fake --yes
AGENT_FLEET_HOME="$temporary_state" uv run fleet run "Fix the canary behavior" --project "$temporary_repo" --runtime fake --sandbox fake
AGENT_FLEET_HOME="$temporary_state" uv run fleet status <run-id>
AGENT_FLEET_HOME="$temporary_state" uv run fleet patch show <run-id>
AGENT_FLEET_HOME="$temporary_state" uv run fleet patch apply <run-id>
```

The output must label both fake adapters honestly. No model provider or project code executes in this phase.

## Scope

### In scope

- Installable Python 3.12+ package, `fleet` entry point, composition root, human Rich output, and versioned JSON envelopes.
- Phase 0 domain models, safe FleetSpec YAML loading, generated JSON schemas, stable typed errors, port protocols, SQLite migration `0001`, and content-addressed artifacts.
- Real Git inspection/worktree/diff/apply operations using structured argv and no shell.
- Deterministic fake runtime and fake sandbox adapters used through the same application ports as future adapters.
- Explicit persisted workflow through scope, candidate implementation, independent verification, bounded repair, presentation, review, apply, cleanup, cancellation, and rejection.
- Durable approval request, one-use capability issuance/consumption, denial, process reconstruction, idempotent resume, and fake logical side-effect evidence.
- Path-boundary, redaction, patch-integrity, verifier-mutation, dirty/diverged-apply, migration/recovery, CLI, integration, and subprocess E2E tests.
- README, contributor guidance, checked-in schemas, and exact validation evidence.

### Out of scope

- PydanticAI, live/provider model calls, credential resolution, model selection, or provider networking.
- Docker execution or claims of OS isolation; the only sandbox is explicitly `security_level=fake`.
- Persistent always-allow trust rules, run-wide grants, full Phase 4 permission policy, or user trust-store mutation.
- Chat/REPL, real model-driven tools, MCP/connectors, FleetPatch, remote Git writes, push/PR/deploy, packaging publication, and licensing.

## Current repository state

The implementation kit was extracted into the repository root and the directory was initialized as an empty Git repository on branch `main`. It currently contains only `AGENTS.md`, `.agent/PLANS.md`, the bootstrap/phase prompts, `README-FIRST.md`, and specifications under `docs/`; no Python package, tests, migration, README, lockfile, or prior implementation exists. `uv` is not installed on the host PATH, while the available interpreter is Python 3.14.6 and Git is 2.50.1. A repository-local bootstrap environment will be used to obtain `uv` without modifying user-level configuration.

Important terms: the **candidate workspace** is a Fleet-owned detached Git worktree where Engineer actions land; the **verification workspace** is a separate detached worktree reconstructed from the canonical patch; a **fake sandbox** records canonical executions and scripted results but provides no isolation; a **capability grant** is a persisted, exact, one-use authorization bound to one pending tool intent.

## Security impact

The implementation crosses repository, filesystem, subprocess, local persistence, approval, and artifact trust boundaries. `docs/SECURITY_MODEL.md` invariants for canonical intents, three-state decisions, no self-approval, exact one-use grants, no secrets in persisted output, path/symlink containment, no-shell subprocesses, worktree separation, verifier non-authority, append-only events, patch target checks, and no silent sandbox fallback apply.

- Repository content and `.fleet/` are untrusted requests; they cannot grant authority.
- All fake Engineer writes and fake command/side-effect requests pass through the application `ToolGateway` using trusted run/task/agent/stage identity.
- Phase 1 baseline policy allows only bounded candidate writes/fake verification commands, denies protected or out-of-scope actions, and requires user approval for the scripted logical side effect.
- Secret resolution is not implemented. A redactor accepts configured test sentinels; text persistence is redacted and patch persistence rejects registered sentinels.
- Git subprocesses use executable-plus-argv and optional stdin; never `shell=True`, a shell command, reset, clean, stash, push, or implicit commit.
- Worktrees and artifacts live beneath the configured Fleet state root. Only Fleet-owned worktrees may be force-removed during cleanup.
- Applying a patch is explicit. The control plane compares repository identity, HEAD, and an exact target-status fingerprint recorded at run start, then runs `git apply --check` before mutation.
- `.fleet/` files newly created by `fleet init` are the only dirty baseline tolerated for the documented immediate init/run journey, and only while their exact status fingerprint remains unchanged. Other dirty or diverged state is refused.
- Fake sandbox output is evidence of deterministic orchestration only and is never described as OS isolation or real test execution.

## Proposed design

The package follows the required direction:

```text
Typer CLI -> application services/workflow -> domain models and policies
                                  |-> project-owned ports
SQLite, local artifacts, Git, fake runtime, fake sandbox -> ports
```

`agent_fleet.bootstrap` will be the composition root. It selects only the explicitly requested fake adapters in this phase and injects a clock, ID generator, `SqliteStateStore`, `LocalArtifactStore`, `GitRepositoryAdapter`, `FakeRuntimeAdapter`, `FakeSandboxProvider`, redactor, gateway, workflow engine, approval/recovery/project/doctor services.

The SQLite store will run numbered SQL migrations and reject newer schema versions. Run transitions and their stage event will share one transaction; events receive a monotonically increasing per-run sequence. Artifacts are atomically written by SHA-256 content address and verified on read. Resource leases make candidate/verification worktrees and fake sandboxes recoverable.

The workflow is resumable from persisted run stage and idempotency keys:

```text
CREATED -> INTAKE -> SCOPING -> WORKSPACE_PREPARATION -> IMPLEMENTING
  -> PAUSED_FOR_APPROVAL -> IMPLEMENTING (resume)
  -> VERIFYING -> REPAIRING -> VERIFYING
  -> PRESENTING -> READY_FOR_REVIEW
  -> APPLYING -> CLEANUP -> COMPLETED
```

Verifier FAIL after the repair bound becomes `REJECTED`; denial becomes `REJECTED`; cancellation becomes `CANCELLED` after Fleet resource cleanup. Candidate and verifier worktrees are removed after the patch/verdict are persisted, while a paused candidate lease is retained for resume. The canonical patch is computed by Git and never trusted from runtime output.

The fake runtime uses an injected script scenario for success, terminal failure, repair-then-pass, approval pause, and verifier-mutation tests. The public CLI defaults to success and exposes an explicitly named `--fake-scenario` only for deterministic demonstrations/tests. Scripted actions remain typed runtime output and are executed or rejected by ToolGateway rather than directly by the runtime.

## Public contracts

- Commands: `fleet version`, `fleet doctor [--json]`, `fleet init`, `fleet run`, `fleet status`, `fleet logs`, `fleet artifacts`, `fleet patch show`, `fleet patch apply`, `fleet approve <id> --once`, `fleet deny <id>`, `fleet resume`, and `fleet cancel`.
- State location: `AGENT_FLEET_HOME` overrides the platform-specific local data directory for testing and reproducible demos.
- Config: strict `agentfleet.dev/v1alpha1` FleetSpec subset using safe YAML and structured verification commands.
- Models: project, run/status/stage, task, role/agent instance, event, artifact, workspace, approval, grant, tool intent/result, sandbox execution, patch, fake role outputs, and versioned CLI envelope.
- Protocols: clock, ID generation, state, artifacts, runtime, sandbox, repository, secret store placeholder, event sink.
- Database: migration `0001` creates migration/project/run/task/agent/event/artifact/approval/grant/intent/resource-lease tables with foreign keys and idempotency/sequence constraints.
- Exit behavior: success and durable pause are successful commands; typed errors use stable category exit codes and versioned JSON error envelopes.
- Compatibility: only `v1alpha1`, runtime `fake`, and sandbox `fake` are accepted in Phase 0/1. Future values fail with actionable errors rather than falling back.

## Milestones

### Milestone 1: Executable Phase 0 foundation

Create packaging, core domain/config/error models, ports, migration/store, artifact storage, schema generation, composition root, version/doctor, and focused unit/contract tests.

Acceptance:

- Package installs in the project environment and `fleet version` plus both doctor renderings execute.
- Safe YAML rejects unknown fields, custom tags, aliases, traversal, and unsupported API versions.
- Migration/reopen, transition/event transaction ordering, artifact hash/integrity, schema no-diff, and path tests pass.

### Milestone 2: Git-backed deterministic success and rejection

Add reusable temporary Git fixture construction, Git worktree adapter, ToolGateway baseline, fake runtime/sandbox, explicit workflow, artifacts, event history, successful/rejected/repair/verifier-mutation tests, and inspection CLI commands.

Acceptance:

- A real temporary Git fixture yields a control-plane-computed patch with exact expected content and hash.
- PASS reaches `READY_FOR_REVIEW`; repeated FAIL reaches `REJECTED`; repair reaches PASS once; verifier mutations are detected/discarded.
- Candidate/verifier/fake-sandbox resource events and leases have safe cleanup behavior.

### Milestone 3: Durable approval, apply, cancellation, and recovery

Add approval/grant transactions, resume/deny behavior, guarded patch apply, cancellation cleanup, orphan recovery, and security regressions.

Acceptance:

- A separate service/CLI reconstruction can approve once and resume a paused run.
- Grant consumption and logical side effect occur once even under repeated resume.
- Denial and cancellation are durable and non-executing; orphaned fake/Fleet resources recover.
- Dirty, diverged, traversal, symlink, prefix-collision, and secret-sentinel cases fail safely without data loss.

### Milestone 4: CLI E2E, documentation, and final quality gate

Complete human/JSON command tests, subprocess E2E installation/execution, manual temporary-repository demo, README/CONTRIBUTING, final diff/security review, and all quality commands.

Acceptance:

- The documented init/run/inspect/show/apply path works in subprocesses against a generated real Git repository and the applied source has the expected behavior.
- Formatting, lint, mypy, unit/integration/E2E, and full pytest commands all pass.
- README and this ExecPlan record exact results and Phase 2-7 limitations without overstating fake execution.

## Detailed implementation steps

1. Add `pyproject.toml`, `.gitignore`, package metadata/entry point, supported Python range, dependencies, Ruff/mypy/pytest settings, and contributor documentation.
2. Define strict Pydantic domain models, stable ID generation, timezone validation, transition policy, canonical serialization/hashing, typed error codes, redaction, and secure logical-path resolution.
3. Define minimal project-owned protocols in `src/agent_fleet/ports/` without concrete-framework imports.
4. Add SQL migration `0001`, migration runner, and explicit SQLite operations for all Phase 1 aggregates, transactional run transitions/events, exact grant reservation, idempotent intent completion, and resource leases.
5. Implement atomic content-addressed artifact storage plus application artifact metadata registration and integrity checking.
6. Implement strict safe FleetSpec YAML loading/proposal generation, `.fleet/` boundary validation, deterministic JSON Schema generation, and checked-in schemas.
7. Implement the structured-argv Git repository adapter: inspect, worktree create, patch compute/hash, verification reconstruction/mutation check, safe cleanup, and guarded apply.
8. Implement `FakeSandboxProvider`, scripted `FakeRuntimeAdapter`, application permission baseline, `ToolGateway`, workflow engine, project initialization, approvals, recovery, doctor, inspection, patch, and cancellation services.
9. Implement the Typer/Rich CLI and versioned JSON envelope, mapping typed errors to stable exit codes with redaction.
10. Build reusable fixture factories and unit, contract, integration, CLI, security, and subprocess E2E tests for every required Phase 0/1 path.
11. Generate schemas, install/sync dependencies locally, run focused tests iteratively, then run the full quality suite and manual demo.
12. Review tracked content for unsafe subprocess use, machine paths, secrets, placeholders, unsupported claims, and scope leakage; update README and plan outcomes.

## Validation plan

Focused validation will include:

- `uv run pytest -q tests/unit`
- `uv run pytest -q tests/integration`
- `uv run pytest -q tests/e2e`
- `uv run python -m agent_fleet.schemas.generate --check`
- CLI tests with `typer.testing.CliRunner` and subprocess invocations using temporary `AGENT_FLEET_HOME`/Git repositories.
- Negative tests for unsafe YAML, path traversal, absolute paths, prefix collision, symlink escape, invalid transitions, event rollback, artifact corruption, approval mismatch/denial, duplicate resume, dirty/diverged apply, verifier mutation, cancellation/recovery, and secret redaction.

Final required commands:

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
```

The manual demo will create all repository/state files below a temporary directory, commit the canary baseline, initialize Fleet, run the fake flow, inspect artifacts/events/patch, apply it, and independently execute or inspect the fixed canary behavior. Exact exit codes and test counts will be added to `Outcomes`.

## Rollback and recovery

All repository mutation is explicit. `.fleet/` proposal application uses staging and atomic per-file replacement; a validation failure leaves the target unchanged. Candidate and verifier worktrees are recorded before use and cleanup is idempotent. Startup/manual recovery may remove only active leases whose paths are beneath Fleet state and whose runs are terminal/orphaned; approval-paused candidate worktrees are retained.

Artifact writes use temporary files plus atomic replace and are safe to retry by content hash. Migration `0001` is transactional; a newer unknown schema is refused instead of downgraded. Run stages use idempotency keys. Approval consumption reserves an exact intent once before fake execution and repeated resume reads the persisted result. Ambiguous real external effects are out of scope.

Patch apply first performs identity, HEAD, exact status-fingerprint, hash, and `git apply --check` validation. Failure does not reset, stash, clean, or overwrite user state. Once applied, a repeat returns the recorded result. A user can abandon cleanup through cancellation for in-progress Phase 1 runs; accepted source changes are never silently rolled back.

## Progress

- [x] (2026-09-03 22:20 PDT) Extracted the kit, read `AGENTS.md`, `.agent/PLANS.md`, every `docs/` specification, bootstrap prompt, and phase prompt; inspected the empty implementation state.
- [x] (2026-09-03 22:22 PDT) Initialized the extracted directory as a local Git repository and recorded tool availability (`uv` absent, Python 3.14.6, Git 2.50.1).
- [x] (2026-09-03 22:48 PDT) Built Milestone 1 packaging, strict domain/config schemas, ports, migration `0001`, content-addressed artifacts, schema generation, version/doctor, and focused tests; `21 passed` for `tests/unit tests/contract`.
- [x] (2026-09-03 22:58 PDT) Built Milestone 2 real Git worktrees/patch extraction, deterministic role/sandbox adapters, explicit workflow, verifier separation, inspection commands, and PASS/FAIL/repair/inconclusive paths; integration suite reached `17 passed` before the final inconclusive addition.
- [x] (2026-09-03 23:02 PDT) Built Milestone 3 durable exact approval, reconstructed-service resume, duplicate-resume protection, denial, guarded apply, cancellation, terminal-lease recovery, injection/path/redaction regressions; subprocess patch E2E passed.
- [x] (2026-09-03 23:28 PDT) Completed Milestone 4 CLI/E2E coverage, documentation, package build, security review, and disposable manual init/run/inspect/apply validation; final suite reached `46 passed`.

## Discoveries

- Observation: The delivered kit was an archive containing only specifications; the extracted directory had no Git metadata or implementation.
  Evidence: Initial `git status` returned “not a git repository,” and the file inventory contained only the kit documents.
  Consequence: Initialize local Git metadata and treat this as a greenfield build; there is no legacy code or migration compatibility to preserve.
- Observation: `uv` is not on PATH, but Python 3.14.6 is available.
  Evidence: `uv --version` returned command-not-found; `python3 --version` returned 3.14.6.
  Consequence: Bootstrap `uv` inside a repository-local ignored tooling environment, then use it for the required workflow without changing user-global locations.
- Observation: Applying the required `.fleet/` tree makes a newly initialized repository dirty, while the requested demonstration immediately runs a code task and patch application normally rejects dirty targets.
  Evidence: `PRODUCT_SPEC.md` requires init to apply `.fleet/`; the bootstrap command sequence places `fleet run` immediately after init; security specifications require target-state checks.
  Consequence: Permit only the exact unchanged `.fleet/` status snapshot produced by init as a recorded run baseline. Any other or changed dirty state is refused, and patch apply must match the complete recorded status fingerprint.
- Observation: Rich line wrapping inserts literal newlines into a serialized JSON string, which makes long CLI envelopes invalid JSON in captured and narrow terminals.
  Evidence: Initial CLI integration tests failed `json.loads` on wrapped doctor/init/error output while the underlying envelope validated.
  Consequence: JSON mode uses plain `typer.echo(json.dumps(...))`; Rich remains exclusively for human-readable presentation.
- Observation: A fresh process can reconstruct a fake sandbox handle from its persisted lease without retaining in-memory adapter state.
  Evidence: Approval-pause integration reconstructed the complete composition root, issued a one-use grant, resumed, and reached `READY_FOR_REVIEW`; a repeated reconstruction/resume preserved a single consumption/execution event.
  Consequence: Treat fake handles as deterministic lease metadata in Phase 1; real resource reconciliation remains a Phase 3 concern.
- Observation: A normal `git worktree add` can execute repository-controlled checkout hooks or clean/smudge filters before Fleet evaluates candidate content.
  Evidence: Security regression fixtures registered malicious `post-checkout` and smudge-filter sentinels; the hardened worktree path left both sentinels absent while preserving the expected tracked files.
  Consequence: Create worktrees detached with `--no-checkout`, disable hooks and global/system configuration on every Git subprocess, read the tree without checkout, and materialize blobs through `git cat-file` with path/symlink validation.
- Observation: Direct adapter imports in application services would invert the required dependency direction even if runtime behavior remained correct.
  Evidence: A final import-boundary audit found configuration and diagnostics services coupled to concrete adapters before correction.
  Consequence: Configuration and system-diagnostics capabilities now flow through project-owned ports; automated architecture tests reject future application/domain/ports imports from adapters.

## Decision Log

- Decision: Use the extracted `agent-fleet-codex-kit/` directory as the repository root and initialize branch `main` without committing.
  Rationale: The kit explicitly targets an empty Git repository, and implementation/tests need repository-local status while the user did not authorize publishing or commits.
  Alternatives: Implement in the archive’s parent or copy files upward; both would mix the source tree with the retained ZIP and weaken the intended root layout.
  Date: 2026-09-03
- Decision: Support only explicit `fake` runtime and sandbox values and fail closed for every other value.
  Rationale: This meets Phase 0/1 while preventing accidental PydanticAI, provider, Docker, or unsafe-host scope expansion.
  Alternatives: Add placeholder adapters or silent fallback; prohibited by the roadmap and security model.
  Date: 2026-09-03
- Decision: Keep one-use approval semantics exact and persisted, but defer run/always grants and generalized trust policy to Phase 4.
  Rationale: Phase 1 requires durable proof of the reservation/consumption shape, while full policy is explicitly later work.
  Alternatives: A boolean approved flag is unsafe and explicitly forbidden; a full Phase 4 engine would expand scope.
  Date: 2026-09-03
- Decision: Treat fake command results as orchestration evidence, not behavioral proof; independently validate applied canary behavior in E2E/manual tests executed by the test/demo harness outside the fake sandbox.
  Rationale: FakeSandbox must never execute or claim isolation, but the E2E acceptance still requires verification of the resulting real patch behavior.
  Alternatives: Execute project code in FakeSandbox or describe scripted PASS as real testing; both would violate phase boundaries/honesty.
  Date: 2026-09-03
- Decision: Persist and present an `INCONCLUSIVE` fake-verifier scenario as reviewable with an explicit proof gap, rather than treating it as PASS or rejection.
  Rationale: The runtime contract requires PASS/FAIL/INCONCLUSIVE, and the architecture permits presenting an inconclusive result honestly for human review.
  Alternatives: Collapse it into FAIL or PASS; either loses the specified semantics.
  Date: 2026-09-03
- Decision: Require Fleet state to live outside the target repository and defer state-root creation until initialization has validated that boundary.
  Rationale: Keeping SQLite, artifacts, canaries, and worktrees outside the target prevents self-observation, recursive dirty state, and accidental persistence into user source.
  Alternatives: Permit in-repository state or create it before validation; both weaken status fingerprints and may mutate a rejected target.
  Date: 2026-09-03
- Decision: Materialize Git worktrees from canonical Git objects rather than invoking checkout machinery.
  Rationale: Repository hooks, attributes, and filters are untrusted executable configuration; object materialization preserves repository bytes without executing them.
  Alternatives: Rely only on disabled hooks or a standard checkout; clean/smudge filters and inherited configuration would remain an execution path.
  Date: 2026-09-03

## Outcomes

Phase 0 and Phase 1 are complete. The repository now contains an installable layered Python package, strict `v1alpha1` configuration and generated schemas, transactional SQLite migration/state, content-addressed artifacts, hardened real Git worktree/patch handling, deterministic fake runtime and sandbox adapters, ToolGateway policy enforcement, durable exact one-use approvals, recovery/cancellation, a Typer/Rich CLI with JSON envelopes, contributor documentation, and unit/contract/integration/offline-E2E coverage.

Acceptance results on Python 3.14.6, Git 2.50.1, and repository-local `uv` 0.12.9:

- `uv sync --all-extras`: passed with the lockfile unchanged.
- `uv run ruff format --check .`: passed; 80 files were already formatted.
- `uv run ruff check .`: passed.
- `uv run mypy src tests`: passed; no issues across 66 source files.
- `uv run pytest -q tests/unit`: 21 passed.
- `uv run pytest -q tests/contract`: 1 passed.
- `uv run pytest -q tests/integration`: 22 passed.
- `uv run pytest -q tests/e2e`: 2 passed.
- `uv run pytest -q`: 46 passed.
- `uv run python -m agent_fleet.schemas.generate --check`: passed with no schema drift.
- `uv build`: passed and produced both sdist and wheel with the CLI, migration, and schema resources present.

The independent disposable manual demonstration reported a healthy fake-only doctor result, initialized the target, reached `READY_FOR_REVIEW`, exposed 38 ordered events and seven artifacts, showed patch SHA-256 `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`, and applied the patch after all guards. The source diff only added the zero-denominator `ValueError`; independent Python assertions passed and `git diff --check` remained clean.

Remaining limitations are deliberate: runtime and sandbox behavior is scripted and provides neither real model judgment nor OS isolation; no project tests are executed by Fleet; provider calls, BYOK resolution, Docker, generalized commands, network/external writes, persistent always-allow trust, chat, FleetPatch, push/PR/deploy, licensing, and release-platform hardening remain Phase 2-7 work. Patch application modifies only the original working tree and never stages, commits, merges, pushes, or opens a PR. The local database is inspectable and append-only through application APIs but is not tamper-proof against the local OS user. This implementation is therefore a verified offline foundation, not the later security-ready MVP.
