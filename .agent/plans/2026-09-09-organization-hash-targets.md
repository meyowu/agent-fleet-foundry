# Bind the CoS proposal hash tool to organization targets

This is a living ExecPlan. Maintain Progress, Discoveries, Decision Log and Outcomes.

## Purpose and user-visible result

An ordinary code-change task must not use the organization proposal hash helper as
a general source-code drafting utility. The latest bounded nano canary repeatedly
hashed invented Python source until its invocation budget was exhausted. Require
each hash request to identify a valid organization target and operation, while
retaining natural-language FleetPatch proposals and explicit user review/application.

For example, `fleet run "Fix division by zero"` still asks CoS for ScopeDecision;
hashing `src/calculator.py` is rejected. A lasting rule request can still propose
an exact replacement of `.fleet/project/verification.yaml`, without applying it.

This is target-bound misuse reduction, NOT enforced natural-language intent routing.
A model could still mislabel content as an organization file or repeat valid helper
calls. Only the existing invocation budgets bound those repetitions. No live
success is inferred from this change or from an offline scripted model.

## Scope and ownership

Root is the only Writer in the main checkout for this slice. Another Writer works
on an isolated business-baseline clone; preserve those independent edits.

Production ownership:

- `src/agent_fleet/application/proposal_tools.py`: immutable target-bound helper.
- `src/agent_fleet/application/workflow.py`: pass the captured visible path set.
- `src/agent_fleet/domain/fleet_patch.py`: additive shared target-path validator.
- `src/agent_fleet/adapters/runtime/prompts/cos.md`: precise helper usage guidance.

Test ownership: `tests/unit/test_proposal_tools.py`,
`tests/contract/test_action_tool_schemas.py`, `tests/evolution_fixtures.py`,
`tests/contract/test_openai_agents_runtime.py`,
`tests/contract/test_langgraph_runtime.py`,
`tests/integration/test_cos_workflow_context.py`, and new narrowly scoped helper
contract tests if needed. Record extra production ownership before edits.

Root also owns this plan, the S1-S3 plan, README and relevant security/user guidance.
An independent Verifier reviews frozen source and actual persisted test evidence.

Out of scope: changing provider/model/endpoint, increasing budgets or retries,
automatic paid retries, intent keyword heuristics, deleting organization support,
new Run/Task/CLI/Session/public model schemas, migrations, permissions, sandbox
authority, applying generated target patches, or implementing full two-stage CoS
intent routing. The accepted strict Verifier correction remains unchanged.

## Current repository state

Baseline commit `a4952dd` has source/test/dependency digest `092b8228` and fresh
3743 passed/23 optional skipped tests over3766 identities. Its real canary failed
before Engineer/Verifier: four responses reported39577 tokens; three pure helper
executions occurred and no Gateway effect occurred. The first and last provider
outputs request the same invented201-byte source text. Historical failures remain.

`Workflow._scope` always supplies `EvolutionContext.input` and constructs
`ProposalHashToolCatalog` for nonfake runtimes. No trusted organization-purpose
field exists in the current Run/CLI/Session entry. The catalog currently accepts
only content. `EvolutionContext.visible_paths` is a frozenset of complete visible
organization files, NOT a complete list of omitted or existing paths.

The existing CoS prompt already reserves hashing for explicit lasting rules.
Independent offline actual-FunctionModel and installed OpenAI/MockTransport probes
retain original context and prior tool call/result identities correctly; no
continuation loss was reproduced. This does not establish vendor-side causality.

## Security impact and proposed design

Keep the tool name `fleet_content_sha256`, its pure/non-side-effect classification,
bounded content computation, invocation lifetime and exact call-ID idempotency.
It reads no repository or user state, performs no I/O and grants no permission.

Its required exact argument object becomes `{operation, path, content}`:

- operation is one plain string, exactly `add` or `replace`.
- path is one plain canonical repository-relative `.fleet/` target,8-4096
  characters, accepted by existing FleetPatch mutable-target rules and the
  existing organization-tree path restrictions (including sensitive names/depth).
- content retains32768-character/65536-UTF-8-byte limits and the runtime's
  existing whole argument-JSON bound. No budget limit is widened.

Add a public target validator in `domain/fleet_patch.py` that combines existing
FleetPatch canonical path validation, the module's existing mutable-path allowlist,
and `organization_tree.validate_organization_path` after validating/removing the
exact `.fleet/` prefix. Do not call the old private allowlist predicate on arbitrary
paths: it assumes prefix validation already happened. Do not change existing
FleetPatch/schema/whole-tree validation paths or their acceptance semantics.

The catalog constructor requires trusted `visible_paths`; validate an exact
frozenset of at most organization_tree.MAX_FILES plain strings and capture it
immutably. It must not retain mutable EvolutionContext.input or caller mappings.
REPLACE requires exact membership/spelling. ADD rejects case-insensitive known
visible collisions; it may hash an otherwise allowed new target. Since omitted
existing paths are unavailable here, actual existence and all other collisions
remain the unchanged proposal/evolve_tree gate, never an inferred authorization.

