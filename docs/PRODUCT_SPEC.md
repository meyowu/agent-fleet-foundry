# Product specification — Agent Fleet

## 1. Product definition

Agent Fleet is a local-first, bring-your-own-key Chief-of-Staff command-line product that bootstraps, operates, secures, and evolves a versioned, reviewable, project-specific agent organization around a software repository.

The positioning is intentionally narrower than “multi-agent framework”:

> A local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization.

The user’s primary interface is one persistent Chief of Staff (CoS). The CoS understands goals, prepares bounded task specifications, proposes the smallest sufficient team and workflow, delegates work to specialist agents, tracks evidence, and presents results. Specialists are ephemeral by default. CoS, Engineer, and Verifier are the initial built-in role templates, not an always-running fixed roster:

- **Chief of Staff** — persistent coordinator; scopes and delegates but does not directly execute arbitrary shell commands or silently alter policy.
- **Engineer** — per-task implementation worker; operates only in the task’s isolated candidate workspace.
- **Verifier** — per-task independent reviewer; evaluates the candidate against the original goal and acceptance criteria. Verifier changes are never included in the accepted patch.

The product’s primary output is not a transcript. It is a set of artifacts:

- task specification;
- implementation plan;
- candidate patch or commit;
- focused and full test evidence;
- verifier verdict;
- risk and limitation report;
- cost/usage report when available;
- proposed fleet configuration patch when the user requests organizational changes.

## 2. Product thesis

The useful abstraction is an **agent organization runtime**, not a free-form agent swarm.

The system must make this interaction possible:

```text
User: Fix the duplicate refresh requests and prove that the regression is covered.

CoS:
  1. scopes the task;
  2. delegates to an Engineer in an isolated worktree;
  3. obtains code and test evidence;
  4. delegates independent verification;
  5. allows at most a bounded repair loop;
  6. presents the patch and evidence;
  7. waits for the user before applying it to the original checkout or performing external writes.
```

Internally the product may use multiple models and agents. Externally it should feel like a reliable senior technical chief of staff, not a chat room the user must manage.

### 2.1 Differentiated product contract

The product has differentiated value only when the following six properties are real, observable, and enforced at the stated boundary. A prompt or model claim does not count as implementation.

1. **Repository-aware bootstrap.** `fleet init .` identifies repository and subproject boundaries, ecosystems, build/package systems, and exact candidate test/lint/build commands without executing untrusted project code. It produces a provenance-bearing `RepositoryProfile`, factual `ProjectKnowledge`, a reviewable FleetSpec proposal, an explicit sandbox capability summary, and a disposable canary report containing the patch and evidence.
2. **Adaptive Fleet.** CoS proposes a typed `FleetPlan` for the smallest sufficient topology. Valid shapes include direct handling, one Engineer, Engineer plus independent Verifier, multiple parallel Engineers, and Researcher plus Architect plus Engineer plus Verifier. The control plane validates configured roles, dependencies, budgets, concurrency, workspace ownership, and required assurance before scheduling. Roles are created for the task and do not gain authority merely from their names.
3. **Independent permission control plane.** Every runtime-requested action passes through ToolGateway and an injected PermissionBroker, with exactly `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`. The user can ultimately allow once, allow for a run, persist an exact project scope, revoke it, and inspect why a rule matched. No harness-native tool may bypass this boundary.
4. **Independent sandbox abstraction.** The control plane selects a provider only when its declared capabilities satisfy the task requirements. Docker is the first recommended real provider; Modal/hosted providers are later adapters; local host execution is explicitly named unsafe. Harnesses do not receive host paths or sandbox handles and do not choose their own execution boundary.
5. **Evidence-first delivery.** A structured `EvidenceBundle` binds exact content-addressed ConfigSnapshot and TaskSpec artifacts, changed files, canonical patch, commands, test/build results, verifier identity and verdict, risks, and proof gaps to the task, plan, configuration, and base revision. A deterministic `CompletionGate` computes assurance from authoritative control-plane records, and status output makes the reason codes and proof gaps reviewable. Simulated output and Agent assertions cannot satisfy requirements for executed or independently verified proof.
6. **Versioned Fleet evolution.** A conversational organization change produces a `FleetPatch` proposal, never a silent edit. The user can inspect semantic and textual diffs, apply an exact validated change, and roll it back through a new audited operation. FleetPatch cannot alter trust, secrets, audit history, hard denies, approval ownership, or sandbox hard limits.

