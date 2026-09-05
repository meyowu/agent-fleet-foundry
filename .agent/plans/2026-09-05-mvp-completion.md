# Complete the project-specific Agent Fleet MVP

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

Complete the remaining product, beginning with an evidence-based alignment audit against the six differentiators in `docs/PRODUCT_SPEC.md`, then deliver the Phase 4–7 functionality, a detailed executable user guide, and the reviewed result merged into the GitHub repository. The user's objective is the complete specified MVP, not merely another passing foundation phase.

A user will initialize an existing repository, talk to a persistent Chief of Staff, receive a validated minimal team, approve exact capabilities, review independently executed evidence and a candidate patch, and evolve the organization's instructions and verification policy through audited configuration patches. For example:

```text
fleet chat .
> For backend changes, require the integration test command.
fleet fleet-patch diff <id>
fleet fleet-patch apply <id>
fleet fleet-patch rollback <id>
```

The original Phase 0/1 bootstrap prompt is historical. The current explicit user request authorizes subsequent implementation and final GitHub delivery. The previous goal's Phase 3 boundary has been satisfied and does not prohibit Phase 4–7 in this goal.

## Scope

### In scope

- Audit all six product differentiators and every Phase 4–7 deliverable and release gate.
- Full exact permission lifecycle: once, run, persistent project scope, deny, explain, revoke, reset; protected ceilings and current-policy revalidation on resume.
- User-owned validated atomic trust storage outside repository; reviewed project/role/workflow/task/sandbox scope intersection and trust modes.
- Persistent CoS chat with durable bounded conversation context, progress, cancellation, restart/resume, and typed organization-change proposals.
- Real adaptive scheduling for all five specified strategies, explicit independent writer scopes and joins, bounded specialist outputs, aggregate budgets, and criterion-specific evidence.
- Persisted, staged FleetPatch proposal/diff/apply/rollback with semantic validation, atomic failure recovery, exact full configuration bindings, and an integration-test requirement example.
- Usable documentation, runner build instructions, packaging, CI, migration/recovery/performance/adversarial checks, offline and Docker E2E, and a detailed `docs/USER_GUIDE.md`.
- GitHub commit/push/merge with final remote identity read-back and proportionate post-merge gates.

### Out of scope

- The explicitly deferred post-MVP roadmap: hosted control plane, Modal/hosted adapters, second harness, domain egress proxy, external connectors, background daemon, cross-machine scheduling, and automatic remote writes by Fleet agents.
- Publishing a package release or selecting a license on the owner's behalf. The guide and release checklist must accurately record the owner-license prerequisite.
- Discovering or reusing ambient model credentials. The manual live-provider release gate requires an explicitly supplied disposable credential; it must remain unproven until such evidence exists.

## Current repository state

The clean starting checkout is `main` at `c700de1fc357844113426d3352cf29b6ffeae0f1`, tree `eb778abcc5c073d4c58f54e6a55c7a04d6333ea4`. Git history contains Phase 0/1, North-Star alignment, Phase 2 PydanticAI, Phase 3 Docker, and cancellation-hardening PRs. This goal works on `codex/mvp-completion`.

`application/workflow.py` owns a durable direct/single-Engineer/Engineer+Verifier state machine. `application/planning.py` constructs plans; `domain/fleet_plan.py` validates additional graph shapes but does not execute them. `adapters/runtime/pydantic_ai.py` supplies strict role results and gateway-backed tools. `application/gateway.py` canonicalizes and records tool requests, while `application/permissions.py` currently exposes a narrow `BaselinePermissionBroker`. One-use grants are persisted and transactionally reserved by the SQLite adapter. Docker and local-unsafe lifecycle cleanup is retained through repeated cancellation.

