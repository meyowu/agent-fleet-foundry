# Agent Fleet

Agent Fleet is a local-first control plane for reviewable agent work. This repository currently implements **Phase 0 and Phase 1 only**: a deterministic, offline CoS -> Engineer -> Verifier workflow backed by SQLite, content-addressed artifacts, real Git worktrees, and explicit patch review/application.

The runtime and sandbox in this release are fake adapters. They make orchestration, state, approval, and patch behavior reproducible, but they do **not** call a model, execute project tests, or provide OS isolation.

## Development setup

Python 3.12–3.14 and Git are required. `uv` is the preferred contributor tool.

```bash
uv sync --all-extras
uv run fleet version
uv run fleet doctor --json
```

Use `AGENT_FLEET_HOME` to place local state somewhere explicit. Tests always point it at a temporary directory.

## Offline fake quickstart

Start from a Git repository with at least one commit and the canary layout documented below. Initialization inspects files but does not execute repository code.

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet init /path/to/canary-repo --runtime fake --sandbox fake --yes
uv run fleet run "Fix the canary behavior" --project /path/to/canary-repo --runtime fake --sandbox fake
uv run fleet status <run-id>
uv run fleet logs <run-id>
uv run fleet artifacts <run-id>
uv run fleet patch show <run-id>
uv run fleet patch apply <run-id>
```

`fleet init` writes a validated minimal `.fleet/` tree after `--yes`, persists the exact proposal, and creates a disposable canary repository under the selected Fleet state directory. The direct init/run path safely tolerates only the exact unchanged `.fleet/` status produced by initialization. Any unrelated or later working-tree change makes run/apply fail closed.

The Phase 1 scripted workflow expects `src/canary_calc/core.py` in the target repository. It changes `divide(a, b)` so division by zero raises `ValueError("division by zero is not allowed")`. `--fake-scenario repair`, `fail`, `approval`, `inconclusive`, and `verifier_mutation` exercise deterministic negative paths. These are test/demonstration scripts, not model judgments.

For the approval scenario:

```bash
uv run fleet run "Fix the canary behavior" --project /path/to/canary-repo --fake-scenario approval
uv run fleet approve <request-id> --once
uv run fleet resume <run-id>
```

`fleet deny <request-id>` followed by `fleet resume <run-id>` rejects the run. Repeated resume does not repeat the recorded logical side effect.

## What is enforced now

- strict Pydantic v2 persistent/external models and safe YAML loading;
- explicit workflow transitions with transactional per-run events;
- SQLite migration `0001`, durable approvals, exact one-use grants, and resource leases;
- model-style writes routed through a trusted-context ToolGateway;
- canonical repository-relative path checks with traversal and symlink defenses;
- structured Git subprocess argv with no shell, reset, clean, stash, push, or implicit commit;
- separate candidate and verification worktrees; verifier mutations are discarded;
- control-plane-computed patch/hash and explicit apply with repository/base/status guards;
- content-addressed artifacts with read-time integrity checks;
- registered sentinel redaction for tests and rejection of a sentinel in candidate patches.

## Honest security limitations

`FakeSandboxProvider` is a recorder with `security_level=fake`; it is not a security boundary. Scripted PASS is not proof that project code ran. The current policy surface exists only to prove Phase 1 candidate writes, fake commands, and a single approval-bound fake side effect. There is no real provider, credential resolver, Docker isolation, general command executor, persistent trust store, exact always-allow rule, network access, external write, chat UI, or FleetPatch.

Local SQLite/events are append-only through the application API but are not tamper-proof against the local OS user. Git worktree cleanup force-removes only Fleet-owned paths beneath `AGENT_FLEET_HOME`; it never resets, cleans, stashes, or discards the target checkout.

Patch application updates the original working tree only. It does not stage, commit, merge, push, or create a pull request.

## Roadmap boundary

- Phase 2: BYOK secret references and `PydanticAIRuntimeAdapter`.
- Phase 3: Docker sandbox plus bounded real file/command tools.
- Phase 4: complete three-state policy and exact project-scoped persistent trust.
- Phase 5: persistent CoS chat and full real role workflow.
- Phase 6: reviewable FleetPatch organization updates.
- Phase 7: release hardening, cross-platform evidence, and owner license decision.

Do not treat this Phase 0/1 implementation as the security-ready MVP described by later roadmap gates.

## Quality gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python -m agent_fleet.schemas.generate --check
```

## Verification snapshot (2026-09-03)

The acceptance suite passed on Python 3.14.6, Git 2.50.1, and a repository-local `uv` 0.12.9 installation:

- formatting: `ruff format --check .` passed (`80 files already formatted`);
- lint: `ruff check .` passed;
- type checking: `mypy src tests` passed across 66 source files;
- tests: unit `21 passed`, contract `1 passed`, integration `22 passed`, offline subprocess E2E `2 passed`, and the combined suite `46 passed`;
- schema drift: `python -m agent_fleet.schemas.generate --check` passed;
- packaging: `uv build` produced both the source distribution and wheel, including the CLI, migration, and checked-in schema resources.

A separate disposable manual run exercised `doctor`, `init`, `run`, `status`, `logs`, `artifacts`, `patch show`, and `patch apply`. Doctor reported healthy with Docker explicitly optional/missing and providers deferred. The run reached `READY_FOR_REVIEW`, persisted 38 ordered events and seven run artifacts, and produced patch SHA-256 `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`. Applying it changed only the canary source behavior; independent assertions confirmed normal division and the zero-denominator `ValueError`, and `git diff --check` passed.

These results validate the deterministic offline Phase 0/1 boundary only. They do not establish model quality, execution isolation, real project-test execution, provider/network behavior, release-platform coverage, or the Phase 2-7 features listed above.

See `AGENTS.md`, `docs/`, and the active plan under `.agent/plans/` for architecture and security contracts.
