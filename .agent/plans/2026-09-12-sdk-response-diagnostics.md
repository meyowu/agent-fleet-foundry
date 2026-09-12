# P1: bounded SDK response-failure diagnostics

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log
and Outcomes as implementation proceeds.

## Purpose and user-visible result

An actual mixed-Harness Canary failed at Engineer's response boundary without
enough safe detail to distinguish the rejected contract. A future `fleet run
... --json` should identify the finite failing branch through its existing
error.message and durable run.failed event, without exposing provider data.
This slice improves diagnosis; it does not make rejected responses acceptable.

## Scope

### In scope

- Fixed trusted diagnostic messages for existing OpenAI Agents SDK response
  rejection branches, and equivalent existing LangGraph response branches.
- Actual pinned SDK/MockTransport offline contract tests and public CLI plus
  reopened SQLite event readback for those bounded messages.

### Out of scope

- No new live request, model selection change, alias wildcard or guard removal.
- No changes to schemas, persistence versions, domain RuntimeDiagnostic fields,
  permission policy, tools, endpoint/header/body allowlists, budgets or retries.
- No raw response model, request ID, body, headers, usage strings or exception
  text in diagnostics. No provider credentials, Docker or productization work.

## Current repository state

The historical starting base09c5a64 contained pinned native runtime adapters. In
adapters/runtime/openai_agents_boundary.py, PinnedResponsesModel._fetch_response
mapped SDK ModelBehaviorError and combined identity/terminal-state failure to one
message; RawUsageReceipt.observe used the same message for invalid JSON/usage.
LangGraph raw_response combined response-envelope checks and used generic
response_policy errors for usage. RuntimeDiagnostic is a deliberately restricted
projection. CLI error.message and run.failed.payload.message already persist
trusted redacted FleetError messages; agent.failed does not contain that message.

Slice G is now delivered in PR11, normally merged at2026-09-12T11:28:17Z with
exact head/merge/tree readback recorded below. Its accepted 4211/23 full suite
and archives describe the frozen G baseline. The newer F Session-restoration
candidate has independent physical22 and integrated full4246/26 acceptance;
its final artifact/delivery records are in `2026-09-12-session-docker-resume.md`.

## Security impact

Provider output remains untrusted. All existing security-model boundaries stay
unchanged. Only finite adapter-owned constant strings may distinguish branches.
Never parse SDK exception text to infer failed versus incomplete or copy provider
values. Unknown request accounting, no tool dispatch, no SDK continuation and
client cleanup after rejected responses remain mandatory. Secrets stay outside
worker environments, commands, logs and repository files.

## Proposed design

Extend each adapter's existing boundary_error helper with a private constrained
constant-message selector only where needed. Keep default behavior unchanged.
For Agents distinguish SDK response processing rejection; identity rejection;
terminal-state/error rejection; raw JSON/usage rejection. Validation order stays
the same: raw transport receipt, SDK processing, then response identity/status.
When multiple fields are wrong, report only the first actually checked branch.

For LangGraph distinguish existing envelope-shape/policy, exact identity,
terminal-state/error and usage rejection without changing the admitted set.
Shared parse_json handles tool/context input too: do not globally relabel it or
change its error categories. Each adapter owns its constants; do not import the
Agents SDK boundary into LangGraph. No new shared abstraction is required.

## Public contracts

Only the existing human-readable error.message becomes more specific. Preserve
PROVIDER_FAILED, CLI exit5, provider_sdk/response_policy where currently emitted,
and unchanged runtime_diagnostic/agent.failed shapes. No CLI flags, schema, model
configuration, database or event type is added. Durable run.failed keeps its
existing message field and can be read after reopening the application.

## Milestones

### Milestone1: fixed diagnostics and actual transport regressions

Acceptance: exact/exact positive; alias/dated and alias/unrelated still rejected;
missing model, failed/incomplete/error, malformed JSON and usage, nested valid
usage retain current acceptance/accounting behavior. Single request on rejection,
zero Gateway/continuation, client closed and no raw provider marker disclosure.

### Milestone2: public propagation and independent acceptance

Acceptance: actual SDK failure through CLI emits the expected constant and exit5;
fresh SQLite/application readback agrees in run.failed while agent.failed's
limited projection stays unchanged. Independent reviewer reproduces negative
branches and checks source closure. Full default/static/package gates precede
staged GitHub delivery. Real mixed-Harness qualification remains separate.

## Detailed implementation steps

