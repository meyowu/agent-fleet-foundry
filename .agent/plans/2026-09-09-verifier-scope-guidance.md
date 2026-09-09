# Verifier scoped reads and evidence routing

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log,
and Outcomes as implementation proceeds.

## Purpose and user-visible result

A Verifier should understand the existing task-local read boundary and use the
already supplied canonical patch and command receipts instead of trying to read
organization directories. This improves the instructions a real Harness receives;
it cannot prove that a model will comply or turn insufficient evidence into a pass.
The ordinary `fleet` task journey, CLI and permissions remain unchanged.

## Scope

### In scope

- Explain the existing `TaskSpec.allowed_paths` and `forbidden_paths` read limits
  in the packaged Verifier prompt and existing read/diff tool descriptions.
- Test actual invocation guidance, unchanged TaskSpec/patch/evidence context,
  legitimate scoped reads and the retained protected `.fleet` read denial.
- Independently review the small candidate and record exact offline results.

### Out of scope

- Any permission, schema constraint, budget, retry, failure, command, output
  validator, CompletionGate or live-canary-goal change.
- New context access, I/O, tools, telemetry, credentials, dependency changes,
  provider settings, task-criterion rewriting or paid requests.
- Guaranteeing successful intent routing, eliminating proof gaps, or claiming
  that a successful test command proves every acceptance criterion.

## Current repository state

The preceding target-bound hash candidate3fe0cafe has3811 default passes and23
optional skips,524 independent component passes and current pre-key archive
acceptance. Its single20:42–20:44UTC real canary failed: CoS/Engineer completed,
both Engineer and Verifier executed python-test with exit0, then the Verifier's
repo.read_file intent targeted `.fleet` and received protected PHASE1_DEFAULT_DENY.
No dispatch claim exists for that denied intent and no VerifierVerdict was accepted.
The attempt and previous failures remain historical evidence, not rewritten tests.

`application/workflow.py:WorkflowEngine._verify` already supplies the complete
TaskSpec, bounded candidate patch, patch hash and criterion_mapping_contract.
TaskSpec contains allowed/forbidden paths, verification_commands and configuration
hash. Full ConfigSnapshot bytes are not separately supplied. The existing
`workspace_get_diff` returns the canonical patch and changed-path summary;
`run_verification` returns an independent command receipt in the ongoing tool
conversation. No new `.fleet` read is needed to retrieve that receipt.

The packaged verifier.md says use only supplied read/verification tools, but does
not explicitly say that task path scopes constrain reads too. The current read
tool says regular scoped file without explicitly distinguishing directories.
This is a plausible guidance omission, not proof of the model's motivation.

## Security impact

All existing SECURITY_MODEL invariants remain authoritative. Guidance is not an
authorization boundary. BaselinePermissionBroker, Gateway, path normalization,
protected organization paths, frozen TaskSpec, sandbox enforcement and failure
semantics remain byte-identical. Do not convert denial into a retryable tool result.
Do not expose additional configuration or filesystem content to a model.

## Proposed design

Add a concise paragraph to the Verifier prompt: task allowed/forbidden paths apply
to reads as well as writes; repo_read_file accepts a repository-relative regular
file, not directories or protected paths. For changed-path inspection use supplied
canonical patch or workspace_get_diff, never read `.fleet`/`.git` or broaden scope.
Independent command results support only the criteria they genuinely establish;
inspection alone does not become independent executed behavioral proof. Missing
proof remains an inconclusive mapping/gap under existing rules.

Clarify only `_READ_FILE.description` and `_GET_DIFF.description` in runtime_tools.py
using their actual symbol names after inspection; do not change parameter models,
catalog membership, executable bodies or tool-result shapes.

## Public contracts

No new CLI, API, persistent model, migration, error, event or JSON Schema. Existing
tool description strings and packaged prompt text change. Existing schema constraints
and output bytes aside from those descriptions remain identical. No dynamic path
enum or inference of permission from a prompt is introduced.

## Milestones

### Milestone 1: frozen predecessor and guidance

