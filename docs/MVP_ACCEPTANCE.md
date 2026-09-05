# MVP acceptance ledger

This is a living review ledger, not a release declaration or a user guide. It maps the normative requirements in `PRODUCT_SPEC.md`, `IMPLEMENTATION_ROADMAP.md`, and `SECURITY_MODEL.md` to implementation evidence and remaining proof. The governing implementation plan is `.agent/plans/2026-09-05-mvp-completion.md`.

## Evidence boundary and update rules

The initial audit on 2026-09-05 inspected the Phase 3 baseline at commit `c700de1fc357844113426d3352cf29b6ffeae0f1`, tree `eb778abcc5c073d4c58f54e6a55c7a04d6333ea4`. **Phase 4 is accepted by E4 below.** This covers the tested local working tree, not a new commit, merge or complete MVP release. No frozen Phase 4 Git identity or separate durable raw log path was recorded; exact command results are retained in the active ExecPlan. Older entries remain historical unless explicitly superseded.

- **Baseline:** relevant code and tests exist; this ledger's initial audit did not rerun those suites.
- **Partial:** a working subset exists but does not meet the complete requirement.
- **Missing:** no operational implementation or required artifact was found at the baseline.
- **Unproven:** implementation or historical evidence may exist, but the required current acceptance evidence has not been recorded.
- **Accepted Phase 4 (E4):** the bounded Phase 4 behavior passed its final regression, full-suite, static, archive and real-Docker gates. Phase 5–7 and live-provider/license prerequisites remain open.
- **Optional/deferred:** explicitly optional or outside this MVP; this is not a label for unfinished mandatory work.

Each acceptance record must state exact commands, exit status, counts/skips, platform and evidence type; link available commit/tree identities and state/events/artifact hashes, explicitly identifying missing identity or raw-log records rather than inventing them. Record whether evidence came from fake runtime, offline PydanticAI TestModel/FunctionModel, a live provider, simulated sandbox, real Docker, or local-unsafe. Preserve failures and superseded evidence. Working-tree acceptance is separate from immutable release/publication evidence.

The initial audit ran only two in-memory probes: malformed referenced Workflow YAML passed `validate_fleet_files`, and a FleetPatch containing both `.fleet/agents/a` and `.fleet/agents/a/b.md` passed the current path validator. No project configuration, Fleet state, provider request, credential resolution, or Docker operation was performed by those probes. Historical Phase 3 test counts and manual Docker results remain in its ExecPlan; they are not fresh Phase 4–7 evidence.

### E4 — accepted Phase 4 snapshot, 2026-09-05

The following gates returned exit 0 on the local macOS/Colima acceptance environment. The final aggregate supersedes earlier Phase 4 intermediate counts and failures, retained below and in the [completion plan](../.agent/plans/2026-09-05-mvp-completion.md). Test layers overlap and must not be added together.

| Command / gate | Exact result |
| --- | --- |
| `uv run pytest -q` | `1001 passed, 10 skipped in 431.79s`; exactly nine opt-in Docker skips and one opt-in live-provider skip. |
| `uv run pytest -q tests/unit` | `510 passed in 53.30s`. |
| `uv run pytest -q tests/contract` | `281 passed in 4.47s`. |
| `uv run pytest -q -m integration tests/integration` | `156 passed, 49 deselected in 311.72s`. |
| `uv run pytest -q tests/e2e` | `4 passed in 44.40s`. |
| `uv run pytest -q tests/integration/test_cli.py` after Phase 4 metadata update | `30 passed in 22.52s`. |
| Ruff formatting/lint; `uv run mypy src tests` | 165 files formatted; no lint findings; no type errors in 141 source files. |
| Generated-schema check and `git diff --check` | Passed, including the post-metadata refresh. |
| Q6 separately enabled real Docker | `9 passed in 42.32s`; zero remaining Fleet-managed containers. |
| `uv build --offline` and archive inspection | Wheel and sdist each contain 129 package files, including 37 schemas, four migrations and three runtime prompts; rebuilt successfully after metadata update. |

E4 accepts F4-01–F4-13 at the documented supported ceiling: current policy, trust mutation failures, reset cutoff, derived-rule receipts, exclusive dispatch, exact role checkpoints/legacy agent restoration and model-reason continuity. Both independent audit findings have fixes and regression coverage in the final suite. Fake/FunctionModel tests remain offline/simulated; separate Docker tests prove the local isolated executor and fresh-verifier path, not model quality. **No live provider was run or live credential used.** Archive validation is not a cold installed-user journey, platform matrix or OSS publication. Phase 5–7, the complete U1–U12 product journey, detailed guide, L1 license and L2 live-provider gates remain open.

## Six product differentiators

| ID | Required observable property | Starting evidence | Remaining proof |
| --- | --- | --- | --- |
| D1 | Repository-aware bootstrap identifies boundaries/ecosystems/commands without executing repository code; produces provenance, ProjectKnowledge, reviewed configuration and disposable canary report. | Baseline: `adapters/repository/profile.py`, `application/projects.py`, `application/bootstrap.py`; repository-profile, bootstrap-security/report and real-Docker tests. | Repeat preview/no-write and real isolated bootstrap after policy/config changes; validate exact report/artifact bindings and publish only after successful cleanup. Demonstrate a fresh user's real repository journey. Q2, Q4, Q6, M1. |
| D2 | CoS proposes the smallest validated topology; direct, single Engineer, Engineer+Verifier, parallel Engineers and declared specialist DAG actually execute with bounded ownership/dependencies. | Partial: `domain/fleet_plan.py` represents all shapes; `application/planning.py` and `application/workflow.py` execute only three. | Actual concurrent work with a deterministic join, specialist artifact dependencies, durable node/approval/budget state, cancellation/recovery and fresh verification of the joined patch. F5-03, F5-04, P5. |
| D3 | Every model-requested action crosses independent Gateway/Broker; once/run/exact persistent project trust, explain and revoke work. | Accepted Phase 4 (E4): policy/approval services, gateway, external trust, scoped receipts and exclusive dispatch. | Preserve the accepted boundary through future chat, graph execution and configuration evolution. E4 distinguishes simulated integration from real-Docker evidence and does not claim live-provider proof. |
| D4 | Exact SandboxProvider selection matches declared capabilities; Docker is isolated, fake simulated, local-unsafe explicit; harness cannot choose a boundary. | Baseline: `application/sandboxes.py`, sandbox providers and contract tests; composition root registers only fake/Docker/local-unsafe. | Preserve real inspection/cleanup tests and unsafe confirmations through all new flows. Approved modes must fail closed unless technically enforced. Remote providers are deferred. Q4, Q6, S02–S06. |
| D5 | Content-addressed evidence binds task/config/plan/base/patch/commands/verifier/cleanup; CompletionGate computes assurance and exposes proof gaps. | Partial: `application/evidence.py`, `domain/evidence.py`, inspection/evidence tests; multi-criterion model mapping is unavailable. | Criterion-specific authoritative references, substantive direct output, joined-candidate evidence, complete budget and risk/proof-gap summary; simulated/unsafe output cannot upgrade assurance. F5-04, F5-11, P5, S08. |
| D6 | Conversation yields a reviewed FleetPatch with semantic/textual diff, explicit apply and new audited rollback operation; protected policy cannot change. | Partial: `domain/fleet_patch.py`, generated schema and unit tests only. | Persisted proposal and inverse history; whole-result semantic validation; crash-consistent publication/Project rebinding; subsequent behavior changes only after user apply. F6-01 through F6-09, P6. |

