# AGENTS.md — Agent Fleet Foundry contributor instructions

## Mission

Build a production-minded, local-first, BYOK command-line product that lets a user interact with a persistent Chief of Staff (CoS). The CoS delegates bounded work to ephemeral specialist agents, beginning with an Engineer and an independent Verifier. The system must produce reviewable artifacts and verifiable evidence rather than merely simulate multi-agent conversation.

The system owns security and orchestration. Models may propose actions, but they never grant permissions, expose credentials, select their own security boundary, approve their own requests, or directly bypass the tool gateway.

## Read before changing code

For any nontrivial task, read the relevant files before editing:

1. `docs/PRODUCT_SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/SECURITY_MODEL.md`
4. `docs/CONFIG_AND_SCHEMAS.md`
5. `docs/IMPLEMENTATION_ROADMAP.md`
6. `.agent/PLANS.md`
7. The active plan under `.agent/plans/`, when one exists

Specifications are authoritative unless the user explicitly changes them. When a code change alters an architectural or security decision, update the corresponding documentation in the same change.

## Execution plans

Use an ExecPlan for any feature likely to span multiple modules, introduce a public contract, change persistence, affect security, or take more than a small focused edit. Follow `.agent/PLANS.md` exactly. Keep the plan current while working; do not write it once and then ignore it.

Implement one coherent vertical slice at a time. Keep the default branch runnable after every phase. Never create dozens of empty abstractions or commands that only print “not implemented.” A small working path is more valuable than a large placeholder architecture.

## Required technical direction

Unless an existing repository decision overrides it:

- Python 3.12 or newer within the supported range declared in `pyproject.toml`.
- Standard `src/` package layout with package name `agent_fleet`.
- Typer for CLI commands and Rich for human-readable terminal output.
- Pydantic v2 models for all external and persistent schemas.
- PydanticAI as the first real model/harness adapter, hidden behind project-owned protocols.
- SQLite for local durable state, with explicit schema migrations.
- Git worktrees for isolated candidate changes.
- Docker as the first real sandbox backend.
- A deterministic fake runtime and fake sandbox for tests.
- Async orchestration at model/tool/sandbox boundaries; avoid unnecessary async in pure domain logic.
- Structured logging and append-only run events.
- No mandatory hosted control plane.

Do not couple domain models to Typer, Rich, Docker SDK objects, PydanticAI internal message types, or provider SDK response types.

## Architecture boundaries

Maintain these dependency directions:

```text
cli -> application/control_plane -> domain
                         |-> ports/protocols
adapters --------------------^
```

- `domain`: pure types, policies, state transitions, validation, and errors.
- `application` or `control_plane`: use cases, workflow engine, scheduling, event emission, approvals, and orchestration.
- `ports`: project-owned protocols for runtime, models, sandbox, state, secrets, clock, IDs, and tools.
- `adapters`: PydanticAI, SQLite, Docker, Git, filesystem, keyring, and terminal implementations.
- `cli`: argument parsing and presentation only; it must not contain business rules.

The deterministic workflow engine coordinates CoS, Engineer, and Verifier. Do not implement the system as unrestricted group chat. Agent-to-agent work moves through typed task envelopes, artifacts, verdicts, and events.

## Security invariants

These rules are non-negotiable unless the repository owner explicitly changes the security model:

