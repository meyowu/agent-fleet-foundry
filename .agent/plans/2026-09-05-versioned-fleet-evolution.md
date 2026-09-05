# Phase 6: reviewable, versioned Fleet evolution

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log and Outcomes. It implements Milestone 4 of `2026-09-05-mvp-completion.md`. This initial version was prepared during Phase 5 final gates, which have now passed. **No Phase 6 source implementation is authorized until the accepted Phase 5 checkpoint and the exact writer contracts below are finalized.**

## Purpose and user-visible result

A user tells CoS: “For backend changes, always run integration tests.” CoS produces a validated FleetPatch proposal with semantic and textual diffs; the organization remains unchanged. Explicit user application creates an audited configuration version. A later backend task actually requires the exact integration command in its TaskSpec and independent evidence. Rollback is a new reviewed inverse change, not deletion of history.

```text
fleet chat .
> For backend changes, always run integration tests.
fleet fleet-patch diff <proposal-id>
fleet fleet-patch apply <proposal-id>
fleet fleet-patch rollback <applied-proposal-id>
```

Rollback is itself the user's explicit authorization for an exact current-head inverse. It persists a new inverse proposal and a new application operation, then restores through the same reviewed publication protocol. The returned new IDs/diffs remain inspectable; history is never erased.

## Scope

### In scope

- Reuse the existing FleetPatch wire format, IDs, path/base/content/secret validators; add missing aggregate/ancestry constraints.
- Natural-language CoS proposal delivery through the ordinary bounded Run/conversation, with no Engineer, worktree, direct repository write or tool-authorized application.
- Typed referenced workflow definitions and declarative verification skills whose path-conditioned requirements are actually consumed by TaskSpec/verification/evidence construction.
- Complete bounded organization-tree manifests, staged validation, durable immutable proposals/versions, exact semantic/text diffs, explicit apply and inverse rollback.
- Project-wide mutation fencing, atomic same-filesystem whole-directory exchange, exact recovery journal and Project configuration rebinding.
- CLI list/show/diff/apply/rollback, explicit stopped-owner recovery if publication outcome is uncertain, schema/migration/security/behavioral tests and documentation.

### Out of scope

- Changing `.fleet/fleet.yaml`, user trust, credentials, grants, approval ownership, hard denies, sandbox/provider/runtime ceilings or audit history through FleetPatch.
- Arbitrary new roles/topologies, executable skill scripts, shell/network expansion, remote filesystem/daemon trust, a hosted registry or automatic evolution/application.
- Applying arbitrary old rollback snapshots over newer versions. The minimum rollback targets the current applied version only and fails on drift.
- Phase 7 packaging/complete guide/platform release proof and live-provider/license prerequisites. No actual credential will be discovered or selected.

## Current repository state

Phase 0–5 is accepted; previous checkpoints are pushed through `7a70b1a` and the accepted chat checkpoint is being finalized. Chat adds atomic conversation/Run ownership and migration 7. The full default suite passed 1472 tests, thirteen real-Docker cases passed separately, and metadata advanced to 5 only after those gates. The persistent-chat plan records exact evidence and post-marker refreshes. No Phase 6 source change has begun.

`domain/fleet_patch.py` currently validates the FleetPatch wire schema, exact file content hashes, base hash and allowed organization paths, including pre-parse/whole-proposal registered-secret checks. It has no operational persistence or CLI. `adapters/config/yaml.py` validates FleetSpec and VerificationProfile, snapshots referenced files and publishes only a new nonexisting `.fleet` tree. Referenced workflow YAML is currently snapshotted but not parsed as an executable typed definition. No operational skill model exists. `WorkflowEngine._scope` freezes verification commands directly from VerificationProfile. Thus editing workflow prose alone cannot implement the backend requirement.

ConfigSnapshot deliberately covers only FleetSpec and referenced files. README and unreferenced safe files are outside that logical hash. A directory replacement must also bind and preserve the complete bounded tree, or it could silently lose user content. `SqliteStateStore.save_project` is an unconditional upsert, so application evolution also needs a revision/fence transaction, not a racy list-of-running-Runs check.

