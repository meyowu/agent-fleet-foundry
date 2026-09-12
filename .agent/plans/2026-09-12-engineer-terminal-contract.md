# Engineer terminal wire contract and exact failure-stage evidence

This is a living ExecPlan written before implementation. Maintain Progress,
Discoveries, Decision Log and Outcomes. It continues P1 Harness qualification,
not the blocked native P0 write work or deferred productization.

## Purpose and user-visible result

An Engineer may execute authorized tools and still return an invalid final report.
Make its closed output schema an explicit strict wire contract when the pinned
SDK can preserve that schema, and distinguish terminal-schema rejection from an
earlier malformed tool envelope without exposing model-controlled error data.
For example, `fleet run ... --json` must still fail closed and preserve accounting
after an invalid final report; its finite error message should identify the stage.
This does not recover or explain the actual unretained live05 invalid payload.

## Scope

### In scope

- First prove unchanged ImplementationReport schema construction with the actual
  pinned Agents SDK and no provider call.
- Exercise valid and malformed Engineer terminal submission after successful
  synthetic tool execution, with actual SDK MockTransport and durable accounting.
- If the construction proof passes, explicitly select strict wire mode only for
  the Engineer execution kind's ImplementationReport terminal. Preserve all other
  terminal compatibility modes and strict local semantic validators.
- Add one trusted fixed terminal-schema failure message, without reading error
  inputs, messages, field paths, contexts, causes or exception representations.
- Required full/local/optional gates, independent review and scoped Git delivery.

### Out of scope

No model/endpoint/dependency/schema/prompt/permission/budget changes; no new provider,
native tool/handoff/checkpoint/streaming, coercion, retry/fallback, raw response
logging, field-level diagnostics, fixture deletion or retrospective success.
No live dispatch is authorized by this plan. Any future paid test needs a separate
finite manual decision after the candidate's acceptance and Git delivery.

## Current repository state

Clean delivered base is PR14 merge c13a3f679222b5af5a6e6ab6fdf8a2504fdda502.
Its556 source/build/README/guide inputs retain PR13 acceptance:4291 offline passes,
32 opt-in skips, six statics and separate Docker/adversarial/package/install gates.
Those results are historical once this slice changes source.

`OpenAIAgentsRuntimeAdapter._run` creates action tools with strict wire schemas,
terminal tools with non-strict schemas, and an Agent with output_type=None. Fleet
interrupts every tool and locally validates the exact terminal output model before
publishing a passive receipt. `boundary.safe_error` currently maps any Pydantic
ValidationError to output_schema/schema_validation, including RuntimeToolCall
construction before the terminal parser. Live05 therefore does not prove a field
or exact parser failure despite five reported requests and three executed tools.

ADR0010's non-strict compatibility rationale applies to dictionary-bearing output
models such as ScopeDecision.role_selections. ImplementationReport is a closed
seven-required-field string/array object; test compatibility, do not assume it.

## Security impact

Wire schema constraints do not replace Fleet authorization or semantic validation.
ToolGateway/PermissionBroker, full-batch checks, exact invocation identity, budgets,
single-send accounting, cancellations, client closure and passive receipts remain
authoritative. A malformed final report must not resume the SDK, accept a patch,
invoke a Verifier, refund usage or replay earlier effects. No API key is needed
for offline synthetic transports. Keep real credentials outside all test workers.

## Proposed design

Use an explicit trusted output-kind choice, not dynamic try-strict-then-fallback.
Preserve the original schema bytes, all seven required fields and every local
validator, including relative paths and unique artifact IDs. CoS/FleetPatch,
Verifier and specialist terminal mode remain unchanged in this slice.

Catch only the local terminal model-validation failure at its known call site;
emit a fixed code-owned stage message through the existing detached FleetError
projection with the original code/category/cause/remediation. Earlier envelope
validation keeps its existing generic diagnostic. Never inspect exception data.

## Public contracts

No new CLI/config/persistence/schema fields or migration. Existing error.message
becomes more specific only for known terminal-schema rejection; codes, details,
remediation, precedence and incomplete/unknown accounting semantics stay unchanged.
The Engineer terminal's outbound strict flag is a deliberate transport policy
change and must be documented in ADR0010 and accepted against real SDK requests.

## Milestones

1. SDK construction and offline counterexample proof: unchanged Engineer schema
   is accepted in strict mode; CoS dictionary compatibility remains demonstrably
   non-strict. No production edit if the first proof fails.