The implementation status is deliberately explicit:

| Differentiator | Accepted implementation boundary | Remaining product milestone |
|---|---|---|
| Repository-aware bootstrap | Static profile, knowledge artifacts, detected-command proposal, read-only diff preview, disposable deterministic canary through the ordinary Docker workflow, validated BootstrapReport, cleanup proof, and `.fleet/` publication only after success | Broader safe project-command discovery/execution and non-local sandbox support |
| Adaptive Fleet | Whole Phase 5 accepted: scoped concurrent children, read-only specialist dependencies, exact approval/ownership state, deterministic joins, fresh parent verification and persistent bounded chat; complete checkpoint `a46b688` is pushed | Preserve current guarantees through the Phase 6 candidate and final release gates |
| Permission control plane | Current user/project/workflow/role/task/sandbox intersection; exact once/run/project trust; explain/revoke/reset; durable single-winner dispatch and identity-bound approval resume; no harness-tool bypass | Preserve these ceilings through Phase 5 chat/adaptive execution and Phase 6 configuration evolution |
| Sandbox abstraction | Exact fail-closed fake/Docker/local-unsafe dispatch; Docker pins a local daemon and immutable image, inspects one-shot containers, enforces network/resource boundaries, and recovers exact resources | Modal/hosted providers, approved network modes, and broader platform evidence |
| Evidence-first delivery | Exact ConfigSnapshot/TaskSpec/FleetPlan/patch/command/cleanup/verdict/BootstrapReport bindings; accepted M1 criterion mapping and M2 joined graph/descendant-cleanup provenance; only fresh Docker verifier evidence can verify | Preserve exact evidence and bounded context through chat and configuration evolution |
| Versioned evolution | Phase 6 locally accepted: bounded CoS proposal, semantic/text diff, explicit native whole-tree apply, durable admission, current-head audited inverse rollback and recovery; complete offline/native/real-Docker evidence | Linux platform proof and final release remain open |

Phases4–6 were locally accepted on2026-09-05. Phase5 is pushed through `a46b688`; Phase6 passed1973 default tests with15 explicit skips and fourteen separately enabled real-Docker cases, with no outstanding managed resources. E6 records exact freezes, failed attempts, repair, metadata6 and checkpoint refresh. Phase7, fresh-user/Linux proof, final GitHub delivery and live-provider/license release gates remain open. No live model-provider acceptance was run. CLI and documentation must label FakeSandbox as simulated, local-unsafe as non-isolating, Docker's local trusted-computing-base limits and unaccepted/platform-dependent behavior directly even when the selected model runtime is real.

## 3. Target users

Initial target users:

- individual software engineers working in an existing Git repository;
- open-source maintainers who want reproducible agent workflows;
- technical users willing to provide a model API credential and install Docker;
- teams interested in versioning their agent roles, workflows, and project knowledge in Git while keeping trust grants and secrets outside the repository.

Initial operating assumptions:

- one local user;
- one active repository per CLI invocation;
- one foreground control-plane process;
- no hosted account, billing system, or multi-tenant service;
- Git-backed repositories for code-change workflows;
- Docker available for the recommended execution mode.

## 4. Product principles

### 4.1 One primary human interface

Users normally talk to CoS. They should not have to choose an Engineer model, manually route every subtask, or read agent-to-agent chatter.

### 4.2 Structured delegation

Agents exchange typed task envelopes, results, artifacts, and verdicts. Unbounded peer chat is not the orchestration protocol.

### 4.3 System-owned control

The deterministic control plane owns workflow state, retry limits, budgets, permissions, approval gates, sandbox selection, secrets, and audit logs. Models may recommend but do not control these mechanisms.

### 4.4 Evidence before claims