`domain/fleet_patch.py` is a protected proposal validator only. `adapters/config/yaml.py` safely snapshots all referenced configuration but its initial publication mechanism intentionally refuses replacement. There is no chat, operational FleetPatch, persistent trust service, or CI workflow yet. `Project.fleet_spec_hash` currently means the full ConfigSnapshot hash, which must remain explicit in evolution code.

### Alignment and acceptance ledger

| Requirement | Starting evidence | Remaining acceptance evidence |
| --- | --- | --- |
| Repository-aware bootstrap | Static profiler, provenance, command proposals, Docker disposable canary and BootstrapReport | Fresh-user quickstart; broader real fixture journey after new policy/config changes |
| Adaptive Fleet | Three strategies execute; five graph shapes represented | Parallel writers execute concurrently with deterministic scoped join; specialist DAG produces artifact dependencies; restart and cancellation |
| Independent permissions | Gateway/broker baseline plus exact one-use reservation | Once/run/always/revoke/explain/reset behavioral tests; no broader or stale authority |
| Independent sandbox | Fake/Docker/local-unsafe exact dispatch and cleanup | Preserve all current Docker enforcement and exercise approved-unrestricted if implemented; no invented domain isolation |
| Evidence-first delivery | Hash-bound patches/commands/verdicts/cleanup; fake cannot verify | Per-criterion mapping; merged-candidate fresh verification; aggregate budgets and evidence summaries |
| Versioned evolution | Schema/path/hash/secret checks only | Natural-language proposal, persisted diff, atomic apply, new rollback audit operation; protected policy unchanged |
| Release and detailed guide | README with prior phase evidence; installable artifacts | Required quality/E2E/security/migrations/package matrix; executable guide; release prerequisites recorded and resolved where authorized |
| Final delivery | Prior four PRs merged | Final work merged to GitHub; source/tree identities and post-merge evidence |

## Security impact

The implementation extends the trusted authorization and configuration control plane. All twenty `AGENTS.md` security invariants and the required tests in `docs/SECURITY_MODEL.md` remain applicable. Models never approve, select credentials, mutate trust, apply FleetPatch, choose Docker flags, or gain authority from a role name. Grants cannot expand task, project, role, workflow, or sandbox ceilings. Verification output and specialist artifacts remain untrusted claims until validated against control-plane records.

Persistent policy changes require atomic, no-follow, restrictive-mode storage with backup/version metadata. Run grants bind a run and exact semantic action scope; persistent grants bind project identity and role/stage/workflow plus canonical command/path/network/security conditions. Ephemeral IDs and retry idempotency keys are not substitutes for semantic scope. Re-evaluate policy on every actual execution, including approved resume. Fail closed on stale, expired, exhausted, revoked, or conflicting authorization state.

Parallel writers receive separate candidate workspaces and disjoint validated scopes. Joins are control-plane Git operations; conflicts fail with preserved artifacts. A fresh verifier receives the final joined patch in another disposable workspace. Specialists have read-only role-bound tools unless their validated plan explicitly assigns writer ownership.

FleetPatch may change reviewed organization files, role/skill references, and verification requirements, but never trust, secrets, hard denies, audit, approval ownership, sandbox ceilings, or runtime credential selection. Crash recovery must reconcile exact before/after snapshots without silently overwriting user edits.

## Proposed design

Implement one runnable vertical slice per phase, preserving old configuration/state compatibility with explicit migrations when persistent contracts change.

