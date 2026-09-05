# ADR 0004: Keep adaptive node authority in exact internal child runs

- Status: Accepted implementation and Phase 5 Milestone 2 acceptance; graph checkpoint pending, full Phase 5 pending chat
- Date: 2026-09-05

## Context

An adaptive fleet needs concurrent Engineers and bounded specialist dependencies. Existing grants, checkpoints, tool dispatch claims, command evidence and resource leases bind one exact Run/Task/Agent identity. A Run also has one pending approval and one Engineer/Verifier checkpoint. Sharing that mutable state between simultaneous writers would mix principals, overwrite pauses or require broader authority matching. Ordinary state transitions are not cross-process ownership locks.

## Decision

The control plane freezes a bounded FleetPlan and atomically registers internal child Run/Task identities for non-verifier nodes. Every child inherits the parent's exact base, project, reviewed configuration, runtime and sandbox boundary, and narrows its task scope. It shares the parent's immutable aggregate budget owner but not its grants. The independently persisted child binding is checked before public patch application and resume; changing Run display metadata cannot make an internal child externally executable or applicable.

A durable graph driver claim and independent node revision checks serialize orchestration. Claims never expire into an implicit right to replay. A stopped owner requires explicit recovery and abandonment of uncertain work. The parent uses WAITING_FOR_CHILDREN for aggregated child pauses; it never invents a parent approval or broadens a child-run grant. Cancellation atomically fences new child dispatch, then retained cleanup proves absence of exact descendant resources.

After the child join, another exact continuation claim serializes the parent's verification, repair and approved-pause rehydration. A public resume of a RUNNING parent is refused; a stale paused snapshot must still win the durable CAS before any async effect. Ownership losers cannot mark the winner failed or clean its workspaces. Claims release on an orderly pause or immediately before synchronous final evidence. A resume-preparation failure whose persistence outcome is uncertain retains ownership for operator-stopped recovery, including when the visible Run still says paused.

Researcher and Architect are ephemeral read-only roles with bounded typed reports, not authority-bearing personalities. They receive only gateway-backed repository observation tools. Independent Engineers work in separate pre-recorded workspaces. The trusted join records ordered child patch/report hashes, applies patches in stable node order to a fresh parent workspace, and extracts a new canonical patch. Conflicts preserve individual artifacts and fail closed. Child commands remain child evidence; a fresh parent Verifier checks the complete original task and joined patch.

If combined verification fails, a documented deterministic fallback runs one parent Engineer within the original scope and repair ceiling, followed by another fresh parent Verifier. The original graph remains immutable provenance; successful children are not replayed or refunded. An event distinguishes this repair from the original join.

EvidenceBundle carries GraphDeliveryEvidence with the exact completed plan/node snapshot, parent join reference and child cleanup receipts. Both actual artifact read-back and exact plan/node equality are mandatory; hashes of the producer's serialized plan, join preparation and cleanup receipts must match their artifact references. A self-consistent substituted embedded plan is not authoritative. Child commands remain child-owned, even when their full suite cannot pass before a sibling patch exists.

Known approved-resume rehydration failure records FAILED, atomically fences the graph to clear its claim, then cleans exact parent resources. Ordinary release cannot run after terminalization. A later uncertain resume-persistence failure retains non-replayable ownership for explicit recovery. Missing artifact bytes raise a typed cause-free integrity error rather than exposing an OS path exception.

## Consequences

- Users inspect one parent result while retaining exact child permissions, budgets, artifacts and cleanup evidence.
- More tasks than concurrency slots can queue without enlarging the execution boundary.
- Approval and completion order cannot determine merge order.
- Restart is conservative: a persisted pause can resume exactly, but unknown dispatched work cannot be assumed absent or free.
- SQLite stores graph ownership and node receipts, not provider SDK history or model-created execution capabilities.
- Graph verification is a separate acceptance milestone; declaring five shapes in a schema does not prove they execute.

## Acceptance evidence

On 2026-09-05, the unchanged source/test aggregate `4cbef9616084ad1465ee5fd84b97f81763f282bc95b96c11b5bb7d35cfeafeb9` passed `1344` default tests with `13` explicit skips. The separately enabled Docker suite passed all twelve cases, with zero managed containers and zero active leases across 22 test databases. Nine subprocess E2E and eleven independent delivery-audit cases passed; exact commands, times and retained failed attempts are in the graph ExecPlan. Final documentation archive/schema checks passed four cases in 4.37s and repeated in 1.73s. M2 is accepted, not committed yet. No live-provider, full-Phase-5 or release acceptance follows from this record.

## Alternatives

- One shared Run for all agents: rejected because exact approval/checkpoint/evidence identities would collide.
- Recursively call public start for every node: rejected because it adds new CoS planning, resets implicit budgets and loses the frozen parent contract.
- Let models select merge order or approve dependencies: rejected because orchestration and authorization are control-plane responsibilities.
- Reuse child tests as final parent proof: rejected because independent changes may conflict behaviorally after joining.
- Automatically reclaim stale claims: rejected because elapsed time does not prove the old owner or its side effects stopped.
