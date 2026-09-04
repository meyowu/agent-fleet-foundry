# Follow-up Codex prompts

Use these only after the previous phase is complete, reviewed, and committed or otherwise checkpointed. Each prompt assumes Codex will read `AGENTS.md`, all relevant `docs/` files, and the previous ExecPlan outcomes.

---

## Phase 2 prompt — PydanticAI and BYOK

Implement Phase 2 from `docs/IMPLEMENTATION_ROADMAP.md`: BYOK provider configuration and the first real `PydanticAIRuntimeAdapter`.

Before editing:

1. inspect Git status and the current implementation;
2. read `AGENTS.md`, `.agent/PLANS.md`, all relevant `docs/`, and previous phase plans;
3. create a new living ExecPlan for Phase 2;
4. identify the exact existing runtime/tool/config boundaries and preserve them.

Requirements:

- Add PydanticAI only inside `adapters/runtime/` and the composition/configuration layer.
- Treat provider/model identifiers as opaque strings; do not hardcode a single vendor or current model name.
- Implement `env:NAME` secret references first and OS keyring only if it can be done cleanly within this phase.
- Resolve secrets only in the control plane. Never persist, log, put in CLI argv, pass to tools, or expose to worker configuration.
- Register all resolved secret values with redaction before provider calls.
- Use project-owned Pydantic output models for CoS scoping, Engineer reports, and Verifier verdicts.
- Expose only project ToolGateway wrappers to PydanticAI. Do not enable a framework-native shell, filesystem, coder, browser, or MCP tool that bypasses PermissionBroker.
- Map provider usage and errors into project types; do not leak provider/PydanticAI objects through ports.
- Validate runtime capabilities before a run.
- Keep `FakeRuntimeAdapter` and all offline tests working.
- Use PydanticAI test/fake model support for CI; no live API call in the ordinary suite.
- Add an opt-in manual live-provider canary command/test with explicit environment gating and no automatic execution.
- Update `fleet init`, `fleet doctor`, configuration schema, README, and examples.

Security tests must prove a sentinel API key is absent from events, logs, exceptions, artifacts, tool inputs, and sandbox specs. Tests must assert only expected tools are registered.

Run all quality commands and record exact evidence in the ExecPlan. Do not begin Docker or full always-allow implementation in this phase.

---

## Phase 3 prompt — Docker sandbox and ToolGateway

Implement Phase 3 from `docs/IMPLEMENTATION_ROADMAP.md`: the real Docker sandbox, bounded file/command tools, and ToolGateway execution path.

Create and maintain a Phase 3 ExecPlan before substantial edits.

Requirements:

- Implement `DockerSandboxProvider` behind the existing `SandboxProvider` port.
- Use structured Docker/subprocess argv with no shell.
- Enforce non-root worker, capability drop, no-new-privileges, no privileged mode, no Docker socket, no host home/root/credential mounts, default network none, resource/time/output limits, and explicit candidate-workspace mount.
- Keep model/provider credentials entirely outside worker environment and mounts.
- Implement `LocalUnsafeSandboxProvider` only under the explicit name `local-unsafe`, with explicit user selection and prominent warnings. Never silently fall back to it.
- Add trusted-context ToolGateway wrappers for bounded list/read/search/write/edit/delete/diff/command operations.
- Implement path canonicalization and symlink/prefix-collision defenses.
- Implement `CommandSpec` as executable plus argv, minimal environment allowlist, no shell, timeout, output cap, and artifact-backed transcripts.
- Keep Git/worktree creation, diff extraction, and patch application in the trusted control plane. Do not broadly mount `.git` metadata merely to make worker Git commands work.
- Support honest network modes only: `none` and approval-gated `approved-unrestricted`. Do not claim domain allowlisting.
- Add resource leases, startup inspection, cancellation cleanup, and failure cleanup.
- Make `fleet doctor` report Docker and isolation details.
- Make the recommended bootstrap canary run inside Docker.

Normal tests remain offline and Docker-free. Add opt-in Docker integration tests that inspect actual user, mounts, environment, networking, security flags, limits, host-sentinel inaccessibility, timeout, cleanup, and no unsafe fallback.

Do not begin broad external connectors or MCP. Run all quality commands and update documentation with enforced properties and remaining limitations.

---

## Phase 4 prompt — PermissionBroker and exact always-allow

Implement Phase 4 from `docs/IMPLEMENTATION_ROADMAP.md`: complete three-state permissions, durable approvals, capability grants, and exact project-scoped always-allow.

Create a Phase 4 ExecPlan. Treat `docs/SECURITY_MODEL.md` as the authoritative acceptance contract.

Requirements:

- Implement canonical ToolIntent and canonical resource types.
- Trusted application context supplies identity, role, run, task, workflow, stage, and sandbox; reject model attempts to override them.
- Implement `ALLOW`, `DENY`, and `REQUIRE_APPROVAL` with stable decision codes and explanations.
- Enforce hard denies, user policy, project requests, role/workflow/task scope, active grants, and sandbox capabilities as an intersection.
- Implement one-use, run-scoped, expiring, revocable grants with transactional consumption.
- Bind approvals to a canonical intent hash and revalidate target state at resume.
- Implement user trust storage outside the repository with schema validation, atomic writes, restrictive permissions where supported, project identity binding, rule IDs, and revocation.
- Implement CLI commands for approve once, approve run, approve always exact project scope, deny, list, explain, revoke, and reset.
- “Always allow” must preserve exact action/resource/principal/project/workflow-stage/sandbox/command/path/network conditions. Do not expose global shell/network/filesystem wildcards.
- Protected actions may not receive ordinary conversational always-allow grants.
- CoS, Engineer, and Verifier cannot approve requests.
- A denial must not trigger an equivalent policy-bypass workaround.
- Persist complete redacted audit events.