1. A typed permission context combines trusted Project/Run/Task/role/stage/config and sandbox conditions. The broker validates the ceiling before considering grants or persistent rules. A user-owned policy service manages exact rules and trust modes. The existing reservation transaction remains the idempotency authority for execution.
2. Chat persists a conversation identity, bounded messages/summaries, and linked runs. The frontend drives application services and streams recorded events; it does not own orchestration. CoS may propose a typed task or organization update. Supported scheduler nodes carry durable checkpoints and dependency artifacts.
3. Adaptive planning produces a frozen graph from CoS proposals constrained by configured templates. Independent writer nodes use separate worktrees, then a deterministic exact-base join. Specialist outputs are bounded artifacts consumed by downstream nodes. Every repair obtains fresh work and verification contexts within effective budgets.
4. FleetPatch stages a complete prospective organization snapshot, validates semantics and references/capabilities, and persists proposal plus textual/semantic diff. Apply verifies the exact base, records a pending operation, atomically switches validated configuration, and updates Project binding. Repeated apply reconciles the same operation. Rollback constructs a new inverse proposal/operation with conflict guards; history is immutable.
5. Release evidence links all requirements to tests, actual CLI behavior, Docker inspection, artifacts, packaging and GitHub state. Documentation uses runnable commands and distinguishes workflow lifecycle from evidence-derived completion.

## Public contracts

- Preserve versioned JSON envelopes and existing command syntax.
- Add `fleet approve --run`, `--always --scope project`; `fleet permissions list|explain|revoke|reset`; a deliberate trust-mode configuration surface.
- Add `fleet chat`, durable conversation selection, status/artifact/permission/cancel/help/exit and resumable user interaction.
- Extend role outputs/plan contracts for specialist dependencies and disjoint parallel scopes; add structured criterion mapping without accepting model proof claims as authority.
- Add `fleet fleet-patch list|show|diff|apply|rollback`, configuration validation, and candidate discard/abandon where the documented lifecycle requires them.
- Generate schemas for all new externally persisted/public structures. Add explicit migration(s) for changed state; old binary use of newer schema fails closed.

## Milestones

### Milestone 1: Alignment audit and refreshed baseline

Acceptance: six differentiators and Phase 4–7 requirements mapped to current symbols/tests; clean baseline identities recorded; baseline offline gates refreshed; independent audits incorporated. Plan precedes substantial implementation.

### Milestone 2: Phase 4 exact permission lifecycle

Acceptance: separate CLI invocations approve once/run/always and resume a real canonical command path; only exact scope matches; revocation and policy changes affect later execution; protected actions remain denied; trust is outside repo; migration/restart/concurrent mutation and security tests pass.

### Milestone 3: Phase 5 persistent adaptive organization

Acceptance: chat restart preserves identity/context/run links; all five requested strategies execute through normal adapters; disjoint parallel patches join deterministically; read-only specialists produce bounded dependencies; independent verification checks joined code and each acceptance criterion; budgets/cancel/approval/recovery work across graph execution.

### Milestone 4: Phase 6 audited organization evolution

Acceptance: CoS request to require backend integration tests creates a proposal with exact diff; target remains unchanged until explicit apply; subsequent backend tasks enforce the requirement; rollback restores prior content through a new auditable operation; malformed/protected/conflicting/secret-bearing changes fail before mutation.

### Milestone 5: Phase 7 release evidence and detailed user guide

Acceptance: fresh install and guide commands work; complete offline, Docker, migration, security, package and platform evidence recorded; all MVP success criteria demonstrated; live-provider/license prerequisites remain explicit until actually satisfied. Linux/macOS CI is configured and inspected if available; Windows support limits are stated from actual primitives.

### Milestone 6: GitHub delivery and completion audit

Acceptance: reviewed source committed and merged into the configured GitHub repository; local and remote identities match; post-merge gates pass; no required feature or guide section is missing; every remaining release gate has authoritative evidence or is a genuine explicitly reported blocker. Do not mark the full goal complete based on partial implementation or documentation of a required missing gate.

## Detailed implementation steps

