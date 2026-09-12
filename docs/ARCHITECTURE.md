# Architecture specification — Agent Fleet Foundry

## 1. System overview

```text
Repository -> RepositoryProfiler -> RepositoryProfile
                                  -> ProjectKnowledge
                                  -> FleetSpec proposal

User goal -> CoS runtime proposes bounded scope + strategy
                                      |
                                      v
                         FleetPlanner -> FleetPlanValidator
                                      |
                              Scheduler / WorkflowEngine
                                      |
Runtime tool call -> ToolGateway -> PermissionBroker -> authorized executor
                                      |                    |
                                      v                    v
                                  audit/event       SandboxProvider

TaskSpec + FleetPlan + canonical patch + command records + verdict
                                      |
                               EvidenceAssembler
                                      |
                                CompletionGate
                                      |
                         EvidenceBundle + user review
```

The control plane is deterministic application code. The LLM/harness adapter is one dependency, not the owner of topology, workflow state, permission, sandbox selection, evidence strength, or completion claims. See [ADR 0001](adr/0001-product-north-star.md).

The architecture implements a project-specific organization runtime, not a generic agent chat bus. Role instances are created from a validated per-run FleetPlan. The plan may be adaptive, but the execution graph, budgets, workspace ownership, and assurance rules remain system-controlled.

Implementation boundary: Phase 0–6 is locally accepted: durable state/artifacts, hardened Git worktrees, bounded repository intelligence, guarded patch application, exact permissions and external user trust, cumulative budgets, all five adaptive strategies, persistent bounded chat and reviewed organization evolution. Phase 5 is pushed at `a46b688`; Phase 6's1973 default passes15 skips and fourteen separately enabled real-Docker passes are recorded in E6 with its checkpoint refresh. Fake and BYOK PydanticAI share project-owned contracts; wired `openai:` and `openai-chat:` support does not imply live-provider acceptance. Docker is the sole current isolated provider; fake is simulated and local-unsafe non-isolating. Section3.14 and ADR0006 define the accepted local publication boundary. Phase7 guide/hardening, fresh-user/Linux proof, final GitHub and live-provider/license gates remain separate. Remote sandboxes are post-MVP.

## 2. Layering and dependency rule

The S1–S3 extension is tracked separately in
`.agent/plans/2026-09-09-s1-s3-system-development.md`. Its initial evaluation layer
keeps immutable task manifests, external outcome observations and pure reporting
outside workflow authority. Typed references alone do not authenticate evidence;
the report cannot grant execution or declare KR acceptance. See
[ADR 0009](adr/0009-independent-evaluation-contracts.md). The independently accepted
September9 OpenAI nano canary is a bounded, unapplied proof, not broader S1–S3
or new-provider/Harness acceptance.

The initial S3 conformance increment is a shared pure invocation-admission guard
used by Fake and PydanticAI, with adapter-parametrized role/output and rejection
tests. It checks exact selection, supported execution kinds and capabilities
before model/credential/tool effects. It does not add a Harness, change Run wire
contracts, grant authority or make checkpoint/streaming claims. The existing
Workflow remains the principal and result boundary; the rest of the common
budget/approval/cancellation/evidence qualification matrix is subsequent work.

S1.1b1 adds a separate non-executing `EvaluationLedgerService -> EvaluationStore`
boundary. SQLite migration0011 persists immutable campaign registration, slot
commitments and preflight observations. Atomic reservation bounds all campaign
budget dimensions, but does not dispatch a Run or authenticate a successful
external oracle. The strict returned `execution_authorized=false` is an explicit
limitation, not a permission decision or a future activation switch.

S2.1a readiness is another independent read-only path:
`cli/readiness -> application/readiness -> repository metadata capture`.
It avoids `bootstrap`/doctor/state-store initialization and never calls a model or
sandbox. Public wire-size projection accounts for actual JSON escaping and redaction;
omissions make the result incomplete. Static discovery is not executable-environment
or business-test qualification.

The reviewed model-free baseline has its own principal and state, not a fake Run:

```text
User CLI plan -> BaselineAdmissionService -> five-minute exact review
User exact once consent -> permanent owner claim -> ResourceService worktree/sandbox
                         -> ToolGateway -> PermissionBroker -> dispatch claim
                         -> Docker read-only source + bounded scratch
                         -> immutable command observation -> exact cleanup -> report
```

`application/baseline.py` owns admission and lifecycle; dedicated baseline ports
and SQLite migration13 retain canonical identities and immutable evidence. Git,
Docker, Gateway, Broker and ResourceService expose separately typed baseline
operations; ordinary Run labels, wire schemas and execution semantics remain
separate. The capability must exist before authorization/ownership is consumed.
Every dispatch revalidates the reviewed source/configuration/trust/image/daemon;
the full resource set and payloads are fenced before cleanup. The lock order is
organization publication, trust read guard, then short SQLite transactions, with
no await inside a SQL transaction. Trust stays guarded through transport drain;
same-process policy saves fail closed while that guard is held.

No runtime/model or secret-store instance is constructed for this composition,
although shared bootstrap modules import SDK code. It may initialize or migrate
state even for `show`. Permanent claims never expire into replay authority; a
stopped-owner recovery checks the exact reviewed cleanup scope and cannot replay
the command. Unknown container creation with no native identity remains unknown,
not a zero-effect inference. Observations are not an independent Agent verdict
or S1 external oracle. Source is mounted read-only, so commands requiring writes
to the project tree are not generally supported. Physical Python/Node and
Session/cold-start qualification remain separate acceptance work.
See [ADR0011](adr/0011-reviewed-model-free-business-baselines.md).

The foreground Session now shares this controller through a lazy factory retaining
the existing Redactor. `/baseline plan` stores a process-local typed review;
`/confirm` calls authorization only; `/baseline run` consumes that exact grant.
`BaselineSessionAdmission` binds conversation/repository/revision and a pure local
selection check inside the existing authorization/claim transaction. It uses the
same SQLite connection, no historical turn reader and no await in SQL. Local
generation prevents a switch-away-and-back from reviving a stale review. Codes are
bounded and remain classified after consumption, so they cannot fall through to
ordinary history review. There is no new migration or fabricated Run/Turn.

Baseline tasks and cancellation drainage have separate ownership from ordinary
Run execution. A per-attempt RAM notification changes CLI routing only after local
admission; a rejected entry restores previous cancellation/progress ownership.
That notification cannot authorize a command: durable admission remains separate.
Operation-scoped metadata reads after normal selection avoid additional secret,
history and runtime access while ordinary Session redaction remains intact. Focus
is not restored after restart; retained recovery stays in the standalone lifecycle.

PydanticAI has explicitly bound OpenAI, Anthropic Messages and Google Developer API
factories. The additional OpenAI Agents SDK and LangGraph Harnesses each own their
actual SDK loop behind the same Fleet runtime port; neither owns execution authority.
The SDK path interrupts function calls before Fleet executes them. LangGraph uses
a fresh bounded async request/validate/Gateway graph, not a native tool executor.
Shared secret registration, full-batch validation, accounting and output validation
remain authoritative. Single-use transport tickets prevent another physical send
under the same reservation. Actual-SDK offline qualification is distinct from
live-provider qualification; README and the active plan bind acceptance to exact
snapshots, including corrected configuration/schema admission.

