# Phase 5: a persistent, bounded adaptive organization

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds. It refines Milestone 3 of `2026-09-05-mvp-completion.md`; that parent remains the complete-project and release ledger.

## Purpose and user-visible result

A user can say `fleet chat .`, submit a code-change request to CoS, handle exact approvals, restart the CLI, and receive the final patch with independent, criterion-specific evidence. CoS chooses only needed roles. Parallel changes use separate worktrees and converge into a newly verified patch. `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, and `/exit` work without asking a model to interpret control commands.

## Scope

### In scope

- Durable cumulative runtime accounting across successful, paused, failed, cancelled and reconstructed calls; logical-agent step ceilings and configured delegation restrictions.
- Canonical patches including bounded new regular files; consistent descendant path scopes; structured acceptance-criterion evidence mapping; repair feedback and useful direct responses.
- All five specified Fleet strategies through fake and offline PydanticAI adapters, plus real Docker code-change acceptance.
- Frozen graph/node identities, disjoint writer scopes, concurrency limits, deterministic join receipts, fresh parent verification, child approval/cancellation/recovery.
- Persistent bounded conversations and event-driven CLI interaction, with explicit run links and restart behavior.

### Out of scope

- Operational FleetPatch (Phase 6), release packaging/complete guide (Phase 7), external researcher networking, hosted/Modal execution, arbitrary shell or new model providers.
- Raw provider message history or SDK objects in durable state; automatic approval, patch application, trust changes, or budget increases.

## Current repository state

Phase 4 is accepted at `2e93092`. Milestone 1 is accepted, committed and pushed at `ab28aaa6192a8e4d92c78dada2413eb5606376b7`: durable budgets, configured role/delegation ceilings, repair/direct outputs, criterion mappings and new text files. Milestone 2 graph execution is accepted on the frozen checksum recorded below, with its checkpoint commit pending. SQLite schema 6 adds exact internal children, durable driver/continuation ownership and deterministic joins. All five strategies execute with shared cumulative budgets and fresh parent verification. Persistent conversation state and chat remain unimplemented; provider SDK history is deliberately not persisted. CLI whole-phase metadata remains 4.

## Security impact

All existing permission, secret, sandbox and evidence boundaries remain enforced. New specialist reports and conversation context are untrusted data, never permission. Role configuration requests can narrow but cannot expand hard ceilings. CoS cannot use Engineer tools. Read-only specialist tools must use the normal gateway and broker. No new provider endpoint or credential discovery is authorized.

Model requests reserve budget before provider dispatch, including PydanticAI internal retries. Tool batches validate completely and reserve allowance before the first effect. Unknown dispatched outcomes remain charged/explicitly unknown; retries cannot refund them or silently reset totals. Token accounting is not a guaranteed monetary pre-spend cap: responses can overshoot, and provider cost may be unavailable.

Child runs retain current strict run/task/agent/workspace/approval identities. A child is internal and cannot independently apply a patch. Its `--run` approval is visibly node-run-scoped, never silently parent-wide. Parent completion requires descendant cleanup. Foreign command evidence cannot be relabeled into parent evidence.

## Proposed design

### Durable budgets and evidence (first runnable slice)

Introduce `domain/budgets.py`, an accounting port and a SQLite ledger with explicit migration 5. A run has immutable effective limits; invocation attempts bind run, logical agent, task, stage and iteration. Transactions reserve model request/token allowances and validated tool batches. The model wrapper records normalized reported usage before structured-output validation. Every application invocation finishes its attempt even on approval, error or cancellation. The summary distinguishes reported, reserved and unknown usage. Legacy runs with no reliable ledger expose incomplete accounting instead of invented zero usage.

`VerifierVerdict` gains optional bounded structured criterion results with criterion IDs, status and exact evidence/command references. `EvidenceAssembler` resolves references only to current task, patch and independent verifier command records. Missing, duplicate, foreign or contradicted mappings cannot establish PASS. Existing single-criterion artifacts retain their conservative compatibility behavior. Multi-criterion tasks require complete typed mapping. Repair invocations receive bounded prior verdict/required repairs, not raw histories.

New-file patch extraction operates only on Fleet-owned workspaces with hardened Git execution, bounded regular-file paths and no protected/symlink/gitlink escapes. Descendant scopes use a shared canonical path predicate consistently in planning, gateway baseline, actual extraction and evidence.

### Adaptive graph (second runnable slice)

Use a parent frozen graph plus internal child Runs/TaskSpecs for advanced nodes, not recursive calls to public `start()`. Nodes bind `(parent run, plan hash, node ID, iteration)` to immutable child identities and dependency artifact hashes. A durable ownership/CAS guard prevents two graph drivers from creating duplicate resources/model calls. A crashed unfinished owner requires explicit recovery; it never grants effect replay.

CoS may propose bounded writer subgoals/scopes/criterion IDs. The planner constructs and validates the exact DAG, role availability/delegation, disjoint writer scopes and concurrency cap. More nodes than slots queue. Specialists are ephemeral read-only Researcher and Architect instances; bounded typed reports become dependency artifacts. Existing direct/single/pair paths remain small and do not instantiate unused roles.

The scheduler executes independent children concurrently, persists each child's pause separately, resumes only approved children, and blocks dependent nodes after failure/denial. Completed child identities/artifacts survive reconstruction. Parent joins validated exact-base child patches in stable node-ID order in a fresh parent-owned workspace; a persisted preparation receipt records ordered inputs. Conflicts preserve individual patches and fail closed. The parent extracts a fresh combined patch, then runs an independent Verifier on all original acceptance criteria. Child command evidence remains provenance only. Cancellation cascades only through exact descendants.

### Conversation (third runnable slice)

Use typed Conversation, Message, Turn and Context models with explicit sequence/revision and project identity. A trusted service persists bounded redacted messages and atomically binds one submitted turn to one run. Context is recent bounded messages plus deterministic compact summaries and authoritative run/artifact references, never whole repositories or raw model history. CoS receives the bounded context as untrusted input.

The CLI has a line-oriented asynchronous session and a noninteractive `--message`/`--json` path. Deterministic slash commands route to existing inspection/permission/cancellation services. While work runs, `/cancel` remains responsive; new messages cannot silently start concurrent runs for one conversation. Restart finds persisted turn/run status. Exit must explicitly handle active execution instead of orphaning it. No slash command or model output approves, applies or changes policy.

## Public contracts

- `RuntimeInvocationServices` gains a trusted optional accounting sideband for adapter conformance tests; the normal application path always binds durable accounting.
- New budget/attempt/request/snapshot Pydantic schemas, append-only accounting events and migration 5; old binaries reject newer schema.
- Backward-compatible optional structured criterion mapping; canonical path helper and new-file PatchInfo behavior.
- Subsequent graph/conversation models, migrations and CLI contracts are frozen before their implementation milestone. Existing v1alpha1 JSON envelopes stay intact.
- `RUNTIME_BUDGET_EXCEEDED` and `RECOVERY_REQUIRED` remain stable; no model text appears in raw exception/audit fields.

## Milestones

### Milestone 1: durable simple-path budgets and evidence

Acceptance: normal offline PydanticAI calls account for internal retries, tool batches, approval pauses, failed outputs, timeout/cancellation and restart. Concurrent reservations have one immutable ceiling. Role maxSteps cannot reset on approval. New-file-only changes yield real canonical diffs. Two-criterion verdicts require exact current evidence and contradictions downgrade assurance. Existing offline and Docker paths remain passing.

### Milestone 2: all five strategies execute

Acceptance: two writer invocations genuinely overlap without exceeding capacity; opposite completion/approval order yields the same joined patch; every declared specialist runs exactly when needed. Scope/dependency/base/artifact conflicts fail closed. Repeated resume cannot duplicate nodes or effects. Fresh parent verification sees both changes and all criteria; cancellation/recovery leaves no unmanaged descendants. Child patches cannot apply independently.

### Milestone 3: persistent chat and full Phase 5 acceptance

Acceptance: conversation reopen and project isolation, atomic duplicate-submit protection, bounded context, responsive cancellation, approval restart, event progress and evidence/usage summaries. A real Docker fixture journey initializes, requests a change through CoS, approves, verifies, reviews and explicitly applies it without manual agent management.

## Detailed implementation steps

1. Implement the budget domain/port/SQLite migration and adapter accounting hooks with security/restart/concurrency tests. Integrate trusted lifecycle accounting in `_invoke_runtime_agent`, run start/resume and summaries.
2. Add structured criterion mapping and conservative evidence resolution, new-file canonical extraction and shared path scope semantics. Pass bounded repair feedback and configured role step ceilings through workflow invocations.
3. Freeze graph domain/persistence contracts, then extend planner/runtime role contracts, templates, catalogs and scheduler. Add internal prebound child-run entry point and explicit patch-apply prohibition.
4. Add deterministic exact-base join, original-task parent verifier, graph approval/cancellation/recovery and negative tests.
5. Freeze conversation domain/persistence contracts; add application service, bounded context and asynchronous CLI. Test normal adapters and reconstruction, not only mocked calls.
6. Regenerate schemas; update specs, ADRs, README and parent ledger with exact full acceptance results; obtain independent fresh review and commit the accepted Phase 5 checkpoint.

## Validation plan

Run focused tests after each change. At each coherent milestone run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src tests`, schema generation drift check and relevant unit/contract/integration/E2E suites. Final Phase 5 repeats every command in the parent plan, default offline full suite, separate opted-in Docker suite, zero residual managed-container check and offline package build.

