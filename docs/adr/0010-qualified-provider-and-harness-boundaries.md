# ADR 0010: qualify provider transport separately from the Harness loop

Status: accepted design; implementation and acceptance are tracked per combination
in the September9 S1–S3 ExecPlan. This ADR does not itself admit a new adapter.

## Context

An upstream framework's provider list is not Fleet's support matrix. Provider SDKs
can consult ambient credentials, change endpoints, retry requests, emit raw logs or
mark clients closed before transport cleanup finishes. Harnesses may deduplicate
tool calls, execute native tools, export traces or drop raw usage/response identity.
Those behaviors cannot acquire Fleet permissions or bypass durable budgets.

## Decision

Provider-specific factories pin explicit credentials, official endpoints and admitted
nonstreaming request shapes. Credentials stay in the control plane. Transport guards,
stateless cookies and per-request single-send tickets prevent an upstream fallback
from spending a second request reservation. A retained cleanup task waits through
repeated cancellation; failure is recorded rather than presented as released state.
SDK/policy errors are projected to finite diagnostics without raw exception chains.

Each Harness implements a real SDK loop behind project-owned runtime contracts.
Fleet still owns role identity, full tool-batch validation, budget reservation,
PermissionBroker decisions, execution, artifacts and completion. The new Agents
SDK loop interrupts every function call. It checks the raw batch before the SDK
can deduplicate it; SDK callbacks only return single-use results after Fleet has
executed the authorized effects. SDK approval is never user permission.

For Agents SDK0.22.1, external action schemas use strict wire mode and original
local validators. Engineer execution-kind ImplementationReport proposals use
strict wire mode with the original closed, seven-required-field schema; the pinned
SDK must preserve its schema exactly. Other terminal proposals retain explicit
non-strict wire mode because bounded-dictionary output fields such as
ScopeDecision.role_selections are incompatible with the SDK strict converter.
This is a fixed execution-kind policy, never a try-strict-then-fallback algorithm.
The original output schemas and strict local Pydantic/role validation are unchanged,
including semantic constraints that strict generation alone cannot establish.
Known local terminal-schema failures expose only a fixed stage message; earlier
malformed-envelope failures retain their separate existing projection. Neither path
reads provider error data or turns a passing tool into an accepted final report.
The September12 Engineer-terminal ExecPlan records candidate acceptance separately;
this decision alone does not establish live compatibility or explain live05's cause.
No dynamic fallback or malformed-output acceptance is permitted. Native tools,
handoffs, hosted sessions, streaming and SDK checkpoint export remain excluded.

Response identity and raw usage must be qualified before SDK conversion discards
them. Unknown usage is not zero; reported overshoot is retained and stops further
admission. A reservation is not an invoice guarantee. The pinned SDK's explicit
disabled/no-processor tracing setup is a Fleet process policy, not per-call OS
isolation or a claim about other software on the host.

The bounded LangGraph1.2.11 path uses a new async StateGraph per invocation, with
only bounded scalar graph state and separately retained request/action data. It
does not install a native ToolNode, checkpointer, cache, hosted session or exporter.
It receives raw OpenAI Responses bytes through a factory-only single-send mode;
original JSON Schema and local role validators check the full tool batch before
any reservation or Gateway effect. The independently owned task ledger drains
request, graph and client cleanup even when repeated cancellation interrupts the
SDK's own exit path. A cleanup failure cannot become terminal success.

Configured model/provider constraints are enforced in generated defaults, edited
FleetSpec, distributed Schema, immutable ModelProfiles and runtime preflight. A
consistent public contract requires all those checks; a later runtime rejection
does not excuse a permissive configuration schema. The prior LangGraph config
omission and its corrective evidence remain in the active plan.

## Alternatives

- Rely on provider names and SDK defaults: rejected because endpoint, retry and
  native-effect behavior would escape the reviewed Fleet contract.
- Reimplement every model loop as a fake adapter: rejected because this would not
  establish replaceability or actual upstream SDK behavior.
- Rewrite all output models for SDK strict schemas: rejected because it changes
  existing public contracts solely for a transport restriction.
- Treat close flags, SDK token defaults or Verifier text as proof: rejected; use
  physical close observations, raw presence-aware usage and authoritative evidence.

## Consequences

Every supported provider/Harness combination needs actual-SDK offline tests and
separate opt-in live qualification. Upgrades must requalify version-specific hooks.
Direct RuntimeConfiguration support does not imply ModelProfile catalog support.
Absent provider credentials remain NOT_RUN. No model credential is reused at a
different provider to fill an acceptance gap.
