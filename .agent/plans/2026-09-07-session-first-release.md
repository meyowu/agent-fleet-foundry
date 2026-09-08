# Session-first Agent Fleet release

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

Authorization: on 2026-09-07 the user answered **确认** to implementing Session, per-role models, custom roles and the real-time local Dashboard, with module-level commits and GitHub merge. This supersedes the development pause, not existing credential/trust boundaries or the Actions-minute constraint. The full objective remains all four capabilities plus validated delivery; completion of an intermediate slice is not completion of this release.

## Purpose and user-visible result

A user opens `fleet` once in a repository, initializes or resumes its session, gives CoS a bounded task, inspects its plan and approvals, reviews the resulting patch/evidence and explicitly applies it without leaving the session. The user may bind different models to different role templates; custom templates drive actual scoped agent execution. A local authenticated dashboard observes those same instances and persisted evidence live.

Target interaction, implemented incrementally and not claimed available until tested:

```text
$ fleet
> Fix the regression and add a test.
> /plan
> /approve
> /resume
> /diff
> /apply
> /confirm <displayed-review-code>
```

The first release ships R1, R2a, constrained R3 and R4a from the prior roadmap. It does not require a second provider to prove different-model routing, nor browser mutation controls to prove real-time observation. Onboarding, budget visibility, recovery and representative offline evaluations are included where needed for these journeys.

## Scope

### In scope

- Interactive bare entry; existing explicit chat/one-shot/JSON compatibility; guided initialization through public BootstrapService; session plan/evidence/code/FleetPatch review and exact confirmation.
- Explicit opt-in pre-execution plan review with a durable, non-replayable planning checkpoint; ordinary existing one-shot behavior remains compatible. Never relabel after-the-fact plan inspection as pre-execution approval.
- User-owned named model profiles and per-role bindings through the existing guarded provider adapter; CoS and all child/repair/verifier invocations use immutable resolved bindings with actual routing/accounting evidence.
- Extensible role-template identities with validated built-in execution kinds, requested tools/scopes/delegation, instructions, model preferences and typed outputs; defaults remain usable and CoS chooses minimal instances.
- Versioned reviewed template changes, compatibility and exact permission principal handling. Custom roles cannot bypass verifier isolation or acquire new execution kinds/tools.
- Authenticated loopback read-only dashboard, packaged local assets, project/session/run/child state, usage, approvals, events, evidence and historical replay with visible disconnected/error states.
- Complete appropriate offline/static/security/unit/contract/integration/E2E/package checks, explicit real-Docker checks when locally available, docs and module commits, normal GitHub merge and exact remote read-back.

### Out of scope

- Hosted dashboard, accounts, remote/multi-user control plane, additional sandbox/harness/provider integration, arbitrary plugins/workflow DSLs, automatic fallback, background daemon and browser mutations.
- Automatic model/credential discovery, changing endpoint trust from repo instructions, public package publication or owner license selection.
- Triggering hosted Actions merely to reproduce already available local checks while the user reports exhausted minutes. Do not weaken branch protection or remove test/security gates to merge.
- Reopening accepted old MVP defects without fresh evidence or treating its old CI as acceptance of new changes.

## Current repository state

Baseline `main` commit `9276cbf44fa32adc8087d618e0ec4aeff60b877c`, tree `12533fc8b1d5f454b7ba29b32635ae10b30e48e1`; new branch `codex/session-first-release`. The only initial untracked content was the prior planning document, preserved and advanced above. Read-only GitHub verification on 2026-09-07 confirmed PR5 merged and main CI33989500224 successful at the baseline, not the new release.

`cli/chat.py::run_session` and `application/conversations.py::ConversationService` already supply persistent conversation selection, bounded context and ownership. `PatchService` and `OrganizationService` own application. Bare `fleet` currently shows help. `WorkflowEngine.start` scopes and immediately executes; there is no durable human plan-review gate.

`RuntimeConfiguration` is currently project/run-wide. `AgentRole` and operational role lookups are fixed; open RoleId syntax alone does not produce custom execution. `OrganizationService` currently protects fleet.yaml and closes configuration over declared references. `Run`/Project/graph/conversation canonical serialization is authority-bearing, so adding optional defaults can still break historical hashes.

The first public BootstrapService publication needs genuine Docker evidence; internal fake registration is test-only. A session is foreground-owned, not a daemon. Dashboard must reuse application/store evidence rather than creating another worker engine.

## Security impact