## Security impact

All AGENTS and SECURITY_MODEL invariants remain. CoS output is untrusted data, including proposal IDs, hashes, rationale and claims of validation. The control plane preallocates and checks expected project/proposal/base identities, rebuilds the prospective tree, derives diffs and validates supported runtime semantics. Tool catalogs expose neither apply nor permission mutation. Adding a required command never grants permission to execute it; current Broker/Grant/dispatch rules still apply, including separate Engineer/Verifier identities.

Proposal persistence and filesystem publication are separate boundaries. All saved payloads/artifacts/errors are bounded and registered-secret scanned. Safe unreferenced files are preserved byte-for-byte; symlinks, hardlinks, special files, case aliases, path ancestry conflicts, invalid UTF-8, protected/sensitive tree entries and bounds violations fail before staging/publication. `.fleet` remains a real directory, not a pointer symlink. The local OS account/filesystem remain trusted; no cross-account tamper-proof claim is made.

An exact project fence must participate transactionally in Run registration (ordinary and chat), configuration-dependent continuation, initialization/rebinding and target code-patch apply. A caller whose preflight used an old configuration must fail after an intervening version change. The fence does not expire automatically. Recovery requires confirmation that the original publisher stopped and never overwrites an unexpected target.

Admission must bind a monotonic head revision and complete tree identity, not only the logical config hash: README-only changes can preserve that hash and rollback can repeat it. Freeze the exact legacy/no-head compatibility contract before changing existing Run/conversation/graph binding serialization. Blockers include CREATED, running, paused/child-wait states, retained claims and outstanding descendant/failed leases. Ready-for-review candidates from an older organization version must not apply even if rollback later repeats their logical hash.

## Proposed design

### Typed configuration and effective behavior

Preserve the existing valid generated Workflow shape and top-level FleetSpec ceilings. Add strict referenced code-change workflow/verification-skill schemas; exact field names and defaults are frozen before their writer begins. Skills are declarative requirements over canonical repository path prefixes and reviewed verification command IDs, not scripts or new authorization.

For a code-change TaskSpec, union baseline required commands with requirements whose path scope intersects the allowed candidate scope. Broad parent scope also intersects a narrower backend prefix; CoS cannot evade a requirement with a broader scope or by omitting a command from its output. All referenced commands must exist, match the supported canonical command surface and retain `networkRequired=false`. Direct read-only responses do not run behavioral commands. Parent joined verification covers the original complete requirements; child scope may narrow work but cannot relax final parent evidence. Verifier mutation immunity remains unconditional trusted code, never a configurable prompt choice.

Prospective whole-tree validation checks schema/reference closure, unique names, size/encoding constraints, runtime capabilities and unchanged protected settings. Referenced skills join ConfigSnapshot using deterministic ordering; existing snapshots without skills retain their exact serialization/hash behavior. Semantically malformed workflow YAML that used to be merely opaque is rejected with a migration/compatibility explanation, not silently accepted.

The narrow wire direction is `WorkflowDefinition.verificationSkills` referencing canonical `skills/*.yaml` beneath `.fleet`, and `VerificationSkill` with version/kind/name, `appliesToPaths` and `requiredCommandIds`. Explicitly extend the existing FleetPatch allowlist only for this validated declarative skill type. Reject executable skill payloads, duplicate YAML keys, dangling/undeclared skill references and inconsistent duplicate workflow limits; no generic configuration loading of arbitrary plugin content.

### Proposal delivery through CoS

The preferred narrow output seam is `ScopeDecision | FleetPatch` for CoS only; other role output schemas stay unchanged. Keep the existing FleetPatch serialization and validator import API. Resolve the current models/fleet_patch dependency cycle by moving only pure schema declarations to a shared non-cyclic location or to models with re-exports, not inventing another mutation format.