1. Writer owns only src/agent_fleet/adapters/runtime/openai_agents_boundary.py,
   src/agent_fleet/adapters/runtime/langgraph_boundary.py,
   tests/contract/test_openai_agents_runtime.py,
   tests/contract/test_langgraph_runtime.py and tests/integration/test_cli.py.
   Root owns documentation; writer may update this plan with exact evidence.
2. Read existing helpers and actual transport fixtures; make the minimum constant
   message change. Preserve error detachment, order and original validators.
3. Add deterministic exact/alias/negative/precedence/redaction/accounting tests
   against actual pinned SDK clients using MockTransport, not live requests.
4. Verify CLI/run.failed durability using existing public initialization helpers;
   do not seed a failure event as if generated by the real path.
5. Freeze source/test hashes, retain all intermediate failures, then obtain fresh
   independent verification. Root integrates only accepted files and updates
   CONFIG_AND_SCHEMAS, README/known issues and the continuation evidence.

## Validation plan

Use a private evidence directory and unique cache-based pytest basetemp outside
the repository. Keep all evidence/fixtures; no cleanup or deletion. Start with
focused offline contract tests, then the new CLI cases. Commands include pinned
ruff format/check, mypy src tests, schema generation --check, uv lock --check
--offline, git diff --check, and exhaustive credential-free pytest partitions
plus final distribution smoke. Full suites and physical Docker require root's
scheduling; no provider/network call is part of this slice.

## Rollback and recovery

No migrations or authority changes. A reviewed Git revert can restore prior
messages. Keep failed/unknown request evidence; never resume by clearing ownership
or replay an unknown dispatch. A later finite live attempt needs a separate
recorded decision after offline acceptance, not automatic retry from this fix.

## Progress

- [x] September12 final README/package refresh passed1/2.82s with no provider,
  Docker or installed-distribution opt-in. Evidence sdk-final-package.CipHDdbF,
  JUnit SHA256 `a51a7f643ee3deacc0f2b6309bee2ae9b6e22d27654d377d6145b4892de61e6b`;
  wheel `a408ed5117999f70616a304769eca77bae3e5ca7c609b57fd4a5d9488d11423a`,
  sdist `ac4e56395b4c8e275d00b5e859fe64aba5183f440f2ba15155229dfcf8501b3d`.
  Frozen G README SHA256
  `93067f151cea89f3b0aac0a5709571ee6f5ecaa69c6b9d7dcf372774de2289a2`.
  Independent terminal/archive readback and normal GitHub delivery were then
  pending; both subsequently completed as recorded below. These are G artifacts,
  not a package qualification of the newer F candidate or its updated README.
- [x] (2026-09-12T11:07:34Z) Complete current-B+G offline gate passed4211/23;
  all4234 collected/JUnit identities reconcile,0 missing/extra/duplicates/failures/
  errors,548 unchanged source inputs. Collection-to-end1728.402139s. Three
  integration groups249/251/265 and default-other3444/23, then both original
  serial cases passed (11.032361/20.072817s process). Six configured static gates
  passed: Ruff473, mypy392, schemas, offline lock99 and whitespace. Evidence
  sdk-diagnostics-full-01 summary SHA256
  `9c8a69b729f686be909f9ccc61161c14645826259f66029cf4ab0e1d7ed5cc65`;
  both source-map SHA256
  `3ac12ca38e29123ef48e8e64a4853f6efa2914edb27f2536847443e182801f2b`.
  Skips are19 Docker/3 install/1 live; warnings and all prior failures retained.
  README/ledger refreshed; final package and independent terminal readback follow.
- [x] (2026-09-12T10:36:45Z) Independent repaired-candidate review PASS and read
  release. Runtime contracts240/6.265s, CLI6/10.772s, original34-run actual-SDK
  differential with zero non-message mismatches, six shared-receipt requests,
  timeout/approval/cancel/hostile probes and two fresh CLI durable JSON/usage
  cases passed. LangGraph221 paired/120 precedence/four parse cases unchanged
  except allowed messages. Original safe_error AST equals HEAD; no new exception
  cause/context loads. Exact before/after candidate identities unchanged. Evidence:
  `sdk-diagnostics-repaired-verifier.53enOW`; the original FAIL remains retained.
- [x] September12 root fast-forwarded this isolated candidate from Foundry
  PR9 to PR10 merge `a96eb29c8139094164c99b6822da3d9f41a58c07` after proving
  zero overlap in all five owned code/test paths. Source/test bytes remain the
  independently reviewed repair. Root owns current architecture/security/known
  issue and acceptance documentation. Full/default/static/package gates and
  separate GitHub delivery follow; pending Session repair is not included.
