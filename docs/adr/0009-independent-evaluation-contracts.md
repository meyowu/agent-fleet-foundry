# ADR 0009: Evaluation observations are not execution authority

Status: accepted design; implementation and qualification are tracked in the
S1–S3 living ExecPlan. This ADR does not declare the task campaign complete.

## Context

A live canary can demonstrate one real role chain, but cannot establish general
task reliability. Product CompletionGate results, user patch application and
external acceptance measure different things. Counting only completed artifacts
would omit preflight failures, unknown requests and missing attempts; counting the
best repeated result would inflate first-round success.

## Decision

Use a separately preregistered, content-addressed EvaluationManifest with immutable
repository/cohort/task/configuration/oracle identities, explicit attempt slots and
finite budget values. Record product status, external result, user acceptance,
application, cleanup and reported usage as separate observations in OutcomeRecord.
No manifest or outcome grants provider, tool, sandbox or patch-application authority.

The first increment is a pure deterministic reporter over deeply immutable scalar
and tuple contracts. It revalidates inputs, preserves every first-round slot in its
fixed denominator, separates repeated/auxiliary attempts and retains missing,
not_run and dispatch_unknown distinctly. Only entirely unobserved groups have a
null success rate. Costs absent from provider reports remain unknown; reported
amounts are grouped by currency and never imply complete billing.

Typed artifact references establish structural linkage only. A later trusted reader
must verify actual artifact bytes and source/Run/configuration/oracle identity;
the reporter cannot inspect files or decide that a Key Result passed. Code-change
acceptance needs the frozen independent oracle, patch, verification, explicit
application, post-apply and cleanup evidence. Read-only acceptance does not require
inventing a patch. Product Verifier output is not the external oracle's answer.

Campaign persistence and execution are subsequent vertical slices: bind attempts
to actual root Runs, reserve atomically alongside the existing runtime ledger and
preserve uncertain dispatch without replay. Do not alter historical Run JSON or
invent a cross-project parent Run to reuse the current project-scoped budget owner.
Existing Gateway, PermissionBroker and Sandbox remain the sole effect boundary.

The later terminal-observer candidate did not pass physical read/write boundary
qualification. Its two recording entries are disabled before state access. Original
campaign/dispatch/budget records remain authoritative, and absence of a final outcome
must remain visible. A bounded descriptor-captured historical view may support
inspection, but publishing such a view to another file cannot provide atomic CAS
against concurrently changing original SQLite state. Do not substitute that design
for the unfulfilled terminal-write requirement or call read-side repair full
evaluation acceptance. The native qualification, rejected alternatives and exact
remaining gate are retained in the active plan.

## Alternatives

Ad-hoc test totals do not preserve frozen denominators or failure provenance.
Embedding mutable historical CommandSpec/budget/CompletionDecision objects inside
a frozen outer wrapper would not create a deeply immutable snapshot. Trusting
model-provided verdicts or structurally valid artifact IDs would collapse the
independent evidence boundary. All three alternatives are rejected.

## Consequences

The first public schemas support reproducible structural reporting, not an
execution CLI, provider qualification or authenticated evidence attestation.
There is no v1 exclusion mechanism or automatic KR PASS. Holdout retirement needs
a new manifest revision; a cohort label alone cannot prove non-exposure. The
accepted small live canary remains separate from the preregistered broader baseline.