1. Read contributor/specification/plan files, inspect Git state, and collect independent permission, workflow, and evolution/release audits.
2. Add strict permission policy models/port and atomic filesystem trust adapter; extend approvals/grants/decisions and SQLite transitions; integrate `PermissionService`, broker, gateway, bootstrap/config/CLI, and behavioral security tests.
3. Add durable conversation and node execution state; extend `ScopeDecision`, `FleetPlan`, runtime catalogs/prompts, scheduler/resource ownership, criterion evidence, and chat presentation. Preserve existing simple-path E2E and extend fixtures for parallel/specialist/repair/restart paths.
4. Add operational FleetPatch state/service/runtime proposal, semantic organization validation and staged atomic config replacement/recovery. Wire CLI and chat, add diff/rollback tests and the backend integration requirement example.
5. Update normative specs and add necessary ADRs alongside architecture changes. Add `docs/USER_GUIDE.md`, contribution/release/data-handling/security guidance, CI, image recipe/version strategy, and adversarial/performance acceptance scripts.
6. Run all required checks, inspect source/package/diff hygiene, perform manual CLI/Docker journeys, request fresh independent verification of the frozen result, then commit/push/merge and verify the final GitHub branch.

## Validation plan

Run focused tests as each behavior changes, then per-phase quality gates:

```bash
uv lock --check
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m agent_fleet.schemas.generate --check
uv run pytest -q tests/unit
uv run pytest -q tests/contract
uv run pytest -q -m integration tests/integration
uv run pytest -q tests/e2e
uv run pytest -q
uv build --offline
git diff --check
```

Run opt-in real Docker with the documented preloaded runner and verify effective configuration plus exact zero residual managed containers. Use generated disposable Git repositories, distinct Fleet state, and registered random secret/host sentinels. Ordinary tests keep sockets/live model requests disabled. Test all fifty-three existing security cases and phase-specific new authority/graph/evolution boundaries. Test migration from previous schema versions, reopen, corruption, and ambiguous operation recovery. Rebuilt package must contain the CLI, schemas, migrations, prompts and user documentation needed by an installed user without tests, local paths, credentials or development state.

Before final delivery, trace every explicit Phase 4–7 deliverable and all twelve MVP user-success criteria to current tests or manual artifacts; inspect actual scopes rather than infer broad coverage from total counts. Record exact commands, counts, skips, errors, platforms and remaining proof gaps. A required live-provider canary is not satisfied by FunctionModel or a fake runtime.

## Rollback and recovery

Preserve the clean starting commit and use normal commits on the working branch; do not rewrite existing history or discard user changes. State migrations are forward-only with old data preserved. Trust writes retain validated prior state and use atomic replacement; failed validation never changes effective authority. Revoke remains effective at the next execution, and uncertain side effects are reconciled rather than replayed.

Existing retained execution -> sandbox -> worktree cleanup must survive repeated caller cancellation. Extend leases by explicit node identity for concurrent work. Failed joins retain reviewable patches and clean only Fleet-owned resources. FleetPatch apply records exact before/after identities and a durable pending operation before publication; crash repair compares both known snapshots and refuses unknown/user-modified content. Rollback appends history and never resets unrelated source changes.

## Progress