- [x] 2026-09-12 independent verification rejected the first candidate
  (diff0dd6155b):34 actual SDK differential runs exposed6 JSON/usage faults
  changing api_connection to response_policy plus remediation. New nested-marker
  traversal also changed timeout/approval codes and read hostile exception
  attributes. LangGraph221 paired/120 precedence cases were unchanged except
  messages;237 contracts and6 CLI cases passed but did not catch these regressions.
  Preserve sdk-diagnostics-verifier.XZf4is, all failed/probe evidence and the
  byte-exact pre-repair diff/plan. Independent read release10:03:59Z.
- [x] 2026-09-12T10:13:07Z reopened ONLY openai_agents_boundary.py, its
  contract tests and this plan.
  Remove _ResponsePolicyError and all raw cause/context traversal. Restore the
  original safe_error mapping/precedence, including its generic ModelBehaviorError
  branch, exactly. Do not recover nested errors or change any code, category,
  detail, remediation, cancellation or unknown-accounting behavior.
- [x] Preserve useful raw JSON/usage messages through a trusted request-scoped
  note, not an exception chain. RawUsageReceipt.request may yield a private note
  containing only an optional finite _ResponsePolicyFailure; observe sets it
  immediately before its existing JSON/usage rejection. Clear the receipt's note
  pointer on context exit; the current _request retains only that local note.
  After the ORIGINAL safe_error projection, override message alone for a
  PROVIDER_FAILED error when this request's trusted note is set. Preserve original
  remediation and runtime_diagnostic (including api_connection for SDK-wrapped
  response-hook failures). Never override timeout/approval/cancellation errors;
  no body/header/exception/model value enters the note. No note leaks into another
  request or into persistence. Keep original validation/accounting order.
- [x] Add actual SDK raw-failure differential regressions against original
  code/category/remediation/accounting plus note lifecycle/stale-note, hostile
  cause/context accessors and timeout/approval invariants. Existing finite direct
  response-model/status/error messages remain. Keep accepted LangGraph/CLI test
  bytes unchanged, then freeze for new independent review and later full gates.
- [x] 2026-09-12 root froze this contract before implementation, following
  read-only diagnosis of retained mixed-live02 and the existing boundary source.
- [x] 2026-09-12T09:51:56Z writer implemented the bounded messages and focused
  acceptance. Both complete runtime contract files passed 237 tests; the five
  focused CLI diagnostic cases passed; changed-source mypy and five-file Ruff/
  diff checks passed. Independent verification and full gates remain separate.
- [x] 2026-09-12T11:19:00Z independent terminal/archive acceptance PASS and
  read release, retained in sdk-final-verifier.xX3CAM. Fresh collection reconciles
  all4234 identities with4211 passed/23 skipped and548 unchanged source inputs.
  Wheel/sdist/current README and332 runtime resources match; installed target
  import origin,115 schemas and read-only migration journal1–13 passed. Source,
  plan and ignored/untracked inventory stayed unchanged; new-content secret and
  absolute-machine-path scans were clear. No paid request or Docker rerun.