Budget tests must cover multi-process reservation races, duplicate settlement, invalid persisted binding, structured retry counts, pre-tool limits, approval/failure/cancel accounting, no secret persistence and honest unknown usage. Evidence tests cover missing/foreign/duplicate/failed criterion references and fake/unsafe non-verification. Patch tests cover new files, tracked edits/deletes, symlinks, protected paths, size limits, unsafe Git configuration and deterministic identity. Graph/chat tests are listed in the milestone acceptance criteria and must assert persisted identities/events/artifacts.

## Rollback and recovery

Keep the accepted Phase 4 commit; do not rewrite it or discard unrelated changes. Migration is forward-only. Immutable budget limits and charged unknown requests survive restart. A provider request with uncertain result is never assumed free. Paused logical agents reuse exact identity with new physical attempts. Existing permanent tool dispatch claims are unchanged. Graph ownership and joins retain prepared records and reconcile exact artifacts rather than replaying effects. Conversation turns preserve one run link across restarts and never duplicate a submission implicitly.

## Progress

- [x] (2026-09-05) Phase 4 full gates passed before Phase 5 implementation; independent graph/chat/budget design audits completed read-only.
- [x] (2026-09-05) Created this detailed plan before substantial Phase 5 work.
- [x] (2026-09-05) Implemented and accepted Milestone 1: durable budgets/criterion/new-file simple-path slice. This does not accept the subsequent graph/chat milestones or all of Phase 5.
- [x] (2026-09-05) Integrated immutable run ledger initialization, per-invocation accounting sideband, terminal/paused/cancelled attempt recording and status/summary snapshots. Initial normal-workflow budget tests: 5 passed in 7.23s; a remaining-active-time timeout regression is being added after review.
- [x] (2026-09-05) Added configured/hard role step caps, actual CoS delegation checks, bounded exact prior-verdict repair feedback and explicit direct-response artifacts. Independent regression file passed 14 tests in 29.71s. A concurrent existing workflow/runtime/plan run passed 82 tests and failed one DIRECT fixture assertion because it loaded the fake adapter before its response field landed; a focused frozen rerun is required and the failure remains recorded.
- [x] (2026-09-05) Normal budget/direct focused rerun: seven tests passed in 10.21s. After adding exact delivery-evidence summaries and a cause-free unexpected-harness-error regression, the seven budget workflow tests passed in 10.93s. Independent role/budget combined rerun passed 20 tests in 41.83s. These are focused results, not the full slice acceptance.
- [x] (2026-09-05) Independent corruption replay closed the owner-remapping, duplicated agent identity and raw exception-context findings: all four probes now fail with `RECOVERY_REQUIRED`, no attempt/request is admitted under mismatched identity, and registered secrets do not survive in the public exception or its context.
- [x] (2026-09-05) Added the normal offline FunctionModel two-criterion/new-module journey in `tests/docker/test_phase5_evidence.py`: fake execution remains INCONCLUSIVE; real Docker separately passed one test in 7.25s with two independent command records, two PASS assessments, exact new-file patch reconstruction, explicit target apply and zero remaining resources. Its offline case plus criterion units passed 32 tests in 5.67s.
- [x] (2026-09-05) Frozen Milestone 1 acceptance: default suite `1170 passed, 11 skipped in 648.79s`; all ten Docker skips separately passed in `62.24s` with one offline case deselected. The remaining skip is the unperformed live-provider canary. Formatting (181 files), lint, mypy (155 source files), offline lock/sync, regenerated-schema check and whitespace gates passed. Full command/evidence log is below; earlier in-flight failures are superseded by this frozen run, not erased.
- [x] (2026-09-05) Final staged whitespace check found one extra empty EOF line in new migration `0005.sql`, which the earlier unstaged diff check could not inspect while it was untracked. The source owner removed only that empty line. `uv run pytest -q tests/unit/test_dispatch_claims.py tests/contract/test_runtime_budgets.py` then passed 71 tests in 1.99s; `git diff --cached --check` passed. Offline archives were rebuilt and exact source/README bytes, corrected migration EOF and exclusions rechecked successfully. No semantic source change or additional full-suite claim accompanies this correction.
- [x] (2026-09-05) Committed accepted Milestone 1 as `ab28aaa6192a8e4d92c78dada2413eb5606376b7`; created the detailed `2026-09-05-adaptive-graph.md` plan and ADR 0004 before graph implementation. Phase 4 and M1 were subsequently pushed to `codex/mvp-completion`; remote read-back matches `ab28aaa`. Main remains `c700de1fc357844113426d3352cf29b6ffeae0f1`; no new merge or whole-Phase-5 acceptance is claimed.
- [x] (2026-09-05) Implemented and accepted Milestone 2: frozen default `1344 passed, 13 skipped in 1160.72s`; real Docker `12 passed, 3 deselected in 140.05s`, zero managed containers and zero active leases in all 22 state databases; E2E `9 passed in 214.64s`; affected focus `16 passed in 164.85s`; independent delivery audit `11 passed in 144.48s`. Source/test checksum remained `4cbef9616084ad1465ee5fd84b97f81763f282bc95b96c11b5bb7d35cfeafeb9`. Latest formatting checked 203 files, lint/mypy (172 files)/55-schema/whitespace checks passed; lock resolved 51 and sync checked 49. Package/schema tests passed four cases in 2.82s before documentation-final rebuild. M2 checkpoint is pending.
- [x] (2026-09-05) Retained the pre-final integration failure (`2 failed, 212 passed, 85 deselected in 823.08s`): terminal rehydration attempted ordinary owner release, and missing child cleanup raised a raw OS error. Failure fencing, cause-free artifact reads and exact embedded plan/join/cleanup hash checks now pass focused and final suites. See the graph ExecPlan for the command/evidence log.
- [ ] Freeze, implement and accept persistent conversation slice.
- [ ] Full Phase 5 gates, documentation, independent review and checkpoint commit.