- [x] (2026-09-05) Confirmed current goal, clean starting main commit/tree and prior phase Git history; read contributor, plan and normative specifications.
- [x] (2026-09-05) Started independent read-only audits for permission, workflow/adaptive chat, and FleetPatch/release gaps.
- [x] (2026-09-05) Created this living ExecPlan before substantial implementation and selected `codex/mvp-completion`.
- [x] (2026-09-05) Completed three independent alignment audits and `docs/MVP_ACCEPTANCE.md`; refreshed baseline `uv run pytest -q`: 745 passed, 7 skipped in 200.97s. Other phase quality commands will run against the completed changes.
- [x] (2026-09-05) Implemented strict exact-scope trust models, private CAS/backup filesystem storage, migration 0004, once/run/always grants, current-policy broker integration, user permission CLI, and reviewed bootstrap scope binding.
- [x] (2026-09-05) Focused trust tests: 70 passed; grant/migration/contracts/recovery: 80 passed; initial workflow/approval/broker integration: 81 passed. Independent security regressions: 10 passed. These are intermediate checks, not Phase 4 acceptance.
- [x] (2026-09-05) Complete simulated once/run/always integrations: 13 passed in 35.27s; CLI tests including invalid-mode redaction: 24 passed. Later checkpoint/workflow regression pass: 64 passed in 117.52s. Bootstrap/security/offline-E2E focus: 12 passed in 31.95s.
- [x] (2026-09-05) Real Docker exact once/run/always cross-process approval journeys: 3 passed, 6 deselected in 22.91s; each executes four commands, retains one Verifier identity and returns verified_complete=true with no outstanding leases. Existing six Docker scenarios also passed during the preceding fixture-debug runs; a single frozen combined rerun remains required.
- [x] (2026-09-05) Intermediate lock/sync, Ruff formatting/lint, 137-file mypy, schema drift, offline wheel/sdist build and diff whitespace checks passed. Combined in-flight suite: 927 passed, 7 skipped, 2 failed in 286.04s; fix old generated-tool expectation and finish worker test edits before a frozen rerun.
- [x] (2026-09-05) Follow-up isolated layers: unit 465 passed in 32.68s; contract 281 passed in 3.47s; offline E2E 4 passed in 30.16s. Frozen worker permission CLI/verifier-checkpoint tests: 31 passed in 53.32s. Trust/policy/contracts: 103 passed in 31.37s plus 200 concurrent first-save repetitions with zero failures. An in-flight integration selection still loaded two superseded checkpoint-test assertions (134 passed, 2 failed, 49 deselected); the frozen worker rerun supersedes those assertions, not the required final aggregate gate.
- [x] (2026-09-05) Full real Docker suite: 9 passed in 54.74s, including a second fully verified run under exact persistent rules with four consumed derived capabilities and no fabricated approvals. Ruff formatting/lint, 138-file mypy, schema drift and offline archive build passed; wheel/sdist each have 128 package files and 36 schemas, exact source-byte identity and exclusions verified.
- [x] (2026-09-05) Closed independent P1 concurrent-dispatch finding with permanent single-winner claims and frozen security/offline/Docker regressions.
- [x] (2026-09-05) Implemented and independently regression-tested the permanent dispatch fence. New claim/getter unit suite: 37 passed in 1.09s; combined migration/grant/dispatch: 96 passed in 3.70s. Six gateway concurrency/restart cases plus twelve offline FunctionModel approval cases: 18 passed in 26.36s. Disabling the fence in a temporary runtime monkeypatch reproduced two duplicate-dispatch failures; no source mutation remained.
- [x] (2026-09-05) Frozen checkpoint/CLI regressions passed 31 tests in 49.81s after the fence and Engineer checkpoint integration; focused legacy once approval adoption passed 1 test in 2.71s. Latest layers: unit 510 passed in 53.30s; contract 281 passed in 4.47s; E2E 4 passed in 44.40s. Real Docker after dispatch/Engineer changes: 9 passed in 42.32s; no globally managed containers remain. Final combined/integration reruns are still running.
- [x] (2026-09-05) Closed mutation-audit/reset partial failures with prepared/completed policy events, CAS, and monotonic grant-reset cutoffs; completed normal CLI and once/run/always Verifier journeys and regenerated schemas.
- [x] (2026-09-05) Accepted Phase 4: frozen `uv run pytest -q` returned 1001 passed, 10 skipped in 431.79s. Nine skipped Docker tests separately passed in 42.32s; the remaining live-provider canary remains explicitly unperformed. Marked integration returned 156 passed, 49 deselected in 311.72s. Formatting (165 files), lint, mypy (141 source files), schema drift, lock/sync, whitespace and offline build passed. Wheel/sdist each contain 129 package files, 37 schemas, four migrations and three runtime prompts, with source-byte identity verified. CLI phase metadata advanced from 3 to 4; `uv run pytest -q tests/integration/test_cli.py` passed 30 tests in 22.52s afterward, with formatting/lint/mypy/schema/offline build/whitespace gates repeated successfully.
- [ ] Complete Phase 5 adaptive chat/workflow and its acceptance matrix.
- [ ] Complete Phase 6 organization evolution and its acceptance matrix.
- [ ] Complete Phase 7 release hardening and detailed user guide.
- [ ] Independent final audit, GitHub delivery, remote identity and post-merge verification.

