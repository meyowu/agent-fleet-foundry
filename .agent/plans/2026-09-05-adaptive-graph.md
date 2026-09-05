# Execute bounded adaptive graphs with exact child identities

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log and Outcomes. It implements Milestone 2 of `2026-09-05-adaptive-workflow-chat.md`; that plan and `2026-09-05-mvp-completion.md` remain the Phase 5 and full-project acceptance records.

## Purpose and user-visible result

CoS can choose multiple Engineers or the Researcher → Architect → Engineer → Verifier workflow when a task needs them. The user does not manage workers. Independent writer tasks actually overlap, each with a separate bounded workspace; the control plane joins their patches deterministically and asks a fresh parent-owned Verifier to check the original task. `fleet status <run>` shows child identities, exact pending approvals, dependencies and results. Restart never silently recreates a dispatched node.

## Scope

### In scope

- Typed bounded writer assignments and all five executable strategies; reviewed concurrency and role ceilings.
- Durable graph ownership, immutable internal child Runs/TaskSpecs, shared cumulative budget and independent exact approval scopes.
- Read-only Researcher/Architect reports as untrusted artifact dependencies.
- Stable ordered patch join, fresh parent verification, sequential bounded repair of a joined candidate, cancellation/recovery and inspection.
- Normal fake/offline PydanticAI/Docker journeys and negative restart/concurrency tests.

### Out of scope

- Persistent chat (next slice), FleetPatch (Phase 6), external research/networking, new providers or automatic patch application.
- Arbitrary model-supplied graph code, recursive public run creation, dynamic permission expansion, child patch application or relabeling child command evidence as parent evidence.
- Replaying a driver whose process stopped after claiming execution. Explicit recovery abandons it and cleans exact descendants.

## Current repository state

The accepted preceding Milestone 1 is committed at `ab28aaa6192a8e4d92c78dada2413eb5606376b7` and pushed to `codex/mvp-completion`. It supplies immutable aggregate accounting, typed multi-criterion evidence, canonical new text files, bounded repair feedback and role step/delegation ceilings. Phase 4 remains the last accepted whole phase.

Milestone 2 graph execution is now accepted on the frozen source/test checksum recorded below, including documentation-final archive read-back; its checkpoint commit is pending. All five strategies execute. Separate internal child Runs preserve singular approval/checkpoint identities, independent durable graph/continuation CAS owns orchestration, and patch/lifecycle services reject public child operations. Cancellation/recovery includes exact descendants. Persistent chat remains unimplemented.

## Security impact

Every specialist read and every Engineer/Verifier operation still crosses the role-bound catalog, ToolGateway and PermissionBroker. Researcher and Architect receive only repository list/read/search/diff, no writes, commands, approval tool or network. Their workspaces start at the parent's exact base and are checked for mutation before accepting reports. Model output cannot create a child, select its sandbox or change its budget.

Child run IDs remain the principal boundary for approvals, commands, resource leases and audit records. `--run` means the displayed child run, not the whole organization. All children share the parent's immutable budget owner but no grants. The parent may wait for children without impersonating a parent approval request.

An internal child is recorded independently in SQLite before its row becomes visible. Patch application consults this binding before any ready/completed shortcut and rejects child patches even if mutable Run flags are removed. Unknown/corrupt graph bindings fail closed. The parent can be accepted only after exact descendant cleanup and fresh joined-patch verification.

## Proposed design

### Plan and role contracts

Add bounded `WriterAssignment` values to `ScopeDecision`: node ID, subgoal, relative path scope and acceptance-criterion IDs. Parallel strategy requires at least two assignments, disjoint canonical scopes and complete original-criterion coverage. An assignment can cover several criteria; it cannot introduce one. The trusted planner builds dependencies and the independent parent verifier node. It accepts queued writers beyond available slots; `max_parallel_agents` limits running child invocations, not the graph's total size.