A completed code task includes repeatable evidence. “The change looks correct” is not sufficient. When full proof is impossible, the system must describe the proof gap and provide the strongest available artifact.

### 4.5 Local-first and BYOK

Repository contents, state, and artifacts remain local unless the user explicitly configures an external service or remote sandbox. The user supplies model access through a secret reference, not a plaintext project setting.

### 4.6 Safe autonomy

Routine work inside an isolated task boundary can be automatic. Crossing into the host, original checkout, network, remote repository, cloud account, messaging system, secrets, or production environment requires policy evaluation and often human approval.

### 4.7 Versioned organization

Role instructions, workflows, project verification commands, and requested capabilities may be versioned in `.fleet/`. Actual user grants, protected policy, and secrets must not be committed to the repository.

## 5. Core user journeys

## 5.1 Bootstrap a repository

Command:

```bash
fleet init .
```

Target interactive flow:

1. Locate and validate the Git repository.
2. Build a deterministic `RepositoryProfile` by inspecting bounded language, manifest, lockfile, build, test, lint, CI, and repository-boundary signals without following escaping symlinks or executing untrusted project code.
3. Show each detected command with its exact executable/argv/cwd, source file, confidence, and ambiguity. Detection is not permission to execute it.
4. Generate factual `ProjectKnowledge` from observed signals, with provenance and unknowns rather than invented architecture claims.
5. Ask for or accept via flags:
   - model/provider identifier;
   - credential reference;
   - sandbox backend;
   - trust mode.
6. Show the exact initial access request:
   - read repository;
   - write `.fleet/` only after review;
   - create state outside the repository;
   - create temporary worktrees and containers;
   - call the configured model provider from the control plane.
7. Generate repository-specific proposed `.fleet/` files in a staging area and show the exact diff.
8. Run a bootstrap canary in a generated disposable fixture repository, not in the user’s business code.
9. The canary performs an end-to-end minimal code change:
   - a tiny fixture contains a failing behavioral test;
   - Engineer produces a candidate fix;
   - Verifier reruns validation independently;
   - CoS reports the patch, events, and evidence.
10. Present a `BootstrapReport` binding the profile, Project Knowledge, FleetSpec proposal, sandbox capabilities, canary FleetPlan, patch, command evidence, verifier verdict, risks, and proof gaps.
11. Apply `.fleet/` only after user confirmation.
12. Enter or offer the CoS chat experience.

The current Phase 3 non-interactive real-runtime/isolated-worker form is:

```bash
fleet init . \
  --runtime pydantic-ai \
  --provider-model '<provider>:<model>' \
  --credential-ref 'env:PROVIDER_API_KEY' \
  --sandbox docker \
  --docker-image '<preloaded-local-image-ref>' \
  --yes
```

`--yes` accepts only the documented bootstrap configuration patch and baseline project-local permissions. It does not grant external write, broad network, host access, or protected actions.

For the implemented adapter, `<provider>` is exactly `openai` or `openai-chat`; there is no implicit fallback. Preview validates the full selection and proposal without reading the environment variable, writing Fleet/repository state, or contacting a provider. Init resolves the explicit reference before writes but does not invoke a model. The `env:NAME` reference is persisted only in Fleet-owned state; `.fleet/` stores the selected runtime and opaque provider/model ID, never the reference or raw value. `fleet doctor` performs inspect-only credential readiness with no provider call. `fleet run` revalidates the registered selection, resolves the credential, and may then send the bounded role prompt/context over HTTPS from the trusted control plane.

Initialization does not overwrite a differing generated `.fleet/` tree. Before any admitted Run establishes an organization head, identical generated bytes may be reused and a credential-reference-only change does not alter repository files. Phase 6 additionally rejects every headed reinitialization, even after `.fleet/` is moved aside or when only the recorded reference changes. Supported edits use reviewed FleetPatch; protected runtime/provider/reference/sandbox changes require a separate project registration with prior state preserved. Rotating the actual key under the same recorded reference remains possible without rewriting registration.

