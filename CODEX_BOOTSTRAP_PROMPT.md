# First Codex task — implement Phase 0 and Phase 1

You are the lead engineer for this repository. Build the first working vertical slice of Agent Fleet, a local-first BYOK multi-agent coding CLI whose primary interface will be a Chief of Staff.

Before editing anything:

1. Read `AGENTS.md` in full.
2. Read `.agent/PLANS.md`.
3. Read all files under `docs/`, especially `PRODUCT_SPEC.md`, `ARCHITECTURE.md`, `SECURITY_MODEL.md`, `CONFIG_AND_SCHEMAS.md`, and `IMPLEMENTATION_ROADMAP.md`.
4. Inspect the current repository and Git status.
5. Create `.agent/plans/<today>-phase-0-1-foundation.md` using the required ExecPlan format. Keep it updated during implementation.

## Scope for this task

Implement **Phase 0 and Phase 1 only** from `docs/IMPLEMENTATION_ROADMAP.md` as a coherent, runnable vertical slice. Do not start real model-provider calls, PydanticAI integration, or Docker execution yet. Those are later phases. However, shape the project-owned protocols so those adapters can be added without moving workflow/security logic out of the control plane.

The final result of this task must support a fully deterministic, offline flow with fake adapters and a real temporary Git fixture:

```bash
uv sync --all-extras
uv run fleet version
uv run fleet doctor --json
uv run fleet init <temporary-git-repo> --runtime fake --sandbox fake --yes
uv run fleet run "Fix the canary behavior" --project <temporary-git-repo> --runtime fake --sandbox fake
uv run fleet status <run-id>
uv run fleet logs <run-id>
uv run fleet artifacts <run-id>
uv run fleet patch show <run-id>
uv run fleet patch apply <run-id>
```

Exact argument placement may differ when a cleaner Typer design requires it, but document and test the actual commands. Do not expose commands that only return “not implemented.”

## Required implementation decisions

### Project setup

- Use Python 3.12+, `src/agent_fleet`, Typer, Rich, Pydantic v2, SQLite, pytest, Ruff, and mypy.
- Prefer `uv` for contributor commands while keeping a standard installable Python package.
- Add the `fleet` console entry point.
- Add a composition root that injects ports into application services.
- Do not add a license without an explicit owner decision.

### Architecture

Implement clear `domain`, `application`, `ports`, `adapters`, and `cli` boundaries. Domain and application code must not import Typer, Rich, Docker, or future harness/provider objects.

Add only the protocol methods required for this vertical slice. Avoid speculative method forests.

At minimum, implement project-owned ports for:

- clock and ID generation;
- state store;
- artifact store;
- runtime adapter;
- sandbox provider;
- repository/Git operations;
- secret store interface or placeholder contract with no resolved secret in this phase;
- event sink if distinct from state store.

### Domain and persistence

Implement typed models and state transitions sufficient for:

- Project;
- FleetSpec Phase 0 subset;
- Run, RunStatus, WorkflowStage;
- TaskSpec;
- AgentSpec/AgentInstance for CoS, Engineer, Verifier;
- FleetEvent with per-run sequence;
- Artifact metadata and content hash;
- candidate/verification workspace metadata;
- approval request and one-use capability grant shape needed for the Phase 1 pause/resume test;
- typed errors with stable codes.

Create SQLite migration `0001` and a migration runner. Enable foreign keys, use transactions for state transition plus event persistence, and prevent incompatible schema use. Use a content-addressed local artifact directory outside the target repository.

Normal tests must use temporary directories and must not write to the developer’s real user config/data directories.

### Deterministic runtime

Implement `FakeRuntimeAdapter` as a real testable adapter, not a special code path inside the workflow engine.

It must support scripted outputs for:

- CoS scoping a canary task;
- Engineer producing a candidate change through ToolGateway-compatible application operations;
- Verifier returning PASS, FAIL, or INCONCLUSIVE;
- a repair iteration;
- an approval-requiring intent.

The same WorkflowEngine and services must later accept a real runtime adapter.

### Fake sandbox

Implement `FakeSandboxProvider` that:

- reports `security_level=fake`;
- records canonical `ExecRequest` values;
- returns deterministic stdout/stderr/exit data;
- supports timeout/failure scripts;
- never claims OS isolation;
- participates in resource leases and cleanup.

Do not implement or invoke Docker in this task.

### Repository and Git fixture

Implement a control-plane Git adapter using structured subprocess argv and no shell.

Create tests that generate a real temporary Git repository containing a tiny canary defect and failing behavioral test. Suggested fixture:

```text
pyproject.toml
src/canary_calc/core.py
src/canary_calc/__init__.py
tests/test_core.py
```

Use Git worktrees for candidate changes. The fake runtime should cause a deterministic candidate edit. The control plane must compute the actual patch and hash rather than trusting an Engineer report.

Create a separate verification workspace from the candidate. Any Verifier workspace mutation must be discarded and must not enter the candidate patch.

Before patch application, verify recorded target identity/base and working-tree assumptions. Never reset, clean, stash, or discard user changes. A dirty or diverged target must produce a typed refusal and remediation.

### Bootstrap behavior

Implement `fleet init` for a Git repository with fake runtime/sandbox flags. It should:

