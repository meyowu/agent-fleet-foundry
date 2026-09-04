# Architecture specification — Agent Fleet

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

Implementation boundary: Phase 0/1.5 enforces durable state/artifacts, hardened Git worktrees, bounded static repository intelligence, adaptive plan artifacts for direct/single/pair offline paths, an independently injected baseline PermissionBroker, explicit fake-sandbox capabilities, CompletionGate, exact allow-once, and guarded patch application. Parallel/specialist scheduling, provider/BYOK, Docker, complete trust semantics, persistent chat, and operational FleetPatch remain later phases.

## 2. Layering and dependency rule

Recommended package layout:

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

Initial event types:

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

`EvidenceBundle` is assembled by the control plane from authoritative state and content-addressed artifacts. It binds project/task/run identity, the exact ConfigSnapshot and TaskSpec artifact IDs/hashes, FleetPlan, required evidence IDs, base revision, canonical changed paths and patch hash, exact command records, verifier identity/verdict, the Verifier-owned command-evidence IDs, reported repairs/regressions/proof gaps, Verifier workspace-mutation detection, risks, and proof gaps. Each evidence item records provenance and strength as `simulated`, `observed`, or `independently_verified` in the Phase 1.5 contract. Inspection revalidates the stored bundle identity/hash and exposes a bounded evidence summary rather than only opaque artifact IDs.

`CompletionGate` evaluates every required criterion against those records and emits a `CompletionDecision`. Evidence strength cannot be asserted by an Agent or upgraded by serialization. Verifier evidence must be authoritative, owned by the recorded Verifier, and bound to the final patch; any reported proof gap, contradictory PASS with repairs/regressions, or detected Verifier-workspace mutation fails closed. Phase 1.5 can map its single scripted verdict only to a single acceptance criterion; a multi-criterion task produces inconclusive assessments and `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`. In particular, FakeSandbox output is `simulated`, never executed proof, so an otherwise successful offline workflow reports `verified_complete=false` with a proof gap.

### 3.14 FleetPatch

`FleetPatch` is a typed organizational-change proposal bound to dedicated FleetPatch/Project IDs and a base FleetSpec hash. The Phase 1.5 foundation validates case-insensitive path uniqueness, exact content hashes, registered-secret absence across the entire serialized proposal through a required control-plane Redactor, and only the minimum path set: `agents/**`, `workflows/**`, the named project charter/architecture/verification files, and `.fleet/README.md`. It intentionally rejects `.fleet/skills/**`; Phase 6 may add skill changes together with their semantic and security contract. Semantic/textual diff artifacts, persistence, and operational show/apply/rollback also remain Phase 6.

## 4. Ports and adapter contracts

Protocols should be small, project-owned, and tested by reusable contract suites.

## 4.1 RuntimeAdapter

The runtime adapter turns a typed role invocation into typed output while exposing only ToolGateway-backed tools.

An invocation contains logical repository/workspace identifiers and bounded artifact references only. It never contains a host filesystem path, `SandboxHandle`, provider credential, permission grant, or callable executor. A runtime may return a typed proposed action; it cannot perform that action directly. Built-in runtime adapters must not import concrete repository/sandbox adapters or subprocess execution code.

Conceptual interface:

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
    agent: AgentSpec
    instructions: str
    input: JsonValue
    context_artifact_ids: list[ArtifactId]
    max_steps: int
    checkpoint_ref: str | None = None


class AgentInvocationResult(BaseModel):
    output: JsonValue
    usage: UsageRecord | None
    checkpoint_ref: str | None
    provider_metadata: dict[str, JsonValue] = {}


class RuntimeAdapter(Protocol):
    @property
    def capabilities(self) -> frozenset[RuntimeCapability]: ...

    async def invoke(
        self,
        request: AgentInvocation,
        tools: ToolCatalog,
        event_sink: EventSink,
    ) -> AgentInvocationResult: ...
```

Do not force all harnesses to serialize their internal state into a common message format. Store an opaque checkpoint reference plus portable task/artifact context. A runtime without checkpoint support can resume by starting a new invocation with a system-generated summary, provided the workflow marks that degradation explicitly.

The first implementations are:

- `FakeRuntimeAdapter` for deterministic tests;
- `PydanticAIRuntimeAdapter` for real model calls.

The PydanticAI adapter must translate project output models and tools without leaking PydanticAI objects into domain/application code.

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
8. enforce time, output-size, and call-count limits as Phase 3/5 executors and budgets are added.

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
    async def resolve_approval(
        self, request_id: PermissionRequestId, resolution: ApprovalResolution
    ) -> CapabilityGrant | None: ...
```

Evaluation is pure where possible. Persistence and user interaction belong to application services.