Add optional subgoal/criterion fields to FleetPlanNode for backward compatibility, and a reviewed workflow `maxParallelAgents` ceiling (default 2, hard maximum 8). Simple strategies remain one-slot and instantiate no specialist. The specialist strategy has a fixed declared dependency chain and uses all original paths/criteria. Default generated configuration declares optional per-task researcher/architect templates without creating persistent instances or adding write permissions.

`SpecialistReport` is a bounded typed role/summary/findings/recommendations/proof-gaps result, not a verdict. Persist exact report metadata/content hashes. Downstream input contains bounded validated reports and reference IDs, never raw SDK history or credentials.

### Durable ownership and child preparation

Introduce `domain/graph.py`, `ports/graph.py`, `adapters/persistence/graphs.py` and migration 6. `GraphStore.initialize(parent_run_id, plan, children)` atomically inserts the frozen graph, static child bindings and preallocated child Run/Task rows with audit events. Each seed contains node ID, iteration 0, Run and Task. Existing initialization with the same authoritative plan returns the stored identity; it does not substitute newly proposed IDs.

Run gains paired `parent_run_id`, `parent_plan_sha256`, `parent_node_id`, `parent_iteration` fields. These are convenient visible metadata, not the sole internal-child authority. Read-only child TaskSpecs carry scoped reads and `control_plane_plan`; writer children carry canonical patch/command requirements without independent-verifier claims. Children inherit the parent's project/base/runtime/provider reference/sandbox/configuration exactly and only narrow task scope. No nested graph is allowed.

Before any effect, the coordinator claims the graph through an expected-revision transaction. A claim includes the exact parent, plan, generation and opaque correlation token. It has no timeout or implicit takeover. Node state changes have separate expected revisions. Artifact/task/config preparation and child ledger initialization occur under this ownership before dispatch; missing or inconsistent preparation cannot produce a model call.

Resource preparation must also precede Git effects: allocate the exact Workspace identity/path without mutation, persist its CREATING lease, then materialize it and activate that same lease. Add project-owned repository preparation/materialization methods and a ResourceService wrapper rather than relying on the current create-then-lease sequence. Cleanup checks both the exact directory and its Git worktree registration; an unknown partial creation remains a recoverable failed lease, not an invented absence claim.

Graph node states are pending, running, waiting_approval, succeeded, failed, blocked and cancelled. Graph-level states are ready, running, paused, joined, failed and cancelled. Inputs freeze on first node dispatch; outputs freeze on successful settlement. Every reference binds artifact ID/hash/kind and owner run/task. Immutable initialization events and duplicated SQL/JSON identities are cross-checked before dispatch and reads that grant authority.

### Coordinator and exact resume

`application/graph.py` depends on a project-owned hooks protocol, not on concrete WorkflowEngine imports. The engine prepares an already-bound child, executes/resumes it, cleans it and joins exact results. It does not call public `start` recursively, so no extra CoS turn or silently reset budget appears.

The coordinator schedules ready nodes in stable node-ID order and keeps at most configured capacity active. It collects actual asynchronous completions, persists per-node results and unblocks dependencies. Approval pauses preserve each child's existing checkpoint and principal. Other ready independent work may finish; then the parent exposes `WAITING_FOR_CHILDREN` at IMPLEMENTING with no fake parent `pending_approval_id`. Resume checks each child approval and starts only approved nodes; unapproved nodes remain paused. Denied/failed dependencies block descendants. Opposite completion/approval order cannot change join order.

Public `fleet resume <child>` refuses independent child execution and points to its parent. Only the claimed coordinator invokes the internal child resume hook. A child that already persisted an exact patch/report before a bookkeeping interruption must not receive a new Engineer invocation; reconcile its bound result and cleanup or require recovery.

The parent budget ledger is checked during active waits as well as before every request/tool batch. Exceeding aggregate active time cancels owned work and preserves charged/unknown usage. This is cooperative process enforcement, not a monetary pre-spend guarantee or a hard real-time scheduling promise.

### Deterministic join and repair

