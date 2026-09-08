# Session-first product roadmap — proposed next generation

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

Status: **implementation authorized on 2026-09-07**. The original 2026-09-05 planning-only pause is historical: after a scope clarification the user explicitly confirmed implementing Session, per-role models, custom roles and the local real-time dashboard, with module-level commits and GitHub merge. The active delivery contract is `.agent/plans/2026-09-07-session-first-release.md`. Preserve the Actions-minute constraint, credential opt-ins and all existing trust/sandbox boundaries. No public publication or license choice is implied.

## Purpose and user-visible result

Evolve the existing secure workflow CLI into a session-first project agent workspace without changing the product's positioning: a local-first, BYOK Chief-of-Staff runtime that bootstraps, operates, secures, and evolves a project-specific agent organization.

The ordinary user should open one session, describe a goal, review the proposed work and sensitive actions, and receive a patch with verification evidence. Advanced users may choose different models and customize specialist templates; beginners should not need to design an organization before completing their first task.

Proposed interaction, **not current command documentation**:

```text
$ fleet
Project: current repository · Session: restored
You: 修复登录超时，并添加回归测试
CoS: proposes a bounded task and the smallest suitable team
You: review the task; explicitly approve any requested exact actions
CoS: shows progress, changed files, patch, tests, verdict, and remaining gaps
You: inspect the patch and explicitly apply this reviewed candidate
```

The session retains relevant identifiers so users do not routinely copy run IDs between commands. A local dashboard observes the same runs; it is not another orchestrator.

## Scope

### In scope

- Session-first entry point, guided repository onboarding, task preview, and in-session review/application of existing code and organization proposals.
- User-owned model profiles and per-role bindings, initially through the existing provider adapter, then an additional provider after separate adapter acceptance.
- Default and user-customized role templates, selected adaptively as temporary task responsibilities.
- A local read-only dashboard with live status and historical evidence; authenticated controls in a later increment.
- Usage/budget visibility, safe cancellation/recovery, runner readiness, installation/migration usability, and representative evaluation tasks.
- Compatibility, security, observable acceptance criteria, and resource-aware validation/release planning.

### Out of scope

- Implementation or validation during the original 2026-09-05 planning turn (historical boundary, superseded for the confirmed release on 2026-09-07).
- Replacing accepted Phase 0–7 history or reporting this roadmap as shipped functionality.
- A hosted SaaS control plane, accounts/billing, remote multi-user collaboration, mobile app, agent marketplace, or mandatory cloud dependency.
- Unrestricted group chat, permanent role rosters, arbitrary workflow DSLs, arbitrary tool/plugin loading, or native harness execution bypass.
- Automatic model fallback, autonomous permission expansion, automatic package installation/image pulling, or unreviewed target-repository changes.
- Background execution in the first session milestone. Persistence of a conversation does not imply a detached worker survives terminal exit.
- Branding, license selection, selecting a specific paid model for the user, and unrelated future integrations.

## Current repository state

Baseline inspected: clean `main` at commit `9276cbf44fa32adc8087d618e0ec4aeff60b877c`, tree `12533fc8b1d5f454b7ba29b32635ae10b30e48e1`, before this plan was added. README and existing acceptance records document previous verification; no runtime suite was rerun for this roadmap.

- `src/agent_fleet/cli/app.py` uses Typer with `no_args_is_help=True`; bare `fleet` currently shows help rather than entering a session.
- `src/agent_fleet/cli/chat.py` already provides `run_session`, bounded input, progress, approvals, resume, cancellation, and persistent conversation selection. Its help directs code patch and FleetPatch review/application to separate CLI commands. Terminal exit cancels and awaits owned work; this is not a daemon.
- `application/conversations.py::ConversationService` owns project-bound conversation selection, durable submissions, bounded/redacted context, idempotency, and recovery constraints. Its `progress()` projects root-run events and pending approvals; it is not a complete child-agent dashboard event stream.
- `application/patches.py` and `application/evolution.py` own code application and versioned organization changes. New interfaces must reuse these services, not duplicate their policy.
- `domain/config.py::RuntimeRequest` and `FleetSpecBody.runtime` select one project-level runtime/model. `AgentRequest` has no per-agent model binding. Project/run/checkpoint records freeze provider model and credential reference.
- `adapters/runtime/pydantic_ai.py` supports OpenAI Responses and Chat routing through the current guarded adapter. These are not two independently supported providers. Real-provider release acceptance remains distinct from offline adapter tests.
- `domain/models.py::AgentRole` and `application/planning.py::FleetPlanner` implement fixed execution roles and five adaptive topologies. Configurable role identifiers alone do not make arbitrary roles operational.
- SQLite, typed events, graph state, structured delivery evidence, independent permissions, sandbox providers, and FleetPatch already exist. There is no reason to replace them with a second orchestration stack.
- The original MVP deferred web UI and daemons. The user's new request proposes a subsequent dashboard scope; it does not retroactively change earlier acceptance claims.