## Phase 4 deliverables

All rows concern the roadmap's three-state permission lifecycle. Grants never expand a protected or effective task ceiling. **Accepted on 2026-09-05 under E4.** The observations below remain regression obligations when later phases change these paths; Phase 5–7 remain unimplemented.

| ID | Deliverable | Starting evidence / missing work | Required proving observation |
| --- | --- | --- | --- |
| F4-01 | Canonical ToolIntent and resource types. | Accepted Phase 4 (E4): domain models, gateway and runtime-tool translation. | Structured executable/argv/cwd/environment/path/network identity is bound by trusted context; aliases and argument injection fail before execution. Q2, P4. |
| F4-02 | ALLOW, DENY, REQUIRE_APPROVAL evaluation with hard denies. | Accepted Phase 4 (E4): `PolicyPermissionBroker` composes the supported baseline ceiling with current policy and protected registry. | Table-driven outcomes plus real gateway execution/no-execution and persisted decision evidence; no grant or trust mode overrides a hard deny. Q2, P4. |
| F4-03 | Project/role/workflow/task intersection and reviewed user ceiling. | Accepted Phase 4 (E4): `PermissionPolicyService.context`, task-path validation, role/request/workflow checks, reviewed init/configure settings. | A CoS scope or repository permission request cannot exceed a separately reviewed ceiling; wrong role/stage/workflow/task/project fails even with a stored grant. Missing new-project registration fails closed; legacy compatibility cannot broaden authority. P4. |
| F4-04 | Exact capability grants with expiry, use counts and revocation. | Accepted Phase 4 (E4): strict exact scope, once/run grants, persistent rule and atomic per-use receipt; migration `0004` preserves old grants. | Once means one successful reservation and <=10-minute expiry; run grants survive request expiry but not run termination; expiry/exhaustion/revocation survive reopen; competing consumers cannot overuse. P4. |
| F4-05 | Matched-rule explanations. | Accepted Phase 4 (E4): rich decisions, rule inspection, current/historical request explanation and grant lifetime/status in list. No grant-ID explain or persistent-deny creation CLI. | Exact matched scope and denial/nonmatch reason remain secret-free. Terminal/changed-stage explanation must label history rather than fabricate current authorization; grant status alone cannot promise execution. P4. |
| F4-06 | Persistent user-owned trust outside repository, atomic validated writes. | Accepted Phase 4 (E4): `domain/trust.py`, `ports/trust_store.py`, `adapters/trust/filesystem.py`; external state-root trust file, strict revisioned schema. | Restrictive regular files, symlink/hardlink/no-follow safety, malformed/corrupt/concurrent writes and CAS failures; prepared evidence before publish, exact current/backup reconciliation after completion failure, no automatic rollback or lost updates. Unsupported POSIX features fail closed. P4. |
| F4-07 | Approval request binds exact intent hash. | Accepted Phase 4 (E4): exact hash binding retains original reviewed display reason on logical retry. | Changing executable, argv, environment, cwd, target path or trusted identity after approval invalidates execution; current policy is checked again. P4. |
| F4-08 | `approve --once`, `--run`, `--always --scope project`, and `deny`. | Accepted Phase 4 (E4): approval service and CLI; historical unscoped requests remain once-only. | Separate process invocations pause, review exact scope, approve/deny and resume; mutually exclusive/invalid mode combinations yield stable JSON errors. P4. |
| F4-09 | `permissions list`, `explain`, `revoke`, `reset --project`. | Accepted Phase 4 (E4): CLI and policy service plus `configure --mode/--allow-path`. | List survives restart; explain matches execution reason; revoke affects next execution; reset preserves other projects and reviewed settings, rejecting grants issued at/before its monotonic cutoff even if SQLite revoke fails. P4. |
| F4-10 | Safe, Balanced and Autonomous Sandbox trust defaults. | Accepted Phase 4 (E4): Safe prompts supported commands; Balanced and Autonomous-sandbox deliberately share the current reviewed-command ceiling. | Compare known/unknown commands and workspace operations; no arbitrary executable/network expansion or assurance upgrade. Unsafe/host/external/protected boundaries remain gated. P4. |
| F4-11 | Audit decision, request, resolution, grant, consumption and revocation. | Accepted Phase 4 (E4): prepared/publish/completed policy protocol and transactional derived-rule receipt events. | Ordered identities/redaction, denied/no-execution paths and crash/retry history. Later-run rule use has exact source rule/scope in issued/consumed events and no fabricated approval. Failed staged-rule activation stays dormant and retry is idempotent. P4. |
| F4-12 | Approval resume semantics. | Accepted Phase 4 (E4): current broker/target/configuration revalidation, both role checkpoints, exact verifier patch checks, logical sandbox rehydration and atomic permanent dispatch claims. | Revoke/deny/ceiling changes prevent execution. Both role identities survive pause; exact verifier context and execution semantics cannot change. Concurrent callers dispatch once; incomplete claims/outstanding execution leases never replay. Changed display reason does not invalidate an unchanged logical command. Provider usage/budget persistence across pauses remains open under Phase 5. P4. |
| F4-13 | Protected action registry; exact always-allow conditions. | Accepted Phase 4 (E4): protected action families and `ExactPermissionScope` validators. | No ordinary all-shell/network/files/projects rule; rules bind project/repository identity, principal, workflow/stage, sandbox and full command/path/network parameters. Protected trust/secrets/audit/approval ownership/sandbox limits cannot be granted through normal flow. P4, security cases 1–15. |

Accepted Phase 4 scenarios to retain as P4 regressions on subsequent changes:

1. Pause for an actual canonical verification command; approve once in a new CLI process; resume in another process. Assert one command result, matching intent hash, ordered events and no second execution on repeated resume.
2. Allow for the run, then submit another semantically identical intent with fresh IDs. It may match in the same run; changed executable/argv/cwd/environment/path/principal/stage/workflow/sandbox or a different run/project must not inherit authority.
3. Always-allow each exact Engineer and Verifier project command separately, recreate the process and start another run. Assert rule match, explanation, source-rule/scope-bound issued/consumed receipts and no fabricated approvals. A second repository and a broader command must still prompt or fail. Inject approval activation failure: the staged rule stays dormant and retry reuses its ID.
4. Approve, then revoke or strengthen hard deny/task/trust policy before resume. Assert fresh broker denial, no grant consumption that authorizes execution, no tool result and a stable audit reason. Also change the registered repository identity/base or configuration before resume: revalidate the trusted execution binding rather than relying solely on the old approval hash.
5. Advance an injected clock across expiry; exhaust use counts; race two consumers for a one-use grant. Assert only one execution and durable remaining-use state.
6. Exercise corrupt YAML/JSON, symlink/hardlink/non-regular trust paths, parent swaps, interrupted atomic publication, immutable-backup reconciliation and concurrent writers. Prepared audit failure prevents publication; publication failure leaves exact prepared evidence; completion failure can leave the published policy effective and must be reconciled by revision/hash. Compare-and-swap rejects stale writers; backups never automatically grant access or undo newer state.
7. Contrast Safe/Balanced/Autonomous defaults against exact fake/Docker/local-unsafe capability snapshots. An isolated-only grant never matches local-unsafe, and trust approval cannot manufacture unsupported network enforcement.
8. Reset project A while B has rules and paused runs. Preserve B and A's reviewed mode/path ceiling, record A's revocations, and reject all A grants issued at/before the durable cutoff even if the subsequent SQLite loop fails. Configure must preserve the cutoff. Search output, exceptions, trust files/backups, SQLite/WAL and artifacts for registered raw/encoded sentinels.