Steps 8–10 are implemented for a Docker-selected init. The target remains untouched through preview and canary execution. Confirmed init uses a deterministic fake runtime with the real Docker provider to produce a nonempty canary patch, Engineer command evidence, a fresh non-mutating Verifier command, cleanup receipts, CompletionDecision, and hash-valid `BootstrapReport`; only then may `.fleet/` be published. Fake or local-unsafe selection cannot satisfy this publication gate. No live provider call or arbitrary target-repository code is required by the bootstrap canary.

### Dirty repository behavior

- Reading and generating a proposed `.fleet/` configuration is allowed in a dirty repository.
- A real code-change run must not overwrite or conflate unrelated local edits.
- The first implementation may require a clean working tree for code-change execution and return a clear remedy.
- Never silently stash, reset, clean, or discard user changes.

## 5.2 Talk to the Chief of Staff

Command:

```bash
fleet chat
```

The first UI may be a robust line-oriented REPL rather than a full-screen TUI. Required behaviors:

- preserve the active conversation/thread identifier;
- accept a natural-language goal;
- show concise stage transitions and approval requests;
- support cancellation;
- support commands such as `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, and `/exit`;
- persist enough state to resume after process restart;
- never print a secret or raw credential;
- offer `--json` or a separate noninteractive command for automation.

Accepted Phase 5 provides these behaviors through `fleet chat [path]`, exact `--conversation`/`--new` selection and `--message` with optional submission key/JSON. Atomic project-bound turn/Run registration precedes model effects; public resume shares non-expiring execution ownership. One active turn, bounded summaries/references, responsive POSIX pipe/terminal controls, exact approvals and retained cancellation/recovery are implemented. The persistent-chat ExecPlan and E5.3 record the full behavioral gates, independent offline review and public bootstrap/Docker/approval/restart/explicit-apply journey. This does not establish live-provider, fresh-user release or final GitHub delivery.

## 5.3 Run a one-shot task

Command:

```bash
fleet run "Add validation for empty project names and include a regression test."
```

Before execution, CoS proposes a typed FleetPlan. The deterministic planner accepts only configured roles and supported topology, then chooses or validates the smallest sufficient strategy:

- `direct` for an answer or control-plane-only result with no worker side effect;
- `single_engineer` for a bounded implementation whose requested assurance does not claim independent verification;
- `engineer_verifier` for the default verified code-change path;
- `parallel_engineers` for independent shards with an explicit join/merge policy;
- a specialist DAG such as Researcher -> Architect -> Engineer -> Verifier when the repository and task justify it.

The plan records why each role is needed. Unplanned roles are not instantiated, and a role name never grants tools or permission. Accepted Phase 5 M2 executes all five strategies through fake and offline-tested PydanticAI adapters. Parallel children receive disjoint scopes and shared cumulative budgets, then join in stable node-ID order; specialists return bounded read-only `SpecialistReport` dependencies. The parent Verifier checks the original task and combined patch. Legacy advanced plans without complete subgoal/criterion mappings remain readable but cannot execute. The deterministic control plane constructs and validates every plan.

For a PydanticAI project, run-time `--runtime`, `--provider-model`, and `--credential-ref` flags may be omitted to use the reviewed Fleet-owned registration. If supplied, they must match it exactly. `--fake-scenario` is rejected for the real runtime. Provider HTTPS remains a trusted-control-plane network boundary distinct from worker networking. Every model-visible action crosses the role-bound tool catalog, ToolGateway, and PermissionBroker. Phase 3 Engineer tools are bounded list/read/search/diff/write/edit/delete plus exact reviewed commands; Verifier receives only list/read/search/diff and exact reviewed commands. Descriptor-relative workspace operations and selected sandbox dispatch remain control-plane-owned; fake commands are simulated, local-unsafe is explicitly non-isolating, and only Docker can produce isolated evidence.

Expected stages:

```text
INTAKE
SCOPING
PLANNING
IMPLEMENTING
VERIFYING
REPAIRING (optional, bounded)
READY_FOR_REVIEW
APPLYING (only after approval)
COMPLETED
```

A run may instead become:

```text
PAUSED_FOR_APPROVAL
WAITING_FOR_CHILDREN
CANCELLED
FAILED
REJECTED
```

A run must be resumable at supported durable approval checkpoints. An adaptive parent exposes exact child approvals through `WAITING_FOR_CHILDREN`; public child resume/apply/cancel/recover are denied. Unknown dispatched ownership never permits automatic replay: operator-confirmed stopped-owner recovery abandons it and cleans exact descendants. Accepted Phase 5 chat retains bounded summaries, exact turn/Run links and frozen context across restart; public resume enforces the same conversation ownership. It does not restore raw provider history.

## 5.4 Review and apply a candidate patch

Before application, present:

- base revision;
- files changed;
- patch hash;
- test commands and exit results;
- verifier verdict and confidence/rationale;
- unresolved risks or proof gaps;
- model usage/cost when the provider exposes it;
- any permission grants consumed.

Commands:

```bash
fleet status <run-id>
fleet artifacts <run-id>
fleet patch show <run-id>
fleet patch apply <run-id>
fleet run abandon <run-id>
```

Application rules:

- Default behavior is review-only; no automatic merge or push.
- Reconfirm that the target repository still matches the recorded base and cleanliness assumptions.
- Refuse unsafe application when the original checkout has diverged; provide a recovery path rather than overwriting.
- Record an application event and resulting revision.
- Remote push and pull-request creation are separate future/optional capabilities and require approval.

## 5.5 Approve a bounded permission request

When an action is not already allowed, show:

```text
Permission request PERM-142
Agent: engineer
Run: RUN-104
Action: network.connect
Resource: registry.npmjs.org:443
Reason: install dependencies declared in the lockfile
Sandbox: docker task sandbox
Requested duration: 5 minutes
Requested uses: 1
Risk: dependency installation may execute package hooks

