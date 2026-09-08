# ADR 0007: Session review, immutable model routing and custom role identities

Status: accepted design, implementation tracked by the 2026-09-07 session-first ExecPlan.

## Context

Persistent chat already owns task execution, but users must leave it to review and
apply results. A single project provider configuration and literal operational
roles prevent project-specific responsibilities and model choices. Merely adding
display labels would not implement the approved product and would obscure trust.
Historical Run, graph, conversation and organization identities are hash-bound.

## Decision

The Session is a foreground presentation over existing application services, not
a second scheduler. Expiring one-use review tickets bind the exact conversation,
selection revision, project, action, patch/proposal and organization generation.
Confirmation revalidates under the same application guard as the effect. A plan
viewer is not a pre-execution approval; that requires its separate durable gate.

Opt-in plan review freezes a revisioned checkpoint after CoS scoping and before
workspace, child or tool dispatch. Explicit user approval changes only the
decision; an atomic single-winner consumption resumes the frozen plan without
rerunning CoS. Unknown consumed execution ownership is never expired or reclaimed
by ordinary resume. Organization publication is fenced while an admitted plan
waits for approval, and cancellation preserves its immutable decision history.

Model profiles and project selections live in user-owned versioned SQLite tables,
not repository YAML. Immutable RunModelBindings pin each actual role ID to a
profile revision and RuntimeConfiguration. A required Run binding hash is written
before any invocation. Descendants inherit it; missing snapshots fail closed.
Aliases and endpoint-like model text never authorize credentials or destinations.
Safe views omit credential references as well as credential values. Profile
changes affect new tasks, not paused ones, and old exact records remain readable.

An optional `.fleet/agents/roles.yaml` joins ConfigSnapshot together with its
bounded Markdown references. Custom roles inherit a supported engineer, verifier,
researcher or architect execution kind. Base tools/steps/delegation and optional
path scope are ceilings; custom catalogs can narrow them, never increase them.
CoS remains unique. CoS output selects role IDs, never permission grants or
execution-kind authority. The deterministic planner derives an execution-kind
binding from the reviewed snapshot and records it in its nodes and instances.

Permissions, grants, tool intents, model bindings and evidence retain the actual
custom principal. The base kind selects only the existing output/tool/workspace
ceiling. Inherited repository permission requests remain requests; a user rule
for `engineer` never matches `backend`. Gateway/Broker revalidate actual principal,
template, task, stage and workspace; Verifier proof keeps its distinct principal,
fresh workspace and final-patch command evidence. Repair must use a reviewed
writer selection, not silently create a different identity.

New optional authority fields are omitted when absent, not serialized as null.
Old canonical hashes therefore stay byte-compatible. Present fields enter new
conversation, graph and organization binding hashes and cannot be stripped to
recover legacy privileges. Forward-only migrations9 (model profiles/bindings) and10
(plan-review heads/immutable versions) preserve existing rows; state downgrade is
not supported.

## Alternatives

Fixed role display aliases would preserve implementation simplicity but fail
actual customization. Letting a harness derive authority from prompts would
violate the independent Permission Broker. Resolving current profiles on every
resume would silently change task identity. Rewriting historical JSON would
invalidate existing review and ownership evidence.

## Consequences

Custom-role and model routing are cross-layer contracts with negative tests at
planning, dispatch, policy, accounting, persistence and evidence boundaries.
Another model is not proof of independent verification. Offline fake execution
is still simulated; neither a dashboard nor a successful Session turn upgrades
its assurance. Hosted UI, additional providers and automatic fallback remain
separate future work.