Acceptance: prior live audit closes its source/dependency freeze and target-bound
slice is separately committed before these production edits. Record new exact
file ownership in Progress, then change only the two guidance surfaces.

### Milestone 2: real offline invocation and unchanged enforcement

Acceptance: tests inspect prompt/definitions delivered to an actual admitted
Verifier invocation, confirm exact TaskSpec/patch fields and independent receipt
flow, and exercise actual forbidden-read Broker denial with no dispatch/effect.
Legitimate scoped read/diff/verification paths remain functional. String tests
alone do not claim model compliance. Independent review and relevant broad runtime,
permission/workflow coverage pass. Full final quality/package gates follow the
parent S1–S3 plan; this plan admits no paid canary.

## Detailed implementation steps

1. Close the predecessor audit/commit; preserve its README/results and failed run.
2. Root is the sole Writer for prompts/verifier.md, the two runtime_tools.py tool
   descriptions, existing contract/test_pydantic_ai_runtime.py and a focused
   integration test only if the existing workflow tests cannot express the oracle.
3. Read the current tests and reuse their bounded fake/FunctionModel facilities.
   Add separate passed-scope and refused-scope cases with durable observations.
4. Run focused runtime/workflow/permission tests, format/lint/type checks and exact
   schema generation comparison; retain initial failures and corrected replays.
5. Freeze exact changed bytes and obtain fresh independent review. Update parent
   README/plan with the narrow result, limitations and any subsequent full gates.

## Validation plan

Use the existing environment with live/Docker/install opt-ins disabled. Expanded
pytest selections and JUnit locations are recorded at execution time in Progress.
At minimum cover contract/test_pydantic_ai_runtime.py, unit/test_runtime_tools.py,
integration/test_pydantic_ai_workflow.py and relevant permission regressions.
No network/model request, source-secret injection or physical sandbox execution.
Compare executable ASTs and parameter schemas to the committed predecessor;
only intended description constants may differ in runtime_tools.py.

## Rollback and recovery

This changes no durable state. Revert only the named guidance/test commit if needed;
do not reset or overwrite unrelated work. Keep the prior denied run, logs and
cleanup evidence intact. No test run may apply its generated patch to the source
checkout or resume/replay the prior paid attempt.

## Progress

- [x] (2026-09-09 20:52 UTC, before implementation) Read-only execution-path
  investigation confirms the context already exists and the exact omission above.
  Consulted official Function calling guidance on clear function/parameter format,
  purpose and when-not-to-use instructions. Model and API settings stay unchanged.
- [x] (2026-09-09 21:06 UTC) Predecessor3fe live FAIL independently sealed21:00:24,
  source freeze released. Source13-path commit584c551 and result-doc commit65e04e5
  pushed; GitHub PR7 head65e04e5/base3fb0971, OPEN/draft/CLEAN, branch Actions[].
  Final-result archive test1PASS2.51s ended21:03:49 before successor code edits;
  its independent comparison uses immutable584 source and held README04844f58.
- [x] (2026-09-09 21:06 UTC, before source edits) Root owns exactly
  prompts/verifier.md, the two named runtime_tools.py description constants,
  tests/contract/test_pydantic_ai_runtime.py and existing
  tests/integration/test_pydantic_ai_workflow.py. Preserve its original successful
  workflow case while adding separate scoped-file/protected-directory/out-of-scope
  read probes with actual durable denial and zero dispatch. No production logic
  or parameter constraints change.
- [x] (2026-09-09 21:20 UTC) Actual FunctionModel invocation and five existing
  workflow variants passed6/19.51s. Original behavior, scoped read plus canonical
  diff, protected .fleet/.git and out-of-scope tests/test_core.py exercised actual
  Git/SQLite/Gateway/Broker with simulated Sandbox receipts. All three denials
  occur after independent simulated python-test, persist FAILED/COMMAND_DENIED,
  have zero denied-intent dispatch claims and no VerifierVerdict; target bytes
  remain unchanged and no active leases remain. This is offline enforcement,
  not physical Docker, model compliance or a live pass.
