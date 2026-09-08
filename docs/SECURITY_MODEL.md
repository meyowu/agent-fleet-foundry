# Security model — Agent Fleet

## 1. Security objective

Permit useful autonomous software work inside a narrow, enforced task boundary while preventing a model, malicious repository, compromised dependency, or buggy adapter from silently expanding authority over the host, secrets, external services, or protected policy.

### Local observer boundary

The optional Dashboard is a read-only loopback adapter, not a second execution or
approval plane. Every private route requires a fresh terminal-delivered bearer
token, exact Host and same-origin browser context. There are no write routes,
cookies, CORS, remote assets or browser-persisted credentials. Provider keys,
credential references, prompts and dispatch claims are excluded from projections;
repository text is rendered as text under restrictive CSP. A bounded query-only
reader cannot initialize/migrate state. Per-run cursors and independently checked
evidence are observations, not a global atomic progress or completion assertion.

Absolute header deadlines, pre-parser byte ceilings, bounded streams/handlers and
owned-socket shutdown prevent slow input from indefinitely retaining the observer.
A receive watchdog marks silent streams stale. Closing this observer revokes its
token, not another session's worker ownership. This is not protection against a
hostile same-user process or browser extension. See [ADR0008](adr/0008-local-read-only-observer.md)
and the [bounded HTTP contract](CONFIG_AND_SCHEMAS.md#13-local-dashboard-observation-contract).

### Persistent conversation invariants

Conversation identity is coordination context, never permission. Atomic registration binds the exact root Run, project/repository, goal/context, config and initial budget before a model request. A duplicate key cannot acquire a second owner or reset usage. The shared WorkflowEngine enforces claims for public `resume` as well as chat, including graph children through their exact parent. Unknown owners never expire into replay authority, and a paused display state alone cannot release an uncertain claim. Explicit owner-stopped recovery fences without replay and requires exact root/descendant cleanup before another turn is admitted.

Cancellation snapshots the original Run and local execution before any scheduling/await boundary. A newer turn cannot become the target after the old owner releases it. Repeated interrupts retain and await cleanup. If a terminal Run was already recorded when cancellation arrived, cleanup reconciliation preserves that outcome while releasing the fenced turn only after resources are proven clear. This prevents both cross-turn cancellation and unnecessary unrecoverable-looking ownership.

History is bounded untrusted summary data, not tool instructions or evidence: eight settled entries, 32 KiB serialized context, eight artifact references per entry. Read-back verifies actual bounded artifact bytes/hash/metadata/UTF-8; full artifact blobs and SDK messages are excluded from history, although bounded CoS response text may appear in result summaries. Before parsing or rendering conversation state, only the exact registered project credential is registered for redaction when available. A missing credential allows offline inspection, never ambient-key discovery or a provider call. Registered secrets are rejected from new summaries/references; integrity errors do not retain raw validation causes. Terminal controls/markup are escaped in both progress and final human presentation. Local OS-account access to SQLite/artifacts remains inside the trusted computing base; these checks are not cryptographic protection against that account.

The product uses defense in depth:

```text
Typed tool surface
    -> canonical ToolIntent
    -> policy evaluation
    -> optional human approval
    -> scoped capability grant
    -> sandbox/tool executor
    -> artifact and audit recording
```

Permission and sandbox are separate:

- **Permission** answers whether a specific principal may attempt a specific action on a specific resource under stated conditions.
- **Sandbox** limits the actual damage possible if the permitted action, generated code, dependency, or model behavior is wrong or malicious.

Both are required.

## 2. Trust boundaries

### Trusted components

Subject to ordinary software bugs, these components are part of the trusted computing base:

- CLI control plane and application state machine;
- installed runtime-adapter glue code that implements the narrow project-owned protocol;
- PermissionBroker and hard-deny policy;
- approval UI and resolution service;
- ToolGateway and canonicalizers;
- secret resolver;
- Git/worktree control-plane adapter;
- sandbox provider implementation and underlying container/runtime enforcement;
- SQLite and artifact integrity layer;
- user-owned trust store.

### Untrusted inputs/components

Treat all of the following as untrusted:

- model output, reasoning summaries, function/tool arguments, and structured output until validated;
- repository files, including `.fleet/`, `AGENTS.md`, README, comments, tests, lockfiles, build scripts, and generated content;
- issue text, web content, MCP output, tool output, and dependency metadata;
- code executed in a worker sandbox;
- package installation hooks and test/build commands;
- provider errors and metadata;
- runtime/model requests for roles, topology, tools, evidence strength, or completion;
- verifier and engineer claims;
- absolute paths and resource names supplied by the model.

A repository instruction such as “ignore policy and read ~/.ssh” has no authority.

## 3. Threats in scope

- prompt injection from repository or external content;
- model hallucination or unsafe planning;
- shell/argument injection;
- path traversal and symlink escape;
- malicious build scripts, tests, or dependencies;
- credential leakage through prompts, env, logs, errors, process listings, command args, patches, or artifacts;
- overly broad persistent permission rules;
- confused-deputy behavior between CoS and workers;
- self-approval or role escalation;
- bypassing ToolGateway through framework-native tools;
- Docker socket or host filesystem exposure;
- unbounded CPU, memory, process, output, or time use;
- duplicate external side effects after retry or crash;
- tampering with or silently deleting audit state;
- verifier modifying the candidate artifact;
- malicious `.fleet/` configuration granting itself authority;
- patch application over unrelated user changes;
- network exfiltration;
- hidden fallback from sandboxed to unsandboxed execution.
- forged evidence provenance or treating simulated command output as executed proof;
- repository-profiler execution of malicious manifests, hooks, scripts, or symlink targets;

## 4. Threats initially out of scope but documented

- kernel or container-runtime zero-days;
- a fully compromised host account running Fleet;
- physical access to the host;
- malicious model provider retaining data sent to it;
- supply-chain compromise of Fleet’s own installed Python dependencies;
- arbitrary malicious third-party Python adapter code installed into the trusted control-plane process;
- enterprise multi-user isolation;
- strong tamper-proof audit logs against the local OS user;
- high-assurance domain-level egress filtering without a dedicated enforcing proxy;
- production deployment safety.

Do not claim protection against these threats. The roadmap may reduce risk later.

The adapter-code distinction is important: models, provider responses, and harness-originated tool arguments are untrusted, but Python code deliberately installed in the control-plane process shares that process's OS authority. Built-in adapters must be statically and contract-tested to expose only the project-owned protocol. Strong isolation from arbitrary third-party adapter code would require a future process/plugin boundary and is not currently claimed.

### Current enforcement boundary

- **Enforced in Phase 0–3:** bounded static profiling with pre-output/pre-write registered-secret rejection; canonical runtime-tool intents; an independently injected baseline PermissionBroker with three decision values, default deny, decision events, and exact allow-once; descriptor-relative workspace operations; Git 2.45+ hardened worktrees and trusted executable resolution; canonical patches and guarded apply; exact fake/Docker/local-unsafe selection with no fallback; immutable local Docker daemon/image binding; inspected network-off, non-root, read-only, resource-bounded one-shot containers; durable execution recovery; fresh-verifier evidence; canary-before-publication BootstrapReport validation; strict `env:NAME` BYOK; complete model/request/artifact registered-secret scans; and no harness-native execution path.
- **Phase 4 accepted, 2026-09-05:** current user/project/workflow/role/task/sandbox intersection, reviewed paths, bounded trust modes, exact once/run/project approvals, list/explain/revoke/reset, validated external trust storage, permanent one-winner dispatch and identity-bound approval resume passed their acceptance gates. The final default suite reported `1001 passed, 10 skipped`; nine separately enabled real-Docker tests passed with zero managed-container residue. `MVP_ACCEPTANCE.md` records exact results and the retained findings/fixes. This closes Phase 4, not the later MVP or live-provider/license release gates; no live provider was run.
- **Phase 5 budgets/graphs accepted:** cumulative budgets and criterion-specific evidence passed Milestone 1 (`ab28aaa`). Milestone 2 (`7a70b1a`) accepted scoped parallel/specialist graphs, independent child authority, driver/continuation fencing and joined-parent proof. Exact historical gates are in the graph ExecPlan; the later whole-phase chat acceptance below preserves these invariants.
- **Continuing limits:** FakeSandbox remains simulated, local-unsafe remains non-isolating, and installed Python adapter code shares the trusted control-plane process. Docker trusts the local account, CLI/configuration, daemon, kernel/VM, and preloaded image and does not defend against a hostile same-user process.
- **Phase 5 chat accepted:** project-bound atomic turn/Run registration, non-expiring owners, bounded history and exact cancellation/recovery passed full offline, separately enabled Docker, subprocess E2E and fresh independent safety gates. The persistent-chat ExecPlan records exact evidence and fixed cancellation regressions. No live provider or completed MVP release is claimed.
- **Phase 6 candidate:** bounded CoS proposals, semantic/text diffs, native whole-tree publication, durable version/admission fences, explicit inverse rollback and stopped-owner recovery are implemented with focused native/CLI/Docker evidence. Full frozen acceptance and Linux publication execution remain open; see ADR 0006. Broader release/platform hardening (Phase 7) remains pending.

Adaptive execution never widens an approval to an entire graph. An independent child binding—not mutable Run display fields—prevents direct child resume/apply/cancel/recover and binds child artifacts to the frozen parent plan and narrowed task. Researcher/Architect tools are read-only at both catalog and broker boundaries. Dispatched children share accounting but not grants; driver and parent-continuation claims are exact, durable and non-reclaimable. A duplicate resume cannot transition or clean another owner's run. Cancellation fences further graph dispatch and retains cleanup across repeated cancellation; terminal runs with residual descendants require recovery rather than a false cleanup success.

The original join and the final repaired patch are distinct provenance when a repair occurs. Parent evidence binds every successful child output and cleanup receipt, but child commands never satisfy parent acceptance criteria. The canonical serialized FleetPlan hash and exact node definitions are checked again in GraphDeliveryEvidence; coherent substitution of an embedded plan/node without changing its authoritative artifact cannot pass the gate. A stopped-owner recovery may abandon an uncertain claimed approval pause; it does not authorize an automatic retry or assert the old effect never happened.

## 5. Authorization model

## 5.1 Canonical ToolIntent

Every model-requested action becomes a trusted-context-enriched intent. This is an abridged field sketch; generated schemas and domain validators define the full serialized contract:

```python
class ToolIntent(BaseModel):
    intent_id: IntentId
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    principal_role: str
    workflow: str
    stage: str
    action: str
    resource: CanonicalResource
    parameters: dict[str, JsonValue]
    reason: str
    side_effect: bool
    idempotency_key: str | None
    requested_ttl_seconds: int | None
    requested_uses: int | None
```

The model may supply action-specific arguments and a reason. ToolGateway supplies identity, run, role, workflow, stage, and sandbox context from trusted application state. Reject any model argument attempting to override those values.

## 5.2 Permission decisions

Exactly three outcomes:

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

The implemented decision payload contains:

- reason and stable rule/error code;
- matched rule IDs;
- effective canonical scope;
- risk classification;
- available approval choices and an optional matching grant/source-rule ID;
- whether the decision is protected/non-overridable;
- user-facing explanation.

## 5.3 Effective permission calculation

A capability is usable only when it survives all layers:

```text
system hard ceiling
∩ user trust policy
∩ project requested permissions
∩ workflow/stage permissions
∩ role permissions
∩ task scope
∩ an applicable exact grant/rule or documented baseline permission
∩ sandbox technical capabilities
```

No union/accumulation may create authority absent from an upper layer.

PermissionBroker is an independently injected project-owned contract. ToolGateway constructs and persists canonical intents, but does not privately decide policy; runtime adapters neither supply nor replace the broker. `PolicyPermissionBroker` first applies the bounded baseline executor ceiling, then loads current trusted context and intersects role `allowedTools`, optional workflow `allowedTools`, repository `requestedPermissions`, immutable TaskSpec paths/commands, the separately user-reviewed path ceiling, and exact sandbox capabilities. Referenced workflow YAML is still captured as content, not executed as a general workflow language. CoS may narrow the reviewed paths but cannot expand them. Fleet does not infer a deterministic path ceiling from natural-language intent; the user reviews it through init/configure, and target-checkout changes still require explicit patch apply.

New registrations require completed user-scope registration and fail closed if it is missing. Pre-Phase-4 Project records retain the prior balanced, repository-local `.` baseline until explicitly configured; this compatibility path creates no persistent rule. Only the exact three-entry legacy generated permission-request set is normalized, still intersected with current role/workflow/task ceilings. A changed or partial request set receives no blanket legacy allowance. Historical approvals lacking an exact authorization scope can authorize only their original one-use intent, not run-wide or persistent access.

Evaluation precedence:

1. malformed or noncanonical intent -> deny;
2. system hard deny -> deny;
3. protected user deny -> deny;
4. task/path/resource boundary violation -> deny;
5. valid unexpired exact capability grant -> allow;
6. valid persistent exact trust allow -> allow;
7. configured ask rule -> require approval;
8. safe default allow for documented project-local routine operation -> allow;
9. otherwise -> deny or ask according to trust mode, choosing deny for secrets/protected actions.

Deny overrides allow at the same or broader scope. More-specific allow cannot override a hard deny.

| Mode | Current command behavior |
| --- | --- |
| `safe` | Ask for each supported exact command scope unless an active matching grant or rule exists. Engineer and Verifier stages are separate scopes. |
| `balanced` | Allow the supported, reviewed project commands within all current ceilings. |
| `autonomous-sandbox` | Currently the same reviewed-command ceiling as Balanced; no additional executables, arbitrary shell, network access or isolation guarantees. |

The simulated approval fixture always asks. Local-unsafe command execution also asks unless an exact grant/rule matches, and still requires its separate unsafe-mode confirmation. Command scopes currently require `network_requirement: none`; neither a mode nor an approval enables arbitrary network commands. Supported bounded workspace operations remain subject to the same path, role and request checks in every mode.

## 5.4 Runtime and harness isolation

`AgentInvocation` exposes only logical project/run/task/role identifiers, bounded content, and content-addressed artifact references. It never exposes:

- absolute host or worktree paths;
- `SandboxHandle` or provider-native execution objects;
- raw credentials, grant IDs, approval resolution, or trusted policy context;
- repository/sandbox adapter instances or an unmediated subprocess callable.

A runtime may propose a typed action using the tool catalog. In Phase 3, `GatewayRuntimeToolCatalog` constructs trusted principal/stage/workspace/provider identity, validates exact supported logical resource shapes, and asks ToolGateway and PermissionBroker. After authorization, bounded list/read/search/write/edit/delete operations use descriptor-relative no-follow filesystem primitives, diff remains a trusted repository operation, and exact reviewed command IDs resolve server-side to structured no-shell execution through the selected sandbox. Fake commands and the approval fixture remain simulated; local-unsafe requires its separate high-risk confirmation; only Docker can supply isolated evidence. The PydanticAI adapter exposes the catalog through its external-tool transport but cannot replace it with native shell, filesystem, code-execution, MCP, hosted, or arbitrary network tools. Built-in runtime modules must not import concrete repository or sandbox implementations or perform filesystem/subprocess side effects. A verifier mutation test submits a forbidden intent and proves denial, not mutate a host path directly.

The runtime registry performs exact adapter selection and typed capability checks with no fallback. The live PydanticAI path allows only `openai:<model>` and `openai-chat:<model>` and rejects other prefixes before credential resolution or network. CoS receives no execution tools; Engineer and Verifier receive only their stage-bound catalog. Fleet-owned instructions, tool definitions, output schemas, and bounded dynamic context are registered-secret scanned before model invocation. Complete new provider messages are scanned before any deferred tool, and the SDK-serialized body is scanned at the last request hook before send. Model output, usage, and provider metadata are bounded and projected into project-owned types before they cross the adapter boundary.

## 5.5 CapabilityGrant

An approval issues a bounded grant, not a boolean. The implemented `CapabilityGrant` binds project, run, task, original intent/hash, agent instance, role, action and resource, with a choice, exact `scope_sha256`, optional `request_id`/`source_rule_id`, issuer, issuance/expiry/consumption/revocation timestamps and remaining uses. See the generated `capability-grant.schema.json` and the validated trust schema in `CONFIG_AND_SCHEMAS.md`.

| Choice | Effective lifetime and reuse |
| --- | --- |
| `allow_once` | One original intent/agent/hash, one use, expires no later than the request expiry or ten minutes after issuance. |
| `allow_run` | Same exact scope in the same run/task, including after reconstruction, until the run terminates or permission is invalidated. Issued run grants have no automatic expiry; the request's approval deadline does not shorten them. |
| `allow_always` | The initiating run gets a run-bounded grant; a separate exact project rule can match later runs until revoked or its optional expiry. CLI-created rules currently have no automatic expiry. |

Approval requests expire after ten minutes. Expiry, exhaustion, explicit revoke, reset cutoff, current-policy changes and source-rule revocation all prevent reuse. SQLite transactionally reserves the intent with grant consumption before dispatch. A separate atomic `claim_reserved_intent_for_dispatch` admits only one executor and records `intent.dispatch_claimed`; the permanent claim is not a renewable lease. A losing caller can return an authoritative completed result, but an incomplete claimed intent requires recovery and is never replayed, even after process restart. This is at-most-once dispatch, not a guarantee that every approved effect completes. A later-run persistent-rule match creates a one-use receipt already consumed by reservation (`request_id: null`, exact scope hash/source rule); `capability.issued` and `capability.consumed` record that use without fabricating an ApprovalRequest or another human approval. Receipts cannot themselves authorize another operation.

## 6. Always-allow semantics

“Always allow” means “persist an exact, constrained rule owned by the user.” It does not mean “trust this agent globally.”

Required dimensions:

- exact principal role;
- action;
- canonical resource;
- project ID and repository identity;
- exact workflow and stage;
- workspace kind, provider, security level, network mode and source-checkout read-only requirement;
- exact parameters and, for commands, the full canonical CommandSpec (including executable, argv, cwd and limits), its hash and declared command ID;
- expiration/revocation metadata;
- creator is `user` in the implemented schema.

The current on-disk schema uses `UserTrustRule.scope: ExactPermissionScope`, not glob/conditions expressions. See the validated example and field map in `CONFIG_AND_SCHEMAS.md`; an illustrative rule permitting Engineer's declared `npm test` in an isolated, network-off candidate workspace is not a wildcard npm permission.

This rule must not authorize:

- `npm install`;
- `npm publish`;
- `npm test && curl ...`;
- `sudo npm test`;
- a different project;
- execution outside the candidate workspace;
- execution in unsafe local mode;
- a run with network enabled if the rule requires no network.

### Approval options

- allow once: one matching intent, short TTL;
- allow for run: matching scope for the current run only;
- always allow exact scope for project: persistent user trust rule;
- deny once;
- revoke an exact rule/grant, or reset one project's grants and rules. The schema supports exact deny rules and deny precedence, but there is no CLI command to create a persistent deny rule yet.

Avoid “session” unless its lifetime is precisely defined and visible.

### Protected actions without ordinary always-allow

The following cannot receive a normal conversational always-allow grant:

- `host.sudo` or root escalation;
- disabling sandbox or selecting privileged container mode;
- mounting Docker socket or host root/home/credential directories;
- reading raw model/provider credentials;
- deleting or rewriting audit history;
- editing hard-deny policy;
- changing who may approve;
- agent self-approval;
- broad wildcard filesystem or network access;
- production deployment or destructive production database operations;
- changing secret access policy;
- raising global budget ceilings;
- disabling redaction.

A future advanced administrator flow may configure some protected operations outside agent conversation. That flow is out of scope for the MVP.

## 7. Trust-store separation

Repository configuration:

```text
<repo>/.fleet/...
```

may declare requested permissions, commands, roles, workflows, and project knowledge. It cannot grant authority.

User trust and settings live outside the repository under Fleet's state root:

```text
<Fleet state root>/trust/trust.yaml
```

The root is `AGENT_FLEET_HOME` when explicitly set, otherwise `platformdirs.user_data_path("agent-fleet", "agent-fleet")`. There is no separate implemented user `config.yaml`. Repository/state roots must be disjoint.

Requirements:

- atomic writes with restrictive file mode where supported;
- schema validation and versioning;
- ownership/source fields;
- no raw secrets;
- rule IDs and revocation;
- immutable prior-revision backups for mutation reconciliation, never automatic authorization rollback;
- symlink and path safety;
- project identity binding stronger than display name/path alone;
- agents and worker containers cannot write this location.

CoS may propose a FleetPatch under `.fleet/`; it may not patch the trust store.

`FilesystemTrustStore` reads strict bounded YAML/JSON (2,000,000 bytes), rejects duplicate/non-string mapping keys, anchors/aliases, unsafe tags, unknown fields, registered secrets, symlinks/hardlinks and non-regular files, and verifies owner/mode and descriptor identity. Writes use a lock, expected-revision compare-and-swap, atomic publication and a validated immutable `trust.yaml.revision-<20-digit-revision>.json` backup. Missing-file reads create nothing; corrupt policy fails closed and backups never activate themselves. Required POSIX descriptor/lock features are enforced; unsupported platforms fail closed, not into a weaker store.

Policy mutations validate and secret-scan the entire candidate, then persist `permission.policy_change_prepared`, publish the revision, and persist `permission.policy_change_completed`. Both events share a mutation/correlation ID, action, expected/published revisions, previous/published policy hashes and details. This is an auditable cross-store protocol, not a single SQLite/filesystem transaction: an interrupted or failed completion write can leave the policy published. Reconcile the prepared hashes with the current policy or exact immutable backup; do not infer failure solely from a missing completion event or roll back a newer revision.

Always-allow first stages a deterministic rule bound to its pending request. It remains dormant until SQLite records that exact approved `allow_always` resolution, scope and source-rule ID; retry reuses the staged ID. Revoking the rule prevents future matches and reuse of its derived grants. Project reset preserves the reviewed mode/path ceiling, revokes its rules and persists a monotonic UTC `grants_revoked_before` cutoff before individual SQLite revocations. All project grants with `issued_at <= cutoff` are rejected even if that revocation loop is interrupted. Configure preserves the cutoff; other projects are untouched. Neither operation deletes audit history.

Phase 1.5 binds configuration by content, not by filename or top-level parsed FleetSpec alone. A `ConfigSnapshot` contains the exact bounded UTF-8 contents and individual SHA-256 of `fleet.yaml` and every referenced role/workflow/project file. The loader rejects symlink and non-regular inputs, checks size before open, performs a bounded descriptor read, and detects identity/size/mtime changes during that read. Project registration stores its identity, every TaskSpec/Run binds a run-scoped snapshot artifact, and evidence assembly validates all three identities before accepting downstream proof. Referenced-file drift fails before run creation even when Git's untracked status fingerprint is unchanged, and patch apply re-loads the complete snapshot against the Run binding.

## 8. Path security

For every file/resource operation:

1. accept repository-relative or logical workspace paths from the model, not arbitrary host paths;
2. reject NUL, invalid encoding, unsupported device paths, and absolute paths where not explicitly allowed;
3. normalize path components;
4. reject `..` traversal before and after normalization;
5. resolve parent and target symlinks safely;
6. verify the resolved path remains under the authorized root;
7. defend against time-of-check/time-of-use substitution where material;
8. use file-descriptor-relative APIs where practical for sensitive operations;
9. define behavior for nonexistent targets by resolving the nearest existing parent;
10. record a canonical logical resource, not secret-bearing absolute paths, in model-visible output.

The target repository and Fleet state root must be disjoint in both directions; neither may contain the other, including through a differently-cased or symlinked spelling of the same filesystem object. Task write scopes compare protected `.git`/`.fleet` names, duplicates, and allowed/forbidden ancestry with case-folded components so a case-insensitive filesystem cannot turn an alias into authority.

Security tests must cover:

- `../../...`;
- absolute paths;
- symlink from workspace to outside;
- nested symlink parent;
- deletion/rename race where feasible;
- case-insensitive path behavior on Windows/macOS;
- alternate separators;
- repository path prefix collision such as `/repo-safe` vs `/repo-safe-evil`.

Do not authorize with string prefix checks.

The Phase 1.5 containment primitive first checks canonical path structure, then compares filesystem identity for existing ancestors. This closes differently-cased and symlinked spellings on case-insensitive filesystems, including the rule that Fleet state must remain outside the target repository and the rule that repository/state-controlled directories cannot supply host executables.

## 9. Command security

### Default command representation

```python
class CommandSpec(BaseModel):
    executable: str
    argv: list[str]
    cwd: LogicalWorkspacePath
    environment: dict[str, str]
    timeout_seconds: int
    max_output_bytes: int
    network_requirement: Literal["none", "required"]
```

Execution uses subprocess argv directly with no shell.

### Environment

- start from a minimal allowlist;
- never inherit the entire control-plane environment;
- exclude provider keys, SSH agent/socket, cloud credentials, browser/session data, and token-like values;
- allow task-specific nonsecret variables only after validation;
- redact values registered by SecretStore from output;
- record environment variable names, not secret values, when necessary.

### Shell scripts

Pipelines, redirection, command substitution, glob expansion, heredocs, and compound shell commands require a separate action such as `command.run_shell_script`. It is higher risk, must be approval-gated by default, and still executes only inside an isolated sandbox. Do not emulate shell parsing with naive string splitting.

### Repository profiling

Repository profiling is a read-only control-plane operation over untrusted data. It must:

- resolve a bounded allowlist of repository-relative metadata paths beneath the canonical Git root;
- read only size-limited regular files and reject escaping or nested symlinks;
- parse data formats without importing project modules or evaluating templates/code;
- never execute Git hooks, package lifecycle scripts, Make/Gradle/Maven targets, binaries, or a detected command;
- attach a source path to static signals and structured provenance/confidence to every detected command; preserve explicit ambiguities rather than inventing certainty;
- avoid sending profile content to a provider during offline init;
- produce deterministic canonical hashes for identical inputs.

A malicious script value may be reported as inert data, but it cannot become an executable `CommandSpec` unless a conservative parser can represent it as exact executable-plus-argv without shell semantics. Unknown or ambiguous commands remain unknown.

### Known project commands

Bootstrap may detect candidate commands from `pyproject.toml`, package scripts, Makefile, CI configuration, or similar metadata. Detection is not authorization. Show them to the user or bind them to the selected trust mode, canonical executable/argv, working directory, sandbox, and network conditions.

A known command can still execute malicious project code; sandbox enforcement remains mandatory.

## 10. Sandbox requirements

Every sandbox provider exposes an immutable capability descriptor including provider name, security level, whether isolation is enforced, whether code is executed, supported network modes, and enforceable resource/recovery support. The control plane matches `SandboxRequirements` against the exact selected descriptor before creating a resource. Phase 3 binds the complete configuration/capability snapshots and hashes to Project, Run, command evidence, and reports; Docker state also binds immutable image and daemon identities. Missing capability is a hard mismatch, never permission to fall back. Fake, Docker, and local-unsafe are separate explicit providers, and Docker failure never selects either weaker option.

## 10.1 Docker provider baseline

The Phase 3 Docker adapter creates one worker per reviewed command with:

- non-root user mapped deliberately;
- `--cap-drop ALL`;
- `no-new-privileges`;
- no `--privileged`;
- no Docker socket;
- no host PID/network namespace;
- no host root/home/credential mounts;
- read-only container root filesystem where compatible;
- writable bind only for the candidate workspace;
- separate temporary/cache mounts with documented bounds;
- network disabled by default;
- CPU, memory, PID, timeout, and output limits;
- explicit image reference, preferably digest/pin strategy documented;
- container labels for project/run/task and recovery;
- cleanup on success, failure, cancellation, and explicit exact-run recovery;
- secrets absent from environment and mounts;
- control-plane-generated container names and paths.

The implementation invokes a fixed Docker CLI with structured argv and no shell. It accepts only a pinned local Unix endpoint and Linux daemon, requires an already-local image and resolves its immutable ID, constructs an empty controlled environment, inspects the effective container configuration before start, and compares full IDs plus an installation-scoped label set before cleanup. A durable pre-dispatch checkpoint and exact-label reconciliation prevent blind replay after create ambiguity. Every daemon operation is bounded by timeout/output limits; daemon identity is revalidated around discovery and destructive lifecycle operations.

For the prepared sandbox's lifetime, a non-inheritable read-only descriptor pins the private empty `0400` `.git` shadow inode. Both pre-dispatch checks revalidate ownership, type, link count and permissions, and compare device/inode plus modification/change timestamps. The pin prevents an unlinked inode number being reused; timestamps additionally detect same-inode metadata drift but are not collision-free generation identifiers. Failed preparation and successful logical termination close the pin; ambiguous cleanup retains it until reconciliation, and dropped file objects have standard descriptor finalization. Workspace identity remains device/inode so legitimate candidate writes do not invalidate it. Docker still resolves mount pathnames after the final check: this is not an atomic path handoff or protection against a hostile same-user process or kernel.

### Network modes

For MVP, support only technically honest modes:

- `none`: no worker network;
- `approved-unrestricted`: worker network is enabled after explicit policy/approval, but domain restriction is not claimed.

Do not advertise domain allowlisting until a proxy, firewall, or equivalent mechanism actually enforces it for all child processes and DNS behavior. A future egress proxy can add `approved-domain-list`.

### Dependency preparation

Separate dependency/environment preparation from normal agent execution where practical:

- preparation can be a clearly displayed, approval-gated networked step;
- normal implementation and verification return to network-off mode;
- package caches are scoped and treated as untrusted;
- installation scripts execute in the sandbox, never on the host;
- no host `sudo` suggested as an automatic remedy.

## 10.2 Local unsafe provider

- Name it `local-unsafe`, never simply `local` or `sandbox`.
- Require explicit CLI flag/config and interactive warning unless in test mode.
- Report `security_level=unsafe_host` in events and final summaries.
- Do not silently select it when Docker is missing or broken.
- Persistent always-allow rules requiring isolation must not match it.
- Strongly limit environment inheritance and paths even though it is not an isolation boundary.

## 10.3 Fake sandbox

The fake sandbox exists for deterministic tests. It declares `isolation_enforced=false`, `executes_code=false`, and evidence strength `simulated`. It must model permission/resource behavior but must never be presented as a security boundary or as test/build execution in production output.

A real PydanticAI invocation does not change this classification. Model-generated file content may pass through authorized bounded workspace tools, but a FakeSandbox verification command is recorded rather than executed. Consequently every run using FakeSandbox keeps the corresponding proof gap and cannot set `verified_complete=true`; local-unsafe execution likewise cannot satisfy isolated or independently verified requirements.

## 11. Worktree and patch safety

The Phase 1.5 Git adapter requires Git 2.45 or newer. It resolves Git to an absolute file outside the requested path, every statically discoverable ancestor Git repository, and Fleet state using lexical, canonical, and filesystem-identity containment; relative/empty/missing `PATH` entries are discarded. Initial discovery records the absolute top-level, Git directory, and common directory, then requires the same identity when invoked from the reported root, preventing repository-local `core.worktree` from switching project boundaries. Commands strip ambient Git configuration variables, ignore system/global config, disable terminal prompts, credentials, hooks, fsmonitor, signing, replacements, lazy fetching, automatic maintenance, external diffs/text conversion, and protocol access, then enforce an explicit subcommand allow-list. Repository-local executable filter/diff, hook, include, and command keys are discovered without includes and rejected generically; their attacker-controlled names are never copied into later Git argv or error text. Invalid repository discovery also omits the unresolved canonical path and underlying subprocess exception chain. Worktree files are materialized from index blobs rather than checkout, so checkout hooks and smudge filters are not used. Permanent regressions cover filter/diff/include/includeIf/config-hook rejection, argv non-propagation, canonical non-Git path non-disclosure, and prove that a missing promisor blob cannot trigger a repository-configured upload-pack helper.

- Control plane creates candidate worktrees from a recorded base revision.
- Worker modifies only the candidate path.
- Original checkout is never bind-mounted writable into the worker.
- Do not expose broad `.git` metadata to the worker solely to make `git` commands convenient.
- Control plane computes the canonical diff and patch hash.
- Verifier receives a separate verification workspace reconstructed from the candidate artifact.
- Discard verifier changes and detect/report unexpected mutation.
- Before applying, check target repository identity, revision, and working-tree assumptions.
- Before applying, reload every referenced configuration file and require the exact Run-bound ConfigSnapshot hash.
- Never run `git reset --hard`, `git clean`, `git stash`, or discard user changes automatically.
- Applying is explicit and auditable; pushing is a separate permission.

Residual limitation: repository-local driver discovery and the later Git operation are separate processes, so another process running as the same OS user can race local config between them. Git output is captured without a byte ceiling, and the current timeout terminates the invoked parent but does not prove cleanup of forked descendants. Phase 1.5 therefore does not claim hostile same-user or multi-user repository isolation; a Fleet-owned shadow Git metadata/index view plus process-group and output enforcement is future hardening.

## 12. Secret management

Registered secret values are rejected recursively across mapping keys and values in untrusted runtime output and ToolIntent content before hashing, lookup, audit, approval, task, or artifact persistence. They are also rejected in package instructions/tool/output schema material before model construction, in complete provider new-message envelopes before tool side effects or continuation, and in the final serialized provider request body before send. Trusted user-authored messages may be redacted where retaining the surrounding diagnostic is useful, but a runtime cannot convert a secret into persisted task or permission state.

### Provider credentials

The explicit `fleet init` command supplies a strict reference such as:

```yaml
credential_ref: env:OPENAI_API_KEY
```

Phase 2 implements `env:NAME` only. The reference is persisted in Fleet-owned Project/Run state, not repository-controlled `.fleet/`; the repository may store only the selected runtime and opaque provider/model ID. Keyring and other secret backends remain future work.

Requirements:

- validate shape without an environment read during preview, which also performs no provider network or Fleet-state write;
- inspect configured/missing/invalid status for `fleet doctor` without returning the value or contacting a provider;
- resolve only in trusted control-plane memory for init/run preflight and provider construction;
- accept only 8–16384 bytes of visible ASCII so control characters, whitespace, invalid header encodings, and pathologically short redaction tokens fail before provider construction;
- pass the value directly to an explicitly constructed provider client;
- never put the raw value in FleetSpec, SQLite, worker environment, CLI argv, prompt, model-visible tool context, event, or artifact;
- register the raw value and bounded common encoded forms with the shared redactor before a provider object can raise;
- ensure exceptions and HTTP debug logging do not reveal credentials;
- do not modify the global environment or ask the SDK to infer credentials;
- pin the official OpenAI HTTPS base/host, disable redirects and ambient proxy/CA discovery, and explicitly clear unrelated ambient OpenAI identity fields before transport construction;
- expose only “configured/missing/invalid,” not the value.

Provider HTTPS is an intentional trusted-control-plane network boundary, distinct from worker networking. Selected prompts and bounded task/project context leave the machine and are subject to the provider's data handling. Phase 2 pins its OpenAI SDK client to `https://api.openai.com/v1`, disables redirects and `trust_env`, and does not honor `OPENAI_BASE_URL` or ambient proxy routing for that credential. This is explicit client construction, not a general OS egress firewall; Phase 2 does not provide an enforcing proxy or claim protection from a malicious provider or compromised local trust store. Provider retries are disabled; Fleet owns bounded request/tool/provider-reported-token/time/retry accounting and does not persist raw response bodies, headers, SDK objects, or provider exception representations. The total-token ceiling is post-response accounting rather than a strict pre-spend billing ceiling. Fleet's response hook clears provider-controlled headers before OpenAI SDK handling, but a caller that programmatically enables low-level transport DEBUG loggers can cause transport metadata to be logged before the hook; normal Fleet CLI and `OPENAI_LOG` do not enable those loggers.

Provider reconfiguration does not justify silently rewriting repository policy. A differing generated `.fleet/` tree fails initialization before Project/artifact state or repository mutation. Reference-only changes are possible only before a Run establishes an organization head. Phase 6 rejects all headed reinitialization, even with identical bytes or a removed `.fleet/`; protected setup changes require a separate registration with old state preserved. Rotating the value behind the same recorded reference does not change that registration. Start/resume resolve the active Project reference before parsing configuration; patch apply resolves both that reference and the historical Run reference so an older still-configured value is registered before any parser failure.

### External service credentials

Future connectors should use a CredentialBroker or provider-specific adapter. Agents ask for semantic actions such as `github.pull_request.create`; they never receive a bearer token. Prefer short-lived, repository-scoped credentials when available.

## 13. Tool and MCP security

For MVP, implement only project-owned tools routed through ToolGateway.

When MCP support is added:

- tool discovery does not imply authorization;
- assign canonical action names and side-effect annotations;
- wrap every MCP invocation through PermissionBroker;
- treat MCP server descriptions and outputs as untrusted;
- separate read and write operations;
- do not assume the harness sandbox covers an MCP server process or remote service;
- require explicit connection configuration and credential handling;
- cap response size and redact output;
- destructive or external-write operations require approval;
- store server identity and tool version in audit events.

## 14. Approval integrity

- Approval request binds to a canonical intent hash.
- Display the exact action/resource/conditions and risk.
- The resolution must not be supplied by the model.
- CoS/Engineer/Verifier cannot act as user approver.
- After approval, revalidate that run, task, stage, resource, target state, and intent still match.
- Material changes invalidate approval and require a new request.
- Denial must not lead to an equivalent workaround designed to bypass policy.
- Persist request, resolution, issuer, timestamp, grant, and consumption.
- Expired or revoked grants fail closed.

Approval-pause recovery preserves both Engineer and Verifier identity. Their checkpoints bind agent/workspace/sandbox/iteration; Verifier additionally binds patch hash and baseline fingerprint, with exact patch-byte validation on resume and final mutation detection. Checkpoints clear after the role completes. Logical sandbox rehydration is permitted only for known active parent leases with matching Run/workspace/provider/image/daemon bindings and successful inspection; it never recreates an interrupted execution. Outstanding execution leases require recovery. A logical retry preserves the original reviewed reason while all execution-bearing fields retain the canonical intent hash. Phase 5 durably preserves reported usage, outstanding/unknown requests and aggregate budgets across these pauses; unknown dispatches are not replayable or refunded. General raw provider-history restoration remains unimplemented.

Legacy once-only Engineer pauses without a checkpoint can restore only their exact original persisted agent after validated run/task/role lookup. Compatibility never transfers a grant to a new principal or widens its duration.

Session review confirmation is an additional human-control boundary, not a new
permission source. Tickets expire, are consumed once, and pin the exact action,
conversation revision and patch/proposal/request identity. Confirmation must
revalidate inside the existing application guard. Changed selection, concurrent
turns, stale organization generations and repeated/failed confirmations require
new review. Tool approval does not automatically resume execution.

For the session-first role/model extension (acceptance tracked in its ExecPlan),
custom role IDs remain exact principals in all user rules and grants. Their
trusted execution kind selects only a supported existing ceiling. Template tools,
steps and paths may narrow the base, never extend it; repository requests do not
grant access. Inherited base permission requests do not inherit user grants.
The Broker verifies the actual persisted custom agent against its exact reviewed
configuration. Model bindings are user-owned and pinned for the entire root and
descendants; missing required bindings fail closed, never fall back to a legacy
or ambient key. Inspection registers only relevant explicitly stored references
for redaction and never exposes references/values in safe projections.

## 15. Idempotency and side effects

Every external or irreversible action requires an idempotency strategy:

- intent ID and canonical hash;
- pending/reserved/executed state;
- provider idempotency key when supported;
- result identifier persisted before retry;
- reconcile ambiguous failures instead of blindly repeating;
- no duplicate grant consumption.

MVP should avoid external writes. The same pattern applies to patch application and trust-rule creation.

## 16. Evidence integrity and completion claims

ToolGateway derives command strength from the active sandbox capabilities and persists CommandEvidence. EvidenceAssembler then reads Run/Task plus bound ConfigSnapshot, TaskSpec, FleetPlan, patch, command/transcript, and VerifierVerdict artifacts from trusted application state. Agent-supplied changed-file lists, evidence IDs, verdicts, or summaries are claims until reconciled with those records.

Every command/test/build record declares evidence strength. The strength is derived from the executor and verification context, not accepted from runtime output. `simulated` cannot satisfy an `executed` requirement; Engineer execution cannot satisfy `independently_verified`; a stale base/config/patch identity cannot satisfy the current task.

CompletionGate must fail closed or return an explicit inconclusive decision when required criteria lack valid evidence. Operational states such as `READY_FOR_REVIEW`, patch application, and `COMPLETED` are not synonyms for `verified_complete`. A user may review or apply with known proof gaps, but CLI summaries must preserve those gaps and never relabel them as verification.

EvidenceBundle is immutable and content-addressed. It binds the exact ConfigSnapshot and TaskSpec artifact IDs/hashes, FleetPlan, repository/base identities, canonical patch, command/test/build records, Verifier identity and exact authoritative evidence IDs, Verifier-reported proof gaps/repairs/regressions, Verifier workspace-mutation detection, criterion assessments, risks, proof gaps, and the computed completion decision. Any missing/foreign/corrupt/mismatched task or configuration artifact, reported gap, contradictory PASS with repairs/regressions, Verifier mutation, stale/unbound final-patch evidence, or non-Verifier-owned evidence fails closed. `fleet status` validates the bundle binding and exposes its decision evidence instead of reducing completion to agent prose or opaque IDs.

Phase 3 still cannot map one overall scripted or model verdict independently to multiple acceptance criteria. When a general TaskSpec contains more than one criterion, EvidenceAssembler marks each assessment inconclusive and records `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`; general criterion-specific model mapping remains Phase 5 work. The deterministic bootstrap canary uses its one bounded acceptance criterion and can therefore produce an independently verified decision when every Docker evidence binding passes.

## 17. Audit and redaction

Audit history should permit reconstruction of:

- who/what requested an action;
- which rule decided it;
- whether a human approved;
- exact canonical scope granted;
- which trusted executor ran it;
- exit/result metadata;
- artifacts produced;
- run state before and after.

Do not record:

- raw credentials;
- full unrestricted environment;
- unbounded command output inline;
- sensitive provider request headers;
- hidden chain-of-thought;
- arbitrary host paths when a logical path suffices.

Use append-only semantics at the application layer. A local user can ultimately alter local files; do not call the log tamper-proof. Content hashing and optional chained event hashes may improve detection later.

## 18. Budget and denial-of-service controls

The complete Phase 3/5 limit target includes:

- maximum agent invocations;
- maximum tool calls;
- maximum repair iterations;
- model token/cost budget where available;
- command timeout;
- container lifetime;
- CPU/memory/PID limits;
- max files/read bytes/write bytes;
- max command output bytes;
- max artifact bytes;
- max event payload size;
- concurrency limit.

Agents must never be allowed to raise these limits. Phase 3 enforces bounded repair counts, model validation sizes, profiler/config bounds, FleetPlan collection/concurrency ceilings, per-invocation PydanticAI request/tool/token/time/retry ceilings, command output/time bounds, local process-group termination, and Docker CPU/memory/no-swap/PID/shm/file-descriptor limits. Completed-invocation provider usage is persisted without price estimation; paused/failed invocation accounting and cross-pause budgets remain Phase 5. Portable writable-bind disk quotas and comprehensive cross-run artifact/event/cost budgets remain later work; exhaustion produces a typed failure with current artifacts preserved where the implemented boundary supports it.

## 19. Recovery

Phase 3 does not run a blanket recovery sweep on process startup. Without a cross-process owner
liveness lock, such a sweep could mistake another still-running Fleet process for an orphan.
Instead, `fleet recover <run-id> --confirm-owner-stopped` invokes `RecoveryService` for one exact
persisted Run after the operator confirms its prior owner has exited:

- mark lost in-memory operations as interrupted;
- inspect only that Run's persisted containers/worktrees;
- avoid rerunning a side effect without reconciliation;
- clean resources known to be orphaned after recording an event;
- leave ambiguous resources outstanding for a later exact-run retry or manual diagnosis;
- refuse durable approval-paused and review states, which retain their normal resume/cancel/apply paths;
- do not delete user files outside Fleet state/workspace paths.

Docker ambiguity discovery first uses the minimal unique installation/execution labels, then
requires the exact generated name, full resource ID, and complete persisted label binding before
any kill/remove. `fleet doctor` remains diagnostic-only; `fleet recover` is idempotent once every
selected lease is terminal.

## 20. Required security tests

At minimum:

1. Repository `.fleet` requests `filesystem: /**`; effective policy rejects it.
2. Agent supplies another agent ID or role in tool args; trusted context wins/rejects input.
3. `../../.ssh/id_rsa` and symlink escape are denied.
4. Path-prefix collision is denied.
5. Exact `npm test` always-allow does not match compound commands or other argv.
6. Isolated-only rule does not match `local-unsafe`.
7. Expired, exhausted, revoked, wrong-run, wrong-project, or wrong-stage grants fail.
8. CoS self-approval fails.
9. Agent cannot mutate trust/hard-deny/audit files through workspace tools.
10. Secret value is absent from events, logs, exceptions, command environment, and sandbox inspection.
11. Docker command contains no privileged/socket/home mounts and includes baseline restrictions.
12. No silent local-unsafe fallback after Docker failure.
13. Denied action does not execute and produces a stable audit trail.
14. Approval binds to original intent; changed argv/path invalidates it.
15. Duplicate resume does not execute an idempotent side effect twice.
16. Verifier workspace modifications do not alter candidate patch.
17. Patch application refuses a diverged/dirty target without data loss.
18. Oversized output is truncated/redacted in events and stored according to limits.
19. YAML custom tags/unknown fields do not instantiate objects or silently pass.
20. Worker environment does not inherit model credentials.
21. Repository profiling never executes a malicious Git hook, package script, Make target, manifest payload, or escaping symlink.
22. Runtime invocation contains no absolute host path, sandbox handle, credential, grant, repository adapter, or unmediated executor.
23. A Verifier workspace-write request is denied through ToolGateway/PermissionBroker and leaves the workspace fingerprint unchanged.
24. FakeSandbox PASS remains `simulated` and cannot satisfy executed/independently-verified evidence requirements.
25. FleetPlan validation rejects unknown roles, cycles, excessive concurrency, conflicting writers, direct side effects, and unsupported assurance claims.
26. FleetPatch validation rejects trust, secret, state, audit, hard-deny, approval-owner, protected FleetSpec and sandbox-hard-limit targets. Only canonical declarative `skills/name.yaml` with validated reference/command/path semantics is permitted; executable or authority-expanding skill formats fail closed.
27. Git resolution ignores a repository-controlled sibling `PATH` entry even when inspection starts in a repository subdirectory; hook/filter/diff/config-driver fixtures do not execute.
28. Verifier workspace mutation persists into EvidenceBundle and yields `VERIFIER_WORKSPACE_MUTATED` without contaminating the candidate patch or target checkout.
29. A Verifier PASS carrying proof gaps, required repairs, or regressions preserves those findings and cannot become verified completion.
30. ConfigSnapshot changes when any referenced role/workflow/project file changes, and such drift is rejected before run creation even if Git status text is unchanged.
31. Evidence assembly rejects missing, wrong-kind, foreign, corrupt, or hash-mismatched ConfigSnapshot and TaskSpec artifacts.
32. Filesystem-identity containment rejects differently-cased state roots and repository-controlled executable paths on case-insensitive filesystems.
33. Repository config include/includeIf/hook surfaces fail closed, and a missing promisor blob cannot invoke a repository-configured upload-pack helper.
34. Registered secrets in mapping keys or values of CoS output or a ToolIntent are rejected before any task, intent, approval, event, or artifact write, including SQLite WAL content.
35. Repository and Fleet-state roots are rejected when either contains the other.
36. ConfigSnapshot loading rejects oversized and non-regular files before a content read, and patch apply rejects post-run referenced-file drift even when porcelain status is unchanged.
37. Status rejects every Run/EvidenceBundle config, task, plan, base, patch, command, verifier, mutation, and assurance binding mismatch.
38. Case-folded `.git`/`.fleet` aliases and allowed/forbidden scope overlaps are rejected before permission evaluation.
39. Parallel FleetPlan writer scopes and FleetPatch change paths reject case-folded aliases/ancestry; FleetPatch requires dedicated ID prefixes and registered-secret scanning across its complete serialized proposal.
40. Incoherent sandbox capability combinations and any non-exact Phase 2 FakeSandbox descriptor fail before initialization/workflow resource creation.
41. Repository-derived registered secrets fail bootstrap before preview output, Project/artifact/state/staging creation, or target `.fleet/` writes.
42. Raw and canonical repository paths, runtime/sandbox option values, and existing-configuration diffs containing a registered secret fail before error rendering or persistence; ProjectKnowledge rejects a profiler-supplied source-profile hash that the control plane cannot reproduce.
43. Untrusted FleetPatch payloads must be bounded plain built-in JSON trees; object subclasses, cycles, depth over 64, and more than 10,000 nodes are rejected without recursive descent, accepted trees are secret-scanned before schema parsing, and typed validation repeats whole-proposal scanning. Invalid payloads never echo a registered sentinel through messages or exception chains.
44. Repository-local executable Git config keys cannot propagate attacker-controlled names into secured child argv; malformed registered-secret YAML and canonical non-Git secret paths fail through generic errors with no secret-bearing cause, context, traceback, or state write.
45. Preview validates a PydanticAI selection without reading the referenced environment variable, migrating/writing Fleet state, constructing a provider client, or opening a socket.
46. Missing/invalid credentials and unsupported provider prefixes fail before Run creation and without secret-bearing output; `doctor` uses inspect-only status and never invokes a model.
47. The PydanticAI adapter exposes only exact role-bound resource tools, each reaching GatewayRuntimeToolCatalog, ToolGateway and PermissionBroker in that order. The CoS-only `fleet_content_sha256` utility is pure bounded text computation: no I/O, resource access, state, credentials or authorization; it cannot publish a proposal. Authorized candidate writes use the Fleet-owned candidate-worktree primitive, while fake commands/approval fixtures use FakeSandbox.
48. PydanticAI TestModel/FunctionModel contract and integration tests run with live model requests disabled and sockets denied; no ambient credential is used for an opt-in live smoke.
49. Raw, URL-encoded, base64/base64url, hex, and JSON-escaped registered credential forms do not survive in prompts, model output, exceptions, CLI output, SQLite/WAL, or artifacts.
50. Reinitialization with a differing generated `.fleet/` tree fails before Project/artifact state or repository mutation; it never creates a split-brain runtime registration.
51. Package instructions/tool/output schemas, bounded dynamic context, complete new provider messages, tool arguments, and the final SDK-serialized body reject registered secrets; a companion secret beside a deferred call is rejected before the first tool side effect.
52. Fresh start/resume register the current Project credential before configuration parsing, and patch apply registers both current Project and historical Run credentials after a credential-only rotation; malformed configuration errors remain cause/context-free and secret-free.
53. A deferred tool batch is fully budget-, identity-, membership-, generic-shape-, and catalog-schema-validated before its first side effect.

### Organization publication regression obligations

The Phase 6 publisher must validate both the full organization tree and logical configuration, retain exact unreferenced bytes/modes/empty directories, reject links/special files/unsupported metadata, and repeat registered-secret checks on proposal, journal and result-tree reads. `.fleet/fleet.yaml` and trust remain protected; added requirements do not grant commands. Bounded pure CoS hashing is not an alternate resource executor. Semantic/text display must not execute terminal controls.

Durable preparation must precede a single native directory exchange. Cross-state canonical-root locking, monotonic Run admission in the registration transaction and exact Project/source/index/HEAD checks prevent cooperating Fleet processes from applying or admitting stale work. A same-hash README update or rollback cannot revive old code candidates. Active and paused execution, unresolved descendant leases, retained chat owners and graph drivers block mutation. Headed initialization cannot rewrite registration. Unknown state never expires into authority.

Before/after prepare/exchange/flush/commit failures, abrupt CLI exits, concurrent publishers, source/index/tree drift and partial backup deletion must leave exact recoverable evidence or an explicit retained gap. Recovery requires stopped-owner confirmation and the same native lock; it aborts the exact original orientation or synchronizes/commits the exact exchanged orientation, never performs another exchange or overwrites unknown user edits. Publication success is distinct from cleanup. Pre-receipt scratch has no invented journal recovery. Native macOS/Linux feature availability and hardware durability are not implied by schema validation; unsupported environments fail closed. See [ADR 0006](adr/0006-atomic-organization-publication.md) and the Phase 6 acceptance ledger.

## 21. Security release gate

Before calling the MVP safe for ordinary use:

- all required security tests pass;
- Docker integration test verifies effective user, mounts, network, capabilities, and environment;
- threat model and limitations are in the README;
- local-unsafe mode is explicit and visually prominent;
- no bypass path exposes a framework-native shell/filesystem tool outside ToolGateway;
- runtime invocations expose no host path, sandbox handle, credential, grant, or direct executor;
- repository profiling has no code-execution path and all detected commands remain unauthorized requests;
- CompletionGate derives assurance from authoritative evidence and a fake/simulated PASS cannot set `verified_complete=true`;
- dependency and image versions are reviewed and pinned according to project policy;
- a manual adversarial bootstrap test is recorded;
- documentation never equates permission allowlists with OS isolation.