Validate exact argument shape before callbacks or serialization. Capture all three
plain scalar strings before validation/redaction callbacks. Include operation,
path and content in the canonical call identity hash; an existing call_id cannot
move identical content to another target or operation. Repeat calls recheck the
current secret registry; returned copies cannot mutate the stored result.
Return the validated operation/path with its digest and byte count. Do not infer
a path for legacy content-only calls, silently add defaults, or expose an unbound
compatibility alias. Keep all max_calls, secret, callback, mutation and replay checks.

`Workflow._scope` passes the existing immutable visible set from its captured
EvolutionContext. Existing runtime adapters consume the dynamic catalog; no
adapter capability/output routing change is needed. CoS guidance clearly states
ordinary ScopeDecision needs no hash, and organization hashes require exact
operation/path/content. The model still cannot approve or apply a FleetPatch.

## Public contracts and compatibility

This is a model-tool argument contract change, not a CLI/public Pydantic model
schema or stored record migration. Existing content-only direct Python catalog
callers and synthetic fixtures must supply the required target fields and visible
set. The old ambiguous form must fail closed; no compatibility fallback.

Full FleetPatch proposal validation, exact before/after hashes, complete-context
rules and reviewed apply/rollback stay authoritative and unchanged. Pure helper
success proves only the supplied text's digest for a stated eligible target.

## Milestones and implementation

1. Add the reusable path validator and target-bound catalog. Test source/protected/
   traversal/control/sensitive/deep paths, valid existing replacements/new ADDs,
   omitted REPLACE rejection, visible ADD collision and immutable target identity.
2. Wire the existing Workflow context and update model guidance/synthetic fixtures.
   Exercise ordinary ScopeDecision and real offline organization proposal journeys
   through existing adapters, preserving no-apply and exact persisted proposal tests.
3. Freeze the candidate, complete focused/static/full offline regression and fresh
   independent verification. Rebuild current documentation/package archives.
   Record exact results and historical failures before scoped commit/push.

## Validation plan

Run with no credentials/network/Docker in ordinary tests:

    .venv/bin/ruff format --check .
    .venv/bin/ruff check .
    .venv/bin/mypy src tests scripts/run_live_canary.py
    .venv/bin/python -m agent_fleet.schemas.generate --check
    uv lock --check --offline
    .venv/bin/python -m pytest -q
    git diff --check

Use the established exact-identity disjoint default matrix if resource contention
requires partitioning; run the unchanged sensitive cancellation oracle last alone.
Record exact command/JUnit identities, skips and import/source/dependency hashes;
do not describe carried or scripted results as new live executions.

Retain all original helper privacy/hostile-subclass/callback/argument-size/call-limit
tests and adapt only their required target fixtures. Add path/operation swapping
under the same call ID, registered-secret additions before exact replay, mutated
definitions/results, full-batch pre-effect rejection and actual strict SDK wire
schema checks. Exercise OpenAI Agents/LangGraph dynamic catalogs as well as
PydanticAI; do not infer a live qualification from mock transport.

Independent acceptance must inspect frozen code, unchanged public schemas and
actual persisted workflow/proposal/no-apply results. A future paid canary requires
a separate explicit before-dispatch one-attempt contract after these gates; none
is authorized by this implementation plan.

## Rollback and recovery

No new persistence or external effect exists. Roll back only these reviewed changes
if necessary, preserving unrelated work and all failed receipts. A failed helper
call does not become a successful proposal, authorize application or replay an
already committed effect. Existing request budgets and no-retry-after-effect rule
remain unchanged. Do not restart any earlier paid run.

## Progress

- [x] (2026-09-09 21:00:24 UTC) Independent final3fe live audit sealedFAIL,
  receiptSHAf89db69bbdc4624907e93bef52ae60a3fd3d3996a809e9e66db8b1126c818727.
  Source513 and dependency bytes unchanged;113 live/91 bootstrap events match
  original SQLite and42 Artifact bindings are physical. Two live python-test
  commands exit0 on identical01c97c27 patch; exact .fleet read denial has zero
  dispatch and original Broker replay agrees. No accepted VerifierVerdict; live
  Gate remains false. Eight responses50560 tokens; zero outstanding/unknown.
  Twelve released leases, four absent paths/containers and empty installation
  scope; both original-only Git registries and unchanged unapplied target checked.
  One private transcript-expectation failure was retained then corrected to
  distinguish bootstrap unittest from live pytest; original evidence unchanged.
  The source freeze is released for separately contracted successor work.

- [x] (2026-09-09 20:44:18 UTC) Separate parent3fe canary FAILED after CoS and
  Engineer completed: Verifier ran python-test then requested repo.read_file
  on .fleet outside task scope. Original intent received protected denial and
  no dispatch; no accepted verdict. Eight requests50560 known tokens, five tools,
  no unknown/outstanding/reserved requests, no replay or apply. This failure
  does not erase local target-bound security acceptance or prove general intent
  routing. Independent actual live cleanup/evidence audit remains pending.