The Gateway catalog derives a bounded, conservative read-path schema hint from
the immutable task scope, without filesystem discovery or new authority. Supported
ASCII prefixes narrow ordinary model choices; unsupported/broad scopes retain the
generic path schema, and a Unicode escape branch defers non-ASCII semantics to the
existing Broker. Each access returns fresh nested definitions. LangGraph prepares
and validates one coherent catalog snapshot before credential resolution, then
regenerates it from raw scope provenance after registering the selected credential.
No client or model request occurs in either synchronous preparation pass. This
closes the selected-key encoding case; it does not qualify arbitrary subsequent
key registrations. Provider wire transforms and local validation differ, so schema
guidance is not a substitute for Gateway/PermissionBroker enforcement.

Migration0012 adds reserved campaign execution through the existing Workflow. An
atomic transaction binds the permanent reservation, unique Run, model selections,
budget and one-use dispatch claim. No automatic retry/replacement or refund follows
an uncertain execution. The successor evidence observer is not publicly wired:
its original source-DB/path-boundary audit failed, and both terminal-recording
entry points now reject before state access. Descriptor-bound read capture is under
repair; read-side progress cannot satisfy the unresolved atomic finalization or
external-oracle requirements.

Conceptual target package layout (not an inventory of implemented files):

```text
src/agent_fleet/
  __init__.py
  cli/
    app.py
    render.py
    commands/
      init.py
      doctor.py
      run.py
      chat.py
      approvals.py
      permissions.py
      patches.py
  domain/
    ids.py
    time.py
    errors.py
    projects.py
    agents.py
    tasks.py
    runs.py
    events.py
    artifacts.py
    repository_profile.py
    fleet_plan.py
    evidence.py
    permissions.py
    policies.py
    workflows.py
    fleet_patch.py
  application/
    project_service.py
    planning.py
    evidence.py
    permissions.py
    run_service.py
    workflow_engine.py
    coordinator.py
    approval_service.py
    permission_service.py
    artifact_service.py
    fleet_patch_service.py
    recovery_service.py
    doctor_service.py
  ports/
    runtime.py
    repository_profiler.py
    permission.py
    sandbox.py
    state_store.py
    artifact_store.py
    secret_store.py
    repository.py
    clock.py
    id_generator.py
    event_sink.py
  adapters/
    runtime/
      fake.py
      pydantic_ai.py
    sandbox/
      fake.py
      docker.py
      local_unsafe.py
    persistence/
      sqlite.py
      migrations/
    artifacts/
      local.py
    secrets/
      environment.py
      keyring.py
      composite.py
    repository/
      git.py
    config/
      yaml.py
    system/
      subprocess.py
  prompts/
    cos.md
    engineer.md
    verifier.md
  schemas/
    fleet.schema.json
  main.py

tests/
  unit/
  contract/
  integration/
  e2e/
  fixtures/

docs/
.agent/
```

Allowed dependency direction:

```text
cli -> application -> domain
application -> ports
adapters -> ports + domain
```

Forbidden directions:

- domain importing Typer, Rich, PydanticAI, Docker, keyring, or SQLite adapter code;
- application importing a concrete provider adapter except in a composition root;
- adapters calling CLI presentation code;
- model prompts determining authorization rules;
- sandbox implementations mutating trust policy.

Use one composition root, likely `agent_fleet.main` or `agent_fleet.bootstrap`, to instantiate concrete adapters and inject them into services.

## 3. Core domain entities

All persistent/external structures use Pydantic v2 models with `extra='forbid'` unless forward-compatible extension fields are intentionally designed.

### 3.1 Identity types

Use opaque string IDs with stable prefixes and UUID-based entropy:

```text
prj_<uuid>
run_<uuid>
task_<uuid>
agent_<uuid>
evt_<uuid>
perm_<uuid>
grant_<uuid>
art_<uuid>
intent_<uuid>
lease_<uuid>
corr_<uuid>
sandbox_<uuid>
ws_<uuid>
plan_<uuid>
fpatch_<uuid>
```

Each typed field validates its own prefix; the generic opaque-ID grammar is retained only where an event causation reference may intentionally point at more than one ID kind. Do not derive security identity solely from user-provided names or absolute paths.

### 3.2 Project

Fields:

- `project_id`;
- canonical repository root;
- Git remote fingerprint when present;
- initial repository identity hash;
- created/updated UTC timestamps;
- active FleetSpec version/hash;
- selected runtime and opaque provider/model identifier;
- the user-selected credential reference in Fleet-owned state only;
- state directory.

Project identity algorithm must be documented. A reasonable first version combines a stored random project ID in local state with repository metadata. Do not require committing a secret identifier into the repository.

### 3.3 FleetSpec

Describes repository-owned requested organization:

- API version and kind;
- metadata/name;
- runtime adapter selection;
- model aliases and opaque provider/model identifiers;
- agent role specs;
- declared tools;
- sandbox request;
- requested permissions;
- workflow definitions;
- budget and concurrency requests;
- verification commands;
- project knowledge paths.

FleetSpec requests behavior. User policy may reduce it.

### 3.4 RepositoryProfile and ProjectKnowledge

`RepositoryProfile` is a deterministic, content-hashed observation of a repository. It contains repository-relative boundaries, ecosystems/languages, manifests and lockfiles, build/package systems, exact candidate commands, evidence sources, confidence, and unresolved ambiguities. Profiling may parse bounded regular files but never imports packages, invokes build tools, runs hooks/scripts/targets, or follows a symlink outside the canonical root. Detection is not authorization.

`ProjectKnowledge` is the user-reviewable factual projection used by CoS and workers. Phase 1.5 derives its summary from RepositoryProfile signals and preserves ambiguities, but does not yet attach provenance/confidence to each summary string. Its `source_profile_sha256` is independently recomputed at the ProjectService boundary rather than trusted from the profiler adapter. The profile and knowledge are immutable artifacts bound to the Project; subsequent changes produce new artifacts rather than rewriting historical run context.

### 3.5 AgentSpec and AgentInstance

`AgentSpec`:

- stable role name;
- instruction file;
- lifecycle (`persistent`, `per_task`);
- model alias;
- allowed tools;
- requested permissions;
- roles it may spawn/delegate to;
- maximum steps/turns;
- structured output schema identifier.

`AgentInstance`:

- instance ID;
- role;
- run/task association;
- lifecycle status;
- runtime checkpoint/message reference;
- creation and completion timestamps.

The persistent CoS identity does not imply unbounded raw transcript retention. Store explicit summaries and run references; make full prompt/message retention opt-in and redacted.

Role IDs are validated extensible identifiers, not a closed enum. A role ID selects a declared responsibility template; it is never an authority token. A run persists only the AgentInstances present in its validated FleetPlan.

### 3.6 TaskSpec

Canonical delegation envelope:

- `task_id`;
- original user goal;
- normalized objective;
- workflow name;
- allowed repository-relative path scopes;
- forbidden paths;
- acceptance criteria;
- required evidence;
- known commands;
- requested capabilities;
- budget limits;
- maximum repair iterations;
- base revision;
- exact configuration-snapshot hash;
- contextual artifact references;
- risk flags.

After scope approval, TaskSpec is immutable for a run iteration. Phase 1.5 persists its exact serialization as a run/task-scoped content-addressed artifact and binds the artifact ID/hash to Run. Material scope changes create a revised TaskSpec and event.

### 3.7 Run and stage state

`RunStatus` values should include:

```text
CREATED
INITIALIZING
RUNNING
PAUSED_FOR_APPROVAL
READY_FOR_REVIEW
APPLYING
COMPLETED
FAILED
CANCELLED
REJECTED
ABANDONED
```

`WorkflowStage` for code change:

```text
INTAKE
SCOPING
PLANNING
WORKSPACE_PREPARATION
IMPLEMENTING
VERIFYING
REPAIRING
PRESENTING
APPLYING
CLEANUP
```

Persist status and stage transitions transactionally with corresponding events. Invalid transitions must fail explicitly.

Operational run status and assurance are distinct. `COMPLETED` records lifecycle/application completion; `verified_complete` is computed by CompletionGate from an immutable EvidenceBundle and may remain false after a user knowingly applies an inconclusive patch.

### 3.8 FleetEvent

Events are immutable application records. Suggested envelope:

```python
class FleetEvent(BaseModel):
    event_id: EventId
    event_type: str
    schema_version: int
    occurred_at: datetime
    project_id: ProjectId
    run_id: RunId | None
    task_id: TaskId | None
    agent_instance_id: AgentInstanceId | None
    correlation_id: CorrelationId
    causation_id: OpaqueId | None  # heterogeneous reference to the causing record
    payload: dict[str, JsonValue]
    redaction_summary: list[str] = []
```

Event vocabulary below includes future workflows; it is not a claim that every listed event currently has an emitting path:

```text
project.initialized
fleet_spec.proposed
fleet_spec.applied
run.created
run.stage_changed
run.paused
run.resumed
run.cancelled
run.failed
run.completed
task.scoped
agent.started
agent.completed
agent.failed
workspace.created
workspace.cleaned
tool.intent_created
permission.decided
approval.requested
approval.resolved
capability.issued
capability.consumed
sandbox.created
sandbox.exec_started
sandbox.exec_completed
sandbox.terminated
artifact.created
implementation.reported
verification.completed
repair.requested
patch.ready
patch.applied
fleet_patch.proposed
fleet_patch.applied
fleet_patch.rolled_back
secret.redacted
recovery.action
```

Payloads should become typed Pydantic models for high-value event types. Do not persist arbitrary provider SDK objects.

### 3.9 Artifact

Fields:

- artifact ID;
- kind;
- run/task origin;
- MIME type;
- byte size;
- SHA-256 hash;
- local content location managed by ArtifactStore;
- creation time;
- producer role/component;
- redaction status;
- metadata.

Artifact kinds:

```text
TASK_SPEC
REPOSITORY_PROFILE
PROJECT_KNOWLEDGE
FLEET_PLAN
PATCH
CANDIDATE_COMMIT
TEST_REPORT
COMMAND_TRANSCRIPT
IMPLEMENTATION_REPORT
VERIFIER_VERDICT
EVIDENCE_BUNDLE
BOOTSTRAP_REPORT
RUN_SUMMARY
FLEET_PATCH
CONFIG_SNAPSHOT
USAGE_REPORT
ERROR_REPORT
```

Artifact content is stored outside SQLite; SQLite stores metadata and content references. Writes are atomic and content hashes verified on read.

### 3.10 ImplementationReport

Structured Engineer output:

- summary;
- files intentionally changed;
- tests added/changed;
- commands requested/executed with evidence references;
- acceptance-criterion mapping;
- unresolved limitations;
- candidate patch artifact ID;
- questions or blocked permissions;
- suggested verifier focus.

The report is not trusted proof. The control plane and Verifier inspect artifacts independently.

### 3.11 VerifierVerdict

```text
PASS
FAIL
INCONCLUSIVE
```

Fields:

- criterion-by-criterion result;
- independently executed evidence IDs;
- discovered regressions;
- required repairs;
- proof gaps;
- final rationale;
- confidence metadata if used;
- verification workspace identity.

`PASS` is a verifier judgment, not the final assurance decision. `INCONCLUSIVE` may still be presented for explicit human review, but it can never be rendered as verified completion. Repair loops are bounded.

### 3.12 FleetPlan

`FleetPlan` is an immutable per-run artifact proposed by CoS and accepted only after deterministic validation. It contains:

- strategy and rationale;
- typed nodes with extensible role IDs and dependency edges;
- task/path scopes and workspace ownership;
- maximum concurrency, steps, wall time, and repair limits;
- required verification and evidence strength;
- the task/run identity and creation time needed to persist and resume the same plan.

The validator rejects missing or duplicate nodes/dependencies, noncanonical or case-folded duplicate scopes, oversized collections, unknown roles, cycles, excessive concurrency, case-insensitively overlapping or out-of-task writer scopes, out-of-task Verifier scopes, non-workspace writers/Verifiers, false parallel dependencies, direct plans with side effects, and code-change assurance claims unsupported by the topology. Phase 1.5 executes `direct`, `single_engineer`, and `engineer_verifier`; parallel and specialist DAGs are representable but not scheduled until a later increment.

### 3.13 EvidenceBundle and CompletionDecision

`EvidenceBundle` is assembled by the control plane from authoritative state and content-addressed artifacts. It binds project/task/run identity, the exact ConfigSnapshot and TaskSpec artifact IDs/hashes, FleetPlan, required evidence IDs, base revision, canonical changed paths and patch hash, exact command records, verifier identity/verdict, the Verifier-owned command-evidence IDs, reported repairs/regressions/proof gaps, Verifier workspace-mutation detection, risks, and proof gaps. Each evidence item records provenance and strength as `simulated`, `observed`, or `independently_verified`. Inspection revalidates the stored bundle identity/hash and exposes a bounded evidence summary rather than only opaque artifact IDs.

`CompletionGate` evaluates every required criterion against those records and emits a `CompletionDecision`. Evidence strength cannot be asserted by an Agent or upgraded by serialization. Verifier evidence must be authoritative, owned by the recorded Verifier, and bound to the final patch; any reported proof gap, contradictory PASS with repairs/regressions, or detected Verifier-workspace mutation fails closed. Phase 3 can map one overall runtime verdict only to a single acceptance criterion; a general multi-criterion task produces inconclusive assessments and `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`. FakeSandbox output is always `simulated`, and local-unsafe is never isolated, so neither can verify completion. A fake or PydanticAI runtime can reach verified completion only when its actual commands run through the isolated Docker provider and every final-patch, fresh-Verifier, inspection, and cleanup binding passes.

### 3.14 FleetPatch

`FleetPatch` is a typed organizational-change proposal bound to dedicated FleetPatch/Project IDs and the logical ConfigSnapshot hash (the legacy wire name is `base_fleet_spec_sha256`). Phase 6 reuses the foundational file-change format, adds file/descendant collision checks and bounds, and permits only role/workflow guidance, named project files, README and narrowly typed `skills/name.yaml`. FleetSpec, trust, credentials, registration, hard ceilings and audit/state remain protected.

`OrganizationService` coordinates validated proposal persistence, semantic/text artifacts, explicit application, inverse rollback and stopped-owner recovery. `OrganizationFileSystem` owns native bounded tree capture/staging/exchange/cleanup; `OrganizationStore` owns immutable trees/proposals/versions/receipts and transaction-local admission. A complete OrganizationTree binds unreferenced bytes, modes and empty directories separately from ConfigSnapshot. The cross-state repository lock and monotonically increasing head prevent simultaneous publication, stale Run admission and hash-ABA replay. Existing Run/Project/conversation/graph serialized contracts are not rewritten. Exact source/index/HEAD checks surround publication; only the organization status allowance and snapshot bindings may be rebound.