[1] Deny
[2] Allow once
[3] Allow for this run
[4] Always allow this exact scope for this project
```

Commands:

```bash
fleet approve PERM-142 --once
fleet approve PERM-142 --run
fleet approve PERM-142 --always --scope project
fleet deny PERM-142 --reason "Use the existing lockfile cache instead"
fleet permissions list
fleet permissions explain RULE-17
fleet permissions revoke RULE-17
fleet permissions reset --project .
```

“Always” must preserve the exact canonical action, resource, principal role, project identity, workflow/stage conditions, sandbox requirement, and relevant command/network constraints. It is never a wildcard over all actions.

## 5.6 Update the fleet through conversation

Example user instruction:

> For backend changes, always run integration tests, and never let the Verifier modify accepted code.

CoS returns a proposed `FleetPatch`, not a silent mutation:

```text
Fleet change FC-012
+ add backend-integration-verification skill
~ update code-change workflow verification stage
~ assert verifier output is non-authoritative for patch content

Run `fleet fleet-patch show FC-012` to inspect.
Run `fleet fleet-patch apply FC-012` to accept.
```

Requirements:

- patch can modify only allowed repository-owned `.fleet/` configuration and role/skill files;
- validate the resulting configuration before presentation;
- show semantic and textual diff;
- require user approval to apply;
- record before/after hashes and support rollback;
- never modify protected user trust policy, secret references, audit records, sandbox hard limits, or approval ownership through FleetPatch.

## 6. Built-in role templates

These definitions are reusable responsibility templates. They do not require every run to create all three instances, do not prohibit repository-defined specialist roles, and do not confer authority outside the effective task, workflow, permission, and sandbox constraints. CoS proposes a team; the deterministic FleetPlan validator decides whether that proposal is executable.

## 6.1 Chief of Staff

Responsibilities:

- clarify and restate the objective when needed;
- create a bounded `TaskSpec`;
- select the declared workflow;
- delegate to allowed roles;
- enforce budget, iteration, and approval limits through the control plane;
- aggregate evidence and communicate status;
- propose FleetPatch changes when asked.

Default restrictions:

- no arbitrary shell;
- no direct write to candidate source code;
- no access to raw secrets;
- no self-approval;
- no direct external write;
- no modification of protected policy.

## 6.2 Engineer

Responsibilities:

- inspect task-relevant code using bounded tools;
- implement the smallest correct change;
- add or update focused tests;
- run allowed verification commands;
- return a structured `ImplementationReport` and candidate artifact.

Default restrictions:

- writes only to the task candidate workspace and only within allowed paths;
- no direct write to original checkout;
- no remote push;
- no host home or unrelated repository access;
- no network unless allowed or approved;
- no secret access;
- bounded command count, runtime, model usage, and repair iterations.

## 6.3 Verifier

Responsibilities:

- start from the original user goal and `TaskSpec`, not only Engineer’s summary;
- inspect the candidate patch and relevant code;
- rerun focused checks independently;
- test edge cases and regressions within budget;
- return `PASS`, `FAIL`, or `INCONCLUSIVE` with evidence and required repairs.

Default restrictions:

- no ability to change the accepted candidate artifact;
- verifier write intents are denied; any future permitted scratch changes remain disposable;
- no self-conversion into Engineer;
- no relaxation of acceptance criteria;
- no external side effects.

## 7. Default trust modes

The lists below describe the broader product target. **Accepted Phase 4 behavior is narrower:** Safe asks for supported exact reviewed commands without a matching grant/rule; Balanced and Autonomous Sandbox currently share the same supported reviewed-command ceiling. All modes enforce reviewed paths and role/workflow/request/task/sandbox intersections. Unknown executables, arbitrary shell, package-registry/network expansion and external writes are not made executable by an approval. Isolated workers support only `network=none`; local-unsafe remains separately confirmed and non-isolating. See `CONFIG_AND_SCHEMAS.md` for implemented choices, lifetimes and CLI.

## 7.1 Safe

- repository read: allow;
- candidate-workspace write: allow;
- known project commands: ask on first use unless explicitly approved during bootstrap;
- unknown commands: ask;
- network: ask;
- external writes: ask every time;
- protected actions: deny.

## 7.2 Balanced — default

- repository read: allow;
- candidate-workspace write: allow;
- detected test/lint/build commands inside Docker sandbox: allow;
- package registry access: ask, with project-scoped exact always-allow option;
- unknown commands: ask;
- original checkout write/application: explicit approval;
- remote writes/deployments/secrets: ask or deny according to protected policy.

## 7.3 Autonomous Sandbox

- ordinary development commands inside the selected isolated sandbox: allow subject to resource limits;
- candidate-workspace writes: allow;
- declared network destinations only when technically enforced and approved;
- all host, original checkout, secret, remote write, production, and protected actions remain gated.

Autonomous Sandbox is not full host access.

## 8. CLI command surface

The target command hierarchy is:

```text
fleet init [PATH]
fleet doctor
fleet chat [PATH]
fleet run <GOAL>
fleet status [RUN_ID]
fleet logs <RUN_ID> [--follow]
fleet artifacts <RUN_ID>
fleet resume <RUN_ID>
fleet cancel <RUN_ID>
fleet approve <REQUEST_ID> (--once | --run | --always --scope project)
fleet deny <REQUEST_ID>
fleet permissions list|explain|revoke|reset
fleet patch show|apply|discard <RUN_ID>
fleet fleet-patch list|show|apply|rollback
fleet config validate
fleet version
```

Do not expose a command before it has real behavior and tests. During phased implementation, it is acceptable for the command tree to be smaller than this target.

All data-producing commands should eventually support stable JSON output. Human-readable output may evolve, but JSON schemas require versioning.

## 9. Bootstrap canary requirements

The canary verifies the full product path without risking the user repository.

- Generate a temporary Git fixture in the Fleet state directory.
- The fixture must be small, deterministic, and language/runtime-compatible with the shipped runner image.
- Include a failing behavioral test and a narrow implementation defect.
- Ask the configured Engineer to repair it.
- Run the change in a candidate worktree and sandbox.
- Ask a separate Verifier context to judge it.
- Persist events and artifacts.
- Delete or retain the fixture according to a documented cleanup policy.
- Show the user exactly which parts used a real model versus deterministic system logic.
- Automated CI tests use the fake runtime and PydanticAI TestModel/FunctionModel facilities with live requests and sockets denied; an opt-in manual smoke test may use a live provider only with an explicitly supplied disposable credential.

Suggested fixture:

```text
calculator_canary/
  pyproject.toml
  src/canary_calc/core.py        # divide(a, b) lacks zero validation
  tests/test_core.py             # expects ValueError with stable message
