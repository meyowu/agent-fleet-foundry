# Product specification — Agent Fleet

## 1. Product definition

Agent Fleet is a local-first, bring-your-own-key command-line product that bootstraps and operates a versioned, reviewable agent organization around a software repository.

The user’s primary interface is one persistent Chief of Staff (CoS). The CoS understands goals, prepares bounded task specifications, selects workflows, delegates work to specialist agents, tracks evidence, and presents results. Specialists are ephemeral by default. The initial fleet contains:

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

Interactive flow:

1. Locate and validate the Git repository.
2. Inspect language/build/test signals without executing untrusted project code.
3. Ask for or accept via flags:
   - model/provider identifier;
   - credential reference;
   - sandbox backend;
   - trust mode.
4. Show the exact initial access request:
   - read repository;
   - write `.fleet/` only after review;
   - create state outside the repository;
   - create temporary worktrees and containers;
   - call the configured model provider from the control plane.
5. Generate proposed `.fleet/` files in a staging area.
6. Run a bootstrap canary in a generated disposable fixture repository, not in the user’s business code.
7. The canary performs an end-to-end minimal code change:
   - a tiny fixture contains a failing behavioral test;
   - Engineer produces a candidate fix;
   - Verifier reruns validation independently;
   - CoS reports the patch, events, and evidence.
8. Show the proposed repository configuration diff.
9. Apply `.fleet/` only after user confirmation.
10. Enter or offer the CoS chat experience.

Non-interactive form must be available for CI/testing:

```bash
fleet init . \
  --provider-model '<provider>:<model>' \
  --credential-ref 'env:PROVIDER_API_KEY' \
  --sandbox docker \
  --trust-mode balanced \
  --yes
```

`--yes` accepts only the documented bootstrap configuration patch and baseline project-local permissions. It does not grant external write, broad network, host access, or protected actions.

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

## 5.3 Run a one-shot task

Command:

```bash
fleet run "Add validation for empty project names and include a regression test."
```

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
CANCELLED
FAILED
REJECTED
```

A run must be resumable when it pauses for approval or when the process exits after a durable checkpoint.

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

## 6. Initial role definitions

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
- any verifier sandbox filesystem changes are discarded;
- no self-conversion into Engineer;
- no relaxation of acceptance criteria;
- no external side effects.

## 7. Default trust modes

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
- Automated CI tests use the fake runtime, while an opt-in manual smoke test can use a live provider.

Suggested fixture:

```text
calculator_canary/
  pyproject.toml
  src/canary_calc/core.py        # divide(a, b) lacks zero validation
  tests/test_core.py             # expects ValueError with stable message
```

The canary is successful only when the candidate behavior passes independently and the accepted artifact does not contain Verifier edits.

## 10. Functional requirements

- Durable run and approval state in SQLite.
- Append-only event history with redaction.
- Stable project identity that is not based only on an absolute path.
- Configuration snapshots attached to runs.
- Deterministic fake runtime, fake sandbox, fake secret resolver, and injectable clock/ID generator.
- Runtime capability declaration and validation.
- Bounded retries and repair loops.
- Cancellation with sandbox/worktree cleanup.
- Crash recovery for orphaned or paused resources.
- Human- and machine-readable errors with stable error codes.
- Artifact hashes and metadata.
- No live model or Docker requirement for normal unit tests.
- Clear `doctor` diagnostics for Git, Docker, configuration, provider credential references, database, and repository state.

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
2. initialize a Git repository with a provider/model reference and Docker sandbox;
3. complete the disposable bootstrap canary;
4. enter `fleet chat` and request a small code change;
5. observe CoS -> Engineer -> Verifier stages;
6. approve a narrowly scoped action once, for the run, or always for that exact project scope;
7. receive a patch, test evidence, verifier verdict, events, and artifact hashes;
8. restart the CLI and inspect or resume the run;
9. apply the candidate only after explicit approval;
10. request a change to the fleet configuration, inspect the proposed FleetPatch, and apply or reject it;
11. revoke a persistent permission rule;
12. run the complete default test suite without a real model, network, or Docker.

A security reviewer can demonstrate that:

- a malicious repository instruction cannot grant itself permission;
- a path traversal or symlink cannot escape the workspace authorization boundary;
- an “always allow npm test” rule does not authorize appended shell commands or other executables;
- worker sandboxes cannot see the provider API key;
- CoS cannot approve itself;
- protected policy cannot be changed through FleetPatch;
- Verifier filesystem changes do not enter the candidate patch;
- failed or cancelled runs leave recoverable state and clean up resources safely.