The trusted invocation supplies a preallocated proposal ID/project/base and bounded current organization context. `_scope` recognizes a validated FleetPatch and builds a direct/read-only proposal-delivery Task/Plan. It persists recomputed proposal/snapshot/manifest/diff evidence and a bounded CoS response, then completes that turn without applying files. Neither the model's selected strategy nor prose can invoke a publisher. The same cumulative accounting, exact conversation owner and secret checks govern proposal calls. Oversized or incomplete context is explicit; a proposal cannot change a file whose exact before identity the control plane cannot establish.

### Durable version journal

Migration 8 is expected to add four records: proposals, immutable configuration versions, project head/fence, and publication operations. Exact Pydantic shapes, authority reads and method signatures will be frozen before implementation.

- Proposal: original FleetPatch and hash; exact project/repository/source Run; base version; before/after logical ConfigSnapshot and complete tree manifest refs; semantic/text diff refs; validator version.
- Version: `(project_id, version)`, predecessor, config/tree hashes, exact artifact refs and originating operation.
- Head: revision, active version and optional pending operation.
- Operation: exact claim/proposal/head revision, before/after identities, explicit user-authorization receipt, status/timestamps and append-only audit binding.

Operation states are PREPARED, COMMITTED, ABORTED and RECOVERY_REQUIRED. An unknown operation is not replayable. First observed version registration records a baseline, not invented historical user approvals. Read APIs validate SQL/JSON identity, immutable receipts and exact artifact bytes before reporting an applicable proposal. Run creation cannot bypass a pending head/fence through a legacy no-chat helper.

### Atomic publication and recovery

1. Read the complete bounded current tree; prepare exact prospective contents and logical snapshots. Stage them in a descriptor-validated private `0700` scratch directory beside the repository, outside the repository itself, on the same filesystem.
2. Fail before publication if scratch ownership/privacy, filesystem identity, directory handles, native atomic exchange or required durability operations are unavailable. Never fall back to multi-file overwrite or an exposed staging tree inside the repository.
3. Acquire the exact repository publication lock. In SQLite `BEGIN IMMEDIATE`, recheck Project/config/head and outstanding active/paused/owned work/resources, acquire the project fence and record prepared audit before filesystem mutation.
4. Revalidate pinned before/after trees and atomically exchange the two real directories using the supported macOS/Linux same-filesystem primitive. Fsync exact affected directories. The prior tree becomes the owned backup.
5. One SQLite transaction records the new immutable version, CAS-updates Project configuration bindings, advances the head, records completed audit and releases the fence. Clean only exact owned scratch after authoritative commit read-back.

Before exchange, staged file contents, complete manifest and exact owned directory metadata must have their supported durability operations completed. Freeze supported file/directory modes and both before/after pinned identities. Persist content-addressed before and after bytes for every whole-tree file, including README/unreferenced content, so rollback works after the temporary backup is removed. Hash-only manifests or a textual diff cannot reconstruct an exact inverse.

Publication must also rebind the exact Fleet-owned Git status allowance: otherwise tracked `.fleet` changes can cause the next promised task to fail PROJECT_DIRTY. Recompute only the reviewed organization delta while proving unchanged source/index/HEAD and unrelated user status. Test both initially untracked generated `.fleet` and tracked organization files. Do not broaden the ordinary dirty-worktree allowance or rewrite old Run evidence.

SQLite and filesystem cannot form one transaction; the journal/fence makes the intervening state unavailable for execution and explicitly recoverable. PREPARED plus exact unchanged target can abort. Exact after-target plus exact before-backup can be explicitly reconciled after owner-stopped confirmation. COMMITTED plus exact after-target returns the original result without a second exchange. Any unknown hash/owner/target/backup retains the fence and reports RECOVERY_REQUIRED. A caught pre-commit failure may restore only when both trees still match and commit failure is known; uncertain commit outcome cannot trigger an automatic reversal. Recovery never cleans a broad sibling directory or resets the repository.