The coordinator records an ordered join preparation receipt containing parent task/config/base/plan identity and exact node/child/patch/scope references. The engine revalidates every child result and absence of outstanding child resources. It creates a fresh parent candidate worktree at the original base, applies patches in node-ID order and extracts a new canonical patch. Scope violations, conflicts, changed bases or artifact mismatches fail closed; individual child artifacts remain inspectable. A committed join result binds the combined patch and preparation receipt.

The parent then uses its existing `_verify` path with the complete original TaskSpec and combined patch. Child command receipts remain child provenance. They cannot satisfy parent command or criterion mappings. A failed parent verification may use the existing sequential parent Engineer repair path, bounded by the original configured repair count and cumulative budget. An explicit `graph.repair_fallback` event identifies this deterministic escalation; it does not rerun successful child nodes or pretend the repaired patch is still byte-identical to the initial join. Fresh parent verification follows every repair.

### Cancellation and recovery

Graph cancellation atomically fences further ownership/node dispatch and marks all nonterminal bound child Runs/nodes cancelled. Cleanup is a separate retained operation over exact descendant IDs. In-process cancellation first cancels and awaits owned tasks so subprocess cleanup cannot race a new dispatch. Parent cancellation/recovery owns its normal status transition; the graph store does not overwrite it. Recovery after owner-stopped confirmation abandons uncertain execution and cleans descendants, never takes over the same execution claim. No unrelated run or installation is touched.

## Public contracts

- New graph domain records, store protocol and SQLite migration 6; generated public schemas at the integrated boundary.
- `RunStatus.WAITING_FOR_CHILDREN`; existing status and resume commands expose child state and exact approvals.
- New Researcher/Architect roles, typed SpecialistReport, specialist report and graph join artifacts.
- ScopeDecision writer assignments and requested concurrency; FleetPlanNode subgoal/criterion IDs; reviewed WorkflowRequest concurrency ceiling.
- Internal-child patch apply always denied, including idempotent/completed paths. Existing standalone runs remain compatible.
- Driver ownership and node CAS failures use typed `RECOVERY_REQUIRED`; invalid proposals fail before child creation.

## Milestones

### Milestone 1: frozen contracts and safe child storage

Acceptance: migration/reopen, atomic initialization, immutable child/plan/project/base/task binding, single-winner driver claims, node transition CAS, corruption/redaction tests and atomic cancellation fencing pass. No child becomes externally applicable during setup.

### Milestone 2: normal adaptive execution

Acceptance: two Engineers genuinely overlap; three or more writers queue under a two-slot cap; all declared specialist roles run only when chosen. Dependency reports are bounded and cannot invoke write/command tools. Combined parent patch contains every scoped change, has fresh independent verification and leaves original target unchanged.

### Milestone 3: restart, cancellation and complete graph acceptance

Acceptance: reverse completion/approval order produces the same patch; multiple exact child pauses survive reconstruction; duplicate resume cannot duplicate workers/effects. Conflicts, tampering, failed dependencies, aggregate exhaustion and repeated cancellation fail safely with exact cleanup. Default suite and real Docker joined-candidate journeys pass before chat implementation depends on this slice.

## Detailed implementation steps

1. Finish frozen Milestone 1 budget/evidence acceptance and checkpoint commit before touching graph source.
2. Add reviewed public contracts and state transitions in models/config/planner; extend optional templates, runtime role output maps and read-only catalog/broker ceiling. Preserve simple-path fixtures.
3. Implement graph domain/port/SQLite adapter and migration with atomic child insertion and claim/cancel semantics. Wire the composition root.
4. Implement coordinator with injected hooks; add engine child preparation/execution/specialist/report/join hooks and explicit child-apply denial. Wire graph status and exact descendant lifecycle handling.
5. Add normal fake and FunctionModel journeys, concurrency barriers, restart and adverse-order tests, then independent real-Docker joined-patch proof and cleanup.
6. Regenerate schemas, run focused/full/static/package gates, update normative docs and both parent plans with exact results, and commit the accepted graph checkpoint.