2. Bounded source/test slice with actual SDK positive control, malformed final
   report and invalid call-envelope distinctions after successful actions.
3. Independent exact-candidate review; full formatting/lint/type/schema/lock/
   unit/integration/offline E2E and applicable Docker/package/install gates.
4. Update README/ledger with exact new results and remaining live limitations;
   commit/push/normal exact-head merge with [skip ci], then authoritative readback.

## Detailed implementation steps

1. Root owns this plan and all docs/ADR/README; one code writer owns only
   adapters/runtime/openai_agents.py, openai_agents_boundary.py and focused
   tests/contract/test_openai_agents_runtime.py plus a narrowly needed new test
   module or existing workflow regression. No shared file writes without handoff.
2. Preserve the missing-field/object-valued criterion_results/duplicate artifact
   IDs rejection cases; include valid-after-tools control and invalid call_id
   envelope. Assert two reported requests where appropriate, zero unknowns,
   unchanged authorized action count, no automatic further send and closed clients.
3. Test emitted tool schema/strict flag for built-in and custom Engineer execution
   kinds; verify other kinds, including organization FleetPatch, are unchanged.
4. Keep full-suite expected identities and optional gate selection unchanged except
   for added named cases. Preserve all failures and use new private result paths.

## Validation plan

Construction probe uses pinned SDK only. Focused command: `.venv/bin/python -B -m
pytest -q tests/contract/test_openai_agents_runtime.py` with no live/Docker/install
opt-ins and auto-loaded external plugins disabled. Record exact commands, selection,
JUnit identities, timings and source hashes for later full/local gates. Do not
count synthetic transports as real-provider proof or add overlapping suite totals.
Fresh independent verifier must test original invariants and the new stage
distinction, not merely accept the writer's claimed passing tests.

### Executed commands and retained gate identities

All commands below use the candidate's pinned `.venv`, an isolated environment,
disabled live-provider access and fresh private output roots. No test assertion,
internal timeout or selection was weakened. Full offline execution uses the
existing exhaustive partitions in `docs/session-first-test-partitions.json`,
followed by the two original serial cases; it is not a sample. Exact expanded
argv, environments, source maps, logs and JUnits remain in the named private
gate roots (these are identifiers, not portable repository-relative paths).

- `engineer-terminal-full-01`: `.venv/bin/python -B -m pytest -p
  pytest_asyncio.plugin -q <exhaustive partition paths / serial case ID>
  --junitxml=<group.xml> --basetemp=<fresh group fixtures>
  -o cache_dir=<fresh group cache>`; six disjoint groups. The four heavy groups
  explicitly deselect the two original serial cases:
  `tests/integration/test_conversation_safety.py::test_cancel_after_rejected_cleanup_reconciles_terminal_fence`
  and `tests/e2e/test_session_business_baseline_cli.py::test_real_session_plans_confirms_runs_and_exits_without_history_reentry`.
  `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`,
  `.venv/bin/mypy src tests scripts/run_live_canary.py`, `.venv/bin/python -B -m
  agent_fleet.schemas.generate --check`, `uv lock --check --offline --python
  .venv/bin/python`, and `git diff --check` supply the six static checks.
- `engineer-terminal-package-01`: `.venv/bin/python -B -m pytest -p
  pytest_asyncio.plugin -q tests/integration/test_distribution.py
  --basetemp=<fresh fixtures> --junitxml=<results.xml> -p no:cacheprovider`.
- `engineer-terminal-adversarial-01`: `.venv/bin/python -B
  scripts/verify_adversarial.py --output <fresh gate root>`.
- `engineer-terminal-docker-01`: `.venv/bin/python -B
  scripts/verify_adversarial.py --output <fresh gate root> --docker
  --image agent-fleet-runner:0.1.0-py314-v1`. The existing standard gate excludes
  the separate six-case baseline cohort explicitly.
- `engineer-terminal-cohort-01`: `.venv/bin/python -B -m pytest -p
  pytest_asyncio.plugin -q tests/docker/test_business_baseline_cohort.py
  --basetemp=<fresh fixtures> --junitxml=<junit.xml> --tb=short -p no:cacheprovider`,
  with `AGENT_FLEET_ENABLE_DOCKER_TESTS=1` and the already prepared
  `AGENT_FLEET_BASELINE_COHORT_IMAGE=agent-fleet-baseline-cohort:20260911-arm64`.