Rollback validates that the selected applied proposal is still the current head, reconstructs exact prior bytes as a new inverse FleetPatch linked by `rollback_of`, persists new diff evidence and applies it under that explicit user command. Drift/newer versions fail; the inverse uses the same full validation and publication protocol. An optional preview may persist/show the inverse without applying it, but bare rollback must not report restoration when only a proposal was created.

## Public contracts

- `fleet fleet-patch list|show|diff|apply|rollback`, selected project where required, stable JSON envelopes and typed conflict/recovery errors. Apply always consumes one exact persisted immutable proposal, not a model-provided filesystem path. Rollback creates and applies an exact inverse through a new audited operation under explicit user authorization.
- CoS output union preserves the existing ScopeDecision tool name and role contracts; add one named FleetPatch output without exposing application tools.
- Strict workflow/verification-skill schemas and deterministic effective requirement calculation. No protected FleetSpec or trust-schema expansion.
- Typed manifest/proposal/version/head/claim/operation/publication receipts; migration 8 with forward-only compatibility.
- Exact event identities for proposed/prepared/applied/aborted/recovery/rollback proposal; all append-only and redacted.
- Precise field/method names, transaction guards, filesystem port and single-writer ownership remain **design pending**, not delegated source contracts yet.

## Milestones

### Milestone 1: executable configuration semantics and safe proposals

Acceptance: a normal offline CoS call produces the existing FleetPatch format; resulting schemas/references/requirements validate; semantic and text diffs survive reopen; original tree/trust remain unchanged. A malformed/protected/secret-bearing proposal fails before authority-bearing persistence. Required backend commands are deterministic configuration semantics, not prompt wording.

### Milestone 2: exact version publication and inverse rollback

Acceptance: user apply performs one atomic version update with exact audit/head/Project bindings. Concurrency, every publication cut point and stale Run/init/code-patch races fail safely. Explicit rollback creates/applies a new inverse and restores exact before bytes without erasing history. Unreferenced safe files survive unchanged.

### Milestone 3: complete Phase 6 behavioral and independent acceptance

Acceptance: public bootstrap/chat/proposal/diff/apply/new backend task/exact approval/independent Docker evidence/rollback journey proves the new command becomes mandatory only after application. Protected policy and verifier mutation denial remain unchanged. All quality, unit, contract, integration, offline E2E, full default, Docker and package gates pass on a frozen source identity; independent verifier returns an evidence-backed verdict before checkpoint.

## Detailed implementation steps

1. Finish Phase 5 gates/docs/checkpoint. Finalize the precise domain/port/concurrency contracts here and assign disjoint single writers before any Phase 6 source change.
2. Add strict workflow/skill models, reference closure and requirement consumption in config loading/TaskSpec construction; retain generated legacy valid files and exact old snapshot identity where no skill exists.
3. Harden the existing FleetPatch validator and establish bounded complete-tree/proposal/version/operation models plus generated schemas.
4. Implement exact filesystem read/stage/exchange/inspect/cleanup behind a project-owned port; verify native primitive semantics against primary platform documentation and test real supported filesystem behavior.
5. Implement migration 8 journal/head/claims and transaction-local project fence checks shared with ordinary/chat Run creation, continuation, registration and target patch application.
6. Add application proposal/diff/apply/rollback/recovery with exact artifact read-back and durable before/after audit. Wire the CoS output branch and thin CLI; no model-authorized apply surface.
7. Add normal and adversarial lifecycle/race/publication tests, real-Docker behavior and CLI E2E. Update specs/ADRs/README/acceptance ledger, run frozen full gates and commit/push only accepted behavior.

## Validation plan

Run `uv lock --check`, `uv sync --all-extras`, Ruff format/lint, `mypy src tests`, schema `--check`, unit/contract/marked integration/E2E/default suites, offline archives and `git diff --check`. Run all real Docker tests separately with explicit local Python/pytest runner; no live provider calls or ambient key use. Re-read managed containers and every acceptance state's outstanding leases/fences after tests.