- Preserve all twenty `AGENTS.md` invariants and `docs/SECURITY_MODEL.md`. Every model effect traverses Gateway/Broker/Sandbox; names, prompts and model choices do not confer permissions.
- Review tickets are deterministic human-control capabilities scoped to exact conversation/project/run/artifact/proposal/action/hash/current organization. No model text can confirm them. Revalidate inside the existing application guard immediately before effects; never resolve “latest” at confirmation time.
- Profile secret references and trusted destination stay user-owned outside repo. Resolve only explicitly selected references, scan all selected secrets before output, and pin per-run mappings. No ambient provider fallback or cross-profile credential reuse.
- Role identity and execution kind are distinct. Preserve actual custom principals in permission scopes and evidence while limiting kinds/output/tool catalogs. A different model is not proof of independent verification.
- The dashboard has bounded loopback-only HTTP, session authentication, exact Host/Origin checks, no CORS exposure, no cache of private responses, no provider keys, escaped untrusted text, CSP, limited request/output sizes and bounded connection lifetime. No direct SQLite mutation or provider calls from the browser.
- Versioned bindings/migrations must retain canonical old-record hashes and fail closed on unknown/foreign/stale records. No silent reinitialization, claim expiry, rerun, refund or insecure host fallback.

## Proposed design

Reuse existing layered services. Add typed application-facing session review queries/commands. Process-local expiring one-shot review tickets survive neither restart nor selected-target changes; a new process requires re-review. Any confirmation naming another project/action/candidate fails before effects. Slow operations remain explicitly owned and cancellation-aware.

For new-user entry, a bounded terminal wizard collects explicit existing runtime/model/reference/image/trust choices, shows the exact public preview and asks for confirmation. Registration calls existing public bootstrap with reviewed proposal/trust revision. No image build/pull or private fake registration is hidden in the wizard.

Model profiles form a separate trusted, validated local catalog. Default configuration is inherited unless a user explicitly binds a role. Snapshot the complete selected bindings before CoS dispatch, use them for all descendant and repair calls, and re-read that snapshot on resume. Versioned sidecar records are preferred over changing canonical historical Run/Project JSON. New aliases and updates apply to new tasks only; missing/disabled/unsupported profiles fail preflight without a fallback.

Custom template catalogs must join ConfigSnapshot and FleetPatch validation. Built-in execution semantics remain bounded; IDs/labels, instructions and requested capabilities are customizable. Planner, graph, invocation builder, permission broker, workspace binding and CompletionGate must agree on the resolved template identity/kind, including joined repair and final verification.

The dashboard uses application snapshots and durable per-run event sequences with a cursor per observed run/child. Start with an initial bounded snapshot and a reconnectable SSE feed. Use consistent revisions/high-watermarks, explicit resync on retention/unknown cursor, and deduplicate on stable event ID. An empty view shows real empty state, never fabricated active agents. Read-only first means no task/approval/application mutation endpoints.

Frontend direction: neutral, compact developer working surface, restrained status accents, readable type, graph/task list beside an evidence/event detail pane. No marketing hero, decorative images, external fonts/CDN or analytics. Preserve Python packaging; use semantic HTML/CSS and small JavaScript modules bundled as package assets unless concrete implementation constraints justify a build dependency. Sites guidance applies to local interface quality, not hosted authentication/D1/deployment.

### M2 storage/resolution contract freeze

Use `domain/model_profiles.py`, `ports/model_profiles.py`, `adapters/persistence/model_profiles.py`, `application/model_profiles.py`, and `cli/models.py`. A profile alias is bounded lowercase ASCII (1–64 characters). Strict versioned `ModelProfile` holds name, monotonic revision, enabled flag and RuntimeConfiguration; only its safe projection omits credential references. `ProjectModelSelection` binds project/repository identity, monotonic revision, optional default alias, exact role overrides and explicit permitted aliases. `RunModelBindings` binds root run/project identities to immutable profile revisions/configuration hashes and role→configuration entries. Missing/disabled/unapproved aliases fail; resolution is user exact override, approved repository preference, reviewed default, or legacy configuration only when no new selection exists. The entire effective role set is preflighted before CoS dispatch.

SQLite migration9 adds dedicated user-owned profile, project-selection and immutable run-binding tables without modifying canonical Project JSON. Use compare-and-swap revisions and atomic audit records for user mutations; reject malformed/foreign/hash-incoherent rows on read. Model bindings contain no credential values and no arbitrary endpoint configuration. Runs must be explicitly bound to their required snapshot before effects; a missing required snapshot cannot fall back to legacy behavior. The runtime integration will either insert bindings with Run registration or add an explicitly omitted-when-absent binding reference with old-wire compatibility tests before modifying Run. The storage writer must not assume an optional default alone preserves hashes.