## Discoveries

- Observation: Atomic one-use grant consumption alone did not imply exactly one dispatch: two concurrent callers could both receive the idempotent RESERVED result and execute it.
  Evidence: Independent gateway barrier reproduction produced two same-intent dispatches with one consumption event and remaining_uses=0.
  Consequence: Add a durable per-intent dispatch-claim table and atomic single-winner claim immediately before execution. A lost or interrupted claim never confers replay rights; concurrent losers may read an authoritative completed result or fail ambiguous. Require regression evidence before Phase 4 acceptance.
- Observation: Git porcelain status alone does not detect changes to an already-modified file during a Verifier approval pause.
  Evidence: A new checkpoint regression appended source bytes without changing workspace_status_fingerprint.
  Consequence: Compare the canonical patch content hash as well as status on restore and after verification; never reuse evidence against changed code.
- Observation: Approval restart was tested previously only with fake execution; a reconstructed Docker provider has no process-local logical preparation for the persisted sandbox handle.
  Evidence: New real-Docker approval tests failed with `SANDBOX_EXECUTION_FAILED` before any resumed command.
  Consequence: Restore only exact active parent leases during approved pause resume, recheck immutable provider/configuration/image/daemon/workspace bindings and inspection, and reject any unresolved execution child. Logical restoration does not replay a command or create a new lease.
- Observation: Recreating a fresh Verifier on each approval pause assigns cached pre-pause command evidence to earlier instances/workspaces, breaking independent verification.
  Evidence: `_verify` created a new workspace and AgentInstance on every invocation; fake tests did not assert evidence ownership.
  Consequence: Persist a typed VerificationCheckpoint before invocation, retain the same agent/workspace/sandbox/patch/baseline across approval pauses, clear it after authoritative completion, and fail closed on altered context. Real-Docker tests now prove both commands bind the final Verifier.
- Observation: Typer enum parsing echoed invalid trust-mode values before the redacted application boundary.
  Evidence: New CLI registered-secret sentinel tests for `--mode` and `--trust-mode`.
  Consequence: Parse the raw choice inside the redacted operation with generic typed diagnostics; do not print the invalid supplied value.
- Observation: Safe-mode approval first reached Verifier execution and exposed missing pause/resume transitions for the verifying stage.
  Evidence: `tests/integration/test_persistent_permissions.py` initially had 9 passes and four full journeys failing on `running/verifying -> paused_for_approval/verifying`.
  Consequence: Add explicit Verifier transitions and rerun the complete flows; do not count Engineer-only approval tests as end-to-end acceptance.
- Observation: Trust-file publication and SQLite audit cannot share one native transaction; reset could also fail partway through revoking SQL grants.
  Evidence: Independent review of `PermissionPolicyService.configure`, `revoke`, and `reset`.
  Consequence: Persist an exact revision/hash preparation event before trust publication, and publish a project grant-revocation cutoff before best-effort materialized SQL tombstones. Failure must leave authorization revoked and visible preparation evidence.
- Observation: Later-run persistent-rule matches need capability evidence, not just an ALLOW decision.
  Evidence: Independent review of the new gateway reservation branch.
  Consequence: `reserve_trust_rule_intent` now creates a bounded request-free consumed receipt, intent reservation and issued/consumed events atomically; it never fabricates a human approval or creates a reusable grant.
- Observation: Existing Phase 3 plan contains an unchecked pre-commit delivery step although local Git proves PR #4 merged at the current baseline.
  Evidence: Git commit graph and matching local/origin main at `c700de1`; prior plan delegates self-referential identities to its delivery report.
  Consequence: Record refreshed delivery authority in this plan rather than repeat completed Phase 3 repairs.