Paths without a prefix below are relative to `src/agent_fleet/` unless otherwise stated.

## Security impact

All invariants in `AGENTS.md` and `docs/SECURITY_MODEL.md` remain in force:

1. Model-requested effects still cross `ToolGateway` and `PermissionBroker`; a role name, model profile, chat message, or dashboard connection grants no permission.
2. Repository files request configuration. User-controlled trust, credential references, and approved provider destinations remain outside the repository. No secret values enter browser state, worker sandboxes, prompts, patches, events, or source control.
3. An agent cannot authorize a request by generating “yes.” Human approval is a deterministic action bound to the exact request, scope, current revision, and applicable candidate hash. Code application and organization application remain separate reviewed actions.
4. A changed model/role configuration affects new runs only. Existing runs and resumable checkpoints retain their resolved bindings. Rebinding protected settings needs an explicit user-owned reconfiguration path, not a FleetPatch privilege escalation.
5. Verifier outputs cannot introduce accepted filesystem changes. Different model choices do not themselves prove independent verification; candidate isolation, no self-approval, and evidence checks remain mandatory.
6. Dashboard serving creates a new local HTTP trust boundary. Loopback alone is insufficient: authenticate access, validate Host and Origin, prevent CSRF/DNS rebinding, escape untrusted content, redact before delivery, and apply response-size/backpressure limits. Do not embed reusable secrets in URLs or logs.
7. Multi-interface requests require idempotency and revision checks. Unknown execution ownership remains a recovery problem, never an invitation to replay potentially completed effects.

## Proposed design

### One session and application core

Reuse Conversation as the persisted session identity and Run as a bounded task execution. Do not introduce another competing history store. Keep terminal presentation in `cli/`; expose typed application queries and commands for both interfaces.

```text
Terminal session                 Local dashboard
       \                         /
        Shared application queries and commands
           Conversation / Run / Graph / Evidence
                  |                  |
          Model/runtime ports   ToolGateway → PermissionBroker → Sandbox
                  |
          User-owned profile resolution
```

First-session state transitions are select/restore → collect goal → preview/admit → run → await decision or deliver → review/apply → next goal. Existing error, failure, and cancellation states remain visible. Registration cannot silently grant trust or start paid work. Resume of a paused task is not automatic approval. Initially allow one active goal per session; show an explicit busy state instead of silently queuing or interrupting it.

### Separate four concepts

- **Model profile:** provider/model identifier, secret reference, trusted destination, supported capabilities, and limits, owned by the user.
- **Harness:** runtime adapter that translates typed tasks into model/tool interactions; it does not control final permissions or execution isolation.
- **Role template:** instructions, supported execution kind, output contract, requested tools/scopes, model-profile preference, and task limits.
- **Agent instance:** one temporary assignment with resolved role/template revision, model binding, task scope, and budget pinned to its run.

Examples such as `planning`, `coding`, and `verification` are profile aliases, not real model IDs. A default profile serves all roles until the user overrides one. CoS and specialist calls must use the same resolution/accounting rules. Repository profile requests cannot cause a credential to be sent to an unapproved destination.

First support explicit variants of existing execution semantics: coordinator, writer, read-only specialist, and verifier. Users may define `backend_engineer` or `security_reviewer`; their display names do not create new authority. Validate templates, typed outputs, delegation, scope overlap, and verifier independence before scheduling. The CoS chooses the smallest suitable set of instances rather than starting every configured template.

