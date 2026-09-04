# Architecture specification — Agent Fleet

## 1. System overview

```text
┌─────────────────────────────────────────────────────────────┐
│                         CLI / REPL                          │
│ init · doctor · chat · run · status · approve · apply      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    Application Control Plane                │
│                                                             │
│ ProjectService  RunService  WorkflowEngine  CoSCoordinator  │
│ ApprovalService FleetPatchService RecoveryService           │
│ EventRecorder   ArtifactService  BudgetService               │
└──────────────┬─────────────┬─────────────┬───────────────────┘
               │             │             │
       ┌───────▼──────┐ ┌────▼────────┐ ┌──▼────────────────┐
       │ Runtime Port │ │ ToolGateway │ │ State/Artifact    │
       │              │ │ + Permission│ │ Ports             │
       └───────┬──────┘ └────┬────────┘ └──┬────────────────┘
               │             │             │
┌──────────────▼───┐ ┌───────▼────────┐ ┌──▼────────────────┐
│ PydanticAI       │ │ Sandbox + Git  │ │ SQLite + local   │
│ Fake Runtime     │ │ Secret adapters│ │ artifact store   │
└──────────────────┘ └────────────────┘ └───────────────────┘
```

The control plane is deterministic application code. The LLM/harness adapter is one dependency, not the owner of workflow state or security.

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
    permissions.py
    policies.py
    workflows.py
    fleet_patches.py
  application/
    project_service.py
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
fpatch_<uuid>
```

Do not derive security identity solely from user-provided names or absolute paths.

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

### 3.4 AgentSpec and AgentInstance

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

### 3.5 TaskSpec

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
- contextual artifact references;
- risk flags.

After scope approval, TaskSpec is immutable for a run iteration. Material scope changes create a revised TaskSpec and event.

### 3.6 Run and stage state

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

### 3.7 FleetEvent

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
    correlation_id: str
    causation_id: EventId | None
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

### 3.8 Artifact

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
PLAN
PATCH
CANDIDATE_COMMIT
TEST_REPORT
COMMAND_TRANSCRIPT
IMPLEMENTATION_REPORT
VERIFIER_VERDICT
RUN_SUMMARY
FLEET_PATCH
CONFIG_SNAPSHOT
USAGE_REPORT
ERROR_REPORT
```

Artifact content is stored outside SQLite; SQLite stores metadata and content references. Writes are atomic and content hashes verified on read.

### 3.9 ImplementationReport

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

### 3.10 VerifierVerdict

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

Only `PASS` can move directly to ready-for-review. `INCONCLUSIVE` must be presented honestly and may require human decision. Repair loops are bounded.

## 4. Ports and adapter contracts

Protocols should be small, project-owned, and tested by reusable contract suites.

## 4.1 RuntimeAdapter

The runtime adapter turns a typed role invocation into typed output while exposing only ToolGateway-backed tools.

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
8. enforce time, output-size, and call-count limits.

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
    async def evaluate(self, intent: ToolIntent) -> PermissionDecision: ...
    async def resolve_approval(
        self, request_id: PermissionRequestId, resolution: ApprovalResolution
    ) -> CapabilityGrant | None: ...
```

Evaluation is pure where possible. Persistence and user interaction belong to application services.

## 4.4 SandboxProvider

Conceptual models:

```python
class SandboxSecurityLevel(str, Enum):
    ISOLATED = "isolated"
    UNSAFE_HOST = "unsafe_host"
    FAKE = "fake"


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
    security_level: SandboxSecurityLevel

    async def create(self, spec: SandboxSpec) -> SandboxHandle: ...
    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult: ...
    async def terminate(self, handle: SandboxHandle) -> None: ...
    async def inspect(self, handle: SandboxHandle) -> SandboxInspection: ...
```

The adapter, not the model, selects host paths and Docker flags.

Implementations:

- `FakeSandboxProvider`;
- `DockerSandboxProvider`;
- `LocalUnsafeSandboxProvider` only after an explicit user selection.

Do not label allowlisted subprocess execution as isolated.

## 4.5 RepositoryPort

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

Important Docker/worktree consideration: a Git worktree’s `.git` file points to metadata in the main repository. Do not solve this by mounting the host `.git` directory broadly into an untrusted worker container. Git lifecycle and diff extraction run in the trusted control plane. Worker tools receive structured repository views and workspace files; if a build genuinely requires Git metadata, add a deliberately scoped mechanism and security review.

## 4.6 SecretStore

```python
class SecretStore(Protocol):
    async def resolve(self, ref: SecretRef) -> SecretValue: ...
```

Initial ref schemes:

- `env:VARIABLE_NAME`;
- `keyring:SERVICE/ACCOUNT`.

`SecretValue` must make accidental stringification difficult and support explicit redaction registration. Never persist the resolved value.

## 4.7 StateStore

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

Implement the code-change workflow as an explicit state machine. Do not let an LLM choose arbitrary next states.

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

## 6. Agent orchestration

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
- explicit ambiguities, risks, and required approvals;
- selected workflow.

The application validates and freezes the TaskSpec. The CoS cannot invent undeclared tools or roles.

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

`fleet init` has two distinct outputs:

1. a proposed repository-owned `.fleet/` configuration;
2. a disposable canary run in Fleet-controlled state storage.

Never test the first model-powered write path against arbitrary user business code.

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

Runtime state is outside the repository, selected through `platformdirs`, for example:

```text
<user-data-dir>/agent-fleet/
  state.db
  projects/<project-id>/
    artifacts/
    workspaces/
    canaries/
    logs/
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
- config snapshots are hashed and immutable.
- artifact rows point to content-addressed local files.
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