## Discoveries

- Observation: PydanticAI may perform structured-output retries within one outer invocation. Evidence: `_SecretBoundaryModel.request` sees every physical model request while `_persist_runtime_observation` sees only successful final output. Consequence: account at the model wrapper plus an application attempt lifecycle, not only around `agent.run`.
- Observation: Current grants/dispatch/evidence bind one run and task exactly. Consequence: internal child Runs preserve that invariant; a shared-run DAG would require a much larger authority-schema rewrite.
- Observation: Scope validation currently mixes exact membership and descendant semantics, and Git extraction omits untracked files. Consequence: fix and regression-test these before joining parallel candidate patches.
- Observation: Cumulative active-time checks only at the next tool/request would let one slow request overrun the remaining budget. Consequence: also wrap active invocation/request execution in the trusted remaining deadline, then preserve unknown provider accounting after interruption.
- Observation: Missing provider token counters cannot be treated as known zero. Consequence: retain partial reported facts and the reserved allowance, explicitly mark unknown usage and fail closed; PydanticAI zero-default provenance requires conservative handling.
- Observation: Independent persisted-corruption probes demonstrated same-project owner remapping could omit old spending, mismatched SQL/JSON agent identities could still reserve requests, and raw validation exception context could retain a registered secret. Consequence: Milestone 1 now requires exact initialization-event/owner-chain binding, validated duplicated Run/Task/Agent columns at dispatch and cause-free boundary errors; retained regressions and the independent four-probe replay reject these cases.
- Observation: Git binary-patch encoding can conceal registered secret bytes from text-only artifact scanning. Consequence: this slice accepts bounded regular UTF-8 changes only, rejecting changed/deleted binary content while leaving unchanged binary repository assets alone. New-file/patch index integrity and exact emitted-patch path parsing are separately tested.
- Observation: An in-flight grouped test process loaded an intermediate new-file extractor before its content-aware changed-path fix (nine failures, sixteen passes, thirty-two deselections); a fresh normal-workflow test passed after the fix. Consequence: freeze source and repeat the entire affected group rather than treat an earlier process as current acceptance.
- Observation: A network-disabled clean wheel installation still needs dependencies absent from the local cache; the Python 3.14.6 attempt specifically could not resolve cached PyYAML. Consequence: successful offline builds, exact archive contents and direct wheel execution against locked dependencies do not establish fresh-user installation or the Phase 7 release gate.