### Shared observability and controlled interaction

Derive dashboard state from durable application events and graph records, with an initial snapshot plus a sequenced, resumable event feed. Start with SSE for one-way updates unless implementation measurements show a concrete blocker. Define cursor scope, snapshot consistency, retention, reconnect, deduplication, and child-run aggregation before adding a browser.

Show queued/running/waiting/failed/completed states, role/model bindings, safe tool activity summaries, approvals, elapsed time, reported usage, patch/test/build artifacts, verifier verdict, risks, and proof gaps. Show unknown usage as unknown. Do not invent completion percentages or expose hidden chain-of-thought; provide bounded decision summaries and evidence instead.

Ship read-only observation before browser controls. Later approval/cancel/apply operations invoke the same application services as CLI commands with typed responses, authentication, idempotency keys, revision checks, and audit receipts. The UI neither edits SQLite directly nor shells out to CLI commands.

### Reliability and onboarding are product features

Reuse repository profiling and `doctor` to explain missing runtime tools, credentials, permissions, and runner dependencies before admitting a task. Detection of a language is not proof that its tests can run. Keep the first supported runner boundary explicit; add a language/build-system slice only with a fixture and executable evidence.

Enforce per-request/agent/run limits and cumulative accounting where supported. Display retries and reported tokens; label prices or usage that are unavailable. Do not describe post-response cost reporting as a guaranteed hard pre-spend dollar cap. Stop dispatching new work when a deterministic limit is exhausted, and record in-flight overshoot limits honestly.

Keep project knowledge bounded, provenance-linked, reviewable, and refreshable; do not add a vector database by default. Add a background supervisor only as a separate later feature with explicit detach, ownership, cancellation, and restart semantics.

## Public contracts

All entries here are proposals, not available command/configuration documentation.

- Bare `fleet` in an interactive terminal enters/selects a session; `fleet --help`, `fleet chat`, existing one-shot commands, JSON envelopes, and exit codes remain compatible. Non-interactive bare invocation must return help or a clear error without hanging, creating state, or launching a server.
- Proposed session operations: inspect current plan/status, review patch/evidence, select pending approval, and review/apply/rollback a FleetPatch. Shortcuts such as `/diff`, `/models`, or `/dashboard` may present these operations; exact grammar is frozen in the relevant implementation plan. No free-form text alone confirms a destructive or protected action.
- New user-owned `ModelProfile` and resolved run/instance binding records; `.fleet` contains requested aliases only. Resolve aliases against explicit user configuration before any paid call. Do not silently reinterpret legacy `providerModel` registration.
- New role-template execution-kind/output contracts separate from the existing `AgentRole` enum. Preserve legacy role IDs and defaults; unknown/unsupported templates fail admission with actionable errors.
- Extend schema exports, config snapshots, model accounting, checkpoints, and migrations as required. Add new migrations rather than rewriting deployed history. Specify old-record decoding and downgrade limitations before implementation.
- New application-level dashboard snapshot/event-feed contracts with stable IDs, sequence/cursor rules, redacted summaries, and explicit stale-state errors. Browser control contracts are not part of the first read-only increment.

## Milestones

Milestone labels R1–R6 are roadmap labels, not replacements for existing Phase 0–7 acceptance. Each increment must remain independently runnable. No duration estimates are promised before a slice contract is frozen.

### R1: Session-first workflow and first-task onboarding — highest priority

Deliver a full goal → task preview → approvals → evidence → patch review → explicit apply loop without leaving the session. Reuse existing conversation/application services. Preserve cleanup-on-exit and bounded history; add input history only with appropriate secret/retention safeguards.

Acceptance:

- A new user can enter a fixture repository, complete guided registration with explicit trust/runtime choices, and finish the canary without copying run IDs or issuing another `fleet` prefix inside the session. Offline E2E uses explicitly registered test fixtures; public first-registration acceptance requires the existing genuine Docker canary. Fake sandbox never satisfies public bootstrap publication.
- Returning restores the correct project-bound conversation; no cross-project history or pending approval leaks. Non-interactive entry does not hang.
- Pauses, denial, cancellation, EOF, signal handling, stale candidate application, duplicate submissions, and unknown claims preserve existing safe behavior. Natural-language or tool output cannot approve itself.
- Existing one-shot scripts, `fleet chat`, JSON outputs, and CLI exit codes retain contract coverage.