- Observation: Current broker does not receive all requested-policy layers, and approval resume bypasses a new broker evaluation after loading a stored grant.
  Evidence: `application/permissions.py`, `application/approvals.py`, and the independent permission audit.
  Consequence: Phase 4 must integrate effective context and revalidation; a trust-store-only feature would not satisfy the security contract.
- Observation: Current FleetPatch and advanced graph types do not have operational execution paths.
  Evidence: `domain/fleet_patch.py`, `application/planning.py`, fixed workflow stage dispatch, absent chat and FleetPatch CLI.
  Consequence: All operational Phase 5/6 criteria remain work rather than being counted as implemented abstractions.
- Observation: Phase 7 calls for a recorded manual live-provider canary and an owner license decision before a public release; neither is supplied by this request.
  Evidence: roadmap release gate and explicit historical prohibition on choosing a license or reusing ambient credentials.
  Consequence: Complete all independent authorized implementation first, keep these gates visible, and do not fabricate release completion or discover unrelated secrets.

## Decision Log

- Decision: Separate capability consumption from a permanent atomic dispatch claim; every gateway executor must win the exact persisted claim immediately before execution.
  Rationale: Idempotent reservation return values can be observed by multiple callers. One capability consumption does not prove one execution; durable claim ownership closes the proven race and conservatively refuses interrupted replay.
  Alternatives: A process-local lock would not protect independent CLI processes; resetting a timed-out claim could duplicate an uncertain command. Both rejected.
  Date: 2026-09-05
- Decision: Persist both Engineer and Verifier logical role checkpoints through approval pauses, while retaining fresh role instances for separate repair iterations.
  Rationale: Grants and command evidence must not transfer between principals during restart. Existing pre-Phase4 once-only requests may adopt only their exact persisted original Engineer identity after validated state lookup.
  Alternatives: Recreate a new agent after each pause, or weaken dispatch identity checks to accept paused/failed actors. Both rejected.
  Date: 2026-09-05
- Decision: Retain the originally reviewed display reason when reconstructing an existing logical intent; keep every execution-bearing field in the exact canonical hash.
  Rationale: Offline FunctionModel tests demonstrated harmless prose/call-ID variation breaking approved commands. Normalizing only the non-authorizing explanation preserves permission scope without making resource/parameter changes equivalent.
  Alternatives: Accept whole changed intents, or rely on deterministic model prose. Both rejected.
  Date: 2026-09-05
- Decision: The product completion scope is the explicit Phase 4–7 MVP and six differentiators, with post-MVP adapters/integrations still deferred by the authoritative roadmap.
  Rationale: The current user requests the complete project; the specifications define its bounded first deliverable and distinguish deferred integrations.
  Alternatives: Stop at Phase 4, or implement every speculative future provider. Neither matches the requested specified product.
  Date: 2026-09-05
- Decision: Preserve independent PermissionBroker/SandboxProvider and evidence authority while adding each user journey as a vertical slice.
  Rationale: New CLI commands or persistent models alone do not complete permissions, adaptive execution, or Fleet evolution.
  Alternatives: Add placeholders or special demo-only orchestration. Rejected because the acceptance contract requires normal execution paths.
  Date: 2026-09-05

## Outcomes

Alignment audit and Phase 4 acceptance are complete. The Phase 0–3 baseline passed 745 offline tests with seven optional skips. Phase 4 now passes 1001 offline tests with ten explicitly gated skips, plus all nine real Docker scenarios separately. Exact approval lifetimes, private user trust, current-scope checks, durable single-winner dispatch, revocation/reset auditing, CLI and bootstrap review are exercised through the normal execution path. Phase 5–7, detailed guide, final GitHub delivery, and live-provider/license release prerequisites remain open. Phase 4 acceptance is not a full-MVP release claim.