```

The canary is successful only when the candidate behavior passes independently and the accepted artifact does not contain Verifier edits.

## 10. Functional requirements

- Deterministic, non-executing repository profiling with provenance, confidence, ambiguity, and canonical hashes.
- Repository-specific FleetSpec and Project Knowledge proposals derived only from observed evidence.
- A persisted, validated FleetPlan that creates only the roles required for the selected strategy.
- Runtime inputs contain logical identifiers and bounded artifacts, never host paths or sandbox handles.
- An independent PermissionBroker is the sole authorization decision point for runtime-requested actions.
- Sandbox requirements are matched against explicit provider capabilities; unsupported requirements fail closed.
- An authoritative EvidenceBundle and CompletionGate distinguish operational completion from verified completion.
- Durable run and approval state in SQLite.
- Append-only event history with redaction.
- Stable project identity that is not based only on an absolute path.
- Configuration snapshots attached to runs.
- Deterministic fake runtime/sandbox, environment-backed strict secret resolver, and injectable clock/ID generator.
- Runtime capability declaration and validation.
- Bounded retries and repair loops.
- Cancellation with sandbox/worktree cleanup.
- Crash recovery for orphaned or paused resources.
- Human- and machine-readable errors with stable error codes.
- Artifact hashes and metadata.
- No live model or Docker requirement for normal unit tests.
- Clear `doctor` diagnostics for Git, Docker, configuration, provider credential references, database, and repository state. A successfully emitted report may have exit status zero while `healthy=false`; callers use `healthy` and required check status for readiness. Doctor never resolves/returns a credential or contacts a model provider.

## 11. Non-goals for the first public MVP

- hosted multi-tenant service;
- mobile or web UI;
- arbitrary background daemon;
- production deployment automation;
- browser/computer-use automation;
- broad cloud administration;
- unrestricted MCP marketplace;
- cross-machine scheduling;
- dozens of permanent agents;
- models negotiating permissions among themselves;
- fully interchangeable arbitrary harness implementations before a second adapter proves the abstraction;
- fine-grained domain egress claims without an enforcing proxy or equivalent mechanism;
- automatic mutation of user trust policy;
- automatic push or merge;
- support for non-Git code-change repositories.

## 12. MVP success criteria

A new user can:

1. install the package and run `fleet doctor`;
2. initialize a Git repository and inspect the evidence-backed repository profile, detected commands, Project Knowledge, and proposed configuration;
3. initialize with a provider/model reference and Docker sandbox, then complete the disposable bootstrap canary;
4. enter `fleet chat` and request a small code change;
5. inspect the selected FleetPlan and observe that only its required role instances run;
6. approve a narrowly scoped action once, for the run, or always for that exact project scope;
7. receive a patch, test evidence, verifier verdict, events, and artifact hashes;
8. restart the CLI and inspect or resume the run;
9. apply the candidate only after explicit approval;
10. request a change to the fleet configuration, inspect the proposed FleetPatch, and apply or reject it;
11. revoke a persistent permission rule;
12. run the complete default test suite without a real model, network, or Docker.

For every run, the user can also distinguish `COMPLETED` as lifecycle state from `verified_complete` as an evidence-derived assurance decision. A run with simulated command output or unresolved required evidence never reports verified completion.

A security reviewer can demonstrate that:

- a malicious repository instruction cannot grant itself permission;
- a path traversal or symlink cannot escape the workspace authorization boundary;
- an “always allow npm test” rule does not authorize appended shell commands or other executables;
- worker sandboxes cannot see the provider API key;
- CoS cannot approve itself;
- protected policy cannot be changed through FleetPatch;
- Verifier filesystem changes do not enter the candidate patch;
- failed or cancelled runs leave recoverable state and clean up resources safely.