### R2: Per-role model profiles and budget visibility — highest priority

R2a binds different models through the existing guarded adapter. R2b adds a second provider only after its own contract tests and explicit live opt-in acceptance. Shared provider configuration does not imply all providers have equal capability.

Acceptance:

- An offline instrumented run assigns distinct configured profile aliases to CoS, Engineer, and Verifier, and its persisted evidence proves each actual dispatch used the resolved binding.
- Default-profile inheritance and overrides are deterministic. Missing keys, unsupported tools/structured output, untrusted endpoints, disabled models, and exhausted budgets fail before dispatch without silent fallback.
- Resume retains original bindings after configuration edits; new runs use newly reviewed settings. Secret-value rotation under the same approved reference is distinguished from destination/reference/model changes.
- Reported usage and retries appear per instance and in run/session aggregates; unknown values are not displayed as zero. Tests prove no cross-provider credential or event leakage.

### R3: Role templates that actually drive adaptive execution — high priority

Provide usable defaults for CoS, Engineer, Verifier, Researcher, and Architect. Add constrained custom templates within supported execution kinds; keep the planner free to choose direct completion or a smaller team.

Acceptance:

- A reviewed custom backend-writer template and read-only security-review template alter actual task assignment, instructions, model binding, and output validation, not just labels in YAML/UI.
- A trivial read-only goal does not spawn a fixed roster. Parallel writer scopes remain disjoint; independent verification is required where the admitted task contract requires it.
- Unknown execution kinds, output mismatches, delegation loops, self-verification, overly broad tool requests, and protected trust edits are rejected before execution.
- Template changes produce a FleetPatch diff and a reviewable version; apply/rollback affects subsequent runs while previous evidence retains its original organization version.

### R4: Local live dashboard — read-only first, controls second

R4a needs R1's shared application/query boundary and event-feed contract; it can ship before all R2/R3 options exist. It must accurately display whichever bindings the run actually has. R4b adds controlled interactions only after read-only/authentication acceptance.

Acceptance:

- A multi-node offline run shows each actual child agent, dependency/wait reason, safe activity summary, approvals, and delivery artifacts. UI state matches persisted state and terminal observations.
- On a normal local fixture, emitted events become visible within two seconds; a disconnected view is visibly stale. Reconnect and cursor replay neither omit nor duplicate final states.
- Hostile repository names, model text, logs, and diff content cannot execute script or escape rendering. An unauthenticated client, hostile Origin, or invalid Host cannot read state or perform actions.
- Read-only mode has no mutation endpoints. Later controls cannot authorize a stale/replaced candidate, replay an already consumed approval, or bypass permission hard-denies through simultaneous CLI/browser requests.
- Serving is local-only by default; no CDN, telemetry, account, provider secret in the browser, or remote dashboard dependency is required.

### R5: Everyday reliability and broader repository readiness

Prioritize clearer installation/upgrade diagnostics, explicit dependency preparation, first verified task, a unified pending-decisions view, and recoverable failures. Reuse existing bounded knowledge rather than replacing it with speculative infrastructure.

Acceptance:

- Each advertised language/build-system runner is exercised on a small repository with genuine test/build evidence. Unsupported dependencies produce actionable diagnostics rather than a false pass or a host-execution fallback.
- Interrupted upgrades and task crashes leave a recoverable state with evidence; stale claims never auto-replay side effects. Data export/deletion/retention boundaries are documented and tested.
- If background execution is added, an explicit detach/attach/cancel flow has one provable owner, durable queue state, and restart tests before it is advertised. Plain session exit keeps its documented behavior.

### R6: Evaluation and release discipline — cross-cutting, expands over time

Start a small deterministic offline evaluation set with R1; expand it with every milestone. Later real-provider evaluations are separate opt-in runs, not substitutes for reproducible regression tests.

Acceptance:

- Cover a small bug fix, regression test addition, scoped refactor, independent rejection, approval denial, cancellation/recovery, budget exhaustion, and repository setup failure. Score correctness and evidence completeness, not how many agents spoke.
- Record run/config/version identities, pass/fail/rejection, time, reported usage, proof gaps, and task-level artifacts. Compare against the previous accepted baseline.
- Public capability claims distinguish offline adapter acceptance, real provider behavior, actual sandbox execution, installed package validation, and platform coverage.
- While Actions minutes are unavailable, do not dispatch workflows or push changes expecting CI. When implementation resumes, run applicable local gates and explicitly record platform/remote gaps; local success does not fabricate remote acceptance. Any future workflow-budget changes require their own reviewed change and must not remove security acceptance.

## Detailed implementation steps

These steps are authorized by the user's 2026-09-07 confirmation, through the bounded contracts and evidence in the active release ExecPlan. The extended roadmap beyond the four confirmed capabilities remains future work.

1. Freeze the R1 task contract; reconcile the next-generation scope in `docs/PRODUCT_SPEC.md` and `docs/IMPLEMENTATION_ROADMAP.md`. Keep accepted history intact. Specify interactive/non-interactive behavior in `cli/app.py::main` and Typer entry-point setup.
2. Extend `cli/chat.py::run_session` presentation and `application/conversations.py::ConversationService` results to select current task/artifacts and present pending decisions. Delegate code review/application to `application/patches.py` and organization operations to `application/evolution.py`; do not move policy into the CLI.
3. Extend `ports/conversation.py`, `application/conversation_results.py`, conversation tests, and schema generation for any genuinely new session commands/results. Add migrations in `adapters/persistence/sqlite.py` only if the existing persisted conversation/run contracts cannot represent the required state.
4. Freeze model-profile and protected-reconfiguration contracts in `docs/CONFIG_AND_SCHEMAS.md` and `docs/SECURITY_MODEL.md`; record a short ADR. Add typed profile/binding models in `domain/`, user-owned configuration loading near `adapters/config/`, and credential resolution through `ports/secret_store.py`. Keep repo requests distinct from trusted settings.
5. Wire resolved bindings through `application/runtime.py`, `ports/runtime.py`, `application/graph_workflow.py`, checkpoints, runtime accounting, and `adapters/runtime/pydantic_ai.py`. Extend the fake adapter to prove dispatch selection and provider isolation offline before adding another provider implementation.
6. Generalize `domain/config.py::AgentRequest`, `domain/models.py::AgentRole` usage, `application/planning.py::FleetPlanner`, typed runtime role outputs, and `adapters/runtime/prompts/` into validated template references. Update `application/evolution.py` admission and version binding so custom roles cannot expand protected authority.
7. Specify dashboard read models and cross-child event cursors using `application/conversations.py::progress`, `application/graph.py`, `ports/event_sink.py`, and `adapters/persistence/graphs.py`. Build an application query layer only as needed; do not introduce a second source of truth or orchestration driver.
8. In the R4 ExecPlan, select a small frontend/server stack and name its exact new paths and local test commands before writing UI code. Add an authenticated loopback HTTP adapter and packaged offline assets; no remotely loaded scripts. Implement read-only snapshots/event replay before mutation endpoints.
9. Extend `adapters/repository/profile.py`, existing doctor/bootstrap services, and runner assets for each specifically supported repository slice. Separate explicit dependency/image preparation from isolated task execution.
10. Update `README.md`, `docs/USER_GUIDE.md`, schemas, migration notes, and milestone ExecPlans with executable current examples and exact test identities/results as each slice ships. Do not copy this plan's proposed commands into current quickstart instructions prematurely.

## Validation plan

### Planning turn

Only inspect repository state and validate this Markdown document. No dependency installation, application invocation, test suite, image/model call, frontend build, commit, push, or Actions dispatch is part of this turn.

Run a whitespace/error check including the new untracked file:

```bash
git diff --no-index --check /dev/null .agent/plans/2026-09-05-session-first-product-roadmap.md
git status --short --branch
```

Check all required ExecPlan headings, matched Markdown fences, and that only this new plan appears in the change inventory. Record results below.

### Future implementation, only after development resumes