CLI groups `fleet models list|show|set|remove|bind|selection` operate on this application service; `set` accepts explicit runtime/provider-model/credential-ref (never a key value), `bind` targets a registered project/default or exact role, and inspection emits no reference or value. Changes affect future runs only. Profile removal must preserve historical snapshots and reject removal while referenced by active user selections, rather than invalidate resumable runs.

### M3 catalog contract freeze

Use `domain/role_templates.py` plus bounded `.fleet/agents/roles.yaml` parsing in the existing configuration adapter. `kind: RoleCatalog`, `apiVersion: agentfleet.dev/v1alpha1`, and `roles` map validated custom IDs to `baseRole` (engineer/verifier/researcher/architect), `description`, `instructions`, optional `modelProfile`, `allowedTools`, `maxSteps`, and optional narrower `allowedPaths`. Canonical defaults cannot be replaced through a custom-ID collision; persistent CoS remains the single coordinator. Optional values must not alter legacy serialized graphs/configurations. Resolve a `ResolvedRoleTemplate` containing actual ID, execution kind and intersected defaults/requests; custom requested tools/steps cannot exceed the base role. Optional catalog and its instruction files join ConfigSnapshot before execution and FleetPatch validation. A absent catalog leaves old snapshot bytes/hash unchanged.

Catalog creation/evolution is reviewed under existing agents/** FleetPatch scope; root fleet.yaml remains protected. The catalog is not operationally accepted until planner, dispatch, permission principals, verifier proof, repair and tests use it. The initial catalog writer owns schemas/parser/resolution only; root integrates execution and does not claim the parser alone completes customization.

### M1b durable planning contract freeze

`Run.plan_review_required` is omitted when false; reviewed root runs can pause at
`PAUSED_FOR_PLAN` after `_scope` but before any workspace, child or tool dispatch.
Migration10 adds immutable/revisioned planning decision records binding exact
Run/task/plan/config/model/base/target/organization authority. Approval is explicit
user CAS under the organization guard and changes no execution state. An atomic
approved-decision consumption changes PAUSED_FOR_PLAN to RUNNING at SCOPING and
records consumption plus event together. Only that winning caller continues the
frozen plan; it never reruns CoS. Public resume refuses reviewed RUNNING tasks;
unknown consumed execution ownership is not reclaimed or expired. Existing
legitimate tool-approval pauses retain their established checkpoints and resume
semantics. Cancellation preserves records and cleanup. Missing required decisions
or stale bindings fail closed. Session `/plan approve` will prepare an exact
expiring ticket; `/confirm` approves only and `/resume` explicitly continues.

### M4 local read-only HTTP contract freeze

The root agent owns all dashboard code and assets. The existing Python package
serves semantic HTML/CSS/JavaScript from package resources; no framework scaffold,
hosted Sites registration, analytics, external fonts or CDN is introduced.
`fleet dashboard [path] --port 0` selects only the exact registered repository and
binds IPv4 `127.0.0.1`. A fresh random bearer token is delivered once in the trusted
terminal, pasted into a password field, held only in page memory and required on
every API request. Tokens never enter URLs, browser storage, events or HTTP logs.
Stopping the foreground server revokes access. No public sign-in system is added.

Routes: GET `/` and exact packaged assets; authenticated GET `/api/catalog` and
GET `/api/runs/<root-id>`, `/api/runs/<root-id>/artifacts/<artifact-id>` and
`/api/runs/<root-id>/events`. The last route is a
bounded SSE fetch stream, with Authorization headers and per-run event-sequence
cursors. Streams expire/reconnect, discover child runs and explicitly signal
resync for stale/future/foreign cursors. Project/run checks apply on every request.
Only static login assets are unauthenticated; there are no write routes.

An independent read port uses read-only SQLite snapshot transactions and bounded
indexed/limited queries for root history, conversations, agents and events. It
does not initialize/migrate state. Existing inspection verifies evidence/model
bindings; only safe projections reach the browser. Each source frame has an
explicit content revision and cursors, not a fabricated global progress number.
Untrusted strings use textContent; CSP denies inline scripts, framing and external
connections. Exact Host/Origin validation and no CORS block cross-origin access
and DNS rebinding. Request headers/body/path, response/event counts, connection
count/time and query work are bounded; errors omit raw exceptions and credentials.

The first useful surface is a compact project run list with selected task state,
actual agent/model rows and events. Empty, error/disconnected and evidence detail
states follow the same neutral theme. Historical selection and bounded event
replay remain read-only. Browser tests use only generated offline fixtures and
explicit loopback test allowance; provider/network-denial defaults remain intact.

## Public contracts

- Interactive bare `fleet` invokes session selection/onboarding; non-interactive bare entry returns help before state/container creation. `fleet --help`, explicit chat pipes, one-shot commands and JSON exit codes stay compatible.
- Freeze `/plan`, `/diff`, `/apply`, `/fleet-patch list|show|diff|apply|rollback [id]`, `/confirm <code>` and `/dismiss` in the R1 review slice. Default selection is current run/sole proposal; ambiguity produces choices, not silent global-latest selection. `/approve` may select a sole current pending request after showing its scope; existing explicit syntax remains supported.
- Existing one-shot PatchService/OrganizationService actions retain compatibility; new review-aware optional contracts bind expected hashes/revisions inside guards. Public session methods require a reviewed ticket.
- New typed profile catalog, per-project binding selection and immutable run/agent model/template-binding records. Exact schema names/migration SQL and old-record canonical compatibility are frozen before their writer starts.
- Custom role IDs resolve to declared execution kinds and fixed output contracts; supported defaults decode unchanged. Explicit template registration and FleetPatch review are required for configuration changes.
- `fleet dashboard [path]` serves an authenticated local read-only view; it must not start an agent or select an unrelated project. The final R4 contract specifies exact routes, token bootstrap/session handling, cursor syntax and limits before HTTP source edits.

## Milestones

### M0: Approved plan and baseline

Acceptance: resumed scope recorded, write ownership/branch defined, existing artifacts preserved, relevant specs read, baseline checks labeled with exact source identity.

### M1: Session-first end-to-end

- M1a: bare entry and guarded in-session plan/patch/FleetPatch review/application, without changing underlying execution scheduling.
- M1b: public guided bootstrap, no-ID pending-decision selection, opt-in durable task-plan review before workspace/tool dispatch, and current profile/template/status discoverability.
- Acceptance: real PTY/pipe and offline fixtures prove restore, wrong-project denial, exact review/expiry/replay/stale/ABA guards, cancellation, history, and one-session patch application; gated public Docker journey proves first initialization without bypassing canary evidence. A delivered turn is never mislabeled as applied or verified.

### M2: Per-role model routing and budget visibility

- A fake/offline instrumented adapter routes CoS, multiple writers and Verifier to different configured models and records actual configurations; mocked transport asserts selected model and only its authorized key reach the request.
- Missing keys, wrong provider/model capability, mismatched binding, secret leakage, changed profile during resume and budget exhaustion have fail-closed tests.
- Default-only projects and old accepted runs remain readable/resumable under their original semantics. Child/join/repair model selection remains pinned, reported unknown usage remains unknown.

### M3: Actual custom role execution

- Custom backend writer and read-only security reviewer alter scheduling, instructions, output validation and model binding, with exact custom permission principals.
- Minimal team selection, disjoint parallel scope, delegation/output validation and fresh verifier evidence remain enforced; arbitrary names cannot bypass any hard deny.
- Template proposal/diff/apply/rollback works across restart and affects future tasks only. Historical configs/hashes and old graph/conversation records retain compatibility.

### M4: Live local dashboard

- Displays authoritative project/session/root/child/agent/model/status/usage/approval/event/evidence data, including waiting reasons and final proof gaps; no private chain-of-thought or invented progress percentages.
- Local emitted events visible within two seconds on normal fixtures; reconnect/resync/ordering and graph child discovery tested; lost connection visibly stale.
- HTTP auth, Host/Origin/DNS-rebinding, XSS/control text, traversal, connection/body limits, secret redaction and no mutation route tests pass. Packaged assets work without network/CDN.
- Browser E2E covers desktop/mobile readability, keyboard navigation, empty/error/disconnected states, historical selection and actual live fixture updates.

### M5: Final verification, docs and module delivery

All four milestones proven, docs/guide/schemas/upgrades/package examples accurate, all required local checks run, independent fresh security/behavioral review resolved, separate feature commits retained, normal GitHub merge and exact remote tree read-back. A skipped/unavailable hosted CI/live-provider/platform check is explicitly not a pass; required branch protection is never bypassed.

## Detailed implementation steps

1. M1a writer owns `cli/chat.py`, bare entry in `cli/app.py`, `application/conversations.py`, new session review contracts/service, `application/patches.py`/`application/evolution.py` expected-review guards, `bootstrap.py` wiring and focused session tests. Keep task scheduling/model-role paths unchanged in this slice; review before M1b.
2. M1b adds a separate validated planning checkpoint to `WorkflowEngine.start/resume`, conversation claim/wait handling, cancellation/recovery and schema/migration fixtures. Do not repurpose command approval or rerun CoS to reconstruct an accepted plan. Add `cli/onboarding.py` presentation over existing preview/bootstrap application operations.
3. Freeze M2 profile/binding schema with canonical-compatibility fixtures, then wire `domain/`, `application/runtime.py`, `application/workflow.py`, `application/graph_workflow.py`, `ports/runtime.py`, config/SQLite adapters and PydanticAI/fake adapters. Own model-profile CLI in a separate module; coordinate only its registration in app.py.
4. Freeze M3 template catalog and execution-kind contracts, then update `domain/config.py`, `domain/fleet_plan.py`, planner, role guidance, runtime tool catalogs, broker/workspace binding, CompletionGate, graph repair selection and evolution/config closure together. Never ship a display-only custom role.
5. M4 owner adds `application/dashboard.py` read models/service, a bounded HTTP adapter, `cli/dashboard.py`, package assets under `assets/dashboard/`, HTTP/integration/browser E2E tests and package inclusion. Freeze route/auth/stream contracts first. Read-only queries must not create runs, dispatch tools or mutate audit state.
6. Root maintains docs/spec ADRs, living plan/evidence register, generated schemas, verification and module commits. Do not alter other writers' work or commit a mixed unfinished feature. User changes remain preserved.
7. Inspect GitHub protection and workflow skip semantics before any remote write. Use local gates plus transparent CI-skip metadata only if compatible with current protection; otherwise report the exact required external gate. Do not disable workflows or change repository settings on the user's behalf.

## Validation plan

Dependency preparation is explicit and separate from offline tests. Do not read ambient credentials or initiate live calls. Use the prepared lock/environment where possible:

```bash
uv sync --all-extras --frozen --offline
uv run --offline ruff format --check .
uv run --offline ruff check .
uv run --offline mypy src tests
uv run --offline python -m agent_fleet.schemas.generate --check
uv run --offline pytest -q -ra
uv run --offline python scripts/verify_adversarial.py --output <new-disposable-evidence-directory>
uv build --offline
git diff --check
```

Record exact test counts, duration, selection, source/tree identity and evidence files. Run focused tests before a module commit; at final freeze run the full offline suite, security checks, schema/format/lint/types/build, migration/installed distribution and explicit Docker selections with existing prepared inputs. No unrelated existing directory may be used as pytest basetemp.

M1 existing regressions: `tests/unit/test_chat_cli.py`, `tests/contract/test_conversation_store.py`, `tests/integration/test_conversations.py`, `test_conversation_safety.py`, `test_fleet_patch_interfaces.py`, `test_fleet_patch_recovery.py`, `tests/e2e/test_persistent_chat_cli.py`, `test_fleet_evolution_cli.py`. M2/M3 add contract/transport/migration/custom-principal/graph cases beyond existing runtime/planning tests. M4 adds HTTP and actual browser E2E; freeze exact executable commands before implementing that slice.

Live-provider calls need an explicitly designated disposable credential/reference/model and separate opt-in. Existing missing L1/L2 public-release gates remain documented; no key/license search or invented acceptance. Validate Linux/type behavior locally where available; do not describe a macOS-only replay as fresh Linux execution.

## Rollback and recovery

Preserve old source and user-state schema fixtures. Add migrations rather than rewrite installed history; newer state must not be silently read by an incompatible binary. Keep profile/template versions immutable and snapshots attached to runs; rotation of a secret value is distinct from rebinding a provider/reference. Review tickets expire on restart and never retarget latest work. Unknown execution claims require explicit existing owner-stopped recovery, not retry. Browser disconnect does not affect terminal ownership. Cancellation retains cleanup and receipts. Code/FleetPatch apply still guards repository/config/base/version identity and preserves unrelated edits. Module commits are revertible in reverse dependency order, but state downgrade needs documented compatibility or forward repair, not destructive resets.

## Progress

- [x] (2026-09-07) User explicitly confirmed new release scope and module commits/merge after clarification.
- [x] (2026-09-07) Baseline and existing remote delivery read back; branch created, prior roadmap preserved/advanced, implementation plan written before source changes.
- [x] (2026-09-07) Independent session and model/role code-path exploration found exact review race, fake-bootstrap boundary and canonical serialization compatibility obligations.
- [x] (2026-09-07) M0 prepared-dependency sync and static baseline: 53 packages checked; Ruff format269 files, lint, mypy219 files, generated schemas and diff check all exit0 on unchanged baseline source. No full suite or live/Docker execution inferred.
- [x] (2026-09-07) M1a session entry and exact review/application slice, including real PTY and independent review.
- [x] (2026-09-07) M1b guided public onboarding and durable plan-review gate; full real-Docker replay accepted below.
- [x] (2026-09-07) M2 per-role model/profile routing and immutable resume bindings; actual SDK mock transport, not live inference.
- [x] (2026-09-07) M2 component/runtime integration: 125 tests passed in 79.21s over profile domain/store/service/CLI/workflow/real-SDK mock transport and existing budget/PydanticAI regressions. Scoped format/lint12 files and whole-tree mypy239 files passed at that snapshot; no actual provider requests inferred.
- [x] (2026-09-07) M3 operational custom roles and versioned evolution; full-parent repair admission correction independently replayed.
- [x] (2026-09-07) M3 configuration component: 81 focused role/config/snapshot tests passed in 42.98s; focused mypy passed three files. Operational dispatch remains unfinished.
- [x] (2026-09-07) M3 planner/gateway/runtime/evidence regression selection: 269 tests passed in 36.67s; 12 new custom-planning tests passed in 0.34s after correcting a test Project ID prefix. Initial legacy planner errors differed only in message order and were corrected while retaining hard checks. Broader permission/graph selection: 63 passed, 1 stale migration-version assertion failed and was updated to supported-version equality; replay still required.
- [x] (2026-09-07) M4 authenticated live local dashboard, actual browser interaction, HTTP security and independent liveness review.
- [x] (2026-09-07) M1 combined replay: 158 passed in 522.60s; additional waiting-plan organization publication fence 1 passed in 7.73s. Includes real foreground PTY behavior, durable plan decision/restart, and a combined custom-role/model-profile/reviewed-plan task. M1 component final 50 passed in 89.43s; model/legacy-upgrade selection 106 passed in 124.44s. These overlap and must not be summed as unique coverage.
- [x] (2026-09-07) M3 operational workflow/planning replay: 20 passed in 72.41s across actual custom principals, graph/specialist/repair execution, permission restart, readonly denial, and versioned rollback. Independent review reproduced one repair scope admission mismatch, now fixed to cover full parent/verifier scope before dispatch; new negative/positive regression makes the old check fail. Final planner 13 passed in 0.37s; independent security selection 46 passed, 5 deselected in 23.12s.
- [x] (2026-09-07) M4 initial vertical slice: actual query-only reader, safe application projection, bearer-authenticated loopback HTTP/SSE/artifact routes and packaged neutral HTML/CSS/JS with CLI launcher. Initial tests: 27 passed, 3 failed in 89.28s (two fixture expectations incorrectly counted the root verifier as a child, one omitted mandatory fake scenario); corrected fixtures and replay pending. Whole-tree Ruff and mypy258 files passed at this snapshot. Not yet browser-accepted.
- [x] (2026-09-07) M4 final focused replay: 33 passed in 81.74s; late live-child discovery after exact plan approval/resume: 1 passed, 29 deselected in 18.52s. The two real fake-runtime writers appear as running children while blocked inside their actual invocation, with three cursor sources and no resync. Browser probe passed 17 assertions twice: escaped hostile strings, honest simulated evidence, patch/graph/event inspection, empty browser storage, keyboard navigation, desktop/mobile/200-percent text bounds, offline/reconnect, disconnect and invalid-token denial. A separate empty fixture showed zero tasks/agents. Actual terminal approval appeared in the browser in approximately 102ms on this fixture, not a latency SLA. Desktop/mobile/zoom/empty screenshots were inspected.
- [x] (2026-09-07) Independent M4 liveness replay: trickled headers terminate at 3.07s; owned connection shutdown joins in under 0.001s without closing an unrelated socket. Actual frontend code reports disconnected/retrying when an SSE body stalls. Independent final M1b/M2 selection: 13 passed, 45 deselected in 23.27s, covering single-winner consumption/resume, missing model/key denial, pinned profile/reference semantics and legacy decision integrity; no remaining finding in the bounded review.
- [x] (2026-09-07) Frozen offline partition 1: unit plus contract, 1747 passed in 205.07s. Partition 3: E2E plus Docker/release directories, 32 passed, 18 skipped in 496.38s. Partition 4: live-test directory with live disabled, 1 passed, 1 skipped in 0.11s. Integration partition remains running; its final late-added dashboard test is reported separately above, never counted twice.
- [x] (2026-09-07) Standalone adversarial script: 734 passed in 278.03s (script elapsed 280.298s), zero skips/errors. This overlaps the default suite and is not an additional unique-test total. Ruff format312 files, lint, mypy260 files, generated-schema drift, JavaScript syntax and diff whitespace passed; offline lock resolved55 and sync checked53 packages. Sorted source/test/scripts file-hash aggregate: `56c18b87e619b4c96b5d5293246b7682d46cdb2d97f5d35f40c47170b4d9c085`.
- [x] (2026-09-07) New public bare-terminal onboarding test: separately enabled real Docker, 1 passed in 10.98s in a shared cache fixture. Actual stdin/stdout PTY proves preview/confirmation precedes publication/resources, genuine independent command/transcript evidence, unchanged target code and zero owned resources; no provider request. Root full Docker replay is still pending as described below.
- [x] (2026-09-07) Corrected full Docker replay: 15 passed, 4 deselected in 204.64s with the unchanged image `sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241`. Independent read-back: all112 leases across27 fresh test databases settled (103 released,9 recovered), zero outstanding, all36 leased worktree paths absent, zero extra worktrees across17 surviving registered repositories, and empty managed-container inventory on the same pinned Colima Unix daemon. Failed private-temp fixtures remain separate and untouched; their39 unresolved historical leases are not counted as successful cleanup.
- [x] (2026-09-07) Final audit repair and stronger regressions: 11 passed in3.43s. The existing VerifierMutation case now proves one exact DENY event and persisted DENIED intent with verifier/run/task/action/resource/content/hash identity, no grant/result/approval, no target mutation and complete cleanup. Two added custom-role narrowing cases prove valid excluded calls fail both validate/execute with zero Gateway calls/records, while permitted reads retain the custom principal. Source/test/scripts freeze `de7ab84636c185e543dfd76b84cc9e97af64aa9ee9ef7ec63f12d3348f4b3135`; final collection2302 tests. Static refresh: Ruff312, mypy260,92 schemas, whitespace all passed. Complete unit/contract and three exhaustive disjoint integration partitions are rerunning on this freeze; `docs/session-first-test-partitions.json` records exact file selections. No old failure is silently removed from this plan.
- [x] (2026-09-07) Final-freeze unit/contract:1749 passed in228.82s. Fresh independent audit-delta replay4 passed in10.02s, no remaining finding in its bounded scope. Offline lock55/sync53 passed again. Complete final results are consolidated in `docs/SESSION_FIRST_ACCEPTANCE.md`; only rows explicitly marked PASS/completed are acceptance.
- [x] (2026-09-07) Complete final-freeze matrix: integration133 passed/1111.34s +182 passed/1072.79s +186 passed/997.53s =501; offline E2E/default Docker/release/live33 passed,19 skipped/742.64s. Together with1749 unit/contract, all2302 collected cases are covered:2283 passed,19 explicit optional skips. Separately enabled real Docker15 passed,4 deselected/370.03s. Standalone adversarial736 passed/459.08s (script461.966s), no skips/errors. Source/test/scripts aggregate remains `de7ab84636c185e543dfd76b84cc9e97af64aa9ee9ef7ec63f12d3348f4b3135`; README and bundled USER_GUIDE are now frozen for final archive/install verification. Old failed attempts remain above, not current failures.
- [x] (2026-09-07) Final distribution/installed gates: wheel+sdist2 passed,1 deselected/99.60s; installed public Docker1 passed,2 deselected/61.78s; archive/schema refresh6 passed/3.01s. Direct/fixture/rebuilt-from-sdist wheel hashes are identical (`da81e444…de9f9`), sdist identical (`a5f3f3ca…f2c3f`); full digests and frozen README/guide identities live in the acceptance ledger. Installed per-role model/plan CAS/replay behavior and all packaged resources passed. A fresh installed CLI Dashboard replay passed all17 browser assertions with inspected desktop/mobile screenshots; exact owned server/browser stopped, token revoked. Independent cleanup proves54 released leases/0 outstanding across3 installed states,18 worktrees absent and no extra registrations across10 repositories, plus empty Docker inventory.
- [x] (2026-09-07) Independent final identity audit: the five default JUnits exactly match2302 collected identities, no overlap/omission/extra; all43 integration files partitioned once. Docker15 and installed3 independently match18 default optional skips; actual live-provider1 remains unperformed. Final Docker112 leases/27 databases settled,36 worktrees absent and17 repositories without extra registrations. Module commits created for contracts `231ccd95e2d04ce872dd9db48eb4069fc3288a05`, runtime/session `c02043f29c31133c4a83161a592c3ee6ecfafdaa`, Dashboard `814b3ae7044a00f74c3713cb35900c2c95b180ca`; isolated staged-tree CLI smoke passed at each, not full-suite claims for intermediate trees. Release-documentation commit and remote delivery follow.
- [ ] M5 full verification, docs, independent review, module commits and GitHub merge/read-back.

## Discoveries

- Final read-back correction: the original unshared `pytest-1070` directory no longer exists. The earlier39 outstanding leases across12 states are a verified historical observation, not currently retained databases; no recovery or manual deletion was performed by the audit and the disappearance mechanism was not established. `docker.xml` and these failure notes remain. Earlier in-place-retention statements below describe the earlier checkpoint, not the final state. Do not turn directory disappearance into recovery/cleanup proof. Explicit shared final-fixture directories remain available and have their separate zero-outstanding audit.
- Full integration partition completed with 4 failed, 496 passed in 1972.33s. Three failures expected the old delegation error wording; earlier template validation now denies the same forbidden team before any worker/resource, and the exact new message assertion retains the remaining persisted-state checks. The fourth was a genuine audit regression: unconditional tool-catalog preflight rejected a recognized built-in Verifier write before Gateway/Broker, losing its exact denial receipt despite preventing the write. Restored the historical Broker path for recognized built-in Engineer/Verifier attempts while keeping advertised definitions least-privileged and custom/read-only catalogs strict. The original denial assertion is preserved; initial repair selection passed12 tests in10.39s. Stronger exact-principal/no-effect regressions and a fresh complete matrix follow. The failed full partition is not acceptance.
- First full Docker attempt used the default macOS private temporary root and returned 14 failed, 1 passed, 4 deselected in 62.08s. Two direct daemon errors prove an invalid bind mount; the sole passing test intentionally creates no container. The other failures wrap create/cleanup/canary failures. Existing user-guide Colima instructions require a shared test root. Failed state and XML are preserved: 39 outstanding execution/sandbox/worktree lease records across 12 state roots remain fail-closed, not evidence of 39 live resources. Do not erase those records or replay uncertain executions. A fresh full run uses a new shared-cache basetemp and the unchanged immutable image; exact cleanup evidence must be reconciled before release.
- An earlier full default run was explicitly interrupted after an already-corrected dashboard test fixture error: 1 failed, 838 passed, 14 skipped in 946.39s, exit2. The fixture called nonexistent `ModelProfileService.project_for_path`; the supported method is `project`. Focused replay passed after correction. The exhaustive partition rerun, not this interrupted attempt, is the acceptance selection.
- Independent M4 review demonstrated two liveness issues: a 3-second socket timeout alone allows slow headers indefinitely, and successful SSE headers alone cannot establish continuing liveness. Added absolute header timer, pre-parser byte bounds, owned-connection shutdown, and a stream-specific 7-second receive watchdog. Negative regressions/review replay are required before acceptance.
- The joined verifier is an instance on the parent Run, not an additional graph child. Dashboard shows the authoritative two writer child records and root verifier; it must not fabricate a third child record.
- Parallel repair executes on the full parent TaskSpec, so a custom repair role must cover the verifier-bound parent scope at admission, not only the union of narrower initial writer scopes.
- Migration9 exposed a pre-migration8 integration fixture that deleted only migration8 while retaining newer tables/version. Its disposable legacy copy now removes versions8+ and their tables; the initial focused run was 80 passed/1 failed, followed by 81 passed after the fixture correction.

- Public bootstrap cannot be fully fake; correct the prior roadmap wording instead of exposing its private test-only initializer.
- Existing apply services accept only IDs; session confirmation needs exact expected review fields checked under their guards, not a frontend-only comparison.
- Existing canonical Project/Run/config/graph hashes can change when optional default fields are added. Migration/serialization compatibility is an acceptance requirement, not a cosmetic schema adjustment.
- Literal roles are enforced in planner, runtime tools, gateway/workspace bindings, broker and evidence. Custom-role work spans these paths, including joined repair; modifying only YAML names cannot satisfy M3.

## Decision Log

- 2026-09-07: custom Plan nodes and Agent instances carry an optional control-plane-derived execution_kind, omitted when absent to preserve historical canonical bytes. Model ScopeDecision selects only role IDs; the planner derives kinds from the exact ConfigSnapshot and runtime/broker/evidence revalidate that binding. Permission scopes retain the custom role ID. Built-in IDs cannot be rebound and no custom CoS kind exists.

- 2026-09-07: user confirmation supersedes the development pause for the four named features and their delivery. Extended roadmap integrations remain deferred; existing CI-cost and secret boundaries remain.
- 2026-09-07: deliver complete modules as smaller verified slices on one feature branch. Root coordinates shared contracts and final commits; writers do not commit/push or revert other writers.
- 2026-09-07: local read-only dashboard is the confirmed observation feature; mutation controls and a daemon are separate later milestones, not needed to show real agent states.
- 2026-09-07: keep current provider adapter first; different models per role require actual selection tests, not claims inferred from TestModel output. Additional providers require separate conformance/live gates.

## Outcomes

All four capabilities are implemented; complete frozen local, independent audit, browser, real-Docker and installed-distribution gates passed as recorded above. Module commits are being assembled and remote delivery remains pending. No live provider calls, remote pushes or CI runs have been performed for this release at this checkpoint. The full goal remains unfinished until GitHub merge/read-back completes M5. The dashboard is intentionally foreground, loopback-only and read-only; new-provider/live-model reliability, fresh Linux execution and public-release license/provider gates are not implied by local tests.