- `engineer-terminal-installed-01`: `.venv/bin/python -B -m pytest -p
  pytest_asyncio.plugin -q tests/release/test_installed_distribution.py
  --basetemp=<fresh fixtures> --junitxml=<results.xml> -p no:cacheprovider`;
  install/Docker opt-ins enabled, standard prepared image and existing offline
  wheelhouse, no live opt-in or dependency download.

Prepared images were rechecked before optional dispatch: standard image SHA256
2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241 and cohort
image SHA256 8bc1c28eb85f3257ab5f2b92d72a7b9cc7ce00de064c7e6ef898dc1605ff4c9a.
No image pull/build occurred. Package/install freeze includes554 source inputs
plus README and the packaged user guide; ledgers, ADRs and ExecPlans are not
package inputs. README/guide remain frozen while those gates are active.

The stopped full gate's exact disjoint results are:

| Group | Pass / skip | JUnit seconds | Process seconds |
| --- | --- | ---: | ---: |
| Default-other | 3526 / 32 | 1655.178 | 1658.825 |
| Integration1 | 267 / 0 | 2027.075 | 2029.943 |
| Integration2 | 252 / 0 | 1255.159 | 1257.957 |
| Integration3 | 249 / 0 | 1228.555 | 1231.327 |
| Original serial cancellation | 1 / 0 | 10.648 | 12.836 |
| Original serial baseline Session | 1 / 0 | 20.551 | 22.697 |

Every heavy/static job had stopped by2026-09-12T15:43:59.342891Z. The unchanged
serial cases then ran in order, ending15:44:34.877544Z. These are the4328 exact
collection/JUnit identities, including32 documented opt-in skips, not extra tests
or a claim of parallel-run wall-time equal to the sum of process durations.

## Rollback and recovery

No migration. Revert this scoped change through normal review if needed. Never
replay failed/unknown live05 or rewrite its bundle. Preserve every prior trial and
the existing deleted-fixture evidence gap. A failing compatibility probe ends
implementation of strict mode, not admission of a relaxed or alternate schema.

## Progress

- [x] Current clean local/remote c13a3f6 verified; prior turn delivered PR14.
- [x] Read-only investigation identified terminal-versus-envelope diagnostic
  ambiguity and the exact Engineer-after-tools malformed-output test gap.
- [x] SDK construction proof before production changes: pinned FunctionTool
  accepts ImplementationReport strict=True/needs_approval=True with exact unchanged
  schema, canonical SHA256
  4194ebb884afc68a653cd6781eb1e304b8a4eefec403c68edae3323c086c743e.
  ScopeDecision strict conversion rejects as expected; no fallback executed.
  Probe exited0/1.081s, with no client, callback, model request or source write.
- [x] Sol code writer assigned only adapter/boundary/focused contracts; root owns
  documentation. Further validation must use the actual changed candidate.
- [x] (2026-09-12 15:07 UTC) Sole writer released the three owned files. Focused
  actual-SDK MockTransport contracts:129 passed/2.95s, zero failures/errors/skips;
  Ruff format/check, git diff --check and mypy src tests (395 files) passed.
  Scoped three-file diff SHA256:
  dc10d6838a1589fd531f3c6eea5810da2cdd79ed548bcf4ae4e8d2d6e791210a.
  A first focused mypy invocation exposed a local shadowed name (fixed) plus
  test-import invocation artifacts; the configured source/test type gate passed
  afterward. Initial129-pass trial and intermediate failed type output remain
  preserved. No provider, Docker, install, credential access or Git write.
- [x] Fresh independent verifier received the released candidate; root launched
  the original partitioned full/offline runner into engineer-terminal-full-01.
  This is an active gate, not a passing full-suite claim.
- [x] (2026-09-12 15:14:50 UTC) Initial independent runtime checks passed129
  cases/5.19s plus8 direct probes, but the verifier then unlinked six newly created
  private synthetic fixture roots. Exact descendant counts were not captured;
  no retained copy or ordinary recovery is available. Candidate files, logs,
  JUnit and manifests were preserved. Root does not accept this trial as retained
  fixture verification and ordered exactly one identical retention-repair rerun
  into a new directory, without assertion changes or any further deletion.
  This is an additional evidence gap, separate from the older738-deleted-fixture
  gap. Neither failure is erased or retrospectively repaired by a later run.