Prepare locked dependencies explicitly with `uv sync --all-extras --frozen` when allowed; network preparation is separate from offline execution. With prepared dependencies and live/Docker opt-ins disabled, preserve these existing quality commands:

```bash
uv run --offline ruff format --check .
uv run --offline ruff check .
uv run --offline mypy src tests
uv run --offline python -m agent_fleet.schemas.generate --check
uv run --offline pytest -q -ra
uv run --offline python scripts/verify_adversarial.py
uv build --offline
```

Focused current suites to extend, not merely rerun unchanged:

```bash
uv run --offline pytest -q tests/unit/test_chat_cli.py tests/integration/test_conversations.py tests/integration/test_conversation_safety.py tests/e2e/test_persistent_chat_cli.py
uv run --offline pytest -q tests/contract/test_pydantic_ai_runtime.py tests/contract/test_runtime_budgets.py tests/integration/test_runtime_budget_workflow.py tests/integration/test_config_snapshot_binding.py
uv run --offline pytest -q tests/contract/test_adaptive_runtime_roles.py tests/integration/test_adaptive_graph_safety.py tests/e2e/test_adaptive_graph_cli.py tests/e2e/test_fleet_evolution_cli.py
```

Each milestone adds unit, protocol contract, migration, integration, security, and offline subprocess E2E cases for its acceptance criteria. R4 additionally needs browser rendering/accessibility, reconnect/stream, hostile-content, HTTP authentication, concurrency, and packaged-asset tests; freeze executable commands in its slice plan before implementation.

Assert real persisted states, profile bindings, events, commands, patch hashes, verifier verdicts, and recovery receipts, not only mock invocations. Installed-distribution validation uses the existing release suite with a deliberately prepared wheelhouse. Real Docker and each live provider require separate explicit opt-ins and exact receipts; neither fake tests nor missing credentials count as a pass. Do not initiate those runs from this planning document.

## Rollback and recovery

- Feature/config changes are versioned. Keep existing one-shot CLI behavior and decoding of old accepted records; add migration fixtures from the current schema before changing persistence.
- Back up user-controlled state before an upgrade; prefer tested forward repair to an assumed reversible destructive migration. Refuse an incompatible downgrade rather than silently discarding newer state. Do not automatically delete user data.
- A submitted task, approval, code apply, and organization operation retain idempotency and compare-against-current-state behavior. UI reconnect replays observations, not commands.
- Profile/template edits do not rewrite active run bindings. FleetPatch rollback changes the organization head for future work; it does not falsify historical evidence or reset user trust.
- Cancellation awaits owned worktree/container cleanup and emits receipts. Orphan/unknown-owner cases require existing explicit recovery controls; a heartbeat timeout alone cannot prove side effects did not execute.
- Browser disconnect does not cancel a task owned by the terminal; terminal exit retains cancellation semantics until a separately accepted supervisor explicitly owns detached work.
- This planning-only file can be revised or removed independently without changing application behavior; no remote rollback is required because nothing is pushed.

## Progress

- [x] (2026-09-05) Confirmed planning-only scope and the no-implementation/no-push/no-Actions boundary.
- [x] (2026-09-05) Inspected current session, runtime/model, role planning, permission/evolution, persistence, and testing contracts.
- [x] (2026-09-05) Drafted staged roadmap and observable acceptance for all four requested capabilities plus daily-use reliability/evaluation.
- [x] (2026-09-05) Validated all 14 required headings, 10 balanced fence markers, no trailing whitespace, and a change inventory containing only this new plan.
- [x] (2026-09-07) User explicitly confirmed resuming the four-capability release and module commits/GitHub merge; active release ExecPlan frozen before implementation.
- [ ] R1 session-first acceptance.
- [ ] R2a per-role profiles and budgets; R2b separate second-provider acceptance.
- [ ] R3 constrained custom-role acceptance.
- [ ] R4a read-only dashboard; R4b separately accepted controls.
- [ ] R5 reliability/repository slices and optional separately accepted supervisor.
- [ ] R6 expanding evaluations and honest release evidence for each milestone.

## Discoveries