The normal CoS runtime may output a FleetPatch using trusted proposal/project/base identities and a bounded visible-file context. It cannot expose protected FleetSpec or replace/remove omitted content. Its pure `fleet_content_sha256` utility computes only on bounded supplied text; it does not access resources, permissions or state. Proposal output produces a read-only/direct Task and review artifacts, not an Engineer or application authority. Apply/rollback are user CLI calls, never model tools. Referenced `VerificationSkill` declarations add path-overlap command requirements to TaskSpec, and EvidenceAssembler independently recomputes them. Exact broker/sandbox checks still authorize each command.

The native publisher stages privately beside the repository and durably prepares complete before/after trees, exact pinned directories and a project fence before one same-filesystem directory exchange. SQLite commit then binds Project, version and append-only audit atomically. Unknown outcomes retain the fence. Explicit recovery aborts an exact original orientation or synchronizes/commits an exact exchanged orientation, never exchanges again or overwrites unknown edits. Cleanup is a separately reported observation. Current-head rollback creates a new exact inverse operation; historical code candidates remain stale. See [ADR 0006](adr/0006-atomic-organization-publication.md) for precise ordering, unsupported metadata/platforms and pre-receipt scratch limitations.

## 4. Ports and adapter contracts

Protocols should be small, project-owned, and tested by reusable contract suites.

## 4.1 RuntimeAdapter

The runtime adapter turns a typed role invocation into strict role outputs (`ScopeDecision` or trusted-context-bound `FleetPatch` for CoS, `ImplementationReport`, bounded specialist reports, or `VerifierVerdict`). All resource/side-effect tools are ToolGateway-backed. The separate CoS content-hash utility is pure bounded computation with no I/O or authorization. Runtime selection is exact; the registry never falls back to another adapter or infers a provider from ambient state.

An invocation contains logical run/task/agent identity, role/stage/iteration, bounded relative content, and artifact references only. It never contains a host filesystem path, `SandboxHandle`, provider credential/reference, permission grant, or callable executor. A runtime may request a typed action through the supplied catalog; it cannot perform that action directly. Built-in runtime adapters must not import concrete repository/sandbox adapters or subprocess execution code.

Implemented evaluation interface (abridged):

```python
class RuntimeCapability(str, Enum):
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    CHECKPOINT = "checkpoint"
    RESUME = "resume"
    USAGE_ACCOUNTING = "usage_accounting"


class AgentInvocation(BaseModel):
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    role: RoleId
    stage: WorkflowStage
    iteration: int
    max_steps: int
    instructions: str | None
    context_artifact_ids: list[ArtifactId]
    checkpoint_ref: ArtifactId | None
    input: dict[str, JsonValue]


class AgentInvocationResult(BaseModel):
    output: ScopeDecision | ImplementationReport | VerifierVerdict
    usage: UsageRecord | None
    checkpoint_ref: str | None
    provider_metadata: RuntimeProviderMetadata | None


class RuntimeInvocationServices:
    configuration: RuntimeConfiguration
    tools: RuntimeToolCatalog


class RuntimeAdapter(Protocol):
    @property
    def capabilities(self) -> frozenset[RuntimeCapability]: ...

    def preflight(
        self,
        configuration: RuntimeConfiguration,
        *,
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight: ...

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult: ...
```

`RuntimeCredentialCheck` separates three security-relevant paths:

- `NONE` validates selection/reference shape without reading a credential; preview uses this mode and also avoids state migration/writes and provider network;
- `INSPECT` reports configured/missing/invalid without returning the value; `fleet doctor` uses this mode and does not contact a provider;
- `RESOLVE` obtains the value inside the trusted control plane and registers redaction before init/run proceeds.

Do not force all harnesses to serialize their internal state into a common message format. Store an opaque checkpoint reference plus portable task/artifact context. A runtime without checkpoint support can resume by starting a new invocation with a system-generated summary, provided the workflow marks that degradation explicitly.

The implemented adapters are:

- `FakeRuntimeAdapter` for deterministic tests;
- `PydanticAIRuntimeAdapter` for real model calls.

`PydanticAIRuntimeAdapter` translates PydanticAI output, usage, and bounded provider metadata into project-owned models without leaking PydanticAI/provider SDK objects into domain/application code. Its live construction allowlist is exactly `openai:<model>` through the Responses API model class and `openai-chat:<model>` through the Chat Completions model class. It constructs an explicit provider/client with the resolved credential, pins the official HTTPS API base and host, disables redirects, ambient proxy/CA discovery, and provider SDK retries, clears unrelated ambient OpenAI identity fields, and applies Fleet-owned request/tool/provider-reported-token/time/retry ceilings. A final request hook validates the SDK-merged endpoint, headers, length, and serialized body before transmission; a response hook rejects registered secrets and clears provider-controlled headers before OpenAI SDK handling. Unsupported prefixes fail before credential resolution or network.

PydanticAI `ExternalToolset` is transport for the exact definitions supplied by `GatewayRuntimeToolCatalog`; it is not an authorization or execution plane. CoS receives no side-effect tools. Engineer may receive bounded list/read/search/write/edit/delete/diff operations and exact reviewed command IDs; Verifier receives only bounded list/read/search/diff and exact reviewed commands, never mutation. The approval probe exists only in its deterministic fixture. Each call binds trusted run/task/agent/stage/workspace/provider identity outside model arguments and crosses `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`. The complete deferred batch is schema-validated without side effects before execution. After authorization, descriptor-relative workspace operations and sandbox commands are resolved by trusted control-plane services; model arguments never contain host paths, executable selection, raw environment, sandbox handles, or Docker flags. Provider-native shell, filesystem, MCP, code execution, hosted tools, and arbitrary network tools are not registered.

## 4.2 ToolGateway

Every tool available to a model is a narrow wrapper that constructs a `ToolIntent` and submits it to ToolGateway.

Conceptual API:

```python
class ToolGateway(Protocol):
    async def execute(self, intent: ToolIntent) -> ToolResult: ...
```

Responsibilities:

1. validate and canonicalize tool input;
2. attach run/task/agent identity from trusted invocation context, not model arguments;
3. ask PermissionBroker for a decision;
4. pause safely when approval is required;
5. invoke the correct trusted executor only with a valid capability grant;
6. redact inputs/outputs before events and model return;
7. record intent, decision, execution, and artifact events;
8. enforce Phase 3 command time/output/process/container limits and the existing runtime call-count budgets; broader cross-run budgets remain later work.

The model must never be allowed to supply its own principal identity, grant ID, approval result, sandbox ID, or unrestricted host path.

Initial logical tools:

- `repo.list_files`;
- `repo.read_file`;
- `repo.search_text`;
- `workspace.write_file`;
- `workspace.delete_path`;
- `workspace.apply_edit`;
- `workspace.get_diff`;
- `command.run`;
- `artifact.read_metadata`;
- `task.report_progress`.

Git operations that affect the source repository are control-plane operations, not arbitrary model shell commands.

## 4.3 PermissionBroker

Conceptual interface:

```python
class PermissionBroker(Protocol):
    def evaluate(
        self, intent: ToolIntent, task: TaskSpec, sandbox: SandboxCapabilities
    ) -> PermissionDecision: ...
```

Persistence and user interaction belong to application services. `PolicyPermissionBroker` reads current state/policy through `PermissionPolicyService`; `ApprovalService` owns resolution, not the runtime or broker protocol. The composition root injects the broker into ToolGateway and a `FilesystemTrustStore` behind `TrustStore`. The store lives at `<Fleet state root>/trust/trust.yaml`, outside the repository; it does not belong to ConfigSnapshot or the worker filesystem.