## Validation plan

Use unit tests for proposal/graph/transition contracts; SQLite contract tests for identity, revisions, transactions and corruption; integration tests through normal WorkflowEngine/Git/gateway for all strategies; offline PydanticAI FunctionModel tests for actual role dispatch; opt-in Docker integration for independent combined-patch commands. Assert persisted Runs, node records, receipts, permissions, leases, patches and user-visible status, not only callback counts.

Negative cases include overlapping/prefix/casefold/forbidden scopes, missing criteria, too many nodes, missing roles/delegation, specialist writes/commands, fabricated or foreign dependency artifacts, changed child/base/config/patch identity, absent child budget, concurrent driver acquire/resume, unknown owner, denied child dependency, partial join, altered target, child apply bypass, aggregate usage exhaustion, cancellation during creation/join/verification, and no cross-project cleanup.

Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src tests`, schema generation check, `uv run pytest -q`, focused integration suites, opted-in Docker tests and offline packaging at the coherent acceptance boundary. Document skips and unperformed live-provider checks separately. Keep source frozen during final tests.

## Rollback and recovery

Retain the accepted budget/evidence commit. Migration 6 is forward-only and older binaries reject it. Never delete user changes or rewrite prior commits. A failed graph retains individual results and join-preparation evidence. Explicit cancellation/recovery cleans only exact bound children and parent resources. Restart after an unresolved dispatch does not refund budget or remove permanent tool claims. A fresh run is required after abandoned ownership or conflicting target/configuration.

## Progress

- [x] (2026-09-05) Read-only workflow and persistence/security investigations completed while the preceding slice stayed frozen.
- [x] (2026-09-05) Recorded this graph ExecPlan and bounded write contracts before graph source implementation.
- [x] (2026-09-05) Accepted and committed preceding budget/evidence slice as `ab28aaa6192a8e4d92c78dada2413eb5606376b7`, tree `6c2a800347863f7d728e884fc57c885cf6ab3903`: 1170 default tests passed, 11 gated skips; all ten Docker cases separately passed. Final staged whitespace check removed one migration EOF empty line; 71 migration/budget regressions and archive-byte checks passed afterward.
- [x] (2026-09-05) Added bounded writer/report boundary models, visible internal-child metadata and WAITING_FOR_CHILDREN before starting independent storage/coordinator/role writers. These are implementation contracts, not graph acceptance.
- [x] (2026-09-05) Integrated graph preparation, child execution, typed specialist dependencies, deterministic patch join, fresh parent verification, public child-operation denial, descendant lifecycle and status inspection. Initial normal fake parallel/specialist journeys passed (2 tests, 16.38s); worker role/planner checks passed (210 focused tests, 4.33s, plus 52 existing workflow regressions, 182.55s).
- [x] (2026-09-05) Worktree identity/CREATING lease now precedes Git effects. Four new real-Git preparation/recovery cases passed in 6.17s; the combined runtime-budget/preparation group passed 11 tests in 17.05s.
- [x] (2026-09-05) Parent EvidenceBundle embeds exact graph/join/child-cleanup provenance; CompletionGate refuses missing, altered or foreign graph delivery. Graph/evidence/criterion group passed 59 tests in 31.26s. Subsequent parent-continuation ownership integration passed the 11 graph/budget integration cases in 41.96s. Full graph gates are still pending.
- [x] (2026-09-05) Storage/domain source frozen after exact plan-node equality hardening: 42 tests passed in 1.39s; earlier broader SQLite/budget/coordinator group passed 113 tests in 5.57s, and ten repeated process races each produced one owner. Generated 55 public schemas; three schema tests and generation/check passed.
- [x] (2026-09-05) Real-Git scheduling covers three writers at two slots, opposite completion/stable join hash, rebuilt exact child approvals, duplicate/stale parent resumes, repeated verifier cancellation and aggregate time exhaustion. Coordinator/store/model/normal/scheduling group passed 81 tests in 94.19s. Subsequent safety/scheduling/normal/preparation group passed 28 tests in 163.63s.
- [x] (2026-09-05) Normal offline PydanticAI FunctionModel parallel/specialist journeys passed (2 tests, 2 Docker deselected, 15.98s). Separate enabled real-Docker graph journeys passed (2 tests, 2 offline deselected, 20.50s) with exact cleanup; global managed-container read-back found zero. No provider calls, ambient credentials, image pulls or builds occurred. Both tests re-open the control plane and explicitly apply the parent patch; parallel child full-suite failures remain child provenance while the complete joined parent suite passes.
- [x] (2026-09-05) Added five subprocess CLI E2E scenarios; combined existing/new E2E passed nine tests in 140.26s. Initial offline archives contained identical 161 package files, 55 schemas, migrations 1–6 and five prompts. Strengthened distribution/schema tests passed four tests in 1.69s, including exact archive bytes and an isolated wheel-content smoke against existing locked dependencies (not a clean dependency install).
- [x] (2026-09-05) Pre-final unit/contract aggregate passed 1030 tests in 56.23s. Independent delivery audit initially found two failures among nine cases (73.98s): terminal-parent ordinary claim release masked a rehydration error; a missing cleanup blob raised raw FileNotFoundError. The pre-final marked integration run independently retained `2 failed, 212 passed, 85 deselected in 823.08s` for those defects. Exact failure fencing and a typed cause-free artifact-read boundary fixed them; embedded plan/join/cleanup consistency gaps were also closed. These failed attempts are superseded by the frozen gates below, not erased.
- [x] (2026-09-05) Frozen M2 acceptance PASSED: full default `1344 passed, 13 skipped in 1160.72s`; separate Docker `12 passed, 3 deselected in 140.05s`; E2E `9 passed in 214.64s`; artifact/delivery/normal graph focus `16 passed in 164.85s`; independent delivery audit `11 passed in 144.48s`. Zero managed containers and zero active leases across all 22 Docker-test state databases. Exact commands and limitations are below.
- [x] (2026-09-05 11:05 UTC) Source/test aggregate remained `4cbef9616084ad1465ee5fd84b97f81763f282bc95b96c11b5bb7d35cfeafeb9` through final tests and 11:02 UTC read-back. Latest static refresh: 203 formatted files (202 at initial freeze), lint passed, mypy passed 172 source files, schema and whitespace checks passed. Lock resolved 51 packages and sync checked 49. Package/schema tests passed four cases in 2.82s before final documentation edits.
- [x] Implement and accept graph contracts/storage.
- [x] Implement and accept normal adaptive execution and joined verification.
- [x] Complete graph restart/cancel/security/Docker gates and acceptance documentation.
- [x] (2026-09-05) README-frozen archive/schema tests passed four cases in 4.37s; after recording that result in README, the same rebuild/source/README/wheel-content checks passed four cases in 1.73s. Source/test checksum remained unchanged at 11:12 UTC.
- [ ] Commit the accepted M2 checkpoint.

## Discoveries

- Observation: existing Run has only one approval/checkpoint per role, and ordinary save_run has no ownership CAS. Consequence: separate child Runs plus an independent graph claim are necessary; widening approval scope is not.
- Observation: artifact rows reference existing Run rows. Consequence: initialize child Run/Task/binding atomically first, then create exact task/config artifacts under claimed ownership before effects; incomplete preparation fails closed.
- Observation: existing TaskSpec permits bounded allowed paths for read-only tasks. Consequence: specialists can reuse the domain contract without pretending to perform code changes.
- Observation: each active invocation's deadline alone does not enforce cumulative time across parallel calls. Consequence: add a parent ledger watcher and preserve the non-hard-real-time limitation.
- Observation: existing Git worktree creation happens before its lease is saved. Consequence: add preallocated worktree identities and CREATING leases for the integrated workflow, including joined and verification workspaces; interrupted creation must remain discoverable.
- Observation: a graph driver CAS loser was side-effect-free inside the coordinator, but the public resume error handler could mark the winning parent's Run FAILED and clean its resources. Consequence: introduce a typed ownership-unavailable failure that never grants lifecycle authority; refuse public resume of an already RUNNING advanced parent.
- Observation: the child graph releases its driver before parent verification. Two stale PAUSED parent snapshots could therefore race after the join. Consequence: use a second exact non-reclaimable continuation claim over joined-parent verification/repair/resume, release before synchronous final evidence or an approval yield, and preserve uncertain claims for explicit owner-stopped recovery.
- Observation: graph delivery assembly requires a completed join, so attempting it during a pre-join failure could mask the original error and prevent cleanup. Consequence: failed-run handling records a bounded evidence.unavailable event for incomplete/corrupt provenance, preserves the original failure and still cleans resources; it never fabricates a successful bundle.
- Observation: cancellation retry previously inspected only parent leases. A CANCELLED graph with no parent leases but a failed descendant cleanup could return early. Consequence: inspect exact descendant leases on retry; other terminal states with remaining resources require explicit recovery without rewriting their terminal outcome.
- Observation: a self-hashed child node could differ from its frozen embedded plan, and a coherently substituted embedded plan could retain the original artifact ID/hash. Consequence: GraphSnapshot validates exact plan/node equality, and CompletionGate independently checks that equality plus the canonical pretty-JSON plan byte hash used by workflow artifact creation. Actual artifact read-back remains required.
- Observation: recovery JSON originally counted only parent leases, and human child-operation errors omitted the actionable parent ID. Consequence: expose application-owned exact parent/descendant IDs for recovery accounting and safely display the redacted parent ID in human errors. The final nine-case CLI E2E suite validates this behavior.
- Observation: ordinary graph ownership release rejects a terminal parent. Consequence: a known approved-resume rehydration failure records FAILED, atomically fences the graph and clears its owner, then cleans parent resources; it does not attempt ordinary release after terminalization. An uncertain subsequent run.resumed persistence failure still retains its claim for explicit recovery.
- Observation: missing artifact storage raised an OS path exception before the typed integrity check. Consequence: missing/raced/OSError/invalid-path reads now produce a typed cause-free artifact integrity error, and unavailable child cleanup can never silently pass assembly.

## Decision Log

- Decision: parent-owned final Verifier is a plan node, not a child Run. Rationale: original-task evidence must retain parent identity and see the full joined patch. Alternative: relabel child evidence; rejected. Date: 2026-09-05.
- Decision: use WAITING_FOR_CHILDREN, not an empty parent approval pause. Rationale: every approval pause must retain its exact request identity. Date: 2026-09-05.
- Decision: initial graph iteration 0 is immutable; joined-candidate repair uses an explicitly audited sequential parent Engineer. Rationale: minimizes replay and grant complexity while preserving bounded repair and independent proof. Alternative: recreate the entire graph and reset successful nodes; rejected. Date: 2026-09-05.
- Decision: no automatic driver lease expiry. Rationale: a timeout does not prove the prior process or external effect stopped. Explicit owner-stopped recovery abandons uncertain work. Date: 2026-09-05.
- Decision: retain backward-compatible loading of legacy advanced FleetPlan nodes, but require complete subgoal/criterion mappings at graph execution before creating children. Rationale: old representation-only advanced plans were never executable; missing boundaries must not silently inherit a broad parent task. Date: 2026-09-05.
- Decision: completed graph delivery carries typed snapshot, join receipt and every child cleanup receipt, while parent command evidence remains parent-owned. Rationale: node success is provenance, not a replacement for independent current-patch verification. Date: 2026-09-05.

## Outcomes

M2 adaptive graph acceptance PASSED on 2026-09-05. Normal fake/offline FunctionModel and real-Docker journeys execute all five strategies with bounded child identity, shared budgets, exact approval scopes, stable joins and fresh parent verification. Adverse scheduling, scope/artifact substitution, duplicate resume, uncertain ownership and descendant cleanup have retained regressions. Independent delivery review has no remaining findings in its bounded surface; final documentation/archive checks passed. The graph checkpoint commit remains pending. Full Phase 5, persistent chat, FleetPatch, release guide, fresh installation/platform proof, live-provider/license prerequisites and final GitHub merge remain open. CLI phase stays 4 until all Phase 5 acceptance gates pass.

### Final acceptance evidence

These local macOS arm64/Colima gates returned exit 0 on the unchanged source/test aggregate, except the explicitly retained failed attempt. Test selections overlap and counts must not be added. The aggregate is a byte-checksum, not a Git identity: `rg --files src tests -g '!**/__pycache__/**' | sort | xargs shasum -a 256 | shasum -a 256` returned `4cbef9616084ad1465ee5fd84b97f81763f282bc95b96c11b5bb7d35cfeafeb9` before and after final testing.

| Gate | Command / exact observed result |
| --- | --- |
| Dependencies | `uv lock --check --offline`: 51 resolved; `uv sync --all-extras --offline --locked`: 49 checked. |
| Final static refresh | `uv run ruff format --check .`: 203 formatted; `uv run ruff check .`: passed; `uv run mypy src tests`: 172 source files passed; `uv run python -m agent_fleet.schemas.generate --check`: 55 schemas, no drift; `git diff --check`: passed. |
| Default full suite | `AGENT_FLEET_ENABLE_DOCKER_TESTS=0 AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 uv run pytest -q`: **1344 passed, 13 skipped in 1160.72s**. Skips are twelve gated Docker cases and the unperformed live-provider case. |
| Separately enabled Docker | `AGENT_FLEET_ENABLE_DOCKER_TESTS=1 AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:phase3 uv run pytest -q -m docker_integration tests/docker --basetemp <fresh-shared-cache>/docker-pytest`: **12 passed, 3 deselected in 140.05s**. The three deselections are offline cases. |
| Resource read-back | Zero Fleet-managed containers; all 22 Docker-test state databases had zero active leases. Exact read-only inventory, not broad cleanup. |
| Subprocess E2E | `uv run pytest -q tests/e2e`: **9 passed in 214.64s**. |
| Final affected focus | Artifact, independent delivery and normal graph selection: **16 passed in 164.85s**. |
| Independent delivery audit | `uv run pytest -q tests/integration/test_graph_delivery_audit.py`: **11 passed in 144.48s**; own-file Ruff, mypy over source/fixture/audit (97 files) and whitespace checks passed. |
| Retained failed attempt | Pre-final marked integration: **2 failed, 212 passed, 85 deselected in 823.08s**; rehydration owner-release and missing-blob errors reproduced. Superseded by repaired focused and frozen full results above. |
| Package gate and final read-back | `uv build --offline --out-dir <temporary-package-root>/final-dist`, then `uv run pytest -q tests/integration/test_distribution.py tests/unit/test_schema_generation.py`: **4 passed in 2.82s** before final docs. README-frozen rebuild/read-back: **4 passed in 4.37s**; repeat after its README result entry: **4 passed in 1.73s**. Both archives match all 161 package source files and README, including 55 schemas, migrations 1–6 and five prompts. Isolated wheel-content smoke passes against existing locked dependencies, not a cold install. |

All model tests used deterministic fake or offline PydanticAI models; no live provider, ambient credential discovery, image pull or image build occurred. Real Docker establishes joined-code execution, not live model quality. Direct wheel-content smoke uses existing locked dependencies; no fresh-user/cross-platform installation is established. Remote read-back confirms only the preceding M1 tip `ab28aaa6192a8e4d92c78dada2413eb5606376b7` on `codex/mvp-completion`; `main` remains `c700de1fc357844113426d3352cf29b6ffeae0f1`. M2 commit/push and final merge are separate pending outcomes.