- [x] (2026-09-09 20:42 UTC) Independent final local prerequisite readback
  sealed20:39:01UTC, SHA02164f91045e: matrix3834 exact/3811PASS/23SKIP;
  static six gates; current archives316 runtime/guide files each; component524;
  final receiver070152a2 accepted16 preflight-only controls. Root read and
  hash-verified the seal before credential handoff. No current live result yet;
  any paid canary belongs only to the separate parent20:16 contract.

- [x] (2026-09-09, before implementation) Read-only source and SDK history mapping
  completed; choose the narrow target-bound contract with explicit limitations.
- [x] Implement and test immutable catalog/path binding.
- [x] (2026-09-09, focused implementation) First selected unit, SDK/Harness and
  workflow/proposal run:320 passed in26.21s. Whole Ruff lint and mypy365 files pass.
  Exact command and320 identities are retained in focused.xml under the private
  hash-target evidence directory; these overlap future full-suite coverage.
- [ ] (2026-09-09, added SDK continuation checks) Initial26-case SDK module run
  retained1 failure/25 passes0.62s: the test receiver assumed every Responses input
  item had a type field, but ordinary input messages omit it. Correct only that
  receiver's discriminator lookup to item.get; retain exact return call-ID,
  path/operation/hash/size assertions. This is a test-fixture correction, not a
  provider continuation fix or accepted retry. Fresh complete replay follows.
- [x] Verify shared adapter/workflow compatibility and exact proposal persistence.
- [ ] Complete full gates, fresh independent review and current documentation.
- [x] (2026-09-09 20:02 UTC) Corrected complete SDK module26 passed0.44s;
  both actual installed SDK mock wire continuations preserve exact call-ID and
  target-bound result, and invalid companion targets block the complete batch
  before any hash execution. No production correction was needed for this replay.
- [ ] (2026-09-09 20:03 UTC) Freeze3fe0cafe09486ffc6f7c68d9580a3d3388db3ef9e47121d92948dda08d200468
  covers all513 source/test/script/dependency paths. Full matrix collected3834
  identities and is running; fresh independent component verification is assigned.
  Source remains fixed; whole-suite acceptance and current archives are pending.
- [x] (2026-09-09 20:24:24 UTC) Independent component PASS sealed with receipt
  SHA575f5234491aed6c67d7fb260bfb7e84036441afc801c4d40f055579f868c10e.
  Exact10-file owned digest65dbf84ef43044b17d846d850b156f8fa42af94d8d67eb018f30eafed7c696be
  and full3fe0cafe code unchanged. Fresh524 unique passes:324 focused/40.57s,
  168 legacy/.69s,26 independent/.31s,and6 additional actual SDK/LangGraph
  controls. Full old FleetPatch AST and strict Verifier/schema/dependency bytes
  unchanged; Workflow AST differs only in captured visible-path binding. Nine-file
  static and108 exact schemas pass. Readback checked103 DBs,78 Artifact byte/hash
  bindings,zero leases,18 original-only Git registries and9 actual workflows.
  Retain94 inert running Run records and10 direct-adapter running attempt metadata
  with settled requests and closed clients; these are not completed product Runs.
  Two verifier expectation failures remain: LangGraph's existing earlier schema
  classifier differs from SDK catalog denial, and direct-adapter fixtures lack the
  Workflow finalizer. Corrected private assertions do not change candidate bytes
  or result state. This component overlaps the full matrix and is not live proof.
- [x] (2026-09-09 20:29:35 UTC) Full3fe0cafe default matrix passed3811/23 skips
  across3834 unique identities,with no failed/error/missing/duplicate/extra cases
  or source/dependency drift. Last-alone unchanged cancellation passed10.622s
  wrapper after the four heavy groups. Complete static gates also pass; final
  independent matrix readback and refreshed README/guide archive are pending.

## Discoveries

- CoS repeatedly selected a valid pure helper despite receiving matching prior
  results. A scripted adapter/SDK differential does not reproduce lost history.
- Visible context is not the full organization tree; ADD existence cannot be
  proven here. Final proposal validation must remain separate and authoritative.
- Visible context may contain a canonical complete file such as
  `.fleet/skills/README.md` which is not a mutable FleetPatch target. Constructor
  validation preserves that valid context; only individual requests enforce
  mutable-target eligibility. Rejecting the whole context would break ordinary
  scoping. The new regression exercises both accepted README hashing and denied
  replacement of the ineligible visible file.

## Decision Log

- Decision: target-bound helper rather than a prompt-only warning or deleting
  organization tools. It rejects source paths and retains current proposal support.
- Decision: no claim of reliable intent routing or loop elimination. A two-stage
  intent/proposal route is a future separately contracted architecture change.

## Outcomes

The target-bound component has independent524-case acceptance on3fe0cafe within
the four-production-file boundary. Full current3834-identity matrix passed3811
with23 explicit optional skips. Independent matrix/readback and pre-key archives
passed before the separate parent canary. That one current live attempt failed
on an out-of-scope Verifier read after genuine verification; no new live success
or GitHub delivery is accepted. Final result-document archive refresh is pending.
Existing092 local acceptance and its failed live CoS attempt remain historical.
The separate parent S1-S3 plan contracted that one bounded canary after all gates;
this offline component does not itself authorize any further paid retry.