Required negative cases: changed proposal/project/base/content/artifact hashes; protected-field/path aliases and ancestry; traversal/symlink/hardlink/special files; bounded tree/context/UTF-8/registered secrets; invalid schema/reference/capability; omitted baseline/conditional command; model apply attempt; changed exact command grant; two-process apply race; stale normal/chat registration and init/code-patch apply; failure before/after prepare, exchange, fsync and SQLite commit; ambiguous restart; current-only rollback and unreferenced-file preservation. Assertions use real persisted state/events/bytes/evidence, not callback counts.

## Rollback and recovery

Source checkpoints remain recoverable Git commits; never reset unrelated work. State migration is transactional/forward-only. Configuration rollback is a new reviewed inverse operation and cannot edit trust/audit or silently undo a newer version. Incomplete publication retains exact hashes/owner/fence and refuses new execution until explicit safe reconciliation. No automatic timeout takeover, duplicate exchange, broad scratch removal, target reset or guessed restoration is allowed.

## Progress

- [x] (2026-09-05) Read-only application/config and persistence/publication audits ran alongside frozen Phase 5 gates. Recorded this living plan before Phase 6 implementation.
- [x] (2026-09-05) Established that opaque workflow prose, bootstrap create-only publication and referenced-only ConfigSnapshot cannot independently meet operational evolution requirements.
- [x] (2026-09-05) Independent read-only design review identified five contract refinements now recorded above: monotonic head/tree admission, exact Git dirty-state rebinding, staged-file durability and recovery identities, explicit skill reference closure, and immutable prior bytes sufficient for rollback after backup cleanup. These are required design constraints, not implementation or acceptance claims.
- [ ] Phase 5 accepted checkpoint; exact Phase 6 contracts and writer ownership frozen.
- [ ] Typed executable configuration and persisted CoS proposals.
- [ ] Atomic version apply, project fencing and inverse rollback/recovery.
- [ ] Full Phase 6 gates, independent verdict, documentation and checkpoint.

## Discoveries

- Observation: referenced workflow YAML is currently opaque and skills are absent. Consequence: add a narrow typed requirement path that actually affects immutable TaskSpec and final evidence; do not present prose changes as enforcement.
- Observation: logical ConfigSnapshot omits README/unreferenced content. Consequence: separately bind a complete tree manifest and preserve safe extras; a README-only version may change the tree hash without changing the logical configuration hash.
- Observation: bootstrap publication rejects replacement, and a symlink root is rejected by the loader. Consequence: use a dedicated same-filesystem real-directory exchange provider with no weaker fallback.
- Observation: config preflight and Run/Project writes are separated in time. Consequence: transaction-local project fencing plus expected configuration identity is required; a preflight list alone cannot serialize evolution against new execution.

## Decision Log

- Decision: protect FleetSpec, trust, credentials and sandbox ceilings; evolve existing role guidance and typed workflow/verification requirements. Rationale: the smallest working organization change does not need new authority or arbitrary roles. Date: 2026-09-05.
- Decision: stage privately beside, never inside, the repository; require same-filesystem atomic directory exchange. Rationale: retain a real `.fleet` directory and one visible full version without exposing temporary unreviewed files as repository content. Unsupported environments fail closed. Date: 2026-09-05.
- Decision: current-head rollback generates and applies a new inverse under the explicit rollback command. Rationale: the command is already exact user authorization; an extra mandatory apply step would surprise the ordinary rollback contract without adding authority protection. Initial design considered proposal-only rollback; refined before implementation after the CLI/spec audit. An optional preview remains possible, and all history/new IDs are retained. Date: 2026-09-05.

## Outcomes

Design preparation only. No Phase 6 code, schema, migration, state or repository mutation has been implemented by this plan. Phase 5 gates passed; its accepted checkpoint and frozen detailed Phase 6 contracts remain the implementation gate. Native-platform verification, full behavior and release evidence remain open.