1. inspect the repository without executing project code;
2. register local project state;
3. generate a minimal proposed `.fleet/` tree in staging;
4. validate it;
5. apply it only with `--yes` or interactive confirmation;
6. never store a secret;
7. run or expose a deterministic disposable canary path without touching unrelated business code;
8. emit and persist events/artifacts.

For this phase, provider/model configuration may use an explicit fake value. Make README clear that live providers arrive in Phase 2.

### Workflow engine

Implement an explicit state machine with validated transitions:

```text
CREATED
-> INTAKE
-> SCOPING
-> WORKSPACE_PREPARATION
-> IMPLEMENTING
-> VERIFYING
-> optional REPAIRING -> VERIFYING
-> PRESENTING
-> READY_FOR_REVIEW
-> optional APPLYING
-> CLEANUP
-> COMPLETED
```

Also support `PAUSED_FOR_APPROVAL`, `FAILED`, `CANCELLED`, `REJECTED`, and `ABANDONED` as appropriate.

Every stage must persist an event and enough output to inspect/recover. Bound the repair loop. Invalid transitions fail explicitly.

### Approval pause/resume in Phase 1

Implement a minimal canonical ToolIntent and decision path sufficient to prove durable approval behavior. A scripted fake scenario must:

1. produce an intent requiring approval;
2. persist ApprovalRequest and mark the run paused;
3. exit cleanly;
4. allow another CLI process to run `fleet approve <id> --once` or `fleet deny <id>`;
5. resume the run;
6. consume a one-use grant transactionally;
7. not execute the logical side effect twice when resume is repeated.

Do not implement full persistent user always-allow rules yet; that is Phase 4. Do not undermine the future design with a global boolean approval flag.

### CLI

Implement real commands required by Phase 0/1:

- `fleet version`;
- `fleet doctor [--json]`;
- `fleet init`;
- `fleet run`;
- `fleet status`;
- `fleet logs`;
- `fleet artifacts`;
- `fleet patch show`;
- `fleet patch apply`;
- `fleet approve --once`;
- `fleet deny`;
- `fleet resume`;
- `fleet cancel` if the application path is complete in this phase.

Human output uses Rich. Machine output uses the versioned JSON envelope from `CONFIG_AND_SCHEMAS.md`. Keep business rules out of CLI functions.

The run command must clearly label the fake runtime/sandbox and never imply that fake validation is a real model or OS security boundary.

### Security constraints for this task

Even though Phase 1 is fake/offline, implement the architecture without known bypasses:

- no `shell=True`, `sh -c`, `bash -c`, or command authorization by string prefix;
- no arbitrary absolute model paths;
- canonical workspace paths;
- no secrets in repository/state/events;
- no direct model/harness tool execution outside ToolGateway abstraction;
- no silent destructive Git operations;
- no verifier changes in accepted patch;
- no repository config granting itself authority;
- no unsafe host executor masquerading as sandbox;
- redact configured sentinel secrets in tests.

### Tests

Add meaningful tests, not only mock-call assertions.

Required coverage:

- domain state-transition rules;
- FleetSpec validation and safe YAML behavior;
- SQLite empty migration and reopen;
- transactional state transition plus event ordering;
- artifact content hash/integrity;
- complete successful E2E fake run against a temporary Git fixture;
- verifier FAIL and REJECTED result;
- one repair iteration then PASS;
- approval pause, process/service reconstruction, approve, resume;
- repeated resume does not duplicate the side effect;
- denial path;
- cancellation and resource cleanup;
- recovery of an orphaned fake resource lease;
- verifier workspace mutation discarded;
- patch hash and exact changed content;
- dirty/diverged target refuses apply without losing files;
- CLI human and JSON behavior;
- path traversal/prefix-collision/symlink tests for any path boundary implemented;
- secret sentinel absent from events/logs/errors/artifacts;
- schema regeneration produces no diff.

Use reusable fixture builders rather than enormous tests.

## Implementation process

- Work milestone by milestone from the ExecPlan.
- Run focused tests continuously.
- If a specification detail is internally inconsistent, choose the smallest secure interpretation, document it in the ExecPlan Decision Log, and continue.
- Do not ask for branding, provider/model choices, remote integrations, or licensing during this task.
- Do not use network access for implementation unless dependencies genuinely must be installed and the environment requires it.
- Do not push, publish, open a remote PR, or modify anything outside this repository and test temp directories.

## Definition of done

Before stopping:

1. Run:

   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src tests
   uv run pytest -q
   ```

2. Run at least one documented manual CLI demo against a temporary repository.
3. Inspect the final diff for architecture leakage, placeholder commands, machine-specific paths, secrets, and unsafe Git behavior.
4. Update the active ExecPlan’s `Progress`, `Decision Log`, and `Outcomes`.
5. Update README with:
   - what works now;
   - quickstart for the fake vertical slice;
   - what remains for Phases 2–7;
   - honest security limitations.
6. Report:
   - files/components added;
   - exact commands and results;
   - E2E behavior demonstrated;
   - important decisions;
   - remaining limitations;
   - the next recommended phase.

Do not claim completion merely because interfaces exist. Completion requires the offline end-to-end run, durable evidence, patch application guard, approval resume test, and passing quality suite.