- [x] Retained initial failures under private verifier-guidance.l1nqKD:
  first.xml5FAIL/1PASS14.10s and second.xml3FAIL/3PASS18.928s (JUnit). Test assumptions
  incorrectly expected only python-test although this ordinary fixture admits
  python-build then python-test, and expected uppercase permission JSON despite
  the existing lowercase deny wire value. Corrected test assertions only; actual
  workflow failure raises FleetError with run_id and persists Run, not Run.last_error.
  Added test-local callback failure capture so secret-safe provider exception
  wrapping does not hide fixture assertion diagnostics. Third.xml6PASS19.51s.
  Initial formatting and two type errors were corrected; focused mypy3 passed.
- [x] (2026-09-09 21:22 UTC) Broader runtime/tool/schema/permission/security
  cohort passed387/81.77s, no failures/skips, broad.xml under the same private
  evidence directory. This overlaps the six focused cases and is not additive.
- [x] (2026-09-09 21:24:44 UTC) Whole-checkout six static gates passed on
  code/dependency9cd328d8440636c30c1ced774ee62502fdadfbc9409bd1f528f1a605e174383e:
  Ruff format434, lint, mypy365,108 schema comparison,offline99-package lock and
  whitespace checks, all exit0/no code drift. Full expanded commands and logs
  retained under private guidance-gates.XoBK9G/static-results.json.
- [x] Fresh independent review held the exact four source/test paths at
  combined digest8c07cc9b0ee40ce0ca031fccc86f70dd2139c13291a9e78f7fe3f3ac6724e994.
  AST comparison confirms only the two specified description constants differ
  in runtime_tools.py. At21:31:51UTC independent PASS released the freeze:
  387 fresh broad cases/68.32s plus19 independent cases/2.08s =406 unique passes.
  PydanticAI Responses/Chat, Agents SDK and LangGraph actual offline wire definitions
  preserve schemas except those descriptions. Malformed batches have zero effect,
  no replay and closed clients. Five workflow databases bind98 artifact bytes,
  ten simulated receipts,30 released leases and ten absent worktree paths; five
  Git registries contain only originals. Positive Fake flows retain proof gaps.
  Independent Ruff3/mypy3 and108 schemas pass,513 code inputs and9826 pinned
  dependency files unchanged. Private asyncio-harness and overstrong blank-Git-
  status assumptions are retained and corrected only in private probes.
  Seal6dbf308aa6eb1412c4c6c09a533e06f9e2c499450165699ef80341389689dd76,
  private verifier-guidance-audit.GO2UDe/verification-pass.json.
- [x] Focused execution, unchanged-enforcement gates and independent acceptance.
- [ ] Final combined-candidate full default/package gates and scoped GitHub delivery.

## Discoveries

- Observation: `.fleet` was an actual denied intent after successful independent
  testing, not an inferred provider-log request. Consequence: preserve denial and
  clarify task-local evidence routing; do not diagnose authentication failure.
- Observation: the command receipt existed in the continuing tool history.
  Consequence: do not add configuration reads or repeat execution to obtain it.

## Decision Log

- Decision: guidance-only repair, not recovery/permission changes. Rationale:
  the control plane correctly rejected the out-of-scope request. Alternative
  denial-to-retry conversion would change failure semantics and needs its own
  architecture/security contract; it is excluded here. Date:2026-09-09.
- Decision: use the existing pure patch view for scope inspection, but retain
  independent-evidence requirements. Rationale: a correct path list alone cannot
  establish behavior. Date:2026-09-09.

## Outcomes

Guidance and focused regressions implemented; six focused cases and387 overlapping
broad checks pass after the retained fixture corrections. Six whole-checkout
static gates and406 independent component checks pass. Final full/package gates
and scoped remote delivery remain pending; component acceptance is not release.
No new model calls. The3fe live failure remains current. Official reference:
[Function calling](https://developers.openai.com/api/docs/guides/function-calling).