Evaluation applies the supported baseline executor ceiling, current repository/Run/Task/configuration bindings, reviewed user paths, role `allowedTools`, optional workflow `allowedTools`, repository `requestedPermissions`, exact deny rules, applicable grants/rules, then documented mode defaults. No lower layer adds authority absent above it. Safe asks for supported exact commands; Balanced and Autonomous-sandbox currently share the same reviewed-command ceiling. They do not enable arbitrary commands or networking and cannot improve sandbox assurance. Engineer and Verifier roles/stages require distinct scopes.

Exact scope binds project/repository identity, role, workflow/stage, action/resource/parameters, full CommandSpec where applicable, workspace kind, provider/security/network and source-checkout read-only status. Once grants bind the original intent/agent/hash and expire within ten minutes or request expiry, whichever is sooner. Run grants match the same run/task/scope until termination or invalidation; they have no automatic expiry and outlive the request's approval deadline. An always-allow rule is separate durable user-owned state; it can match later runs while active and within current ceilings. Legacy registrations retain only their previous Balanced/`.` baseline; new registrations require completed reviewed settings. Unchanged legacy generated permission requests receive narrow compatibility normalization, not new authority. Historical unscoped approvals remain once-only.

Policy publication crosses two stores: validate/secret-scan candidate → durable `permission.policy_change_prepared` → expected-revision atomic trust publication → `permission.policy_change_completed`. The event pair shares mutation ID, action, revisions and before/after hashes. Immutable prior-revision backups support exact reconciliation after an interrupted publication/completion; they never auto-activate or justify rolling back newer state. Always-allow stages a deterministic request-bound rule that remains dormant until its matching SQLite approval resolution activates it. A later-run rule use reserves the intent and creates a consumed capability receipt in one SQLite transaction, with exact source rule/scope and issued/consumed events but no fabricated approval. Revoke affects future decisions. Reset preserves reviewed settings, revokes project rules and publishes a monotonic `grants_revoked_before` cutoff before SQLite grant cleanup; grants issued at or before it cannot authorize execution even if cleanup fails.

Immediately before any executor, Gateway calls `StateStore.claim_reserved_intent_for_dispatch`. Its SQLite transaction checks the active trusted context and inserts the intent's permanent unique claim with `intent.dispatch_claimed`; only one concurrent caller wins. A loser returns a completed authoritative result or fails ambiguous, never dispatches again. The claim is not an expiring lease and an incomplete claimed operation is not replayed after restart. This separates idempotent reservation/grant consumption from exclusive dispatch ownership.

See `CONFIG_AND_SCHEMAS.md` for the actual validated schema and CLI, and `SECURITY_MODEL.md` for filesystem, mutation and compatibility limitations. The store requires its POSIX no-follow/lock protections; unsupported platforms fail closed.

## 4.4 SandboxProvider

Conceptual models:

```python
class SandboxSecurityLevel(str, Enum):
    ISOLATED = "isolated"
    UNSAFE_HOST = "unsafe_host"
    FAKE = "fake"


class EvidenceStrength(str, Enum):
    SIMULATED = "simulated"
    OBSERVED = "observed"
    INDEPENDENTLY_VERIFIED = "independently_verified"


class SandboxCapabilities(BaseModel):
    provider: str
    security_level: SandboxSecurityLevel
    isolation_enforced: bool
    executes_code: bool
    supported_network_modes: set[str]
    supports_resource_limits: bool
    supports_recovery: bool


class SandboxSpec(BaseModel):
    image: str
    workspace_host_path: Path
    workspace_container_path: str = "/workspace"
    network_mode: Literal["none", "approved-unrestricted"] = "none"
    cpu_limit: float
    memory_mb: int
    pids_limit: int
    timeout_seconds: int
    environment: dict[str, str]
    read_only_root: bool = True


class ExecRequest(BaseModel):
    executable: str
    argv: list[str]
    cwd: str
    environment: dict[str, str]
    timeout_seconds: int
    max_output_bytes: int


class ExecResult(BaseModel):
    exit_code: int
    stdout_artifact_id: ArtifactId | None
    stderr_artifact_id: ArtifactId | None
    started_at: datetime
    completed_at: datetime
    timed_out: bool


class SandboxProvider(Protocol):
    capabilities: SandboxCapabilities

    async def create(self, spec: SandboxSpec) -> SandboxHandle: ...
    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult: ...
    async def terminate(self, handle: SandboxHandle) -> None: ...
    async def inspect(self, handle: SandboxHandle) -> SandboxInspection: ...
```

The adapter, not the model, selects host paths and Docker flags.

Phase 1.5 introduced intrinsic capability validation. Phase 3 registers fake, Docker, and local-unsafe providers behind the same port, resolves the exact persisted selection, and matches per-plan `SandboxRequirements` before initialization or workflow resource creation. A mismatch fails closed; there is no fallback to a weaker provider. Fleet reports and hashes the full descriptor/configuration, binds them to Project and Run, and copies their identities into command evidence and the final bundle. Docker Project/Run state additionally pins the resolved immutable image and local daemon identity.

Implementations:

- `FakeSandboxProvider`;
- `DockerSandboxProvider`;
- `LocalUnsafeSandboxProvider` only after an explicit user selection.

Do not label allowlisted subprocess execution as isolated.

## 4.5 RepositoryProfiler

```python
class RepositoryProfiler(Protocol):
    def profile(self, repository: RepositoryInfo) -> RepositoryProfile: ...
```

The profiler reads a bounded allowlist of regular metadata files through safe repository-relative resolution. Static signals record their source paths; detected commands additionally record structured provenance and confidence. ProjectKnowledge is a factual summary but does not yet attach provenance/confidence to each string. Conflicting supported signals remain explicit ambiguities, and no detected command executes. Identical supported inputs produce the same semantic profile hash.

## 4.6 RepositoryPort

Own Git and candidate-workspace lifecycle from the control plane:

```python
class RepositoryPort(Protocol):
    async def inspect(self, root: Path) -> RepositoryInfo: ...
    async def create_candidate_workspace(
        self, project: Project, run_id: RunId, base_revision: str
    ) -> CandidateWorkspace: ...
    async def compute_patch(self, workspace: CandidateWorkspace) -> PatchInfo: ...
    async def create_verification_workspace(
        self, candidate: CandidateArtifact
    ) -> VerificationWorkspace: ...
    async def apply_candidate(
        self, candidate: CandidateArtifact, expected_target: TargetState
    ) -> ApplyResult: ...
    async def cleanup_workspace(self, workspace_id: str) -> None: ...
```

Use structured subprocess arguments. The model does not invoke `git worktree`, `git reset`, `git clean`, `git stash`, `git push`, or `git apply` directly.

The Phase 1.5 adapter probes repository-local executable integration keys without includes and fails closed on any filter, diff, hook, include, or command surface. It never copies attacker-controlled config-key names into a later child argv or error. Repository discovery failures are generic and discard the unresolved canonical path plus underlying subprocess exception before returning to the application boundary.

Important Docker/worktree consideration: a Git worktree’s `.git` file points to metadata in the main repository. Do not solve this by mounting the host `.git` directory broadly into an untrusted worker container. Git lifecycle and diff extraction run in the trusted control plane. Worker tools receive structured repository views and workspace files; if a build genuinely requires Git metadata, add a deliberately scoped mechanism and security review.

## 4.7 SecretStore

```python
class SecretStore(Protocol):
    def inspect(self, ref: SecretRef) -> SecretInspection: ...
    def resolve(self, ref: SecretRef) -> SecretValue: ...
```

Implemented Phase 2 reference scheme:

- `env:VARIABLE_NAME`.

Keyring and other secret backends remain roadmap work. `SecretValue` redacts string/repr/format output, rejects serialization, and exposes one explicit provider-only reveal method. `EnvironmentSecretStore.resolve` registers the raw value and bounded common encodings with the shared `Redactor` before returning it. Never persist the resolved value. The reference is persisted on Project/Run rows in Fleet state so a malicious repository cannot choose an unrelated ambient environment variable; `.fleet/` stores runtime and provider/model only. Workflow start/resume registers the active Project binding before configuration parsing, and patch apply registers both the current Project and historical Run bindings so credential-only rotation cannot expose an older still-configured value through parser failures.

## 4.8 StateStore

Expose transaction-aware operations for projects, runs, events, tasks, approvals, grants, artifacts, and fleet patches. Avoid a generic key-value interface.

Required properties:

- SQLite foreign keys enabled;
- WAL mode where appropriate;
- schema version/migration table;
- explicit transactions for stage transitions plus events;
- uniqueness constraints for idempotency keys;
- deterministic ordering by sequence number, not timestamp alone;
- no secret values;
- graceful detection of incompatible newer schemas.

## 5. Workflow engine

CoS may propose topology, but `FleetPlanValidator` freezes a valid plan before any worker starts. The scheduler instantiates only planned nodes whose dependencies are satisfied and never derives authority from a role label. Supported strategies and provider capabilities are control-plane inputs, not model declarations.

Implement each supported workflow as an explicit deterministic state machine. Do not let an LLM choose arbitrary next states. The initial `engineer_verifier` code-change strategy follows:

```text
CREATED
  -> INTAKE
  -> SCOPING
  -> WORKSPACE_PREPARATION
  -> IMPLEMENTING
  -> VERIFYING
       -> PASS -> PRESENTING -> READY_FOR_REVIEW
       -> FAIL and retries remain -> REPAIRING -> VERIFYING
       -> FAIL no retries -> REJECTED
       -> INCONCLUSIVE -> PRESENTING with proof gap
  -> optional APPLYING after user command/approval
  -> CLEANUP
  -> COMPLETED
```

Each stage:

- reads a persisted input snapshot;
- emits a stage-start event;
- performs an idempotent or idempotency-keyed action;
- persists output artifact references;
- emits success/failure/pause event;
- commits the next state.

The Phase 2 `direct` strategy terminates after a control-plane presentation and is invalid if a proposed node requests a worker side effect. `single_engineer` may produce a candidate for review but cannot claim independent verification. `engineer_verifier` preserves a fresh verification context and bounded repair loop. These paths work through either runtime adapter. Parallel and arbitrary specialist DAG execution remain unsupported until merge/join ownership and failure semantics are implemented and tested.

### Approval pause

When ToolGateway returns `REQUIRE_APPROVAL`:

1. persist `ApprovalRequest`;
2. persist runtime/workflow checkpoint information;
3. mark run `PAUSED_FOR_APPROVAL`;
4. emit events;
5. stop executing new side effects;
6. release or retain sandbox according to a documented policy;
7. on explicit once/run/project approval, revalidate current target/configuration/policy and issue a scoped capability; explicit resume revalidates again and reserves the same logical intent idempotently;
8. on denial, return structured denial to the agent or fail the stage according to policy.

Do not simply throw an in-memory exception and lose the run.

The implemented Engineer and Verifier approval paths persist paused intent/request state and resume the recorded stage. `AgentStatus.PAUSED` preserves the paused role rather than marking it failed. `Run.engineer_checkpoint: AgentExecutionCheckpoint` retains agent/workspace/sandbox/iteration/creation time and clears after implementation. Its `VerificationCheckpoint` subclass additionally binds final patch and baseline workspace fingerprint; resume reuses the same verifier context and validates canonical patch bytes, with another exact mutation check before accepting its result. After CLI reconstruction, only known active parent sandbox/workspace leases may be rehydrated under the same logical identities and inspected capabilities; outstanding execution leases require recovery and are never replayed. Logical tool retry preserves the original reason (display prose), while every execution-bearing field still participates in exact intent-hash checks. Approval itself does not execute the tool. General interrupted-stage recovery, provider conversation checkpoints and durable usage/budget accounting across pauses remain Phase 5; this flow does not promise restoration of arbitrary provider internals or exactly-once external services.

For a legacy once-only Engineer pause without a checkpoint, resume may adopt only the exact original persisted agent after validated state lookup and run/task/role binding checks. It never substitutes a new principal or upgrades that historical grant's lifetime.

## 6. Agent orchestration target

The rich role inputs below remain the Phase 5 target. Phase 2 supports both deterministic FakeRuntime scripts and live PydanticAI role invocations. In either case CoS returns a strict bounded scope/strategy record, the application-owned FleetPlanner constructs and validates FleetPlan, and Engineer/Verifier receive bounded logical context without host paths, credentials, grants, or executor objects. This proves the real runtime/control-plane boundary; FakeSandbox still prevents claims about actual command execution or OS isolation.

## 6.1 CoS invocation

Inputs:

- user goal;
- repository summary and declared project knowledge;
- active FleetSpec snapshot;
- applicable policy summary without secrets;
- workflow options;
- budgets.

Output:

- `ScopeDecision` and `TaskSpecDraft`;
- proposed `FleetPlan` with the smallest sufficient topology and rationale;
- explicit ambiguities, risks, and required approvals;
- selected workflow.

The application validates and freezes TaskSpec and FleetPlan. CoS cannot invent undeclared tools/roles, raise limits, schedule unsupported topology or claim assurance absent from evidence. Phase 4 validates proposed `allowed_paths` against canonical/protected boundaries and the separately user-reviewed project ceiling; current policy is checked again before execution/resume. Fleet does not derive that ceiling from natural-language intent. Candidate work never implicitly mutates the target checkout: explicit patch review/apply remains required.

## 6.2 Engineer invocation

Inputs:

- immutable TaskSpec;
- selected relevant files/artifacts;
- tool catalog restricted to its role and stage;
- iteration feedback when repairing.

Output:

- `ImplementationReport`.

The application computes the actual patch after invocation; do not trust the Engineer’s changed-file list as canonical.

## 6.3 Verifier invocation

Use a fresh runtime context. Inputs:

- original user goal;
- TaskSpec;
- actual candidate patch metadata/content within limits;
- relevant repository view;
- declared verification commands;
- Engineer evidence labeled as untrusted claims.

The Verifier works in a separate verification workspace built from the candidate artifact. After verification, compute and record whether the workspace was mutated; discard all verifier changes in every case.

## 6.4 Repair loop

- Maximum count comes from the effective policy and cannot be raised by agents.
- Feed only structured verifier failures and relevant evidence to Engineer.
- Every iteration receives a fresh iteration ID and artifact set.
- Recompute the candidate patch and reverify independently.
- Stop on pass, budget exhaustion, denial, cancellation, or max iterations.

## 7. Bootstrap architecture

The complete bootstrap target has four linked outputs:

1. a content-addressed `RepositoryProfile` and factual `ProjectKnowledge` derived without code execution;
2. a repository-specific proposed `.fleet/` configuration with an exact diff;
3. a disposable canary run in Fleet-controlled state storage;
4. a `BootstrapReport` that binds the profile, proposal, sandbox capabilities, canary plan, patch, evidence, and proof gaps.

Never test the first model-powered write path against arbitrary user business code.