- [x] (2026-09-12T11:28:17Z) Exact-head commit/push and ordinary
  [PR #11](https://github.com/meyowu/agent-fleet-foundry/pull/11) merge/readback
  complete. Head `13daa225d8a195a9e16d317bac6b21e282b89319`, merge
  `5b09fea1c5fdb79066498496852adbb9e5239773`, identical tree
  `5d918cf7954918058cda150686183fd101390f63`. No admin bypass, rules changes or
  branch deletion. Actions readback is0 for head and merge, not hosted CI success.
- [x] Post-merge smoke: clean diagnostics worktree fast-forwarded to merge5b09fea;
  existing `tests/integration/test_cli.py -k runtime_diagnostic_survives_reopened_logs`
  passed3,32 deselected in6.62s under a cleared no-key/no-Docker/no-install
  environment. `sdk-postmerge-smoke.xml` and its fixtures remain private and
  retained. These overlapping smoke cases are not added to the4211 full-suite count.

## Discoveries

- The current-B documentation review confirmed all five accepted code/test hashes
  and zero upstream overlap, but rejected two prose errors: stale Outcomes said
  independent review had not run, and docs said the whole note was cleared rather
  than the receipt pointer. Root corrected only those statements after read
  release2026-09-12T11:05:09Z. Preserve sdk-diagnostics-doc-verifier.LZsVVd as FAIL;
  the repaired code's earlier independent PASS remains separate and unchanged.
- A response-hook error can be wrapped by the pinned SDK as APIConnectionError.
  Finite diagnostics must preserve that existing classification and remediation,
  not return a nested error in place of the trusted outer projection. Reading
  arbitrary exception chains also introduces new accessor execution; do not use
  them as a diagnostic side channel.
- The failed live02 record proves Engineer response_policy, not the specific
  rejected field. Alias versus dated model equality is only an offline hypothesis.
- agent.failed intentionally carries only the diagnostic projection; branch
  messages belong to existing CLI error.message and run.failed, not new fields.
- The OpenAI SDK wraps an exception raised by an HTTP response observer in an
  APIConnectionError before PinnedResponsesModel regains control. The finite
  JSON/usage message therefore travels in a request-local note while the original
  safe_error projection remains authoritative for code, provider_sdk category,
  api_connection cause, remediation and details. The receipt clears its pointer
  on context exit; a later request begins with a distinct empty note.
- LangGraph records valid response usage before later catalog checks. The first
  focused LangGraph run confirmed mixed-terminal and unknown-tool failures retain
  reported usage, while response envelope/model/status/error/usage failures stay
  unknown. Tests preserve that existing accounting order rather than relabel it.
- Directly checking the five changed files with mypy is not a valid repository
  test configuration: top-level test fixture modules were unresolved and their
  existing Any-return sites followed transitively. It also identified one new
  BaseException/FleetError narrowing assertion, which was fixed. The two changed
  source modules then passed strict mypy; root retains the configured full gate.

## Decision Log

- 2026-09-12: retain exact model equality. Adding diagnosis must not weaken trust.
- 2026-09-12: use existing message fields and per-adapter constants; no new schema
  or dependency for a finite diagnostic distinction.
- 2026-09-12: use private StrEnum values only. RawUsageReceipt may attach one
  finite JSON/usage value to its current request note. No exception chain is read;
  only a safely projected PROVIDER_FAILED message may be replaced, so timeout,
  approval and cancellation precedence remains unchanged.

## Outcomes

Implemented in the five owned source/test paths. Agents now distinguishes SDK
processing, model, status, error, malformed JSON and usage failures; LangGraph
distinguishes envelope, model, status, error and usage while shared parse_json
keeps its prior category/message. Actual offline SDK transports prove exact model
acceptance, alias/dated rejection, precedence, redaction, one-send unknown
accounting, zero tool effects, no continuation and client closure. CLI exit 5 and
error.message agree with a freshly reopened run.failed payload; agent.failed has
no message and retains its restricted diagnostic shape.

Repair evidence: the reopened Agents contract and frozen LangGraph contract pass
`240 passed in 5.27s`; the frozen actual-SDK CLI durability case passes `1 passed
in 1.08s`; reopened source mypy, two-file Ruff format/check and git diff --check
pass. JUnit, pytest basetemps and both intermediate failed runs are retained under
the private user-cache directory
`agent-fleet-p0p1-20260911.UXOEb6/sdk-diagnostic-repair.W7ZuAMnY/`.
The initial six-failure category differential is `raw-existing-001`; the later
mixed-precedence test correction is `agents-contract-001`. Five-file SHA-256
freeze: openai boundary `7ff5a8533c83b8a1ded68d3aa84898731a731ec6abd348fc6218f2d03b07f0a7`,
LangGraph boundary `3de0829175897602ec86b5821d9619c47831732973ba7288633e6812ced06189`,
Agents contract `ab0c769b155e1a977873acc502b6e0e29ce0c6ef878e44b79e299f5f52d36aa9`,
LangGraph contract `ca75a48879b1fca31cf691aa225e1c200ed2abf9245b0ab5d6cc23fa1c67a268`,
CLI integration `118bce019655737be10d074c89e66fad7dafe1d403df98c251d2cad8dafa4b27`.

Independent repaired-code verification passed at10:36:45Z, with exact byte
continuity after integration onto current-B confirmed separately. The complete
default suite passed4211/23 with4234 exact identities and548 unchanged source
inputs; all six configured static checks passed (including mypy392 files).
The G README and ledger recorded that exact full result. Final frozen-G-README
package closure passed1/2.82s. Independent terminal/archive readback passed
at11:19:00Z; PR11 was normally merged at11:28:17Z with identical head/merge tree
and zero Actions for both. These G code/archive identities remain historical
evidence; later F documentation changes do not retroactively refresh the archives.
F's physical repair has since passed current integrated full4246/26, distribution1
and fresh-install3; its final independent artifact review and GitHub delivery are
recorded separately in the F plan.
No additional paid attempt was authorized;
the prior live failure's exact field remains unresolved and alias mismatch is
only an offline hypothesis.