- Observation: the public initialization gate requires real isolated evidence, even when the runtime is deterministic.
  Evidence: `application/bootstrap.py` and `tests/docker/test_conversation_journey.py`.
  Consequence: correct the R1 acceptance wording; offline fixtures are not a public fake-bootstrap bypass.
- Observation: persistent sessions already exist, but some core review/application actions remain outside them.
  Evidence: `cli/chat.py` help/dispatch and `application/conversations.py::ConversationService`.
  Consequence: R1 integrates a complete user journey; it does not rebuild persistence from zero.
- Observation: model selection is project/run-bound, while role configuration and execution semantics are different layers.
  Evidence: `domain/config.py::RuntimeRequest`, `AgentRequest`, `domain/models.py::AgentRole`, and `application/planning.py::FleetPlanner`.
  Consequence: per-role models and meaningful custom roles require admitted/pinned execution contracts, not just new YAML fields.
- Observation: current protected runtime reconfiguration and unknown-owner recovery deliberately fail closed.
  Evidence: `docs/SECURITY_MODEL.md`, config snapshot binding tests, conversation safety tests.
  Consequence: customization and a second UI must preserve these constraints with explicit new user-controlled paths.
- Observation: project progress is not yet a full multi-child dashboard feed.
  Evidence: `application/conversations.py::progress` and existing graph persistence.
  Consequence: define a consistent aggregate read model/cursor before presenting real-time child states.

## Decision Log

- Decision: resume the four-capability release under the 2026-09-07 implementation plan after explicit user confirmation.
  Rationale: the user resolved the distinction between the already merged MVP and the proposed next generation; preserve historical acceptance and CI-cost limits.
  Alternatives: leave implementation paused or incorrectly treat the old MVP merge as completion of the new request.
  Date: 2026-09-07.
- Decision: session-first is the next implementation slice; reuse the current core.
  Rationale: closes the most visible daily-use gap with existing verified services.
  Alternatives: rewrite the engine, or build a dashboard before there is a complete session journey.
  Date: 2026-09-05.
- Decision: default profile plus optional per-role overrides; existing provider first, second provider separately.
  Rationale: satisfies differentiated models without making every user choose a model for every task or widening credential boundaries at once.
  Alternatives: global-only models; all providers and automatic fallback in the first increment.
  Date: 2026-09-05.
- Decision: roles are validated templates for ephemeral responsibilities, not permanently running agents.
  Rationale: preserves adaptive minimal teams, authority boundaries, and typed delivery.
  Alternatives: fixed rosters or arbitrary prompt names with no execution semantics.
  Date: 2026-09-05.
- Decision: dashboard read-only before control, and no default background daemon.
  Rationale: observation, authorization, and process ownership are separate acceptance problems.
  Alternatives: full bidirectional dashboard and detached execution in one change.
  Date: 2026-09-05.
- Decision: target a coherent next product increment of R1 + R2a + constrained R3 + R4a, delivered as smaller runnable slices.
  Rationale: covers all four requested capabilities without adding SaaS, unrestricted plugins, or multi-provider complexity to the critical path. R4a may start after R1's shared event contracts stabilize.
  Alternatives: bundle every future integration into the release, or ship disconnected configuration screens without end-to-end behavior.
  Date: 2026-09-05.

## Outcomes

Historical planning artifact completed on 2026-09-05; implementation was not started in that turn. Document checks on that date:

- Required-heading/fence check: exit 0; 14/14 required headings, 10 balanced fence markers.
- Explicit trailing-whitespace check including the untracked plan: exit 0, no findings.
- `git diff --check`: exit 0, no findings in tracked changes. `git diff --no-index --check /dev/null .agent/plans/2026-09-05-session-first-product-roadmap.md` returned exit 1 for the new-file comparison, with no whitespace/error diagnostics; the independent check above covers the new file.
- `git status --short --branch` and `git ls-files --others --exclude-standard`: only this new plan; no source, README, workflow, or other tracked file changes.

No application tests, real-provider calls, Docker execution, installation/build, commit, push, or GitHub Actions run was performed in the original planning turn. Implementation was authorized on 2026-09-07; new results belong to the active release ExecPlan, not to these historical checks. Existing acceptance and public-release limitations are not waived.