## Phase 5 deliverables

| ID | Deliverable | Starting evidence / missing work | Required proving observation |
| --- | --- | --- | --- |
| F5-01 | `fleet chat` line REPL with durable conversation/run references. | Missing command, conversation schema and persistence; baseline creates a CoS per Run. | Restart retains conversation identity, bounded turns and run links; new and resumed sessions are distinguished. P5. |
| F5-02 | CoS converts messages to validated TaskSpec drafts. | Partial: `_scope` converts a single goal to ScopeDecision/TaskSpec. | Ordinary conversational task and organization requests follow typed routes; no raw history or agent-provided authority enters accepted tasks. P5. |
| F5-03 | Smallest valid adaptive team with all five strategies and explicit joins/assurance. | Partial three-strategy planner; fixed stage dispatcher ignores advanced plan nodes. | Barrier/event evidence proves bounded overlap for parallel writers; DAG dependency artifacts are identity/hash bound; known roles, disjoint ownership and explicit joins are enforced. P5. |
| F5-04 | Fresh Engineer each iteration, candidate extraction, fresh independent Verifier workspace, bounded repair, evidence mapping and summary. | Partial existing pair path; repair input omits prior verdict details and criterion mapping supports one general criterion only. | Engineer receives validated failure feedback; actual patch wins over claimed output; joined candidate is independently checked; repair success and exhausted-budget paths report exact evidence. P5. |
| F5-05 | CoS cannot use Engineer write/command tools. | Baseline role catalog isolation and empty CoS tools. | Test attempted direct mutation through chat/planning, custom roles and deferred batches; deny before any workspace change. Q2, P5. |
| F5-06 | Verifier modifications discarded and reported. | Baseline verifier mutation denial/disposable workspace evidence. | Repeat for simple, repaired and joined candidates; mutation cannot contaminate accepted patch and cannot be hidden by a PASS. Q2, P5. |
| F5-07 | Compact event-driven progress UI. | Missing chat progress; existing command presenters expose status. | Progress derives from recorded events, remains usable during long work/approval, and does not fabricate completed nodes or expose secrets. P5. |
| F5-08 | `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, `/exit`. | Missing chat slash commands. | Exercise each command with no run, active/paused/terminal run and restarted session; cancel interrupts actual work and retains cleanup evidence. P5. |
| F5-09 | Restart/resume and approval pause. | Partial replay of a role stage; PydanticAI rejects arbitrary checkpoints; early workflow stages are not resumable. | Crash at persisted intake/scope/preparation/node/tool/join/verification boundaries, recreate process, reconcile safely without duplicate side effect; preserve usage/iterations and approval associations. P5. |
| F5-10 | Budget enforcement and usage summary. | Partial runtime request/tool/output limits; role limits and aggregate graph/conversation limits are not fully effective. | Configured role maxSteps is enforced; concurrent nodes share aggregate limits; retry/restart cannot reset spend; summaries distinguish requested output limits from provider-reported token usage. P5. |
| F5-11 | INCONCLUSIVE and exact proof-gap presentation. | Baseline completion reasons; multi-criterion tasks remain inconclusive. | Independent per-criterion artifact references resolve only to the correct run/task/plan/patch/verifier evidence; missing/contradictory proof stays inconclusive; direct answer is substantive. P5, Q2. |
| F5-12 | Bounded context selection. | Baseline guidance/artifact/tool bounds; no persistent conversation selection. | Oversized history/artifacts/guidance are bounded deterministically; only relevant approved content is selected; no whole-repository/raw-history default or secret leakage. P5. |

The Phase 5 proving suite must cover role tool isolation, CoS direct-write denial, claimed-versus-actual patch, verifier use of the original goal, verifier mutation, successful second repair, exhausted repair budget, chat cancellation, restart/approval, context limits, and final summary contents. It must additionally cover sibling failures/cancellation/approval, conflicting joins, disjoint concurrent ownership, dependency artifact substitution and aggregate budgets. Tests that only construct a FleetPlan do not prove graph execution.

## Phase 6 deliverables

| ID | Deliverable | Starting evidence / missing work | Required proving observation |
| --- | --- | --- | --- |
| F6-01 | Reuse typed FleetPatch and persist proposal/status/history. | Partial schema/validator only; no StateStore methods, table, service or lifecycle. | Reopen preserves exact project/proposal/base/change/rollback bindings; corrupt/foreign/wrong-kind artifacts fail closed. P6. |
| F6-02 | Natural-language CoS semantic proposal and textual patch. | Missing runtime output route and conversational use case. | Normal chat organization request produces a bounded validated proposal and inspectable rationale/diffs without target mutation. P6. |
| F6-03 | Stage complete proposed files separately. | Partial initialization staging; differing replacements refused. | Staging is Fleet-owned, bounded and separate; preview/show cannot mutate active config; proposed tree covers exact references and allowed auxiliary files. P6. |
| F6-04 | Validate paths, schema, references and runtime capabilities. | Partial FleetSpec/VerificationProfile validation; workflow definitions opaque; skills absent. | Malformed workflow/skill schema, missing references, file/descendant or case aliases, symlink escape and unsupported capabilities are rejected before publication. P6. |
| F6-05 | Reject protected settings, secrets and trust/audit/state paths. | Baseline allowed-path and whole-proposal registered-secret validation. | Apply/rollback repeat protection and secret checks over the whole resulting tree. A role/workflow/skill change cannot alter runtime credentials, hard denies, approval ownership or sandbox limits indirectly. P6, Q2. |
| F6-06 | Human semantic diff/unified diff and list/show/apply/rollback CLI. | Missing operational commands. | Separate processes inspect identical stored hashes/diffs; explicit user apply is required; invalid modes/IDs have stable JSON errors. No model tool applies its own proposal. P6. |
| F6-07 | Atomic application, before/after hashes and conflicts. | Initialization writer is not a replacement/removal transaction. | Stale base/prior bytes/add-existing/remove-absent/concurrent edits fail without altering originals; injected failure/crash yields either known prior or known next tree with coherent Project/operation state. Unknown edits require safe recovery. P6. |
| F6-08 | Rollback is a new audited operation. | `rollback_of` is only a schema field. | Reopen and rollback restore prior content while retaining original proposal/application history and new before/after hashes; rollback conflicts never overwrite intervening user work. P6. |
| F6-09 | Require integration tests for backend changes. | VerificationProfile already feeds TaskSpec required commands. | Before proposal/apply/after apply/after rollback tasks show the expected command requirement changes; schema-only or documentation-only edits cannot satisfy this row. P6. |

Phase 6 must prove every roadmap negative case: invalid schema, traversal/symlink, trust/hard-deny/secret/audit mutation, base conflict, atomic failure preserving originals, rollback history, and model self-application denial. It must also prove that old runs retain their original configuration snapshots and that applying new configuration coherently updates the Project binding for subsequent runs.

## Phase 7 deliverables and release gates

| ID | Deliverable | Starting evidence / missing work | Required proving evidence |
| --- | --- | --- | --- |
| F7-01 | Linux/macOS E2E matrix; Windows limitations and available tests. | Missing CI: `.github/workflows/` is empty; historical local macOS/Docker evidence only. | Recorded Linux/macOS jobs for supported Python versions where feasible, actual platform/tool versions and failures; document POSIX no-follow/process/local-Unix Docker constraints rather than claiming Windows support. Q1–Q6, M1. |
| F7-02 | SQLite migration upgrades. | Baseline migrations 0001–0003 and v1/reopen/newer-schema tests. | Upgrade realistic previous-version rows including paused approvals, active leases, chat/plan/FleetPatch state; preserve events/artifacts and fail closed in older binaries. Q3, P4–P6. |
| F7-03 | Orphan Docker/worktree recovery. | Baseline exact-run recovery and repeated-cancellation cleanup. | Preserve existing real Docker recovery matrix; extend node/parallel/apply crash cases; reconcile only exact owned resources and record zero outstanding leases/container residue. Q4, Q6, P5, P6. |
| F7-04 | Stable CLI errors and JSON schemas. | Baseline versioned envelope/error enums/schema generation. | All new modes/slash operations/data/error surfaces have consistent persisted schemas and stable errors; compare generated schema files and package copies. Q1, Q3, Q5, P4–P6. |
| F7-05 | Reproducible versioned runner image. | Mutable default `python:3.14-slim`; README mutable `phase3` image tag; test recipe excluded from distribution. | Reviewed immutable base/digest/platform policy, version strategy and install-accessible recipe/instructions; built image inspection and packaged-quickstart proof. Q5, Q6, M1. |
| F7-06 | Security checklist and adversarial test script. | Baseline normative security list and many tests; no standalone release checklist/script. | All 53 cases below and new phase boundaries mapped to current results; reproducible manual adversarial bootstrap with sentinel/no-residue evidence. Q2, Q6, M2. |
| F7-07 | Complete README quickstart and architecture diagrams. | README/architecture exist but reflect Phase 3. | Update after behavior exists; fresh user can install, initialize, chat, approve, inspect/apply, evolve/rollback and recover using actual commands. Detailed `USER_GUIDE.md` is still pending, not supplied by this ledger. M1. |
| F7-08 | Contribution guide and useful issue templates. | Minimal CONTRIBUTING exists; no issue templates. | Contributor clean setup/checks and boundary expectations match CI. Decide whether issue templates add value; absence alone is not a mandatory blocker. Q1, review. |
| F7-09 | Changelog and release process. | Missing changelog/release procedure. | Record compatibility/migration/platform/security changes; explicit build/test/freeze/review/version/license/live-gate/publish procedure and rollback policy. Package publication is not implied by implementation. Review, Q5. |
| F7-10 | Generated configuration schemas. | Baseline 28-schema generation/distribution path. | Generate every changed/new public/persistent contract; no drift; package includes schemas and migrations required for installed behavior. Q1, Q5. |
| F7-11 | Event/artifact scale smoke. | Missing scale test. | Bounded representative event/artifact volume; measured append/list/read/status latency, database size and memory constraints; no quadratic unbounded history or lost ordering. P7. |
| F7-12 | Optional local OpenTelemetry-compatible instrumentation. | No implementation found. | Optional: either record deliberate deferral or test bounded/redacted local instrumentation; no mandatory external exporter/service. This row alone does not block MVP. Review/P7 if selected. |
| F7-13 | Dependency review and lock policy. | `uv.lock`, declared dependency ranges and manual lock checks exist. | Reviewed dependency/image versions and update policy; reproducible frozen CI environment; documented supported runtime range and upgrade behavior. Q1, Q5, review. |
| F7-14 | Explicit data handling/provider disclosure. | README documents control-plane HTTPS, selected context disclosure and token/logging limitations. | Extend to durable conversations, trust files/backups, proposals, artifacts, retention/export/deletion and actual logging defaults. No raw provider credentials in retained data. Q2, review. |
| F7-15 | Owner license decision before public release. | Unproven: no LICENSE or explicit license selection in the active plan. | Record the owner's exact authorization and selected license, then validate metadata/package inclusion. Do not choose or imply a license from repository visibility. External gate L1. |

| Release gate | Starting status | Closing evidence |
| --- | --- | --- |
| R1 Default suite passes offline after dependencies are installed. | E4 passed the current Phase 4 tree: 1001 passed, 10 explicitly optional skips. | Repeat Q1–Q5 on the eventual full-MVP release tree; current success does not pre-accept later code. |
| R2 Optional Docker integration suite passes. | E4 passed nine real-Docker cases with zero managed-container residue. | Repeat Q6 for the eventual full-MVP release, retaining exact resource/inspection and candidate evidence. |
| R3 Manual live-provider canary recorded. | Unproven; stale smoke must be repaired; no explicitly supplied disposable credential. | L2 and M3. Fake runtime or TestModel/FunctionModel is insufficient. |
| R4 Every product MVP user-success criterion demonstrated. | U1–U12 below remain partial/unproven. | Current automatic/manual evidence for each individual row. |
| R5 Security release gates met or explicitly documented as blocking gaps. | Baseline security foundation; final candidate unproven. | S01–S11 and mapped cases below; documenting a mandatory gap does not count as passing it. |
| R6 README distinguishes enforcement/guidance and isolated/unsafe modes. | Baseline distinction exists. | Current guide/CLI review and M1; preserve honest fake/unsafe/loopback/host trust limitations. |
| R7 No placeholders, fake claims, plaintext secrets or machine-specific paths. | Needs new candidate and distribution inspection. | Q1, Q2, Q5; inspect tracked/distributed product files and user-visible examples. Historical private acceptance paths are not portable setup instructions. |
| R8 Fresh user follows quickstart successfully. | Missing independent installed-user proof. | M1 using the built distribution and published-accessible runner assets, with actual commands/results. |

## All twelve MVP user-success criteria

| ID | Product criterion | Starting evidence / gap | Required closure |
| --- | --- | --- | --- |
| U1 | Install package and run doctor. | Package/CLI/distribution tests exist; no fresh wheel/sdist installation proof. Doctor exit zero means report completed, not `healthy=true`. | Q5/M1: install each distribution in a clean environment, invoke installed `fleet version` and `fleet doctor --json`, check required diagnostics. |
| U2 | Initialize Git repository and inspect profile, commands, ProjectKnowledge and proposal. | Baseline preview/profile/security/bootstrap paths. | Q2/Q4/M1: exact provenance/artifacts/diff and no preview writes; malicious repo content never executes. |
| U3 | Initialize explicit provider/model plus Docker; complete disposable canary. | Public Docker bootstrap exists; manual live-provider path unproven. | Q6/M3: explicit selected provider/credential reference, immutable Docker boundary and successful report with clean publication/cleanup. |
| U4 | Enter chat and request small change. | Missing chat. | P5/M1/M3: ordinary conversational request produces actual bounded change and independently verified reviewable output. |
| U5 | Inspect plan and observe only required roles run. | Three-strategy tests exist; advanced graph execution missing. | P5: compare plan nodes with persisted AgentInstances/workspaces/events for all five topologies, including actual concurrency and join. |
| U6 | Approve once, run or exact project scope. | Once only at baseline. | P4/M1: separate CLI invocations, durable exact matching and broader-action denial; new-policy revalidation. |
| U7 | Receive patch, tests, verdict, events and hashes. | Baseline artifact/evidence path; criterion/graph gaps. | Q2/Q4/P5/M3: read artifact bytes, verify all bindings and independent command results, preserve risks/proof gaps. |
| U8 | Restart CLI and inspect/resume. | E4 accepts exact approval-stage role/context restoration and permanent dispatch claims; general chat/graph/model-budget recovery remains missing. | Preserve P4 and complete P5/P6 restart, usage, conversation and operation state; do not infer generic replay safety from approval recovery. |
| U9 | Apply candidate only after explicit approval. | Baseline `patch apply` explicit command and dirty/diverged guards. | Q4/M1: no silent target writes, explicit reviewed apply changes expected bytes; verifier changes excluded; drift/config changes refuse safely. |
| U10 | Request fleet change, inspect and apply or reject. | Schema only. | P6/M1: proposal leaves active files unchanged; apply changes subsequent behavior, reject leaves it unchanged, rollback records a new operation. |
| U11 | Revoke persistent permission. | Accepted at the E4 supported scope: revoke/reset survives reopen and invalidates exact grants/rules. | Retain P4 through later phases and demonstrate in M1. Revocation does not remove underlying Balanced defaults; Safe mode exposes the next required approval. |
| U12 | Default suite needs no real model/network/Docker. | E4: 1001 ordinary tests passed; exactly nine Docker and one live-provider case skipped by explicit opt-in gates. | Repeat Q4 on the full-MVP tree; retain offline adapter coverage and exact skip reasons. |

Cross-cutting product acceptance: `COMPLETED` is lifecycle state; `verified_complete` is independently derived assurance. No user journey, role result, code patch, schema or successful process exit can override missing required proof. In particular fake/local-unsafe and contradictory/mutating verifier results must remain unverified.

## Security release gates

| ID | SECURITY_MODEL section 21 requirement | Starting evidence / remaining proof |
| --- | --- | --- |
| S01 | All required security tests pass. | Baseline test targets below; Q2 and the full final Q4/P4/P5/P6 matrix must pass. Required cases cannot be closed by aggregate counts alone. |
| S02 | Real Docker verifies effective user/mounts/network/capabilities/environment. | Contract tests are not OS enforcement proof. Q6 must inspect real effective configuration and credential/host sentinels on the final candidate. |
| S03 | Threat model and limitations appear in README. | Baseline text exists; review changed trust/chat/config data flows and M1 disclosures. |
| S04 | local-unsafe is explicit and visually prominent. | Baseline separate confirmation/warnings; repeat init/run/chat/approval paths and JSON warnings under Q3/P5. Ordinary `--yes` is insufficient. |
| S05 | No framework-native shell/filesystem bypass outside Gateway. | Architecture/runtime/secret-boundary tests exist; extend to conversation, custom roles, proposal output and every new tool route. Q2/P5/P6. |
| S06 | Invocation contains no host path, sandbox handle, credential, grant or executor. | Baseline strict runtime request/context tests; extend node/dependency/repair/chat context and prove denied injection. Q2/P5. |
| S07 | Profiling cannot execute code; detected commands are unauthorized requests. | Baseline profiling/Git defenses; Phase 4 command trust must not equate detection with self-grant. Q2/P4. |
| S08 | CompletionGate uses authoritative evidence; simulated PASS cannot verify. | Baseline evidence gate; test graph joins and criterion mapping without trusting model claims. Q2/P5/Q6. |
| S09 | Dependencies/images reviewed and pinned under policy. | Lock exists; mutable runner recipe and documented update policy still need work. Q1/Q5/F7-05/F7-13. |
| S10 | Manual adversarial bootstrap recorded. | Historical Phase 3 report exists; final changed candidate needs M2 with exact artifacts, sentinels and residual-resource checks. |
| S11 | Permission allowlists are never equated with OS isolation. | Baseline documentation is honest; review all new help, guide and completion summaries. Trust mode cannot upgrade fake/local-unsafe capabilities. |

## All 53 required security-test cases

Numbers below match `SECURITY_MODEL.md` section 20. Listed files are starting test targets, not proof that every assertion already exists or passes. Q2 runs the relevant existing unit/contract/integration security surface; P4–P6 identify mandatory new behavior tests. For each row, retain the case numbers in the eventual test/evidence record.

| Cases | Required assertion | Starting test targets and remaining proof |
| --- | --- | --- |
| 1 | Repository broad filesystem request cannot grant itself authority. | `tests/unit/test_permission_broker.py`, `tests/integration/test_security_gateway.py`; P4 must exercise effective requested-policy intersection, not only hardcoded baseline denial. |
| 2 | Forged agent ID/role cannot replace trusted context. | `tests/unit/test_runtime_tools.py`, `tests/contract/test_pydantic_ai_runtime.py`; extend to node/custom-role/chat tools in P5. |
| 3–4 | Traversal, symlink escape and prefix collision fail. | `tests/unit/test_path_security.py`, `tests/unit/test_workspace_files.py`, `tests/integration/test_security_gateway.py`; P4/P6 cover trust/config replacement paths too. |
| 5–7 | Exact command mismatch; isolated grant versus unsafe; expired/exhausted/revoked/wrong-run/project/stage. | Partial `test_permission_broker.py`, `test_security_gateway.py`; P4 must assert full new persistent/run-grant semantics and actual non-execution. |
| 8–9 | CoS cannot self-approve or mutate protected trust/hard-deny/audit. | Existing gateway/runtime role tests; P4 registry and P5/P6 routes must reject all new bypasses. |
| 10 | Secrets absent in events/logs/errors/command environment/inspection. | `tests/unit/test_secret_boundary.py`, `test_runtime_models.py`, `tests/integration/test_pydantic_ai_workflow.py`, Docker contract/real tests; include new trust/chat/proposal data and WAL in P4–P6/Q6. |
| 11–12 | Docker restrictions and no unsafe fallback. | `tests/contract/test_docker_sandbox.py`, `tests/docker/test_real_docker.py`, `tests/unit/test_project_runtime_integration.py`; Q6 is required for effective runtime enforcement. |
| 13–15 | Denial audit/no execution; exact approved intent; duplicate resume does not repeat effect. | `tests/integration/test_approval_recovery.py`, `test_security_gateway.py`, `tests/e2e/test_offline_cli.py`; extend current-policy revalidation/concurrent reservation under P4. |
| 16–17 | Verifier cannot change accepted patch; diverged/dirty target refuses without data loss. | `tests/integration/test_verifier_mutation_evidence.py`, `test_workflow.py`, `tests/e2e/test_offline_cli.py`; repeat joined/repair flow in P5. |
| 18 | Output obeys truncation/redaction/storage limits. | `tests/unit/test_process_runner.py`, `test_runtime_models.py`, sandbox/runtime contracts; P5/P7 add graph/context/history aggregate bounds. |
| 19 | YAML tags/unknown fields fail safely. | `tests/unit/test_config.py`; P4 trust and P6 workflow/skill/result-tree parsers require equivalent negative tests. Baseline Workflow YAML is not semantically parsed. |
| 20 | Worker environment excludes provider credentials. | Docker/unsafe contracts, `tests/unit/test_secret_boundary.py`; Q6/M2 inspect actual environment and encoded sentinels. |
| 21 | Profile cannot run hooks/scripts/Make/manifests/escaping symlinks. | `tests/unit/test_repository_profile.py`, `tests/unit/test_bootstrap_security.py`, repository contract fixtures; Q2 plus M2. |
| 22–23 | Runtime exposes no unmediated capabilities; verifier write denied and fingerprint unchanged. | `tests/unit/test_runtime_tools.py`, `test_architecture_boundaries.py`, `tests/integration/test_verifier_mutation_evidence.py`; custom-role/node variants in P5. |
| 24–25 | Simulated PASS cannot verify; invalid plans fail. | `tests/unit/test_evidence_gate.py`, `test_fleet_plan.py`, `tests/integration/test_workflow.py`; advanced execution/joins cannot weaken these invariants in P5. |
| 26 | FleetPatch rejects protected targets and unsupported skills. | `tests/unit/test_fleet_patch.py`; P6 may admit skills only with an explicit semantic/security contract and negative apply/rollback tests. |
| 27 | Repository PATH/Git config/hook/filter/diff surfaces cannot execute. | `tests/contract/test_phase1_adapters.py`, `tests/integration/test_repository_fsmonitor.py`, `tests/unit/test_repository_profile.py`; repeat runtime/preview use in Q2/M2. |
| 28–29 | Mutation and contradictory PASS remain visible and unverified. | `tests/integration/test_verifier_mutation_evidence.py`, `test_verifier_verdict_semantics.py`, `tests/unit/test_evidence_gate.py`; criterion/join paths in P5. |
| 30–31 | Referenced config drift invalidates; foreign/corrupt/missing/wrong-kind/task/config bindings fail. | `tests/unit/test_config.py`, `tests/integration/test_config_snapshot_binding.py`, `test_task_spec_binding.py`; evolution must extend snapshots without rewriting historical runs in P6. |
| 32–33 | Filesystem identity/case aliases and Git includes/promisor helper escapes fail. | `tests/unit/test_path_security.py`, `test_bootstrap_security.py`, `test_repository_profile.py`, `tests/contract/test_phase1_adapters.py`; record platform applicability rather than assuming identical filesystems. |
| 34–35 | Secret-bearing scope/intent rejected before persistence; repository/state roots disjoint both ways. | `tests/integration/test_security_gateway.py`, `test_cli.py`, `tests/unit/test_bootstrap_security.py`; P4 trust-root and P5 conversation/plan fields extend this. |
| 36–37 | Bounded regular snapshot reads; post-run drift and any status evidence-binding mismatch rejected. | `tests/unit/test_config.py`, `tests/integration/test_config_snapshot_binding.py`, `test_task_spec_binding.py`, `test_workflow.py`; P5/P6 add joined/evolved binding substitutions. |
| 38–39 | Protected case aliases and ancestry conflicts rejected; FleetPatch ID/path/whole-proposal secret contract. | `tests/unit/test_path_security.py`, `test_fleet_plan.py`, `test_fleet_patch.py`; initial probe shows FleetPatch file/descendant overlap is currently accepted: P6 must add and pass regression. |
| 40 | Incoherent or substituted sandbox capabilities fail before resource creation. | `tests/contract/test_fake_sandbox.py`, `tests/unit/test_project_runtime_integration.py`, `test_runtime_models.py`; preserve exact Docker/unsafe dispatch with new modes. |
| 41–42 | Secret-bearing repository/profile/options/diffs fail before preview/state/write; ProjectKnowledge source hash independently reproducible. | `tests/unit/test_bootstrap_security.py`, `test_repository_profile.py`, `tests/integration/test_cli.py`, `test_bootstrap_report.py`; P6 prospective-tree/diff scanning required. |
| 43 | FleetPatch raw JSON type/depth/node bounds and whole-proposal secret scan precede schema/errors. | `tests/unit/test_fleet_patch.py`; preserve through runtime proposal, persistence, show, apply and rollback in P6. |
| 44 | Attacker Git keys never enter executable argv; malformed secret config/errors remain generic/cause-free. | `tests/contract/test_phase1_adapters.py`, `tests/unit/test_config.py`, `test_bootstrap_security.py`, `tests/integration/test_config_snapshot_binding.py`; new parser paths need same behavior. |
| 45–46 | Provider preview is static; missing/invalid credentials/unsupported provider fail early; doctor inspect-only. | `tests/integration/test_cli.py`, `tests/unit/test_doctor_runtime_integration.py`, `test_project_runtime_integration.py`, `test_runtime_registry.py`; Q2/Q3, no live credential needed. |
| 47–48 | Exact gateway-backed role tools and offline TestModel/FunctionModel; live requires explicit inputs. | `tests/contract/test_pydantic_ai_runtime.py`, `tests/integration/test_pydantic_ai_workflow.py`, `tests/conftest.py`; extend custom roles and repair stale live smoke before M3. |
| 49 | Raw/URL/base64/base64url/hex/JSON-escaped secret forms absent throughout. | `tests/unit/test_secret_boundary.py`, `test_runtime_tools.py`, `tests/contract/test_pydantic_ai_runtime.py`, `tests/integration/test_pydantic_ai_workflow.py`; include chat/trust/backups/FleetPatch in P4–P6. |
| 50 | Differing init proposal cannot split repository and runtime registration. | `tests/unit/test_project_runtime_integration.py`, `tests/integration/test_cli.py`; P6 creates a distinct reviewed transaction with coherent Project rebinding, retaining init's safe contract. |
| 51–52 | Secret-free prompts/schemas/context/messages/serialized request; credential rotation covered before start/resume/apply parsing. | `tests/contract/test_pydantic_ai_runtime.py`, `tests/unit/test_secret_boundary.py`, `tests/integration/test_config_snapshot_binding.py`; new graph/chat/proposal paths must register current/relevant historical secrets before handling untrusted content. |
| 53 | Entire deferred batch validated before first side effect. | `tests/unit/test_runtime_tools.py`, `tests/contract/test_pydantic_ai_runtime.py`; P5 node identity/aggregate budgets and P6 proposal tools must not introduce partial prevalidation execution. |

The product's eight security-review demonstrations are covered respectively by cases 1/8/9, 3/4/32/38, 5/14, 10/20/49, 8, 26/39/43, 16/23/28 and 15/17 plus F7-03. These mappings preserve the product acceptance wording without treating a narrow unit test as proof of the entire user journey.

## Known integration gaps discovered in the initial audits

| Gap | Concrete baseline path | Acceptance consequence |
| --- | --- | --- |
| Baseline approved-resume policy gap superseded in Phase 4 source; accepted in E4. | New `application/permission_policy.py`, updated approvals/gateway re-evaluate current policy. | P4 must prove revocation/deny/ceiling changes after approval affect actual execution on the frozen candidate. |
| Baseline user-ceiling/target-binding gap superseded in Phase 4 source; accepted in E4. | Reviewed trust paths and current repository identity/base/status/configuration checks now precede scope/approval/resume. | P4 must prove CoS cannot expand reviewed scope and approved resume rejects stale bindings; include partial initialization and legacy compatibility. |
| Phase 4 concurrent once-dispatch race reproduced; fixed and accepted in E4. | Two callers observed the same pending intent before consumption; idempotent SQLite reservation returned it to both. Gateway now requires permanent atomic dispatch ownership. | Shared-SQLite barrier test must prove one executor, one consumption and no restart replay of a claimed incomplete intent. |
| Phase 4 model-reason resume failure reproduced; fixed and accepted in E4. | Offline PydanticAI repeated the same command with changed reason; unchanged logical key conflicted with the full intent hash. Gateway now preserves the original reason and role checkpoints retain identity. | Offline PydanticAI once/run/always with new call IDs/reason must resume; changed command/resource/parameters still fail. Paused/failed provider usage remains a Phase 5 accounting gap. |
| Planner and scheduler execute only three strategies. | `application/planning.py: FleetPlanner.create`; `application/workflow.py: WorkflowEngine._continue`. | A valid parallel/specialist schema is not a completed adaptive fleet. |
| Singular Run/resource/idempotency assumptions conflict with node concurrency. | `application/resources.py` selects first candidate/sandbox; `application/runtime_tools.py` idempotency lacks node identity; `adapters/persistence/sqlite.py: save_run` overwrites full JSON without CAS; Run has singular pending approval/patch/verifier fields. | P5 needs node-scoped ownership, conflict-safe state transitions, exact approvals and artifact joins; test overlapping completions and crashes. |
| Custom role configuration is not operational. | Workflow/runtime/tool maps still hardcode three built-ins. Phase 4 now consumes role/workflow `allowedTools`; general `mayDelegateTo`/`maxSteps` and specialist execution remain Phase 5. | Role names do not grant authority; configured limits and allowed delegation must affect validated execution. |
| Repair feedback, direct answer and criterion mapping gaps. | Engineer input currently carries TaskSpec/repair count but not prior verdict; `application/evidence.py` marks multiple criteria inconclusive; direct flow lacks substantive answer delivery. | P5 must test real feedback consumption, bounded useful direct artifact, and exact criterion-specific evidence. |
| Chat/restart semantics incomplete. | No conversation schema/CLI; `_scope` creates fresh CoS per Run; PydanticAI rejects checkpoints; early stages cannot resume; `RecoveryService` fails/cleans interrupted runs. | Define safe replay/reconciliation at each supported boundary; do not promise durable model internals or generic exactly-once external effects. |
| Snapshot/base hash naming and membership differ. | `YamlConfigurationAdapter.hash` hashes FleetSpec; `Project.fleet_spec_hash` stores full ConfigSnapshot hash; loader includes referenced files only, not README/unreferenced skills. | P6 must specify the complete organizational baseline and bind all editable files; update Project snapshot artifact/hash/status coherently and preserve old runs. |
| Workflow/skill validation missing; file/descendant collision accepted. | `validate_fleet_files` parses only FleetSpec/VerificationProfile; `validate_fleet_patch` compares equal case-folded paths only. | Both in-memory probe failures need permanent P6 negative tests before operational apply. |
| Adding files does not register roles/workflows/skills. | FleetSpec agents/workflows map lives in protected `.fleet/fleet.yaml`; no skills field or consumer exists. | Do not blanket-allow the manifest. Define constrained semantic evolution with protected-setting comparisons or document the exact supported update subset; fulfill the requested skill behavior. |
| Init writer cannot serve as configuration replacement transaction unchanged. | `YamlConfigurationAdapter.check_apply/apply` refuse differing targets. | P6 must support replace/remove, crash-safe before/after reconciliation and audit without relaxing init or overwriting user edits. |
| Opt-in live smoke is stale after Phase 3 bootstrap gating. | `tests/live/test_provider_smoke.py` publicly initializes pydantic-ai with fake sandbox and expects success; offline E2E asserts that fake init fails. | Repair fixture/setup and add real-provider+Docker journey before the authorized live gate. Existing fake-evidence assertions cannot prove isolated MVP behavior. |
| Distributed quickstart lacks its runner recipe. | `pyproject.toml` sdist excludes tests; README points to `tests/docker/Dockerfile.runner`; recipe uses a mutable base. | Package or publish supported runner assets and prove installation without source-checkout-only files. Archive presence is not installed-user success. |
| Release/platform infrastructure absent. | Empty `.github/workflows/`; no standalone scale/adversarial scripts, changelog/release process or owner license. | F7 obligations stay missing/unproven until artifacts and their actual execution evidence exist. |

## Proving commands and manual protocols

Commands below identify the proving surface. P4 now names present working-tree tests; **P5–P7 proposed files remain future requirements, not runnable evidence today.** Names may be updated with equivalent explicit case mapping. No command in this ledger has been run merely by being listed.

### Existing offline commands

Q1 — contributor checks, lock and schema drift:

```bash
uv lock --check
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m agent_fleet.schemas.generate --check
git diff --check
```

Dependency installation may use the network. After dependencies are installed, ordinary tests must run with live-provider and Docker opt-in flags absent. Record interpreter/Git/OS versions; Q1 alone does not prove cross-platform execution or dependency review.

Q2 — baseline unit/contract security and domain surface:

```bash
uv run pytest -q tests/unit tests/contract
```

Q3 — persisted integration surface, including files with imperfect marker coverage:

```bash
uv run pytest -q tests/integration
```

Q4 — subprocess E2E and complete default suite:

```bash
uv run pytest -q tests/e2e
uv run pytest -q
```

Q5 — build and archive verification:

```bash
uv build --offline
uv run pytest -q tests/integration/test_distribution.py
```

Q5 must be supplemented by the proposed installed-distribution test below and M1. Existing archive tests check runtime prompts, migrations and schemas, but do not install each distribution into a fresh environment or prove README runner assets are available to its user.

### Explicit real-Docker command

Q6 requires an operator-prepared local image and supported local Unix daemon. Set `AGENT_FLEET_DOCKER_TEST_IMAGE` to the reviewed preloaded image and `AGENT_FLEET_ENABLE_DOCKER_TESTS=1` explicitly before running:

```bash
uv run pytest -q -m docker_integration tests/docker/test_real_docker.py
```

Record the image digest, Docker client/server versions, daemon identity, platform, effective user/mounts/network/capabilities/environment/resource constraints, command/cleanup evidence and exact managed-resource absence. Use the documented host-shared temporary directory on macOS/Colima. Do not pull/build images, access a remote daemon or silently select local-unsafe as a test fallback.

### Phase-specific automated acceptance targets

P4 — exact permission lifecycle and process recreation:

```bash
uv run pytest -q tests/unit/test_trust_policy.py tests/unit/test_scoped_grants.py tests/unit/test_permission_policy_security.py tests/contract/test_trust_store.py tests/integration/test_persistent_permissions.py tests/integration/test_permission_cli.py tests/integration/test_verifier_approval_resume.py tests/integration/test_gateway_concurrency.py tests/integration/test_pydantic_ai_approvals.py
```

P5 — durable chat, all five executable topologies, criterion mapping, restart/cancel/budget behavior:

```bash
uv run pytest -q tests/integration/test_chat.py tests/integration/test_adaptive_workflow.py tests/integration/test_workflow_restart.py tests/e2e/test_chat_cli.py
```

P6 — operational evolution, transactional apply/recovery, behavior and rollback:

```bash
uv run pytest -q tests/integration/test_fleet_patch_workflow.py tests/integration/test_fleet_patch_recovery.py tests/e2e/test_fleet_patch_cli.py
```

P7 — fresh installed distributions and measured scale:

```bash
uv run pytest -q tests/e2e/test_installed_distribution.py tests/integration/test_state_scale.py
```

P4–P7 must run offline with generated fixture repositories and temporary Fleet state unless explicitly marked real Docker. Installed-distribution acceptance must exercise both wheel and sdist with declared dependencies in a fresh environment, outside the source checkout, using the installed `fleet` executable. Verify packaged schemas/migrations/prompts/runner/user assets through their installed access path and demonstrate representative JSON errors and a complete offline supported flow.

### Manual release evidence

M1 — fresh-user journey. An independent reviewer installs the frozen distribution in a fresh environment, follows the completed quickstart/guide verbatim, checks doctor readiness, prepares the documented runner, previews and initializes a disposable Git fixture, uses chat/approval/status/artifacts/apply, changes/rejects/applies/rolls back organization configuration, revokes trust and restarts/recovers. Capture exact commands, exit statuses, artifact hashes and resulting file bytes. Separate dependency/image preparation from ordinary Fleet execution. This protocol is incomplete until all required behavior and guide assets exist.

M2 — adversarial bootstrap. On the frozen candidate, use a disposable Git repository and disjoint state/trust directories with registered random raw/encoded secret sentinels and an outside-mount host sentinel. Exercise malicious repository instructions/config/hooks/paths, denied capabilities, verified Docker execution and interrupted cleanup. Record rejection before unauthorized effects, exact effective sandbox inspection, secret absence, intact outside sentinel and zero owned-resource residue. Run the eventual versioned adversarial script; a script name without a recorded execution is not evidence.

M3 — explicitly authorized live-provider journey. First repair the stale smoke and prove its setup offline. Obtain an explicitly supplied disposable credential plus selected provider/model/reference; do not discover or reuse ambient credentials. With documented opt-in inputs set, run:

```bash
uv run pytest -q -m live_provider tests/live/test_provider_smoke.py
```

Also record the complete real-provider+Docker user journey required by U3/U4, using a disposable fixture and the normal CLI path. If the repaired smoke covers only a fake sandbox, it proves provider integration only. The real-Docker combined journey must independently validate patch behavior and canary/report/evidence/cleanup bindings. Record provider/model metadata and reported usage without storing credentials or unredacted prompts. Live model quality, Docker enforcement and packaging are separate claims.

## External gates and genuine post-MVP deferrals

- **L1 — owner license: unproven.** The active plan records no supplied license choice. Selecting a license or publishing a package is outside the current implementation authorization. Complete independent implementation and release artifacts first; do not label the public OSS release ready until the owner's exact license decision is recorded.
- **L2 — disposable live credential: unproven.** No explicit disposable provider credential is supplied by the active task. Ordinary tests, CI, builds, documentation and offline smoke repair can proceed. M3 cannot be marked passed from historical model-adapter tests, ambient variables, fake runtime or TestModel/FunctionModel.
- **Modal/Hosted/remote sandboxes and cloud control plane are deferred after MVP.** `SandboxName` and composition-root registration accept exactly fake, Docker and local-unsafe. Abstract capabilities or a negative test mentioning hosted do not constitute a hosted implementation. Their absence is not a Phase 7 blocker.
- Other explicit post-MVP work: second harness/conformance matrix, enforcing domain egress proxy, GitHub App/MCP/external connectors, daemon/scheduler, concurrent repositories/cross-machine scheduling, richer TUI/web/mobile interface, skill/plugin distribution, signed audit export and enterprise policy integration. Phase 6's local reviewed skill semantics remain in scope even though plugin distribution is deferred.
- Unsupported approved worker networking must stay rejected until an enforcing implementation exists. An exact permission rule may represent network conditions without claiming that Docker `network=none` or host execution implements domain allowlisting. Optional telemetry and useful issue templates remain optional under the roadmap.
- Git commits, push, PR merge and remote identity checks are separate delivery outcomes under the active plan. They do not prove release/security acceptance, and local passing tests do not prove remote CI or merge completion.

## Evidence register

| Date / candidate | Activity | Result and scope | Requirements closed |
| --- | --- | --- | --- |
| 2026-09-05 / Phase 3 baseline | Read-only spec/source/test audit; two in-memory validator probes. | Operational Phase 4–7 gaps mapped; malformed Workflow and file/descendant FleetPatch acceptance reproduced without writes or external services. Existing suites not rerun by this audit. | None; this initializes the ledger. |
| 2026-09-05 / concurrent Phase 4 working tree, not frozen | `uv run pytest -q tests/integration/test_persistent_permissions.py`; targeted Ruff and mypy checks. | Exit 0: 13 tests passed in 35.27s on local macOS. Fake-runtime/FakeSandbox lifecycle, separate Engineer/Verifier scopes, activation retry, current ceilings and exact later-run consumed receipts; no provider/Docker execution and no verified-complete claim. Later source changes to run-grant lifetime, reset cutoff and publication audit require a fresh full P4/Q1–Q4 run. | None; focused regression evidence only. |
| 2026-09-05 / concurrent Phase 4 documentation review | Four-document implementation/schema/CLI boundary refresh; in-memory Pydantic validation of documentation examples. | Complete UserTrustPolicy YAML, VerificationProfile YAML and labeled runtime/sandbox fragment validate (exit 0); Python sketches and future YAML are explicitly non-complete/target examples. Prepared/publish/completion, reset cutoff, checkpoint/rehydration and current versus historical inspection are documented. Phase 5–7 and external gates remain open. | None; documentation is not execution evidence. |
| 2026-09-05 / concurrent Phase 4 independent integration audit | Two source-unmodified probes in disposable local fixtures: shared-SQLite gateway concurrency and offline PydanticAI FunctionModel approval. | Before fixes: two simulated executor entries for one intent/one consumed grant; changed display reason caused an unchanged approved command to fail with zero dispatches. Fixes are wired; final named regression/full gates remain required. No provider or Docker operations were performed by this audit. | None; regression findings retained until final evidence supersedes them. |
| 2026-09-05 / E4 accepted local working tree | Final aggregate, layered, static, archive and real-Docker acceptance; post-metadata CLI/static/archive refresh. | Exact snapshot above: `1001 passed, 10 skipped`; Docker `9 passed`, zero managed-container residue; metadata CLI refresh `30 passed`. Prior Phase 4 provisional evidence and both regression findings are superseded. Live provider and full-MVP release remain unproven. | F4-01–F4-13 at the documented supported boundary. |

E4 supersedes the provisional Phase 4 statements in these historical entries: the two reproduced regressions are fixed and covered by the accepted final suite. It closes F4-01–F4-13 only, not Phase 5–7 or external release gates. Future entries must identify their evidence and supersede rows explicitly; this ledger must never turn a documented limitation into a whole-MVP completion claim.
