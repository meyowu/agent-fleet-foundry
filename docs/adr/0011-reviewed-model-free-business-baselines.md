# ADR 0011: keep business baselines separate from agent task evidence

Status: accepted design. The isolated implementation passed independent offline
review and has been integrated; combined main gates, physical execution and Session acceptance are tracked in the September9
approved-business-baseline ExecPlan. This ADR is not execution or release proof.

## Context

Static repository readiness cannot establish whether an existing project's tests
actually run. Users need to review and execute one configured command without
paying for model calls. Existing TaskSpec, Run, resource leases and CommandEvidence
bind real agent/task/stage identities; inventing these identities would corrupt
the evidence and permission contracts. Ordinary candidate workspaces are writable,
whereas a baseline should observe the existing committed source without edits.

## Decision

Introduce a user-controller-only baseline path through the existing PermissionBroker,
ToolGateway, ResourceService, Git and Docker adapters. Construct no model, secret
store, runtime registry, agent or Workflow. Do not expose baseline methods in any
model tool catalog. Keep ordinary Run schemas and public port methods unchanged;
new baseline-owned types and internal protocols carry distinct identities.

A five-minute review binds the project, committed regular-file source manifest,
command, configuration, user policy, image, daemon and resource/mount limits.
Explicit allow-once consent consumes one permanent owner claim before allocations;
one permanent dispatch claim precedes command creation. Capability, source and
policy are rechecked at use. Absence, expiry, process restart and unknown results
never refund those claims. An overlapping active user command deny wins, and no
trust mode or persistent allow can substitute for the explicit baseline consent.

Authority-bearing nested data is bounded canonical UTF-8 bytes plus typed tags and
hashes, not borrowed mutable dictionaries inside a frozen wrapper. Reconstruct and
validate at use. Docker receives the exact reviewed argv without a shell, a read-only
source bind, masked Git control data, fixed bounded scratch, no network, non-root
execution and existing hardening controls. Fake and LocalUnsafe cannot be selected
as baseline executors. No image pull, dependency installation or host fallback.

Ten additive schema13 tables hold independent reviews, consent, permanent claims,
leases, redacted observations, immutable reports and cleanup facts. Do not write
synthetic Run/Task/Agent records or CommandEvidence/EvidenceBundle artifacts.
Reports say `baseline_observation_only`, preserve observed nonzero/unknown results,
and never award CompletionGate or S1 oracle success. No raw output or raw-output
hash is persisted; bounded output is redacted and terminal controls are escaped.

Normal cancellation joins owned work and drains an exact fenced whole-lease set
in execution, sandbox, workspace order. Stopped-owner recovery requires conservative
PID absence and exact reviewed cleanup scope; it can clean, never rerun. Incomplete
child cleanup prevents parent removal. Recovery appends facts/reports rather than
rewriting history. Cooperating organization/trust locks and SQLite CAS do not
protect against arbitrary same-user host writes or unseen filesystem ABA.

## Alternatives

- Treat static readiness as a baseline: rejected; it does not execute tests.
- Create a fake Run or weaken old identity fields: rejected; it conflates user
  observation with actual agent delivery and widens existing authorization.
- Execute directly from CLI or use writable candidate mounts: rejected; execution
  would escape the independent Gateway/permission and read-only source boundaries.
- Retry an uncertain command or sweep all resources: rejected; uncertainty grants
  neither execution authority nor cleanup authority over a different scope.

## Consequences

Schema13 is forward-only: old schema12 binaries refuse migration/opening through
their normal migrating composition. Do not downgrade user state by dropping tables.
All ordinary Run behavior, old schema bytes and explicit security regressions need
requalification. Baseline BLOB growth can hit the existing evaluation observer's
32 MiB per-file/128 MiB total capture ceilings; this is an availability limitation.

Standalone CLI, Session confirmation integration, actual Python/Node execution,
first-user cold starts and live agent delivery are separate acceptance gates.
Offline synthetic Docker transport tests do not prove physical mount enforcement.
An exit-zero baseline is an observation of one command, not project correctness,
a fix, an applied patch or independent task completion.