The profiler runs before configuration generation. Manifest content, package scripts, Make targets, and CI files are untrusted strings; they may identify candidate commands but are not executed or authorized during init. Static signals carry repository-relative source paths, and detected commands additionally carry structured provenance and confidence. ProjectKnowledge summary strings do not yet carry per-statement provenance. An absent command is left unknown rather than invented.

Phase 3 implements all four items for Docker-selected initialization. Preview computes and displays the bounded proposal without creating Fleet state or target `.fleet/`. Confirmed init stages Fleet-owned state, runs the deterministic disposable fixture through the ordinary planner, gateway, broker, Docker provider, artifact, verification, cleanup, and completion boundaries, validates the hash-linked `BootstrapReport`, and only then atomically publishes the target `.fleet/`. The canary never executes arbitrary user business code. A PydanticAI initialization validates and resolves the explicit BYOK reference before writes, but the bootstrap canary deliberately uses the deterministic fake runtime; provider HTTPS begins only when a role is invoked by `fleet run`.

Initialization stages and validates the complete generated tree before publishing target configuration. Before organization admission, it may accept an identical existing tree, and a credential-reference-only update does not affect repository files. It never merges or overwrites a differing `.fleet/` tree. Phase 6 adds the shared publication lock and durable head guard: after admission, identical init and reference-only rebinding are also rejected, including after the target configuration is moved aside. A different protected setup requires separate registration with prior state preserved. Reviewed FleetPatch is the supported organization-update engine; bootstrap is not an update bypass.

The canary run uses the same application planning, gateway, permission, sandbox, artifact, and completion path as ordinary runs. Target publication requires an isolated Docker Engineer execution and a fresh Docker Verifier execution bound to the final patch, successful terminal inspection, and complete cleanup. Fake and local-unsafe selection can preview but cannot pass this gate; a fake run may prove orchestration and patch integrity only and cannot claim that project tests ran or that OS isolation exists.

Proposed `.fleet/` tree:

```text
.fleet/
  fleet.yaml
  agents/
    cos.md
    engineer.md
    verifier.md
  workflows/
    code-change.yaml
  skills/
  project/
    charter.md
    architecture.md
    verification.yaml
  README.md
```

This is the initial built-in tree, not a closed roster. The FleetSpec schema accepts validated project-specific role and workflow identifiers, while a per-run FleetPlan selects only the required subset. Repository-aware generation may add evidence-backed project knowledge and detected verification commands; it must not invent facts or grant permissions.

Runtime state is outside the repository, selected through `platformdirs`, for example:

```text
<user-data-dir>/agent-fleet/
  state.db
  artifacts/
  workspaces/
  projects/<project-id>/
    canaries/
```

Do not store API keys under `.fleet/` or the state database. Repository `.fleet/fleet.yaml` may store the reviewed runtime and provider/model identifier; only Fleet-owned state may store the `env:NAME` reference.

## 8. Configuration loading

Loading order:

1. parse repository `.fleet/fleet.yaml` as an untrusted request;
2. parse referenced repository role/workflow files within the `.fleet/` boundary;
3. load current user settings and trust rules from the separate Fleet-owned trust store;
4. calculate effective configuration through intersection and validation;
5. snapshot repository configuration for the run, retaining current policy as a separate, revocable authority source;
6. validate runtime and sandbox capability requirements before starting.

ConfigSnapshot captures the exact bounded UTF-8 content/hash of `fleet.yaml` plus every referenced role, workflow and project file, sorted and content-addressed. Referenced role/workflow content is captured, not parsed into a general executable workflow language. The repository requests fake/PydanticAI runtime, provider/model where applicable and an exact fake/Docker/local-unsafe configuration. The explicit `env:NAME` reference comes only from Fleet-owned state and must agree with run overrides. A shared Redactor scans configuration before parsing, writing or snapshotting, with cause-free generic failures for secret-bearing input. Project and every TaskSpec/Run bind this snapshot. Phase 4 separately reloads user policy and checks role/workflow/request/task/sandbox intersections at authorization and resume; frozen repository configuration cannot freeze or bypass later revocation.

Init preview includes the reviewed mode/path proposal and policy revision without creating state. Confirmed initialization binds that review to the current revision; new Project records require a completed trust registration, so a partial registration cannot silently acquire a legacy default. Reinitialization preserves existing mode/paths when their flags are omitted.

`fleet init` is not an in-place merge mechanism. A differing generated tree fails before changing Project/artifact state or `.fleet/`. Before any admitted history, explicit whole-tree review can resolve a new registration conflict. Once an organization head exists, initialization cannot rebind that Project even if generated bytes match or the user moves `.fleet/` aside. Organization evolution uses the reviewed Phase 6 publisher; protected registration changes require a separate registration with preserved prior state, not an init bypass.

Unknown fields fail closed in v0.x unless a documented extension namespace exists.

Do not allow YAML custom object tags. Use safe loading and Pydantic validation. Protect against aliases/oversized input as appropriate.

## 9. Persistence schema

Current SQLite tables (schema version 4):

```text
schema_migrations
projects
runs
tasks
agent_instances
run_events
approvals
capability_grants
artifacts
tool_intents
tool_dispatch_claims
resource_leases
```

Key design points:

- `run_events` has a monotonically increasing per-run sequence.
- schema migration `0002` copies all v1 AgentInstance rows and permits a null `task_id` only for `role='cos'`, so the running CoS lifecycle can be persisted before its ScopeDecision creates TaskSpec; completed CoS rows are rebound afterward.
- approvals have request state and resolution audit fields.
- migration `0004` preserves prior grants and makes their approval reference nullable for persistent-rule receipts. Grants record exact scope hash, source rule, expiry, uses, issuer and consumption/revocation. Request-free receipts are bounded and consumed during reservation, not invented approvals or reusable run grants.
- migration `0004` also adds `tool_dispatch_claims(intent_id PRIMARY KEY, intent_hash, claimed_at)`. Claims are permanent at-most-once execution ownership, with no timeout/reclaim path; interrupted dispatch requires reconciliation rather than replay.
- migration `0005` adds durable aggregate budget/attempt/request/tool accounting; migration `0006` adds exact graph/child/node/join/driver state. Graph details are in section 13.
- project settings and persistent exact rules live in the separately validated/revisioned trust store, not SQLite; policy mutation events record the cross-store publication protocol. Migration `0007` adds accepted conversation ownership; migration `0008` adds the Phase 6 candidate's separate immutable organization journal/admissions, without moving trust into repository files.
- resource leases track worktrees/containers for crash recovery.
- exact ConfigSnapshot and TaskSpec serializations are content-addressed, immutable, and identity-bound to Project/Run artifacts.
- artifact rows point to content-addressed local files.
- RepositoryProfile, ProjectKnowledge, ConfigSnapshot, TaskSpec, FleetPlan, and EvidenceBundle may be stored as typed content-addressed artifacts referenced by backward-compatible Project/Run fields; they do not require one table per type.
- A persisted plan is immutable for resume. The workflow never regenerates topology silently after restart.
- deletions are explicit lifecycle operations; do not cascade away audit history accidentally.

## 10. Error model

Create typed errors with stable codes and user-action guidance. Suggested categories:

```text
CONFIG_INVALID
PROJECT_NOT_GIT
PROJECT_DIRTY
PROVIDER_CREDENTIAL_MISSING
RUNTIME_CAPABILITY_MISSING
SANDBOX_UNAVAILABLE
SANDBOX_CREATION_FAILED
COMMAND_DENIED
APPROVAL_REQUIRED
APPROVAL_DENIED
PATH_OUTSIDE_SCOPE
SECRET_ACCESS_DENIED
MODEL_OUTPUT_INVALID
MODEL_PROVIDER_FAILED
WORKFLOW_INVALID_TRANSITION
WORKFLOW_BUDGET_EXCEEDED
PATCH_TARGET_DIVERGED
ARTIFACT_INTEGRITY_FAILED
STATE_SCHEMA_INCOMPATIBLE
RECOVERY_REQUIRED
```

CLI exit codes should be documented and stable by category. Human messages include a remedy; JSON output includes code, message, details, and correlation ID.

## 11. Observability and usage

- Emit structured local logs with correlation/run/task IDs.
- Events are the source for user-visible run history.
- Redact before writing logs or events.
- Cap command output and store large output as artifacts.
- Record model token/cost metadata only when supplied; label estimates as estimates.
- Phase 2 persists one content-addressed `runtime_usage` artifact for each invocation that reports usage; values are provider-neutral and no price is estimated.
- Telemetry outside the machine is opt-in and out of scope for the initial MVP.
- Provide `fleet logs` from event history, not from scraping terminal output.

## 12. Composition and testability

Every nondeterministic boundary is injectable:

- runtime;
- sandbox;
- state store;
- artifact store;
- repository/Git;
- secret store;
- clock;
- ID generator;
- user approval channel.

A complete fake-adapter stack executes the primary workflow without network, Docker, GitHub, or an API key. PydanticAI adapter and workflow tests use its explicit `TestModel`/`FunctionModel` facilities while live model requests and sockets are denied. The same application services are used with the live adapter; there is no separate “demo” orchestration path.

## 13. Adaptive graph implementation boundary (Phase 5 Milestone 2)

The development branch implements all five plan strategies. Milestone 2 acceptance passed: 1344 default tests, twelve separately enabled Docker tests, nine offline E2E cases and eleven independent delivery-audit cases. Exact overlapping selections and results are tracked in `.agent/plans/2026-09-05-adaptive-graph.md`; this closes neither persistent chat nor the remaining MVP release gates.

`application/graph.py` owns dependency scheduling through `ports/graph.py` and injected execution hooks. `application/graph_workflow.py` bridges those hooks to the existing workflow/runtime/gateway/resource services without recursively starting new public tasks. `adapters/persistence/graphs.py` uses migration 6 to atomically bind the parent plan, internal child Run/Task rows, immutable independent child identities, node revisions, ordered join receipts and non-reclaimable driver claims. It checks duplicated SQL/JSON identities and journal hashes on authority-bearing reads; local SQLite is still not tamper-proof against the OS account.

The independent final Verifier retains parent Run/Task identity. Other nodes receive exact scoped children, their own approvals, and the parent's cumulative budget owner. Concurrency bounds active children while allowing queued writers. Read-only Researcher/Architect reports are typed, size-bounded artifact dependencies, never instructions that can grant a permission. Models cannot change node dependencies, join order, sandbox choice or the effective role/scope ceiling.

Graph ownership spans child dispatch and join. A separate claim generation serializes joined-parent verification, repair and approved resume, including stale simultaneous pause snapshots. Ownership losers cannot fail or clean the winner. Claims have no TTL. A failure after resume preparation but before its Run update remains an uncertain claimed pause; operator-stopped recovery abandons it and cleans exact owned resources rather than replaying it.

RepositoryPort now separates pure `prepare_workspace` identity allocation from `materialize_workspace`. ResourceService persists its exact CREATING lease before any Git effect. Cleanup checks both the path and exact Git worktree registration. Ordered child patches are reapplied to a new parent candidate at the original base; scope/path metadata must agree with actual patch paths. Every final verification uses the normal fresh-workspace path. Sequential parent repair remains bounded and emits `graph.repair_fallback`, preserving the initial join and child provenance.

EvidenceAssembler reads back the graph, exact parent join artifact, child outputs and current terminal cleanup receipts. EvidenceBundle embeds `GraphDeliveryEvidence`; CompletionGate rejects missing or incoherent graph delivery and preserves parent-only verification identities. A child's full-suite failure does not establish joined failure or success: only a fresh parent verifier can test the combined result. Failed pre-join work emits explicit unavailable-evidence diagnostics instead of fabricating a completed graph bundle.

## 14. Persistent conversation boundary (Phase 5 accepted)

`application/conversations.py` is a project-bound facade over the existing WorkflowEngine, inspection, approvals and resource lifecycle. CLI input and progress are asynchronous but the conversation is not a daemon, runtime principal, permission grant or shared specialist. New goals receive fresh root Runs and budgets; identical submission retries do not. Graph descendants retain their existing parent budget ownership and never acquire a separate conversation binding.

Migration 7 adds conversations, turns and claim history. `SqliteConversationStore.register_turn_run` uses a single SQLite transaction at the workflow's existing post-preflight/pre-budget registration boundary. It binds exact project/repository, submission/context hashes, initial Run/config/budget and one opaque execution claim before any CoS request. Duplicates return their original Run without a claim. Shared private connection-local Run insertion/event helpers avoid a nested transaction or weaker alternate workflow preflight. Authority-bearing reads cross-check bounded SQL/JSON identities, immutable receipts and claim history.

Both chat and ordinary workflow resume validate this binding before any terminal, approval or graph shortcut. One active turn and revisioned non-expiring claims prevent another process from replaying uncertain work. Orderly approval pause releases the owner into WAITING; delivery/failure settles the turn only against validated Run/evidence/resource state. An unknown persistence outcome retains ownership even if the displayed Run appears paused. Explicit operator-stopped recovery fences the exact owner, cleans root and descendants, then reconciles the turn; it never restarts a claimed invocation or resets accounting.

`ConversationContext` contains at most eight settled entries and 32 KiB of typed summaries/status snapshots/artifact references. Its truncation is visible and its hash is frozen per submission. Artifact bodies are independently read with a 16 MiB bound and checked against actual bytes/hash/metadata/UTF-8 and registered secrets. Full blobs are not copied into history; bounded CoS response text may appear in result summaries. The current goal remains the existing Run.goal; no raw SDK message history is retained. Historical delivery status is not retroactively rewritten when its patch is later applied. InspectionService revalidates current evidence when constructing user-visible results.

`cli/chat.py` multiplexes POSIX input, compact paginated events and owned execution completion. Slash commands call deterministic application methods. Input buffering is bounded and backpressured; terminal controls and Rich markup are escaped. Ctrl-C/EOF/exit retain and await cancellation rather than abandoning a task. The service snapshots the exact original Run and local execution before scheduling cancellation, so a later turn created by another process cannot be selected after cleanup. Cancellation after a terminal outcome reconciles an already fenced, resource-free turn while preserving the terminal Run's historical status.

Phase 5 acceptance passed: 1472 default tests, thirteen separately enabled Docker cases, nineteen subprocess E2E cases and twenty-nine fresh independent conversation-safety cases. The living persistent-chat plan records exact overlapping selections, failed regressions/fixes and post-gate metadata/archive refreshes. Conversation summaries cannot upgrade simulated evidence, approve a tool or apply a patch.

## 15. Initial repository files

The first implementation phase should create at minimum:

```text
pyproject.toml
README.md
CONTRIBUTING.md
AGENTS.md
.agent/PLANS.md
docs/...
src/agent_fleet/...
tests/...
.github/workflows/ci.yml        # only if requested/appropriate; no secrets
```

Do not add a license without an explicit repository-owner decision. Do not advertise unreleased commands or security properties as complete.