1. Every model-requested side effect passes through `ToolGateway` and `PermissionBroker`.
2. Permission decisions are exactly `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`.
3. Agent output is untrusted input. It is never an authorization decision.
4. Repository configuration may request permissions but cannot grant them.
5. Persistent trust rules live outside the repository in a user-controlled trust store.
6. Hard-deny rules cannot be overridden by project files, agents, FleetPatch, or ordinary approval prompts.
7. API keys and external credentials remain in the control plane and are never mounted into worker sandboxes.
8. Do not pass secrets in command arguments, logs, events, model context, generated patches, or exceptions.
9. Do not use `shell=True`, `sh -c`, `bash -c`, `eval`, or string-prefix command authorization in ordinary command execution.
10. Commands are represented as canonical executable-plus-argv structures. Shell scripts require a distinct, higher-risk capability and explicit approval.
11. Resolve and canonicalize paths, reject `..` escape, and account for symlinks before authorization.
12. Never silently fall back from an isolated sandbox to a local host process.
13. The unsafe local executor must be explicitly named and selected, and must emit a prominent warning.
14. Never mount `/`, the user home directory, SSH/cloud credential directories, browser profiles, or the Docker socket into a worker container.
15. Docker workers run non-root, drop capabilities, use `no-new-privileges`, receive resource/time limits, and have networking disabled by default.
16. “Always allow” grants a precise action/resource/condition scope; there is no ordinary global “allow everything forever.”
17. CoS cannot approve its own request or modify protected trust and audit controls.
18. Verifier-generated filesystem changes never become part of the accepted candidate patch.
19. External writes, pushes, deployments, destructive operations, and secret access remain approval-gated.
20. Audit events are append-only from the application’s point of view and must be redacted before persistence.

If an implementation shortcut conflicts with these invariants, choose the safer behavior and document the limitation.

## Coding rules

- Prefer small modules with explicit contracts over framework magic.
- Use precise domain-specific names. Avoid generic modules such as `utils.py`, `helpers.py`, or `manager.py` unless the scope is genuinely narrow and documented.
- Use enums or constrained literals for states and decisions; do not scatter magic strings.
- Use timezone-aware UTC timestamps.
- Inject clock and ID generation into logic that needs deterministic tests.
- Preserve exception causes and convert adapter failures into typed domain/application errors at boundaries.
- Never catch broad exceptions merely to continue. Mark a run failed or paused with actionable evidence.
- Validate all data read from YAML, JSON, SQLite, model structured output, and external tools.
- Make operations idempotent where retries are possible.
- Use atomic file writes for configuration and trust-store mutation.
- Use transactions for state transitions that must stay consistent.
- Do not log raw model prompts by default. Store only explicitly configured, redacted records.
- Prefer standard library functionality when it is clear and safe; add dependencies only for a concrete need.
- Do not change licenses, publish packages, push branches, create remote pull requests, or contact external services without explicit user direction.

## Testing contract

All ordinary tests must run without network access, external API keys, Docker, or a real model.

Minimum test layers:

- Unit tests for pure domain logic and policy evaluation.
- Contract tests for every protocol implementation.
- SQLite migration and recovery tests.
- CLI tests using Typer’s test runner.
- Fake-runtime workflow tests for success, rejection, approval pause/resume, retry limits, cancellation, and failure recovery.
- Security regression tests for path traversal, symlink escape, command injection, overly broad always-allow matching, secret redaction, self-approval, and protected-action denial.
- Optional Docker integration tests behind an explicit marker and environment check.
- PydanticAI adapter tests using its test/fake model facilities; no live provider calls in CI.
- End-to-end tests against a generated fixture Git repository.

A feature is incomplete when tests merely assert mocks were called. Assert persisted states, emitted events, artifacts, command scopes, diffs, and user-visible results.

## Quality commands

Keep these commands valid as the project evolves. Prefer `uv` for the contributor workflow while preserving standard Python package compatibility:

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
```

If the repository chooses a different equivalent tool, update this file and CI together.

## Documentation and decisions

Record material architecture choices as short ADRs under `docs/adr/`. An ADR must state context, decision, alternatives, and consequences. Do not create an ADR for routine implementation details.

Keep README examples executable and aligned with actual CLI behavior. Mark future functionality as roadmap, not as implemented.

## Completion requirements

Before reporting a task complete:

1. Re-read the user request and active ExecPlan.
2. Inspect the final diff for accidental scope expansion.
3. Run the focused tests plus the full local quality suite appropriate to the change.
4. Confirm no secret or machine-specific path entered tracked files.
5. Update docs, schemas, examples, and migration notes when relevant.
6. Summarize what changed, exact validation commands and results, known limitations, and the next roadmap phase.
7. Do not claim a security property that is not enforced by code or the underlying OS/runtime.