## Decision Log

- Decision: implement budget/evidence, graph, then chat as separately demonstrable slices. Rationale: each normal execution path stays testable and the durable graph depends on correct cumulative accounting and patch semantics. Alternative: broad simultaneous placeholders. Date: 2026-09-05.
- Decision: preserve exact node-run approval identity and independently verify only the parent joined patch. Rationale: reusing child evidence as parent authority would violate existing evidence bindings. Alternative: widen every existing grant/intent/evidence schema to shared-run nodes. Date: 2026-09-05.
- Decision: persist portable bounded context, not raw provider history. Rationale: provider-neutral state, strict secret boundaries and predictable size; reconstructed models may use different display prose without changing execution intent. Date: 2026-09-05.
- Decision: text-only canonical patch delivery until binary content has a separate proven secret-scanning boundary. Rationale: the MVP text-edit tool surface does not need binary mutation, and Git binary encodings must not hide registered secret bytes. Alternative: introduce optional guards with a permissive default; rejected. Date: 2026-09-05.

## Outcomes

Milestones 1 and 2 are accepted on 2026-09-05. M1 provides bounded durable accounting, role/delegation ceilings, repair/direct outputs, text-only new files and exact criterion mappings; M2 executes all five strategies with independently bound children, stable joins and fresh parent verification. Legacy runs without reliable accounting remain `legacy_unknown`; uncertain dispatched ownership never permits replay. Phase 4 (`2e93092`) remains the last accepted whole phase. M1 is committed/pushed at `ab28aaa`; M2's final documentation archive read-back passed four tests in 4.37s and repeated in 1.73s; its checkpoint remains pending. Persistent chat, full Phase 5, Phase 6/7, live-provider/license prerequisites and final main-branch delivery remain open. The graph ExecPlan contains the exact M2 acceptance log; the following M1 record remains historical.