- [x] (2026-09-12 15:21:29 UTC) Retention-repair independent PASS released:
  same129 focused identities passed/8.11s, same8 direct probes passed, no more
  test executions or deletion. Six roots retain70 SQLite databases,71 directories
  and9 confined resolvable symlinks. Immutable reads verified integrity and the
  five direct journals' failed attempts/two reported requests/30 tokens/one tool
  call; all70 hashes remained unchanged. Candidate imports, three file hashes and
  scoped diff match. VERDICT.md SHA256:
  cdc348d6ed4f85f9f52c423da78c51752c05a302cdb430d8586485e300f8ded7.
  An initial native SQLite CLI read produced error14 with no individual captured
  exit code; preserve it. Later Python immutable read success is independent
  evidence, not an erasure of that diagnostic or the prior deletion.
- [x] Full runner stopped normally:4296 passed/32 explicit opt-in skips,4328
  collected/JUnit identities, zero missing/extra/duplicate/failure/error and554
  unchanged source inputs. Six statics passed (format483/type396/lock99 plus
  lint/schema/whitespace). Both unchanged serial cases followed every heavy and
  static job. Summary SHA256:
  16ff8280a0cea450e7a732ffaba906be1a38d0dd95c2a9a74afcc33182accd1f.
- [x] Independent full/source/static readback PASS released at
  2026-09-12T15:50:12.047570Z. All13 recorded PIDs absent and38 original gate
  report files unchanged. Verdict SHA256:
  9bba86a1c8c2d29322e7839a20bb8819d202dedfc28bb91d7c8289c4f9b186ff.
  First private audit classified all28 Docker skips by the standard message and
  failed; retain it. Corrected same-byte classification confirms22 standard +6
  cohort +3 install +1 live skips, not passes, with no test/collection replay.
- [x] Separate docs-only PR15 merged at15:50:05Z, merge
  e9deb1f1f09e70d4b83bdab079e63f77fea471f0. After full read release, this worktree
  fast-forwarded to that merge with all H edits preserved and all554 accepted
  inputs rehashed unchanged. No H implementation was in that PR; source base
  c13a3f6 in the earlier run remains the truthful historical execution identity.
- [x] Package runner stopped exit0:1 passed/3.393s, wrapper5.841281891s,
  all556 source/README/guide inputs unchanged. Fresh independent package readback
  PASS released2026-09-12T16:00:02.933884Z; verdict SHA256
  b6568bd1c36d5be41839dc50eb8a6c49e2d056ea18943b9ee647025623472f23.
  Both337-file archives match332 normalized runtime/resources,115 schemas,
  13 migrations and5 prompts;341 artifact identities/hashes remain unchanged.
  Wheel SHA256029ad4b3e0adde81c4a1530c09a0c310dfbcda772730e445cb7e8b7232f1f39c;
  sdist SHA25675aa98e2a340267dba57d14198dcfc6168a2b791ae7fd404033206323e5700dc.
  No package publication, new build or failed oracle in independent readback.
- [x] Offline adversarial runner stopped exit0:806 tests, zero failure/error/skip,
  wrapper341.045727015s,556 inputs unchanged. Original JUnit SHA256
  5ab108a2f7c04ded83fe3133ea96d716dff9f289c0a7dc0ecde9ed6534e4cb7e.
  Independent readback PASS released2026-09-12T16:09:25.277106Z; verdict SHA256
  4ba9516c6dad64c63c2921c6a9c2f8257f008f663869f68ea440dd8ce470d443.
  Exact806 identities match the original18-file selection and full collection;
  seven original report identities/hashes unchanged. JUnit337.403s and inner
  gate340.944s. Exact wrapper PID absent; inner pytest PID was not captured, so
  its stop proof is the retained synchronous wait/exit, not an independent
  broad child-process absence claim. No failed oracle or rerun in this review.
- [x] Standard Docker runner stopped exit0:22 tests, zero failure/error/skip,
  wrapper427.190111876s,556 inputs unchanged. JUnit SHA256
  37114db81dceccf031e9283be7e5e292cc88d1103c6c9c40243ca124d64ecb78.
  Separate original six-case cohort stopped exit0, zero failure/error/skip,
  wrapper398.767834187s,554 inputs unchanged. Both evidence roots were released
  for fresh independent stopped-owner/physical/immutable database review.