PermissionBroker is independently injected into ToolGateway; it is not a private conditional inside the gateway and is not supplied by the runtime adapter. The broker evaluates canonical identity and resource context built by the control plane. Phase 1.5 retains the narrow baseline rules and exact allow-once grant. Run-wide and persistent exact rules, explanation/revocation UI, and the user trust store remain Phase 4.

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

Phase 1.5 validates intrinsic capability coherence and matches the exact immutable FakeSandbox descriptor before initialization or workflow resource creation. A mismatch fails closed; there is no fallback to a weaker provider. It reports the full descriptor at init and binds provider/security level into each command record. Per-plan `SandboxRequirements` matching and a complete immutable capability snapshot in run evidence are required with real providers in Phase 3.

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
    async def resolve(self, ref: SecretRef) -> SecretValue: ...
```

Initial ref schemes:

- `env:VARIABLE_NAME`;
- `keyring:SERVICE/ACCOUNT`.

`SecretValue` must make accidental stringification difficult and support explicit redaction registration. Never persist the resolved value.

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

The Phase 1.5 `direct` strategy terminates after a control-plane presentation and is invalid if a proposed node requests a worker side effect. `single_engineer` may produce a candidate for review but cannot claim independent verification. `engineer_verifier` preserves a fresh verification context and bounded repair loop. Parallel and arbitrary specialist DAG execution remain unsupported until merge/join ownership and failure semantics are implemented and tested.

### Approval pause

When ToolGateway returns `REQUIRE_APPROVAL`:

1. persist `ApprovalRequest`;
2. persist runtime/workflow checkpoint information;
3. mark run `PAUSED_FOR_APPROVAL`;
4. emit events;
5. stop executing new side effects;
6. release or retain sandbox according to a documented policy;
7. on approval, issue a scoped capability and resume the same logical tool intent idempotently;
8. on denial, return structured denial to the agent or fail the stage according to policy.

Do not simply throw an in-memory exception and lose the run.

## 6. Agent orchestration target

The rich role inputs below are the Phase 5 target. Phase 1.5 uses deterministic FakeRuntime scripts: CoS returns a bounded scope/strategy record, the application-owned FleetPlanner constructs and validates FleetPlan, and Engineer/Verifier receive only the minimal scripted goal/scenario/iteration/patch fields. This proves control-plane routing and evidence integrity, not model reasoning quality.

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

The application validates and freezes the TaskSpec and FleetPlan. The CoS cannot invent undeclared tools or roles, raise limits, schedule unsupported topology, or claim assurance that the plan/evidence cannot provide.

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

Phase 1.5 implements items 1 and 2 and creates the disposable fixture for item 3. It does **not** execute that fixture during `fleet init` and does not emit a `BootstrapReport`; isolated canary execution and the bound report remain Phase 3 acceptance work.

When implemented, the canary run must use the same application planning, gateway, permission, sandbox, artifact, and completion path as ordinary runs. The current fake sandbox produces simulated evidence only, so a separately requested fake run can prove orchestration and patch integrity but cannot claim that project tests ran or that OS isolation exists.

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

Do not store API keys under `.fleet/` or the state database.

## 8. Configuration loading

Loading order:

1. parse repository `.fleet/fleet.yaml` as an untrusted request;
2. parse referenced repository role/workflow files within the `.fleet/` boundary;
3. load user settings and trust rules from user config/data directories;
4. calculate effective configuration through intersection and validation;
5. snapshot the effective non-secret configuration for the run;
6. validate runtime and sandbox capability requirements before starting.

The complete list is the target pipeline. Phase 1.5 implements steps 1–2, validates the FleetSpec and VerificationProfile schemas, and captures the exact bounded UTF-8 content/hash of `fleet.yaml` plus every referenced role, workflow, and project file in a sorted content-addressed `ConfigSnapshot`. The composition root injects the same Redactor used by state/artifacts; generated and loaded configuration is scanned before parsing, writing, or snapshotting, and secret-bearing parser failures are replaced by cause-free generic errors. Project and every TaskSpec/Run bind this snapshot. User settings/trust intersection and a broader effective configuration remain Phase 4 work.

Unknown fields fail closed in v0.x unless a documented extension namespace exists.

Do not allow YAML custom object tags. Use safe loading and Pydantic validation. Protect against aliases/oversized input as appropriate.

## 9. Persistence schema

Initial SQLite tables may include:

```text
schema_migrations
projects
fleet_spec_versions
runs
tasks
agent_instances
run_events
approvals
capability_grants
artifacts
fleet_patches
resource_leases
```

Key design points:

- `run_events` has a monotonically increasing per-run sequence.
- approvals have request state and resolution audit fields.
- capability grants record exact scope, expiry, remaining uses, issuer, and consumption.
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

A complete fake-adapter stack must execute the primary workflow without network, Docker, GitHub, or an API key. The same application services are used with real adapters; do not create a separate “demo” orchestration path.

## 13. Initial repository files

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