### Milestone 1 command and evidence log

The frozen gates ran on macOS arm64 with Python 3.14.6, Pydantic 2.13.5, PydanticAI 2.39.0 and pytest 9.1.1. Docker used the preloaded `agent-fleet-runner:phase3` image and a fresh `mktemp` directory beneath the host-shared cache for `--basetemp`; no image pull/build or live model call occurred.

| Gate | Command and observed result |
| --- | --- |
| Schema regeneration | `uv run python -m agent_fleet.schemas.generate`; expected Phase 4 delta: four updated JSON Schemas and six new schemas, 43 total. No additional generator drift. |
| Dependencies | `uv lock --check --offline`: 51 resolved; `uv sync --all-extras --offline --locked`: 51 resolved, 49 checked. |
| Formatting/lint/types | `uv run ruff format --check .`: 181 formatted after the source owner fixed one wrapping-only difference; `uv run ruff check .`: passed; `uv run mypy src tests`: 155 source files passed. |
| Default full suite | `AGENT_FLEET_ENABLE_DOCKER_TESTS=0 AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 uv run pytest -q`: **1170 passed, 11 skipped in 648.79s**. Skips are exactly ten gated Docker cases and one gated live-provider case. |
| Separate Docker suite | `AGENT_FLEET_ENABLE_DOCKER_TESTS=1 AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:phase3 uv run pytest -q -m docker_integration tests/docker --basetemp <fresh-shared-cache>/docker-pytest`: **10 passed, 1 deselected in 62.24s**. |
| Resource read-back | Local-daemon preflight plus read-only managed-label listing found zero managed containers; all 18 Docker-test state databases contained zero outstanding resource leases. No broad cleanup was performed. |
| Drift/whitespace | `uv run python -m agent_fleet.schemas.generate --check` and `git diff --check`: passed. Final `git diff --cached --check` also passed after the whitespace-only migration correction and 71-test focused rerun recorded above. |
| Offline archives | `uv build --offline --out-dir <fresh-shared-cache>/dist`: wheel and sdist built; each contains 140 package files, 43 schemas, migrations `0001`–`0005`, and three runtime prompts. Every packaged source byte matches the checkout; tests, plans, development state, local home paths and acceptance secret sentinels are excluded. |
| Installed-content smoke | Direct wheel import, `fleet version --json` (version `0.1.0`, whole-phase metadata `4`), 43 schema resources and fresh SQLite migration through version 5 passed against the locked dependency environment. |

The independent end-to-end Docker fixture invokes the real PydanticAI protocol with an offline FunctionModel, writes an existing module plus a new UTF-8 module through the gateway, and runs the exact dependency-free command in separate Engineer/Verifier workspaces. Both transcripts contain three successful tests and the sandbox-boundary marker. Two explicit criterion references resolve to the fresh verifier receipt and yield `verified_complete=true`; the identical fake-sandbox mapping remains INCONCLUSIVE. The target is unchanged until explicit `PatchService.apply` after control-plane reconstruction.

A supplemental clean, network-disabled wheel installation was attempted on Python 3.13.15 and 3.14.6 but could not resolve uncached dependencies (including PyYAML); fresh-user installation is not claimed. No actual provider credential or live provider was used. Graph/specialist execution was subsequently accepted under M2 above. Persistent chat, full Phase 5 acceptance, Phase 6/7, cross-platform/fresh-user release proof, the owner license decision and final GitHub merge remain open.