- [x] Physical readback PASS released2026-09-12T16:09:47Z; verdict SHA256
  2bb7dda16a92380a3d8a71012db2307d650a241332ec807f386ae8b088ff7ce8.
  Standard pytest424.20s; five immutable journals, nine actual CompletionGate
  decisions,20 command receipts,56 released leases,18 absent workspaces,22 empty
  exact installation namespaces and20 absent native IDs. Six cohort journals
  retain actual business exits0/2/1/0/1/1,18 released leases/receipts and six
  absent workspaces/namespaces/native IDs; pytest395.95s, JUnit SHA256
  115e713d7fd397975bbcbd29edd5e8310a336606a40ddc68d235612ecd1a52de.
  All556 held inputs and2462+960 retained file/symlink entries unchanged, with
  all11 DBs admitted through pinned no-sidecar immutable reads. No current audit
  failure or mutation. Cohort runner did not retain an OS PID: actual Popen plus
  synchronous child.wait and normal wrapper exit establish its observed stop;
  session81417 is not a PID and no independent exact-PID absence is claimed.
  Cleanup is exact-scope, not daemonwide; stopped-fixture read acceptance does
  not qualify native P0 writes or hostile same-user races.
- [x] Fresh-install runner stopped exit0:3 tests, zero failure/error/skip,
  wrapper373.496671915s,556 inputs unchanged. JUnit SHA256
  6da8b7e3cfd00db60c2ce6b4d0b1fe863c4cd5293da9d19e519a7ec7d1b3dd62.
  Released the stopped evidence root for separate installed/public-journey review.
- [x] Installed/public-journey independent PASS released
  2026-09-12T16:18:16.251035Z; verdict SHA256
  87e60322f8367f4433ce9f72c6a3526186c311e55caf063ec9c93d2f5b0b0c7a.
  Original three-case pytest369.93s. Six fresh archives equal the accepted H
  pair; all three installs match332 runtime/resource files,115 schemas and80
  locked distribution metadata entries. Six immutable migration1–13 journals,
  10 CompletionGate decisions,18 code receipts and215 artifacts validate.
  Public real-Docker target run_1cd12429d09246d5b8630d8794c68ce8 verified then
  explicitly applied its one-file patch; Engineer/Verifier commands each retain
  exit0/5 passed. Same-submission replay creates only one Run; exact permission
  revocation and organization rollback hold. All54 leases released,18 workspaces
  and6 native IDs absent, only the exact installation namespace queried. All15
  supplemental checks passed; all held source/docs/evidence unchanged, no failed
  oracle, rerun or deletion. These are two seeded offline installs and one public
  fake-runtime/real-Docker journey, not three real-model cold starts.
- [x] Root preflight reviewed the frozen three-file source diff and seven-path
  total scope; all556 package inputs match,50 relative links resolve and scoped
  sensitive-pattern/whitespace checks pass. Final living-plan/ledger bookkeeping
  is outside package inputs. Current branch remains based on delivered PR15;
  remote main still matches e9deb1f1, unprotected with no rulesets.
- [x] Final independent seven-path documentation/diff review PASS released
  2026-09-12T16:23:51.803177Z; verdict SHA256
  8b9966ab3a49dec171d487a5a32e51f87c69966b014dd282031be5e521a6b474.
  All556 accepted inputs,50 relative links/anchors, protected contracts and
  current evidence/limitation claims passed; candidate/PR bytes stayed unchanged.
  A private system-Python datetime.UTC report-formatting failure occurred after
  successful assertions and snapshots; original exit1/script/error remain.
  timezone.utc finalization exited0 on the same checked bytes without tests,
  DB/resource/Git replay or candidate changes. Post-release changes only record
  this actual review and later Git bookkeeping; package inputs remain frozen.
- [ ] Exact H Git delivery and authoritative remote readback.

## Discoveries

Official Structured Outputs guidance distinguishes strict schema generation from
JSON-only output: https://developers.openai.com/api/docs/guides/structured-outputs.
This adapter uses terminal function tools, not text response_format. Official
guidance is not proof of the installed SDK's schema transformation or live05 cause.

## Decision Log

- September12: test an explicit Engineer-only strict terminal policy rather than
  change all output models for CoS's incompatible dynamic dictionaries. Keep
  semantic validators and all security controls. This strengthens one wire
  contract and makes future evidence more diagnostic; it does not assert a
  previously unproved provider/model defect or successful live qualification.

## Outcomes

Implemented after the construction proof; writer-focused and retained independent
runtime, full/source/static, package, adversarial, standard Docker/cohort physical
and fresh-install/public-journey acceptance passed. Counts from overlapping gates
must not be added. Final independent review passed; Git delivery is pending at
this pre-publication record. No live qualification is claimed.
Native P0, actual external-repository/cold-start
and Provider/Harness campaigns remain incomplete. Additional-provider credentials
are absent in the current trusted process; no new paid request has been made.