Implement all applicable security tests in `SECURITY_MODEL.md`, including traversal/symlink, command-compound mismatch, wrong project/run/stage, expired/exhausted/revoked grant, self-approval, repository self-grant, protected actions, changed intent, isolation mismatch, duplicate resume, and secret redaction.

Demonstrate manually that approving `uv run pytest -q` always for one project does not approve a different argv, project, unsafe executor, network condition, or shell compound command.

Run all quality commands and document the exact policy semantics. Do not begin FleetPatch in this phase.

---

## Phase 5 prompt — complete CoS/Engineer/Verifier product flow

Implement Phase 5 from `docs/IMPLEMENTATION_ROADMAP.md`: the complete real Chief-of-Staff user journey, bounded multi-agent workflow, and durable chat/recovery behavior.

Create a Phase 5 ExecPlan and begin by mapping the existing state machine, runtime, ToolGateway, permission, sandbox, repository, and artifact contracts.

Requirements:

- Add `fleet chat` as a durable line-oriented REPL; do not overinvest in a full-screen TUI yet.
- Support `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, and `/exit`.
- CoS converts a user goal into a validated TaskSpec and selects only declared workflows/roles/tools.
- CoS has no direct Engineer write/command tools and cannot approve itself.
- Use a fresh ephemeral Engineer invocation per implementation/repair iteration.
- Control plane computes actual patch and changed paths; Engineer claims are non-authoritative.
- Use a fresh Verifier context with original goal, TaskSpec, actual patch, relevant repository view, and evidence.
- Build a separate verification workspace; discard and report any verifier mutation.
- Implement PASS, FAIL, and INCONCLUSIVE behavior.
- Bound repair iterations, tool calls, wall time, and model usage according to effective policy.
- Persist stage outputs, checkpoints/summaries, events, and artifacts so a process restart can inspect/resume a paused run.
- Keep context bounded; do not send an entire repository or unbounded transcript by default.
- Present patch, base revision, hashes, tests, criterion mapping, verifier rationale, proof gaps, permissions consumed, and provider usage where available.
- Patch application remains explicit; no push/merge/deploy.

Add adversarial tests for role/tool isolation, false Engineer claims, Verifier defect detection, verifier mutation, repair success/exhaustion, chat cancellation/restart, approval pause/resume, context limits, and honest proof gaps.

Run an end-to-end manual demo in a small disposable real repository using Docker and an explicitly configured model credential. Redact the credential and record only safe evidence. Keep the complete fake/offline suite passing.

---

## Phase 6 prompt — FleetPatch self-improvement under human control

Implement Phase 6 from `docs/IMPLEMENTATION_ROADMAP.md`: conversation-driven, versioned, reviewable fleet configuration updates.

Create a Phase 6 ExecPlan and inspect every protected boundary before editing.

Requirements:

- Add the typed FleetPatch model, persistence, artifact, events, and statuses.
- CoS may propose changes only to an allowlisted subset under `.fleet/`.
- Stage changes outside the active repository tree or in a controlled candidate workspace.
- Produce semantic changes plus unified diff.
- Validate target paths, symlinks, base hash, schemas, references, runtime capabilities, role/workflow integrity, and absence of secrets.
- Reject attempts to modify user trust, hard denies, approver ownership, audit history, sandbox hard limits, state storage, credentials, or protected actions.
- Nothing changes until the user runs the explicit apply command.
- Implement list/show/apply/rollback commands.
- Apply atomically with conflict detection and before/after hashes.
- Rollback is a new audited operation; do not erase prior history.
- A model cannot invoke apply or approve its own proposal.

Use the example: “For backend changes, always run integration tests, and the Verifier must never contribute accepted patch content.” Demonstrate a valid proposed change and protected-boundary rejection.

Add tests for schema failure, path escape, protected setting mutation, secret insertion, conflict, atomic failure, rollback, and model self-application. Run the full quality suite.

---

## Phase 7 prompt — release hardening

Implement Phase 7 from `docs/IMPLEMENTATION_ROADMAP.md`: hardening and preparation for the first OSS release candidate.

Create a Phase 7 ExecPlan with an explicit release checklist and evidence matrix.

Requirements:

- close recovery gaps for orphaned worktrees/containers and interrupted approvals;
- test SQLite upgrades and incompatible schema behavior;
- stabilize CLI exit codes and JSON schemas;
- generate and check configuration schemas;
- define runner image build/version/digest policy;
- perform dependency and secret-handling review;
- add adversarial security test tooling and document the threat model/limitations;
- verify Linux/macOS behavior and document/test Windows support boundaries available in the environment;
- make quickstart executable by a fresh user;
- ensure README distinguishes fake vs real, permission vs sandbox, isolated vs local-unsafe, and implemented vs roadmap;
- remove placeholder commands, dead abstractions, debug output, machine-specific paths, and accidental provider coupling;
- add changelog and release procedure;
- leave license selection as an explicit repository-owner gate if still undecided;
- do not publish or push without direct instruction.

Run the complete offline suite, optional Docker suite, and one explicit live-provider canary. Produce a final release-readiness report mapping every MVP criterion and security release gate to evidence, pass/fail status, and remaining blockers. Do not claim release readiness while a security gate is unmet.
