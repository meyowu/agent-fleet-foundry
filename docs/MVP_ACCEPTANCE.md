# MVP acceptance ledger

This is a living review ledger, not a release declaration or a user guide. It maps the normative requirements in `PRODUCT_SPEC.md`, `IMPLEMENTATION_ROADMAP.md`, and `SECURITY_MODEL.md` to implementation evidence and remaining proof. The governing implementation plan is `.agent/plans/2026-09-05-mvp-completion.md`.

## Evidence boundary and update rules

### P1-H — Engineer terminal contract, 2026-09-12

The closed seven-field Engineer ImplementationReport uses strict terminal wire
mode with unchanged schema and local semantic validators. CoS/FleetPatch and
other execution kinds retain their existing non-strict compatibility policy;
there is no try-strict/fallback. Known local terminal-validation failure exposes
only a fixed stage-specific message, with unchanged codes/categories/accounting.
Earlier malformed call envelopes retain the generic message. No raw failure data,
permissions, model selection, prompt, dependency or retry policy was changed.

Current full offline gate:4296 passed/32 opt-in skips,4328 exact collected/JUnit
identities, zero missing/extra/duplicate/failure/error and554 unchanged inputs.
Six statics passed:format483, lint, mypy396, generated schemas, lock99, whitespace.
Two unchanged sensitive cases ran serially after all heavy/static jobs; their
passes and the129 focused cases are already included in the full count.
Fresh independent full/source readback released at15:50:12.047570 UTC, verdict
SHA256 `9bba86a1c8c2d29322e7839a20bb8819d202dedfc28bb91d7c8289c4f9b186ff`.
An earlier independent focused trial deleted six temporary fixture roots; that
gap remains recorded. The identical retained rerun passed129 cases and8 probes,
with70 preserved SQLite fixtures independently read back and unchanged.

Separate optional gates all stopped normally with zero failures/errors/skips:

| Gate | Current result |
| --- | --- |
| Package | 1 passed/3.393s; wrapper5.841281891s. |
| Offline adversarial | 806 passed/337.403s; wrapper341.045727015s. |
| Standard Docker | 22 passed/424.20s; wrapper427.190111876s. |
| Generated Python/Node Docker cohort | 6 passed/395.95s; wrapper398.767834187s; actual business exits0/2/1/0/1/1. |
| Fresh installation | 3 passed/369.93s; wrapper373.496671915s. |

All556 applicable source/README/guide inputs remain unchanged; counts overlap
other gates and are not added to4296. Package, adversarial and exact-scope physical
readback independently passed. The latter checks five standard plus six cohort
journals, real command and CompletionGate evidence, and scoped cleanup, not
daemonwide absence or native P0 write safety. Original cohort PID was not captured;
normal Popen/wait exit is retained, without an independent exact-PID absence claim.
Fresh-installed/public-journey independent review passed at16:18:16.251035 UTC;
verdict SHA256 `87e60322f8367f4433ce9f72c6a3526186c311e55caf063ec9c93d2f5b0b0c7a`.
Six archives match the current accepted pair; three installs each match332
runtime/resources,115 schemas and80 locked distribution metadata entries. Six
immutable journals,10 CompletionGate decisions,18 code receipts and215 artifacts
validate; exact public replay/apply/revoke/rollback and scoped cleanup pass.
These are two seeded offline installs and one public fake-runtime/real-Docker
journey, not three live-model cold starts. Git delivery remains pending at this
pre-publication record. Exact commands, original failures, retained evidence
and final outcomes are recorded in the
[H ExecPlan](../.agent/plans/2026-09-12-engineer-terminal-contract.md).
This slice does not diagnose live05's exact invalid payload or qualify a new live
path; native P0 and the broader original campaigns remain incomplete.

### P1 — six real public-repository readiness observations, 2026-09-12

Six immutable original Python/Node repositories were each acquired and statically
inspected once from delivered c13a3f6. Observed exits1/1/1/1/1/0 mean five incomplete
and one complete static inspection, not six runnable environments or business-test
successes. All reports retain environment unverified, baseline not_checked,
commands0 and execution_authorized=false; no source or Fleet state mutation.
No model, dependency install, project command or Docker run was performed.

The separate normally completed focused regression passed61 cases/22.993s,
process exit0/27.410s, with all556 source/README/guide inputs unchanged. Its earlier
30-second watchdog-aborted trial also recorded61 passing JUnit cases but exited-9;
it remains an incomplete process gate, not another success. Independent readback
passed at15:42:41 UTC; Git delivery is pending at this publication record.
Exact pins, command-discovery limitations, retained
failures and acceptance records are in the [observation report](PUBLIC_REPOSITORY_READINESS.md)
and [pre-execution plan](../.agent/plans/2026-09-12-public-repository-readiness.md).
This does not close native P0 finalization, the24-task campaign, real cold starts
or wider Provider/Harness qualification; generated Docker baselines below remain
a separate evidence set.

### P1-D and P1-E — baseline observations, 2026-09-12

The current candidate adds the existing typed retained observation to
`BaselineShow`, with same-transaction validation of review/execution/report/
resource identities. Standalone CLI and Session expose the same nullable bounded,
redacted/control-escaped output, hashes and flags. Showing it does not redispatch
a command; CLI startup can still initialize/migrate state. No new authority,
migration, capture channel or model completion is introduced. Six optional
generated Python/Node fixtures prove observations through public CLI and real
Docker. The ordinary Docker gate explicitly excludes that cohort unless its
separate prepared image is selected. Existing strict nonempty/no-skip/error gates
remain intact. Details: [baseline delivery plan](../.agent/plans/2026-09-12-baseline-delivery.md)
and [cohort guide](BASELINE_COHORT.md).

The stopped `baseline-current-full-01` default gate used exhaustive disjoint
selection, not sampling. All4323 collected/JUnit identities reconcile:4291 passed,
32 skipped, zero missing/extra/duplicate/failure/error and554 unchanged source
inputs. The32 skips are28 Docker (including six cohort),3 fresh-install and1 live,
not passes. Exact expanded argv, source maps, logs and JUnits remain private.

| Gate | Exact result |
| --- | --- |
| `.venv/bin/python -B -m pytest -p pytest_asyncio.plugin -q`, exhaustive disjoint groups | 4291 passed/32 skipped; collection-to-last-test12:27:23.181872Z–13:02:57.986927Z,2134.805055s. |
| Three integration partitions | 267/252/249 passed; pytest2089.20/1393.75/1371.64s; process2095.550333/1400.059610/1378.019690s. |
| Default-other partition | 3521 passed,32 skipped; pytest1761.65s, process1768.568405s. |
| Original cancellation and baseline-Session serial cases, after every heavy group stopped | One pass each; pytest9.85/18.49s, process11.894497/20.343215s. Original assertions/deadlines preserved; included in4291. |
| `.venv/bin/ruff format --check .`; `.venv/bin/ruff check .`; `.venv/bin/mypy src tests scripts/run_live_canary.py` | 479 formatted files; lint passed;396 type-checked source files. |
| `.venv/bin/python -B -m agent_fleet.schemas.generate --check`; `uv lock --check --offline --python .venv/bin/python`; `git diff --check` | All passed;99 locked packages. |

Full summary SHA256 `2c53c43438604443a276135d6b705ce8178a13157a4cf35873c701b6cf049e1c`;
both554-input maps SHA256
`990c82b4804e434132d1d950804f96e625116e1eb07d13577095792fec760788`.
Independent full/source/static readback passed at13:11:38.548093Z. Fresh collection
found the same4323 identities in3.59s and reconciled all six JUnits. Both original
serial cases followed all four heavy groups, all six static checks and each other;
their JUnit times are9.855s/18.490s. All554 current inputs match both frozen maps
at PR12 mergee45d7e34. Fifteen held D/E source changes match the earlier freeze;
the other539 match PR12, including the eleven accepted F paths. CI/docs were
excluded from that source hold. Source/index/HEAD stayed unchanged. The verifier's
initial syntax-error wrapper failure remains retained, without candidate mutation.
Verdict `de-current-full-readback.tIgE2Reu/VERDICT.md` SHA256
`173d805ca6d12cb46ed9883f305f00f503b9090dd00ae86d628923f921c8286c`.

The separately selected `baseline-current-cohort-01` passed6 in437.84s
(wrapper441.880657s), zero failure/error/skip and554 unchanged inputs. Independent
physical readback released at12:24:48.236807Z. Actual business exits are0/2/1/0/1/1;
all six conclusive observations validate, but the four nonzero business checks
remain failures. Each case has one exact consumed authorization/owner/dispatch/
observation/report, unchanged source and matching public/durable output. All18
baseline leases and cleanup receipts are released; six workspaces and six exact
native IDs are absent. Thirty-six metadata-only queries confirm six empty exact
installation scopes on the matching daemon; all960 retained entries are unchanged.
These are not global Docker or bootstrap-Run cleanup claims.

Verdict `de-current-physical-readback.tNFUKO52/VERDICT.md` SHA256
`b67e04703b6124f5f4ff4402945bfc72c59d485f4e722374580d16ef24b46553`;
cohort JUnit SHA256 `466be03f5d0aab60bfd9dbfaff7eea8b0fe5467f3fcbeb3e0e6e7dff8b5a9ef1`;
summary SHA256 `a66c105925c23df8ac9305091d6d08c7c5a9bfcf0ebcad6da5e100d541d011b6`.
Historical isolated D04 and all rejected retry/cleanup/signal assumptions remain
retained, as does the separate738-deleted-fixture evidence gap in the F plan.

After every full-test process stopped, root preserved stash
`9bfc8931fcd70163654a2788388b88da2cca6fa2`, fast-forwarded to PR12 merge
`e45d7e34bb01de94bada6fdd6a0a718c94af2f37` and reapplied D/E cleanly; all554
source inputs still match the completed full freeze. All four final current-D
runners have now stopped exit0, with zero failure/error/skip and identical556-input
source/README/guide before/after maps (SHA256
`9a5777d3d7def14eee4563ca2b8b4cd160738dafee30798be8ee78487d260c10`).

| Separate final runner | Exact result |
| --- | --- |
| Distribution package | 1 passed/3.93s; wrapper5.919342995s. |
| Standalone offline adversarial | 806 passed/277.11s; gate279.713s, wrapper279.785661936s. |
| Standard Docker, explicit six-cohort exclusion | 22 passed,22 deselected/339.43s; gate342.365s, wrapper342.505614996s. |
| Fresh installation | 3 passed/379.37s; wrapper381.090124846s. |

Exact original entry points, run names and four JUnit hashes are in the baseline
delivery plan. These counts overlap other gates and are not added to4291.
Documentation preflight passed at13:21:14.092425Z, report
`de-docs-preflight.YeFP53qX/VERDICT.md` SHA256
`b9b9c5cebcdc30257a90b3931da31e1087b9c6fb51da1c12d39e52812641e694`.
Stopped-package independent review passed at13:26:35.964296Z: two archives and
the distribution test's isolated installed tree match332 runtime/resource files,
115 schemas and frozen README/guide. Report `de-package-verifier.gP1HqMis/VERDICT.md`
SHA256 `6e8be37bc02c4ddcb7d33f60683832afd66a8ec852da0b7455a56cd600fa989b`.
That package verdict is not the separate fresh-install/public journey verdict.
Standard-Docker physical independent PASS/read release13:33:53.349491Z:
five immutable DBs, nine CompletionGate replays,20 real receipts,56 released leases,
18 absent workspaces,22 empty exact installation namespaces,20 absent native IDs
and772 unchanged fixture files; all556 inputs unchanged. Report
`de-final-docker-readback.zCIrmCUq/VERDICT.md` SHA256
`5ffa894084233376f6671bef15fd9a78f2eea0dd39e7bdcbd59c0c06e9763227`.
Offline-adversarial independent PASS/read release13:30:11.951208Z:15 checks,
806 unique passing identities, original selection/guards and all556 inputs unchanged.
Report `de-adversarial-verifier.jr0KXSUU/VERDICT.md` SHA256
`da76c2eb2cf5c2258d5e76f162db5787fbf4d1d5ea70bae862e9b43cd15da738`.
Fresh-installed/public-journey independent PASS/read release13:36:39.943744Z:
six fresh archives equal the accepted pair; three installs each match332 resources,
115 schemas and80 locked distributions. Seven immutable migration1–13 journals,
10 CompletionGate decisions,18 code receipts and215 artifacts bind the original
three passing cases. Target `run_096b73b647264ceaaf25a3d0a1782348` has two-role
pytest5-pass verification followed by explicit public apply. All54 leases released,
18 workspaces/six native IDs absent, exact namespace `946fc4aa52da4954a3db128eb6cc244a`
empty and556 inputs unchanged. Report `de-installed-verifier.0bmfABzF/VERDICT.md`
SHA256 `2b045ff24569cc8974990cb607d67bb94f7d7ffc373ea20865b55cfbe00467a4`.
The verifier-only initial test-name spelling assumption/correction remains retained,
not an artifact failure. Final terminal documentation/diff review passed/read
release13:49:47.091626Z, with exact28 paths/556 inputs unchanged. Report
`de-final-terminal-verifier.xacbqQOz/VERDICT.md` SHA256
`9e1d7e0060a4ad34f9954af62b23c3019288ab37bb7ec431a81c363738a90424`.
The PR-draft spent-retry phrase was corrected; verifier-only line-wrap failure
is retained. Postrelease changes are only factual terminal/live03 bookkeeping,
not source/README/guide. Exact D/E Git delivery completed at2026-09-12T13:55:02Z
in [PR #13](https://github.com/meyowu/agent-fleet-foundry/pull/13): head
`1577eb0914f6b4757d7fd706634bac076ff05a63`, merge
`606a255580c9ee76f75e899de533431d5ca58c5d`, identical head/merge tree
`83868cd4efebb2b8607f73adcf6e5f112aa24546`. Normal exact-head merge;
protectionfalse/rules[]/checks0/statuses0, no force/admin/rule changes or branch
deletion. `[skip ci]` and Actions0 on both commits are not hosted CI PASS.
Original54-case baseline/cohort-fixture/adversarial-selection postmerge smoke
passed4.38s, all556 accepted inputs unchanged, no key/Docker/install/live call;
those54 passes overlap the full matrix. Evidence `baseline-github-delivery.json`
SHA256 `e5d54dd60879df566bc8bb8d827d80bd30207e62fea70c0b3bca2ca60b4e239e`
and retained `baseline-postmerge-smoke.xml`.
Cleanup acceptance is scoped to the reviewed fixtures/namespaces;
the six-cohort evidence remains separate.
Historical F results and archives below cannot qualify newer D/E bytes.

Six generated repositories are not six external projects or the24-task campaign.
Generic manifests, cold-start slots and campaign reservation/execution machinery
already exist; actual repository/task/oracle/profile identities and completed
cold-start/provider/Harness campaigns remain unqualified. Native P0 finalization
remains NOT_GO/`write_boundary_unqualified`; live02 remains failed with unknown
charge. These D/E gates make no paid provider requests and do not imply an
additional-provider credential, hosted CI success, whole P0/P1 completion or
public package release. The separate live03 attempt is recorded below.

Separate from D/E, the manually authorized finite live03 replay on clean delivered
PR12 stopped NOT_PASSED:13:33:03.149828Z–13:34:07.112382Z,63.962s wall;
pytest1 failed/62.23s,13 warnings. Target `run_8f2d52ea5c4c4648a8deb56b543beded`
completed two CoS requests (14911 input/6538 output/21449 total tokens), followed
by one Engineer reserved UNKNOWN response: three request reservations/two agent
invocations, zero target tools/commands/patch/Verifier. Exact CLI/run.failed message:
`The Agents SDK response model did not match the selected model.`; unchanged
`PROVIDER_FAILED`/`provider_sdk`/`response_policy`. This confirms live03's
model-identity guard branch, not the raw returned model (unretained/unknown) or
a dated-snapshot cause, and does not retroactively identify live02's failed field.
Engineer usage/charge remain unknown. Cleanup reports complete/no outstanding
leases. Independent failed-attempt readback passed/released13:44:44.347799Z,
`mixed-live03-readback.tm0PwoSS/VERDICT.md` SHA256
`bb8ef5f08f37d739ee05627ae15690f424b93bdadb97b0925a70b18c2dc2b47a`.
All8 leases released/3 workspaces absent/2 bootstrap native IDs absent, exact
namespace empty;140 fixture files and PRIMARY550/BASELINE556 inputs unchanged.
All33 stored artifacts validate,21 run exports match and12 project-scoped artifacts
stay separate. Retain the verifier's initial count-assumption failure. The
original failure bundle stays inconclusive/cleanup_unproven; later physical
cleanup supplements it without modifying assurance or unknown cost. Bootstrap fake-agent/real-Docker
evidence is not target-provider proof; no D/E source changed. Initial launcher03
raw/canonical selection-hash preflight failed before credentials/output/request;
retain `mixed-live03-preflight-failure.md`. Separately authorized03b used unchanged
selection. Live02 remains FAILED; no automatic attempt04 or model change is implied.

Prior live04 is a separate explicitly authorized diagnostic configuration,
manually dispatched at13:57Z from clean delivered PR13, and stopped NOT_PASSED:
13:57:54.978425Z–13:58:49.445718Z,54.467s wall; pytest1 failed/52.66s,13 warnings.
CoS stays PydanticAI/openai:gpt-5-nano; Engineer/OpenAI Agents SDK and
Verifier/LangGraph select exactly openai:gpt-5-nano-2025-08-07. No source,
response-admission guard, task oracle, permissions or finite budget changed.
The deprecated snapshot is not a permanent model recommendation. The later
[tracked plan](../.agent/plans/2026-09-12-pinned-model-canary.md) faithfully records
the earlier private pre-dispatch protocol, not a plan that preexisted dispatch.
Target `run_b2ce5fa98bd54c0b81f6f3c1515a9d7f` completed one CoS request with4684
input/4633 output/9317 total tokens; the first Engineer request remains UNKNOWN.
Two invocations/two requests yielded zero target tools/commands/patch/Verifier.
Exact CLI/run.failed message: `The Agents SDK rejected response processing.`,
with unchanged `provider_sdk/response_policy`. The different finite message does
not establish that pinning fixed identity or prove a precise SDK/incomplete-response,
returned-model or deprecation cause; raw detail and Engineer usage/charge remain
unknown. Independent failed-attempt readback PASS/read release14:04:35.683988Z,
`mixed-live04-readback.xy2UP1bs/VERDICT.md` SHA256
`ad2b1c7ff10f354378c6c3a0947122936f33e82290b4659f7521a5b7ccdfffea`:
CLI equals immutable event37; all33 artifacts validate (21 run/12 project),
8 leases released/3 workspaces absent, exact namespace
`bac0631c525e142d2f27d2a3c9b8957d` empty/2 bootstrap native IDs absent on the
matching e470 daemon. All140 fixtures/both556 maps/raw and canonical selection
unchanged; no04 auditor assertion failed. The original inconclusive/cleanup_unproven
bundle is preserved; supplemental cleanup does not promote assurance. Live04 remains
NOT_PASSED. This record authorizes neither implementation nor attempt05.

Latest live05 is the separate pre-dispatch
[low-cost Harness configuration experiment](../.agent/plans/2026-09-12-low-cost-harness-canary.md),
not an automatic retry or source repair. CoS stays PydanticAI/openai:gpt-5-nano;
Engineer/OpenAI Agents SDK and Verifier/LangGraph explicitly select
openai:gpt-4.1-nano-2025-04-14 under unchanged source/oracle/permissions/budgets.
Independent12-check pre-dispatch review passed/read release14:18:20.155306Z,
`live05-predispatch-verifier.iNjcw9rZ/VERDICT.md` SHA256
`0d08d2465de8435d8f55a237cd81a780a3ce3df82c0581f5d7fc3ca7730768b3`;
root separately decided one dispatch at14:19Z. It stopped NOT_PASSED:
2026-09-12T14:19:49.008936Z–14:20:26.503411Z,37.495s wall;
pytest1 failed/35.69s,13 warnings. Target `run_8f55c18e3547410bb929945ddc0bc13c`
returned `RUNTIME_OUTPUT_INVALID` with `output_schema/schema_validation` and
`The bounded Agents SDK invocation did not satisfy its trusted contract.`
Runner cleanup reports complete, recovery not withheld and diagnostic_errors[];
independent failed-attempt machine audit PASS/read release14:27:18.204341Z.
Evidence `mixed-live05-readback.pamnbbdY/result.json` SHA256
`33c54cbc07c289fea9a5cd2b09f513b2c60f9ff097acbdcbe722f1fe9c3d1b74`;
human VERDICT.md SHA256
`952cd3a8efe4e0f81e898dbd0050ad71ea1381ab59a12c8906a2ed8f3d1273d7`
confirms the same release and facts. Actual live outcome remains
NOT_PASSED. CoS1 request:4678 input/2304 output/6982 total tokens; Engineer4:
10201 input/304 output/10505 total. Together5 reported requests/17487 tokens,
zero unknown/outstanding requests; billed cost unknown. Engineer used
workspace.get_diff, workspace.write_file and command.run. One standalone
real-Docker `python -m pytest` exit0 receipt exists, but there is no accepted
Engineer message, Run-attached receipt, patch or Verifier invocation. Original
target unchanged;9 leases released,3 workspaces/3 native IDs absent, exact namespace
`5fbbf50e61a8105ebc63d1a6280eceea` empty;143 fixture files/both556 maps unchanged.
All36 artifacts validate as24 Run exports and12 project records. The original
inconclusive/cleanup_unproven bundle remains unchanged: standalone receipt and
supplemental cleanup are not qualification promotion. This finite error still
does not reveal the exact rejected content or justify a repair. Preserve all
prior failures; no additional
paid attempt follows05 in this experiment.

### P1-F — exact Docker Session restoration, 2026-09-12

The repair adds an internal `SandboxProvider.restore(handle, spec)` seam after
existing paused-lease checks. Exact retained handle/specification, installation,
workspace, Docker daemon/image and held Git-shadow pin must still match, including
identity rechecks after awaits. Absent state uses strict restoration; conflicting
state is preserved and rejected. Duplicate `create` rejection, execution
reservations, permission checks, recovery rules and the no-host-fallback boundary
are unchanged. No CLI/schema/migration/dependency or provider call is added.

Fresh independent offline review passed 233 sandbox contracts, 17 ownership/
recovery cases and 22 adversarial cases. After separately retained test-driver and
fixture repairs, `session-docker-full-03` passed the real-Docker marker selection:
22 passed, 22 deselected, zero failure/error/skip; pytest 246.90s, wall 248.916883s.
All 547 physical source inputs stayed unchanged. Independent physical readback
released at 2026-09-12T11:20:08.137149Z; all 619 held candidate files and Git state
stayed unchanged during that review.

| Physical acceptance surface | Exact observed result |
| --- | --- |
| Public same-process terminal, packaged learning fixture | Plan review and two distinct command approvals; Engineer and independent Verifier each have an exit-zero pytest transcript with 5 passed; `ready_for_review`, `verified_complete=true`, no gaps. Original source unchanged. |
| Retained and recreated conversation variants | Each has two independent exit-zero pytest receipts with 3 passed, structured criterion mappings and verified completion. Original source stays unchanged until explicit public canonical patch apply; only the intended core and new metadata module then change. |
| Synthetic negative terminal fixture | Four distinct approvals/receipts, reviewed build exit1 and pytest exit2 for each role. `verified_complete=false`, with `COMMAND_EXECUTION_FAILED` and `CRITERION_NOT_PASSING`; a passing negative test is not a successful task. |
| Five Session/onboarding fixture cleanup audit | 9 bootstrap/target Runs, 20 typed command receipts, 56 released leases, 18 recorded workspace paths absent and 20 exact native IDs absent. All 22 attempt-specific installation-label inventories are empty on the matching daemon. |

The other 17 physical cases have named passing JUnit evidence; the deep lifecycle
ledger audit covers the five Session/onboarding fixtures, not arbitrary Docker
resources. Physical01 remains FAIL (19 passed/2 failed); physical02 remains FAIL
(20 passed/1 failed). Driver/asset failures, stopped-state backups and exact
physical01 cleanup remain recorded in the [restoration plan](../.agent/plans/2026-09-12-session-docker-resume.md).
Verdict `f3-physical-readback.IRwinLHh/VERDICT.md` SHA256:
`6460cbb8d1f841a1b9ef430eb04e4fa90ab3113462939b397163d22f33b021ab`.
Physical03 summary SHA256:
`2fbd8d4d215890e70381d18a3f89df56fc13454ce3b957fba0f58095c95bc7dd`;
JUnit SHA256 `7df44f76ddaacd538346b09c1f88e60a9343f41d8b513c22dac40a08cabe5ff2`.

Root integrated the identical reviewed F source/test bytes atop PR11 merge
`5b09fea1c5fdb79066498496852adbb9e5239773`. Independent combined-source verification
passed at11:39:28Z: all548 current inputs match the full-gate freeze,11 F inputs
match accepted physical03 and the other537 match PR11, including G's five paths.
All17 source/AST checks passed twice;55 existing Docker provider functions are unchanged.
Verdict `bgf-source-verifier.cm9BlI/VERDICT.md` SHA256
`e05a4f2f921825fbdc5ae9ae8d500578c2f3ff017c95b5c983a43bfa4225acbd`.
This verdict excludes documentation, full-test and package acceptance.
The current integrated full offline gate `session-current-full-01` passed4246,
with26 skips and4272 exact collected/JUnit identities, zero missing/extra/duplicate/
failure/error and548 unchanged source inputs. Collection-to-last-test elapsed
1901.692739s (11:29:00.673Z–12:00:42.366Z). Integration groups passed253/248/265;
default-other passed3478 with26 skips, and the original two serial cases passed
once each. Skips are22 Docker,3 fresh-install and1 live, not passes. Ruff format474,
lint, mypy392, generated schemas, offline99-package lock and whitespace passed.
Exact commands, durations, warnings and hashes are in the restoration plan.

The current standard Docker adversarial entry point also passed22,22 deselected,
zero failures/errors/skips (pytest461.18s; wrapper466.009177s), with550 unchanged
source/README/guide inputs. Because it overlapped the default serial cases' first
execution, the unchanged two serial cases were repeated after both jobs stopped:
2 passed24.66s, separate overlapping proof, not two additional unique tests.
Independent current full/static/source terminal readback passed at12:07:04.862044Z:
fresh collection, all six JUnits, all six static argv/results and548 current
source inputs matched. Report f-full-verifier.NEXvzSz5/VERDICT.md SHA256
`4bb76964ce14b834e4cc79ad3ab07cd436299349763e17189cb6e8217b386bdb`.
Current physical readback passed at12:07:33.940349Z: all22 identities/550 frozen
inputs matched; five stopped immutable Session DBs replayed9 completion decisions
and20 command receipts,56 released leases,18 absent workspaces and20 absent native
IDs. All22 exact installation scopes empty;772 deep-fixture files unchanged, no
auxiliary files or retained DB handles. Original terminal/conversation apply
boundaries match the earlier physical03 scope. Report
f-current-physical-readback.Qj0IIVgX/VERDICT.md SHA256
`f7fce493a1bdfff94c56a63e9dcf753ca22433b1d78579750b8cf30a2bcd6784`.
The unchanged standalone offline adversarial gate passed806 in285.69s
(288.595s gate,288.692113s wrapper), no failure/error/skip; original550 inputs
remained unchanged. Subsequent README/guide-only corrections are independently
reviewed; they do not change this source qualification. The distinct final-doc
distribution check passed1/3.35s (5.009104s wrapper); final fresh-install passed3
in270.05s (271.984476s wrapper), no failure/error/skip and550 unchanged inputs.
Final artifact review passed at12:48:11.175677Z; F GitHub delivery subsequently
completed as recorded below.
Eight archives and four installed trees match332 current runtime resources,
115 schemas and the final README/guide. Seven immutable journals1–13 and10
replayed completion decisions passed;54 leases released,18 workspaces absent,
6 exact native IDs absent and one exact installed-Docker namespace empty.
Original final-artifact FAIL was only the stale un-packaged G Outcomes sentence;
the eight-check exact correction recheck passed without source/artifact changes.
Report f-final-sentence-recheck.PIEGQyGw/VERDICT.md SHA256
`45f9cb7519ddc1f33d869c5702eed85247c62ca410e404e8bd750747a03ca836`.
The standalone
adversarial report independently passed in session-adversarial-verifier.tH7c6E3a
(SHA256560f5b48d1ec377912f9159da0fe8b3556ab4ef4c0151935d0885550367ae744).
These overlapping counts are not added to4246. This bounded physical
qualification does not establish mixed-Harness/live-provider reliability, close
the separate current D/E gates or qualify native P0 finalization.

[PR #12](https://github.com/meyowu/agent-fleet-foundry/pull/12) merged normally at
2026-09-12T12:52:42Z: head `b07382369f705b4d76661e17348c04e12dbbb245`, merge
`e45d7e34bb01de94bada6fdd6a0a718c94af2f37`, identical tree
`d02b0447ddabf20923f5b44f0eb44a0599150ea6`. Exact-head premerge readback had
protected=false, rules[], checks0 and statuses0. No bypass or branch deletion;
head and merge use `[skip ci]`, with Actions0 for each, not hosted CI PASS.
Postmerge restore contracts passed22,211 deselected in0.28s; these overlap prior
tests. Exact remote readback is retained in `session-github-delivery.json`.
F's README/guide and archive hashes are frozen historical artifacts, not packages
of the newer D/E documentation or source. No full P0/P1 completion is claimed.

### P1-G — bounded SDK response diagnostics, 2026-09-12

This separate slice builds on PR10 mergea96eb29 and changes only two runtime
boundary modules, their two contract suites and CLI diagnostic regressions.
No new schema, migration, dependency, endpoint, authority, budget or retry is added.
Fixed messages identify existing response rejection branches through CLI
error.message and durable run.failed; agent.failed keeps its restricted projection.
The receipt clears its request-note pointer on context exit while the current
request retains only the finite local note for projection. Later requests start
with a new empty note. Original code/category/remediation and timeout/approval/
cancellation/unknown-accounting behavior remain unchanged.

The first candidate was independently rejected for changing error classification
and inspecting exception chains. The repair passed fresh independent review at
10:36:45Z:240 runtime contracts,6 CLI cases,34 actual-SDK differential runs,
request-note/hostile/precedence probes and two independent raw JSON/usage CLI
durability cases. LangGraph221 paired/120 precedence/four parse cases remained
unchanged except allowed messages. All code/test bytes remained identical when
root fast-forwarded onto PR10. A later documentation-only FAIL identified stale
review status and imprecise pointer-lifecycle wording; both were corrected without
changing the accepted code. All failed sources/reports/fixtures remain retained.

The complete G-baseline offline gate used a cleared no-key environment with Docker,
live and fresh-install opt-ins disabled. Expanded argv, JUnit, timestamps and
source maps are retained privately in sdk-diagnostics-full-01. Counts overlap
with the focused reviews; do not add them as extra distinct tests.

| Gate | Exact result |
| --- | --- |
| `.venv/bin/python -B -m pytest -p pytest_asyncio.plugin -q`, exhaustive disjoint selection | 4211 passed,23 skipped;4234 collected/JUnit identities,0 missing/extra/duplicate/failure/error;548 source inputs unchanged. Collection-to-final-test10:38:46.421Z–11:07:34.823Z,1728.402139s. |
| Integration partitions | 249/251/265 passed; pytest1689.78/1190.73/1569.24s; process1692.147728/1193.75/1572.03s. |
| Default-other partition | 3444 passed,23 skipped;1580.73s pytest,1584.00s process. |
| Original serial cancellation / baseline Session cases | One pass each, process11.032361/20.072817s; original deadlines/assertions unchanged. |
| `.venv/bin/ruff format --check .`; `.venv/bin/ruff check .` | 473 files formatted; lint passed. |
| `.venv/bin/mypy src tests scripts/run_live_canary.py` | 392 files passed. |
| `python -B -m agent_fleet.schemas.generate --check`; `uv lock --check --offline --python .venv/bin/python`; `git diff --check` | All passed; lock99 packages. |

The23 skips are19 explicit Docker,3 fresh-install and1 live-provider cases, not
passes. Existing JUnit record_property and SDK deprecation warnings are retained.
Summary SHA256 `9c8a69b729f686be909f9ccc61161c14645826259f66029cf4ab0e1d7ed5cc65`;
both source maps SHA256
`3ac12ca38e29123ef48e8e64a4853f6efa2914edb27f2536847443e182801f2b`.
Final G-baseline README/package refresh passed1/2.82s; wheel/sdist/JUnit/README
identities are recorded in the diagnostics plan. Independent terminal/archive
readback passed at11:19:00Z in sdk-final-verifier.xX3CAM: fresh collection and all
six JUnit files reconciled,548 source inputs matched,332 archive/installed runtime
resources and the frozen G README matched,115 schemas and migration journal1–13
passed. [PR #11](https://github.com/meyowu/agent-fleet-foundry/pull/11) was normally
merged at 2026-09-12T11:28:17Z: head
`13daa225d8a195a9e16d317bac6b21e282b89319`, merge
`5b09fea1c5fdb79066498496852adbb9e5239773`, identical tree
`5d918cf7954918058cda150686183fd101390f63`. Exact-head merge used no admin bypass,
rule changes or branch deletion. Actions readback is zero for both head and merge,
not hosted CI success. These archives are historical G artifacts, not packages
of the newer F candidate or its updated README.
After fast-forwarding the clean diagnostics worktree to that merge, the existing
CLI runtime-diagnostic durability selection passed 3 tests, with 32 deselected,
in 6.62s under a cleared no-key/no-Docker/no-install environment. Retained evidence
is `sdk-postmerge-smoke.xml`; these overlapping smoke tests are not added to 4211.

No new live request was made by this slice. The mixed-Harness live02 below remains
failed with unknown Engineer usage; new diagnostics cannot reconstruct its missing
field-level cause. F's separate full/static/physical/artifact acceptance and PR12
delivery are recorded above. Current D/E gates, native P0 finalization
and broader Provider/Harness campaigns remain separate. No hosted
CI success, full P0/P1 completion or package publication is implied.

### P1-B — explicit Canary-selection infrastructure, 2026-09-12

This continuation record supplements, rather than rewrites, the historical
phase snapshots below. Governing plan:
`.agent/plans/2026-09-11-p0-p1-completion.md`. Candidate base is the Foundry
rename merge `09c5a64f06888c2feb6ae8aea2cd0aca8f212148`; P1-A's five Session
rejection/continuation cases were already merged in PR8. This slice changes
optional test infrastructure and its documentation, not production adapters,
permissions, schemas, dependencies or budgets.

`scripts/run_live_canary.py --selection FILE` now accepts a bounded strict JSON
selection for CoS, Engineer and Verifier. Production runtime validators admit
pairings; dedicated credential namespaces, a cleared child environment, canonical
selection digest and complete five-role configuration closure precede dispatch.
The legacy canonical default remains unchanged. Admission is not live qualification.
The guide documents single-attempt limits, no automatic retry/fallback/apply,
unknown usage and exact evidence/cleanup requirements.

All commands below returned exit0 in the pinned local macOS arm64/Python3.14.6
environment with live, Docker and installation opt-ins disabled. The full suite
was partitioned exhaustively, not sampled. Raw expanded argv, timestamps and
JUnit are retained privately in `canary-full-03`; test layers overlap.

| Gate | Exact result |
| --- | --- |
| `.venv/bin/python -B -m pytest -p pytest_asyncio.plugin -q`, disjoint full selection | 4181 passed,23 skipped;4204 unique collected/JUnit identities;0 missing/extra/duplicate/failure/error. Four parallel groups then two unchanged serial cases, total run08:45:53.168579Z–09:18:13.693271Z. |
| Three integration partitions | 249/264/251 passes; process walls1899.447208/1802.854939/1290.383776s. |
| Default-other partition | 3415 passed,23 skipped; wall1766.097497s. |
| Original cancellation and baseline-Session serial cases | One pass each; walls16.403791/20.625948s. No deadline/assertion changes. |
| `.venv/bin/ruff format --check .`; `.venv/bin/ruff check .` | 472 files formatted; lint passed. |
| `.venv/bin/mypy src tests scripts/run_live_canary.py` | Passed,392 source files. |
| `.venv/bin/python -B -m agent_fleet.schemas.generate --check`; `uv lock --check --offline --python .venv/bin/python`; `git diff --check` | All passed; lock99 packages. |
| Independent terminal readback | Both548-input source maps and current source identical;620 held candidate files unchanged; all4204 identities reconciled independently. Both archives matched332 current package resources and the then-current README. |

The23 skips are exactly19 opt-in Docker,3 fresh-install and1 live-provider case.
They are not promoted into passes. Independent verdict timestamp
09:23:34.139259Z: **PASS for B offline infrastructure only**. Summary SHA256:
`a7fdd78c5a799dacb16e41ffdede30d2e1ba71675b10c3525cd43551376f883a`;
source-map SHA256:
`6045d3ff6d8e2ec6600590a4d269c4fe9125a8f424c42b33da3787ab06feafaf`.
The earlier full01 failure and interrupted full02 remain retained and separate.
Final documentation/package closure and immutable GitHub delivery are recorded
in the continuation plan; this working-tree record alone does not prove merge.

#### Separate live02 result: NOT_PASSED

One manually selected OpenAI attempt followed that offline PASS, using
PydanticAI/CoS, OpenAI Agents SDK/Engineer and LangGraph/Verifier, all
`openai:gpt-5-nano`. Selection SHA256:
`0ed325d81f65ee619a0f114fee838e89972d7de57202a5347b034a8fc95a2e0d`.
The private `openai-mixed-live-02` launcher ran09:24:18.047687Z–09:25:00.076977Z
(42.03s); pytest returned1failed/40.29s with13 SDK deprecation warnings.

Target `run_a9580c06384644688ea9bf3ec1bed908` failed while implementing.
CoS completed one real request with4681 input+4077 output=8758 reported tokens.
Engineer reserved its first request, then failed `PROVIDER_FAILED` with
`provider_sdk/response_policy`. Target totals:2 invocations,2 model-request
reservations,1 unknown request/32768 unknown-token reservation,0 tool calls.
There is no target command evidence, patch or Verifier invocation; the total
charge is unknown. Five reviewed bindings are frozen at revision4. The separate
scripted bootstrap's two Docker commands and successful report are not target
evidence. No patch was applied and no automatic retry occurred.

The launcher stopped normally. Independent09:35:07Z terminal readback confirmed
all8 leases released (2target/6bootstrap),3 workspace paths absent, both native
bootstrap containers absent on the matching daemon and an empty exact
installation-filtered inventory. Receipt hashes, target Git baseline/five files
and all original evidence were preserved. Stopped, identity-checked immutable
SQLite reads created no sidecars. Its target failure bundle was assembled before final cleanup and still
records that earlier proof gap; later lifecycle/cleanup evidence must be read
separately, not used to rewrite the failed bundle. The precise rejected response
field remains unresolved. Exact model-alias equality is an offline hypothesis,
not an observed provider response or proven cause. Native P0 qualification,
D/E local candidate evidence is recorded above with final gates/delivery separate;
additional-provider and mixed-role campaigns remain incomplete. The separate F
Docker Session repair is delivered in PR12 with historical full4246/26, physical
and final artifact acceptance. No remote CI success,
whole P0/P1 completion or public package release is implied.

### Historical phase evidence

The initial audit on 2026-09-05 inspected Phase3 baseline `c700de1fc357844113426d3352cf29b6ffeae0f1`. Phases4–6 are accepted by E4–E6. E7 binds the repaired runtime3293244, final accepted PR head `e413192bacf236ae243f350b4ade12f7fefbc650` and actual [PR #5](https://github.com/meyowu/agent-fleet-foundry/pull/5) merge `0cead7dcafcace07d64892c0ff41ed72939d706a`; accepted and merged trees equal `7b052436feb7c537391d4f421a8ee35468a93380`. Subsequent documentation-only main/package checks are a separate delivery record. Whole-phase metadata remains6 because live-provider/public-license gates remain unperformed; no complete public release is claimed. ExecPlans retain exact commands and failed attempts. Earlier snapshots and starting/baseline columns remain historical evidence and regression obligations, not current missing implementations.

- **Baseline:** relevant code and tests exist; this ledger's initial audit did not rerun those suites.
- **Partial:** a working subset exists but does not meet the complete requirement.
- **Missing:** no operational implementation or required artifact was found at the baseline.
- **Unproven:** implementation or historical evidence may exist, but the required current acceptance evidence has not been recorded.
- **Accepted Phase 4 (E4):** the bounded Phase 4 behavior passed its final regression, full-suite, static, archive and real-Docker gates. Phase 5–7 and live-provider/license prerequisites remain open.
- **Accepted Phase 5 (E5.1/E5.2/E5.3):** durable budgets/evidence, adaptive graph execution and persistent chat passed the frozen full behavioral/static gates and are committed/pushed through `a46b688`. Phase 6/7 and external release prerequisites are not accepted by these results.
- **Accepted Phase 6 (E6):** reviewed organization evolution passed the frozen local default/Docker/static gates and is committed/pushed as b42cdf9. Linux execution, final installed-user/platform release evidence and external gates are not implied by local acceptance.
- **Optional/deferred:** explicitly optional or outside this MVP; this is not a label for unfinished mandatory work.

Each acceptance record must state exact commands, exit status, counts/skips, platform and evidence type; link available commit/tree identities and state/events/artifact hashes, explicitly identifying missing identity or raw-log records rather than inventing them. Record whether evidence came from fake runtime, offline PydanticAI TestModel/FunctionModel, a live provider, simulated sandbox, real Docker, or local-unsafe. Preserve failures and superseded evidence. Working-tree acceptance is separate from immutable release/publication evidence.

The initial audit ran only two in-memory probes: malformed referenced Workflow YAML passed `validate_fleet_files`, and a FleetPatch containing both `.fleet/agents/a` and `.fleet/agents/a/b.md` passed the current path validator. No project configuration, Fleet state, provider request, credential resolution, or Docker operation was performed by those probes. Historical Phase 3 test counts and manual Docker results remain in its ExecPlan; they are not fresh Phase 4–7 evidence.

### E4 — accepted Phase 4 snapshot, 2026-09-05

The following gates returned exit 0 on the local macOS/Colima acceptance environment. The final aggregate supersedes earlier Phase 4 intermediate counts and failures, retained below and in the [completion plan](../.agent/plans/2026-09-05-mvp-completion.md). Test layers overlap and must not be added together.

| Command / gate | Exact result |
| --- | --- |
| `uv run pytest -q` | `1001 passed, 10 skipped in 431.79s`; exactly nine opt-in Docker skips and one opt-in live-provider skip. |
| `uv run pytest -q tests/unit` | `510 passed in 53.30s`. |
| `uv run pytest -q tests/contract` | `281 passed in 4.47s`. |
| `uv run pytest -q -m integration tests/integration` | `156 passed, 49 deselected in 311.72s`. |
| `uv run pytest -q tests/e2e` | `4 passed in 44.40s`. |
| `uv run pytest -q tests/integration/test_cli.py` after Phase 4 metadata update | `30 passed in 22.52s`. |
| Ruff formatting/lint; `uv run mypy src tests` | 165 files formatted; no lint findings; no type errors in 141 source files. |
| Generated-schema check and `git diff --check` | Passed, including the post-metadata refresh. |
| Q6 separately enabled real Docker | `9 passed in 42.32s`; zero remaining Fleet-managed containers. |
| `uv build --offline` and archive inspection | Wheel and sdist each contain 129 package files, including 37 schemas, four migrations and three runtime prompts; rebuilt successfully after metadata update. |

E4 accepts F4-01–F4-13 at the documented supported ceiling: current policy, trust mutation failures, reset cutoff, derived-rule receipts, exclusive dispatch, exact role checkpoints/legacy agent restoration and model-reason continuity. Both independent audit findings have fixes and regression coverage in the final suite. Fake/FunctionModel tests remain offline/simulated; separate Docker tests prove the local isolated executor and fresh-verifier path, not model quality. **No live provider was run or live credential used.** Archive validation is not a cold installed-user journey, platform matrix or OSS publication. Phase 5–7, the complete U1–U12 product journey, detailed guide, L1 license and L2 live-provider gates remain open.

### E5.1 — accepted budget/evidence slice, 2026-09-05

The accepted Phase 4 checkpoint is `2e930920cff955c7db60c6bc8391a4671a310ce7`. The first Phase 5 slice was subsequently committed as `ab28aaa6192a8e4d92c78dada2413eb5606376b7`, tree `6c2a800347863f7d728e884fc57c885cf6ab3903`. Both checkpoints are now pushed to `codex/mvp-completion`, with remote read-back at the M1 tip. Main remains `c700de1fc357844113426d3352cf29b6ffeae0f1`; this is not a new merge or published release.

The frozen default suite passed `1170 passed, 11 skipped in 648.79s`; the ten Docker cases separately passed in `62.24s` (one offline case deselected), with zero managed containers and zero outstanding leases in all 18 Docker-test databases. The remaining skip is the unperformed live-provider case. Ruff formatting (181 files), lint, mypy (155 source files), offline lock/sync, schema drift (43 schemas), whitespace and offline source-identical wheel/sdist gates passed. Each archive contained 140 package files, migrations 1–5 and three prompts. A final EOF-whitespace-only correction to migration 5 passed 71 migration/budget regressions and renewed archive checks before commit.

This accepts cumulative request/tool/accounting limits, exact configured role/delegation ceilings, direct response and bounded repair feedback, typed criterion mappings and text-only new-file patches. An actual offline FunctionModel + Docker journey verifies two criteria against the current independent parent patch and explicitly applies a new module after review. It does not establish live-model quality, fresh dependency installation, all Phase 5 or the MVP. Full evidence and retained failed intermediate approaches are in `.agent/plans/2026-09-05-adaptive-workflow-chat.md`.

### E5.2 — accepted adaptive graph slice, 2026-09-05

Implementation now covers all five strategies, exact internal child identities, queue/concurrency bounds, bounded read-only specialist dependencies, immutable driver/continuation claims, deterministic joins, fresh parent verification, cancellation/recovery and structured graph delivery. The independent store, scheduling, role and delivery audits have retained regression tests. Public CLI E2E exercises status/artifacts, exact child approvals, parent-only lifecycle/application, human/JSON parent remediation and descendant-only recovery while preserving an unrelated graph.

The final local macOS arm64/Colima gates passed on source/test aggregate `4cbef9616084ad1465ee5fd84b97f81763f282bc95b96c11b5bb7d35cfeafeb9`, unchanged through final testing and read-back. This is the hash of sorted repository-relative source/test file byte hashes, not a Git commit. The [graph ExecPlan](../.agent/plans/2026-09-05-adaptive-graph.md#final-acceptance-evidence) retains commands and earlier attempts; test layers overlap.

| Command / gate | Exact result |
| --- | --- |
| `AGENT_FLEET_ENABLE_DOCKER_TESTS=0 AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 uv run pytest -q` | `1344 passed, 13 skipped in 1160.72s`; twelve gated Docker cases and one unperformed live-provider case. |
| Separately enabled full Docker suite | `12 passed, 3 deselected in 140.05s`; three offline cases deselected. Zero managed containers and zero active leases across all 22 test state databases. |
| `uv run pytest -q tests/e2e` | `9 passed in 214.64s`. |
| Final artifact/delivery/normal graph focus | `16 passed in 164.85s`. |
| `uv run pytest -q tests/integration/test_graph_delivery_audit.py` | Independent audit: `11 passed in 144.48s`; no remaining findings in its bounded review. |
| Final dependency/static/schema refresh | Lock: 51 resolved; sync: 49 checked; Ruff format: 203 files (202 at freeze); lint passed; mypy: 172 source files; 55 schemas and whitespace checks passed. |
| Offline build plus `uv run pytest -q tests/integration/test_distribution.py tests/unit/test_schema_generation.py` | Pre-documentation: `4 passed in 2.82s`; final README-frozen rebuild/read-back: `4 passed in 4.37s`, repeated after its result entry with `4 passed in 1.73s`. Both archives match all 161 package source files and README; 55 schemas, six migrations, five prompts and isolated wheel-content smoke passed against existing locked dependencies. |
| Retained pre-final marked integration failure | `2 failed, 212 passed, 85 deselected in 823.08s`: rehydration attempted terminal-parent ordinary owner release; missing cleanup bytes leaked a raw OS exception. Fixed and superseded by the focused and frozen full gates above. |

This accepts the graph-specific F5-03/F5-04/F5-09/F5-10/F5-11 boundaries, not every Phase 5 row. Actual plan/node equality and producer-byte hashes bind plan/join/cleanup content; application assembly also reads exact stored artifacts. Known rehydration failure fences the graph before cleanup; uncertain later resume persistence retains non-replayable ownership until explicit stopped-owner recovery. Parallel child suites may fail while a sibling module is absent; only the complete joined parent suite can yield independent verification. Fake/FunctionModel tests do not become live-provider evidence, and FakeSandbox remains INCONCLUSIVE. No actual provider credential, live request, image pull or build was used for E5.2. Its checkpoint was subsequently committed/pushed as recorded in E5.3. Persistent chat implementation and its focused evidence are separate from full Phase 5 acceptance; final GitHub merge, fresh installation/platform proof and L1/L2/Phase 6–7 gates remain open.

### E5.3 — accepted persistent chat and complete Phase 5, 2026-09-05

M2 was committed and pushed as `7a70b1a940209487deac5585583ba1f9924be8d9`, tree `bf75f1d681e36b30954235214ed641202945b060`; remote main remains `c700de1`. M3 adds migration 7 and ten schemas (65 total), atomic turn/Run registration, shared non-expiring resume ownership, bounded context and responsive CLI. The frozen gates below accepted persistent chat and the complete Phase 5, subsequently committed/pushed as `a46b688`.

Focused observations: persistence/conversation/budget/graph group 203 passed in 69.27s; new CLI unit/subprocess group 31 passed in 65.60s and existing CLI/permission group 54 passed in 43.41s. Fresh independent safety review found and fixed an exact cancellation-target race and terminal-fence reconciliation defect; final 29 passed in 51.59s, root replay 29 passed in 51.80s. The public initializer→chat→Safe approval→reconstruction→independent real-pytest verification→explicit apply journey passed 1 Docker test in 15.82s (one offline case deselected). Two distinct principals each ran three real tests; the original target was unchanged until apply and no leases remained. Test groups overlap and are not additive.

The real Docker journey uses offline FunctionModel responses, a synthetic exact credential reference and an explicitly built local runner containing genuine cached pytest dependencies. The image was built with no pull/network, identity `sha256:15245c81b1efb7a68bad269f03737955eb5e6a2b7fc79aa98faa49c93a899851`. No actual provider credential/request was used. This does not prove fresh-user dependency installation or a distributed image. Failed fixture assumptions and both independent defects remain in the [persistent-chat plan](../.agent/plans/2026-09-05-persistent-chat.md).

All frozen behavioral gates passed on local macOS arm64/Colima with source/test checksum `2f806013a7e029b5dea20c08ca64a94a4dd135a156a65662bfa31a859ec8b3f3`, unchanged through those gates. Selections overlap and must not be added together.

| Command / gate | Exact result |
| --- | --- |
| Full default suite, Docker/live opt-ins disabled | `1472 passed, 14 skipped in 1354.35s`; thirteen gated Docker cases and one unperformed live-provider case. |
| Separately enabled Docker suite | `13 passed, 4 deselected in 101.98s`; zero managed containers and zero outstanding leases across 24 databases. Nine historical RECOVERED records remain for audit. |
| `uv run pytest -q tests/unit` | `716 passed in 67.88s`. |
| `uv run pytest -q tests/contract` | `396 passed in 9.57s`. |
| `uv run pytest -q -m integration tests/integration` | `251 passed, 85 deselected in 952.14s`. |
| `uv run pytest -q tests/e2e` | `19 passed in 255.40s`. |
| Fresh independent safety review and root replay | `29 passed in 51.59s`; replay `29 passed in 51.80s`. |
| Frozen dependency/static/schema gates | Lock: 51 resolved; sync: 49 checked; Ruff formatting/lint: 217 files, no findings; mypy: 186 files; 65 schemas. |
| Initial archive/schema selection | `5 passed in 3.29s`; 178 package files, 65 schemas, seven migrations and five prompts. Final README-frozen archive results are recorded separately below. |
| Post-metadata CLI/archive/schema refresh | `35 passed in 32.52s`; Ruff formatting/lint passed across 219 files, mypy across 186 files, schemas and whitespace checks passed. Two previously untracked files were recognized by the formatting inventory; this is not an additional behavior change. |
| README-final archive/schema read-back and result-entry repeat | `5 passed in 1.99s`, then `5 passed in 1.70s`. The final wording-only refresh also passed `5 tests in 1.70s` (exit 0); no README changes followed that check. |

After the frozen behavioral gates, only whole-phase metadata and its two assertions changed from 4 to 5; the focused refresh above passed separately. Final source/test checksum `f7e5d377c89c21876052841809c7efa454cbd20764420a5465b7f0a868ec89f6` identifies this metadata-only update; `2f806013…` identifies the unchanged full behavioral acceptance tree. Phase 5 was subsequently committed/pushed as `a46b688`. Phase 6 whole-phase acceptance, release hardening/guide, fresh-user/platform proof, final GitHub merge and live-provider/license prerequisites remain open.

### E6 — operational organization evolution: locally accepted 2026-09-05

Final behavioral freeze: `e1d946ceeeb2b5ec7f3a47d7c6353ce6b6a0b5f35b740f818040188d386c9ffb`; source-only `b35653c7d6dedbaaf51644bfae31274ecf6e9f1f863be9585a5ab5422be4e5ab`. Final default: **1973 passed,15 skipped in1499.51s**, zero errors/failures. JUnit partitions: unit1010, contract567, integration369, offline E2E22, four offline Docker-directory cases and one provider-readiness case. These are partitions of one all-layer run, not additional independent suite executions. Fourteen actual Docker cases and one actual live-provider case are skipped by default. Separately enabled real Docker: **14 passed,4 deselected in178.84s**; focused workflow/configuration/error compatibility: **57 passed in291.68s**. Static: Ruff249, mypy213,82 schemas, lock51/sync49 and whitespace passed. Independent integration PASS (36/226.85s) plus read-only delta PASS and six fresh guard/lock/error probes cover the final narrow repair. Platform: macOS arm64/Colima, not Linux or live inference. Marker5→6/package refresh and checkpoint identity are recorded subsequently in the evolution plan.

Retained failure before the final repair: default `1 failed,1972 passed,15 skipped in1753.32s`; marked integration `1 failed,283 passed,85 deselected in1196.66s`; chained E2E `22 passed in288.16s`. Only code-patch guard-entry CONFIG_INVALID incorrectly replaced the public PATCH_TARGET_DIVERGED error. The implementation now translates that exact boundary error without a cause/context; the original expectation remains and Run immutability is asserted. Other guard/body/exit errors stay unchanged. The final successful freeze above supersedes the earlier candidate results below, which remain historical evidence rather than current open failures.

Implementation: bounded CoS FleetPatch output and pure content hashing, immutable proposal/diff artifacts, strict workflow/verification skills, complete-tree native publication, SQLite migration 8, monotonic admission, exact current-head inverse rollback and user-confirmed recovery. Existing schema/wire identities are preserved; the catalog now exports 82 schemas. ADR 0006 defines supported metadata and crash/cleanup limits.

| Selection | Observed result |
| --- | --- |
| Joint proposal/publication/recovery/interfaces/schema/presentation | `30 passed in 81.38s`. |
| Expanded joint recovery, including exact source/index/tree drift | `17 passed in 66.79s`. Unknown user changes survive; post-exchange drift remains fenced until exact user-owned repair. |
| Fresh-process CLI chat/proposal/diff/apply/rollback and abrupt publisher exits | `3 passed in 28.99s`. Actual exit after durable prepare and after exchange; explicit recovery aborts/commits without exchanging again. |
| Public bootstrap/chat/rule apply/backend work/independent Docker proof/code apply/rule rollback | `1 passed in 26.38s`. Each Engineer/Verifier ran five baseline and two integration tests; four command receipts, zero proof gaps, unchanged grants, exact scope cleanup. Offline FunctionModel, not live inference. |
| Initial source/test freeze (superseded) | `1c4f51631c8205e3741d8b7367d98a5ef85a8a42e896e98f85d822af52c5471e`, using sorted `rg --files src tests` SHA-256 aggregation. The interrupted regression results below supersede its candidate full-suite claim. |
| Frozen dependency/static/schema gates | Lock: 51 packages resolved; sync: 49 checked; Ruff format: 247 files; lint: no findings; mypy: 213 source files; 82 schema drift check and whitespace check passed. |
| Frozen unit / contract | Unit: `1010 passed in 57.13s`; contract: `567 passed in 29.81s`. These overlap the eventual default suite, not additive totals. |
| Frozen complete Docker selection | `14 passed, 4 deselected in 141.89s`; explicitly selected `-m docker_integration tests/docker` using the existing local runner. Final residue/lease read-back remains pending. |
| Interrupted initial default / marked integration | Default: `2 failed, 746 passed, 14 skipped in 730.56s`; integration: `2 failed, 157 passed, 85 deselected in 638.24s`, both deliberately interrupted after reproducing the same two legacy test assumptions. A resumed secret-bearing tree now fails earlier with typed RECOVERY_REQUIRED; the rotation fixture cannot rewrite a headed Project. Tests now retain exact pre8 compatibility using an isolated test-owned database copy, with the original headed project preserved. No production authority guard was weakened. |
| Corrected credential boundary focus | `3 passed, 7 deselected in 7.80s`. A prior in-flight attempt loaded swapped start/resume assertions and returned `2 failed, 12 passed in 57.40s`; the corrected start still expects CONFIG_INVALID, while resumed/candidate full-tree rejection expects RECOVERY_REQUIRED with no head write or secret leak. |
| Offline E2E after initial interruption | `22 passed in 220.49s`; the separate-process suite continued after integration interruption. No evidence was discarded. |
| Intermediate frozen repeat | `ee9662bbf3dba07f93bf745f3e976776a88fd123539d5d8dc65389f021d6d1f5`: unit1010/57.68s; contract567/30.83s; Docker14 passed4 deselected/156.89s; CLI/config40/97.72s; archive/schema6/3.23s. Obsolete init-bypass remediation was replaced with exact restore/review/separate-registration guidance; authorization semantics did not change. |
| Remaining legacy fixture failure (retained) | Default `1 failed, 890 passed, 14 skipped in 1297.84s`; marked integration `1 failed, 212 passed, 85 deselected in 860.81s`. Foreign-TaskSpec setup attempted a Run insert without organization admission/configuration identity. Corrected the fixture to acquire the real admission guard; the foreign artifact integrity rejection remains unchanged. Focused six tests passed in31.37s. |
| Independent integration audit | PASS with identical start/end intermediate checksum; fresh `36 passed in 226.85s` across proposal/publication/recovery/interfaces/CLI/skill evidence. Read-only test-delta review confirmed applicability at the final hash below. No duplicate Docker/live/Linux execution was claimed by the auditor. |
| Final strengthened behavior and freeze | Public Docker journey `1 passed in 32.41s`: real admitted revision0 and rollback revision2 backend tasks require only python-test, pause before any command receipt, and cancel cleanly; revision1 retains both required commands and independent execution. Source/tests `6eba65d4b190a8d8cfa3a3c16cc11e126d4f807bd885db27956cbc266cd832c2`; source-only `7a5ef57c2c92f652fd5edc76881eaa7244897a13fcbcca510ddd19462bcc2fa8`. |
| Final layered/static/Docker results so far | Unit `1010 passed in60.75s`; contract `567 passed in31.21s`; Docker `14 passed, 4 deselected in161.88s`. Ruff248/lint, mypy213, schema82 and whitespace passed. Full default/marked integration/E2E repeats remain running, not accepted yet. |
| Final Docker resource read-back |26 distinct databases:97 released and9 historical recovered leases, zero outstanding leases, zero pending organization heads, two published versions; zero globally managed containers. An initial read-only audit used uppercase status literals and failed its assertion; correcting the inspector to the actual lowercase wire values passed without any data mutation. |

Local platform: macOS arm64/Colima; image `sha256:15245c81b1efb7a68bad269f03737955eb5e6a2b7fc79aa98faa49c93a899851`. The same final resource read-back passed again after the repaired freeze's Docker suite. No actual provider key, live-provider call, Linux native-publication acceptance, fresh-dependency installation or final merge is claimed by these tests. The living evolution plan retains failed fixture assumptions, the public error repair and their successful repeats, plus later checkpoint identities.

### E7 — accepted local release candidate and GitHub delivery

The governing [release-candidate ExecPlan](../.agent/plans/2026-09-05-release-candidate.md) retains exact attempts, inputs and boundaries. The current local runner built from packaged digest/hash-pinned resources is `agent-fleet-runner:0.1.0-py314-v1`, image `sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241`, on macOS arm64/Colima. Prepared dependencies bind Python3.14.6, lock55 and52 applicable wheels; preparation is explicitly network-enabled, but installation/execution is offline with provider requests denied.

Current repaired behavioral freeze: `c03fa3d455b073958ade3c4d365a0231319e1b59eb715af3b79bb278bff5d3c3`, checkpoint3293244. Linux exposed device/inode reuse in the prior static Git-shadow check; a retained read-only/non-inheritable descriptor now pins its lifetime, with metadata drift checks at both dispatch boundaries. No timestamp-only uniqueness or atomic Docker pathname handoff is claimed. The original unlink tests remain, same-inode/lifecycle tests were added, and the tracked organization fixture no longer depends on ambient Git identity. Historical de0e230 full Linux failed3/1983 passed/25 skipped; those failures are not hidden or counted as acceptance.

| Repaired candidate gate | Exact current evidence |
| --- | --- |
| Static/dependencies | Ruff267; mypy219 on Darwin/Linux;82 schemas; lock55/sync53 and whitespace passed. |
| Full default | macOS2004 passed/18 explicit skips1515.89s; Linux1997 passed/25 skips994.03s. Local JUnit partitions:unit1027,contract578,integration372,offline E2E22,four Docker-directory offline cases andone readiness case. |
| Standalone offline / real Docker |734 passed199.76s /14 passed4 deselected148.37s, no skips/errors/failures; script manifest `8387db7309d7981c8e6b53ce52a46ad7459836d50534e7df6ea8f610e774f187` and verdict0 for both. Named replay is a subset; full/security/platform counts overlap. |
| Fresh installed wheel/sdist/public Docker |3 passed105.72s on repaired source; final help/655-line guide refresh3 passed94.60s under `<operator-cache>/agent-fleet-phase7-final-installed.EzciAj`. Prior six-database read-back:42 released leases, no outstanding/pending/active ownership;171 mixed fake/Docker blobs match persisted hash/size, no managed containers. Final evidence-text-only archive refresh is recorded in the plan. |
| Independent repair / guide |277 Docker/native/proposal tests20.01s plus independent mutation/inode/lifecycle probes; PASS. Separate guide audit PASS:28 help checks without state creation,47 local links/anchors, balanced fences,2 asset tests0.51s and one archive/resource test2.03s. Final delta PASS proves production AST unchanged apart from resume docstring, actual no-state help, exact main/PR triggers with nine unchanged gates and CI-shape test1/0.07s. |
| Linux platform selections |Python3.12.14/3.13.15/3.14.7 each1659 passed/5 exact Darwin metadata skips in465.07/440.14/489.22s. Real native Linux publication and original shadow-replacement contracts ran. |
| macOS platform selections |Python3.12.14/3.13.15/3.14.7 each1664 passed, no skips, in446.19/505.08/515.57s. Git2.55.0 across CI. |
| CI opt-ins |macOS fresh wheel/sdist2 passed1 deselected50.95s; Linux Docker+installed journey15 passed6 deselected153.57s, amd64 image `sha256:a5335772f0126e59e2cf5abe1fa0f44a21274697469a6309c4b76b97fa0309a3`. |
| Complete CI verdict | All nine workflow33986257215 jobs passed. Linux standalone script729 passed/five named Darwin skips146.02s, no unexpected skips/errors/failures and verdict0. |
| Final delivery refresh | Only resume-help prose, exact main/PR CI-trigger assertions and documentation change after the full behavioral freeze; final source/test/script aggregate `c400cdb40fa16bb13d2c1a8732893560ccc91db5fdbf916bdcf6868857378cf6`. Final package/cosmetic/head checks and GitHub merge/read-back remain separately recorded below/in the plan. L1/L2 public-release gates remain unperformed. |


Final accepted PR and delivery evidence supersede the final-head/package/merge prerequisites in the preceding historical snapshot:

| Final gate | Exact evidence |
| --- | --- |
| Final content and CI | Head `e413192bacf236ae243f350b4ade12f7fefbc650`, source/test/script c400cdb; [workflow33987810067](https://github.com/meyowu/agent-fleet-foundry/actions/runs/33987810067)9/9 SUCCESS. Linux full default1997 passed/25 expected skips1031.53s; separate security729 passed/five exact Darwin skips142.20s, script144.749s, zero errors/failures/unexpected skips, verdict0; script manifest `a46326969b352cc72f22790fbf43f25cd2ca53d61649e62582adfab8432cf0b8`. |
| Six final platform selections | Linux Python3.12.14/3.13.15/3.14.7 each1659 passed/five Darwin skips433.35/473.61/596.86s; macOS same versions each1664 passed/no skips439.26/531.45/527.98s. Git2.55.0. This is the specified selection, not all integrations on every combination. |
| Final CI opt-ins | Fresh macOS wheel/sdist2 passed/one deselected56.55s; Linux Docker plus installed public journey15 passed/six deselected181.22s. Built amd64 runner `sha256:a4b5dfae90f84dc1dd7c09fe7961668806f5934497187da900e1f7d31c3843e2`. |
| Final PR local package |3 passed/no skips94.91s; retained cache set `agent-fleet-phase7-final-evidence-package.yj3VQm`. JUnit `662bd321df57a8a49e3131d12a29ec24adfd33ad75d8c05372c3a408acd61835`; command log `00f1bd80ceb3a4a7eb4076769193989f369cac319c6a9799379463b45fe66881`. Wheel `31653e5f5555f4fb1a6c496aa7e6544a884d20fc96b8237a5d1dd1492fc5a6eb`; sdist `52cf389a0ca5b3e8b2e10dab71c8395247147f1bba91b128974c8fef4682efef`. All archive copies agree;6 databases,42 released leases,171 mixed fake/Docker artifacts hash/size verified,zero outstanding/pending/active ownership andzero managed containers. |
| Actual GitHub merge | PR #5 MERGED at2026-09-05T20:02:01Z, commit `0cead7dcafcace07d64892c0ff41ed72939d706a`; accepted/merged tree `7b052436feb7c537391d4f421a8ee35468a93380`; local/remote main matched and diff to e413192 was empty. Normal exact-head merge, no admin/force/branch deletion or visibility change. Post-merge documentation/package checks are recorded separately in the release plan; main-push checks identify the final record revision. |

Post-merge README/package acceptance:41 CLI/tooling/archive/assets tests passed34.50s; Ruff267/mypy219 on Darwin/Linux/schema82/lock55/sync53/whitespace and offline build passed. Source/test/script c400cdb is unchanged. Final README package replay passed all3 fresh wheel/sdist/public-Docker cases/no skips97.72s in retained cache set `agent-fleet-phase7-merged-package.4WxgN8`, using explicit installation/Docker opt-ins, LIVE_PROVIDER=0, the prepared lock55 wheelhouse and already-local runner v1. JUnit `002291b5500e18f418b259ab79d8580d2048fdde5922064bdda4d25ac8266135`; public command log `0263d8c0f783ccdabbd8fa4e610a2e401e615481db1e3cc230a9ccb73972b562`. Five wheel copies (including sdist-built/root dist) equal `2fafa1dfe41485611156c656088b40fbe73bcfb366177f8d31e01b5e5f20cb16`; four sdist copies equal `1fa495214c6cb92da41f9e21473ab194286cfa2189e5ee16c750dc40fe7eacd2`. Read-only audit:6 databases,42 released leases,171 size/hash-verified mixed fake/Docker artifacts,zero outstanding/pending/active ownership andzero globally managed containers. These hashes supersede only the prior PR package bytes; runtime/tests/guide/CI/dependencies remain unchanged.

Final documentation commit/tree, actual main CI conclusion and remote/worktree/resource read-back are maintained after normal push in the **Delivery** section of [PR #5](https://github.com/meyowu/agent-fleet-foundry/pull/5) and the task handoff. That external read-back is required before final handoff; this file cannot contain its own commit identity and does not claim a not-yet-created commit or CI pass. A superseded initial main run is cancellation, not acceptance. No implementation is reopened merely to record these self-referential identities.

Historical preparation and earlier installed attempts (superseded where the current tables supply newer evidence):

| Candidate gate | Observed result and boundary |
| --- | --- |
| Fresh wheel/sdist and installed public Docker journey | `3 passed in60.92s`. Each installs into a new environment outside the checkout with an empty cache, no system packages, frozen runtime/build constraints and lock-verified wheel hashes. Wheel/sdist prove packaged bytes,82 schemas/eight migrations, stable JSON, preview/fake-init refusal and an explicitly test-seeded fake flow. The separate installed wheel Docker journey uses public init, exact approvals, two independent five-test receipts and explicit code apply; no private init shortcut or real model key. |
| Upgrade/readiness/tooling/assets focus | `18 passed in12.76s`; later configuration/audit/archive focus `11 passed in2.31s`. Realistic schema7 projection preserves paused approvals, active ownership/graph/chat/budgets/events/artifacts during migration8; prior-version refusal leaves it unchanged. This is a real database fixture, not execution of a historical binary. |
| Scale/readiness focus | `9 passed,1 skipped in3.36s`; only actual live-provider case skipped.1000 explicit events+256 artifact events and256 artifacts/1MiB; append1.609682s, writes0.536526s, pagination0.064872s, read-back0.210839s, status0.004753s, DB+WAL5,844,544bytes, traced peak972,057bytes. One host's bounded smoke, not an SLA. |
| Static and bounded independent audit | Ruff267/mypy219/schema82/whitespace passed. Independent read-only audit PASS with18 passes/1 deselected in0.66s covered environment isolation, resource packaging, CI permissions and prerequisite enforcement; it did not execute full installed/Docker/CI gates. |
| Retained failures | Initial scale event-type assumption:1 failed/2 passed. Hardened installed Git fixture still supplied forbidden `-c`:3 failed, corrected without changing the production guard. A subsequent command used the wrong image variable:2 passed/1 setup error in35.24s, superseded by the correctly gated three-case pass above. |
| Expanded installed guide replay | `3 passed in92.32s`: installed doctor healthy/required checks, exact Safe/src init, chat with cross-process approval/resume/duplicate submission, status/artifacts/logs, exact project trust creation/revoke, code apply and no-op confirmed recovery. A separate public registration uses only offline FunctionModel response substitution (installed Fleet imports exclusively) for CoS proposal/diff/whole-tree apply/inverse rollback and historical chat read-back. Each CLI process retains argv/exit/stdout/stderr in test-owned evidence; no environment/key values are captured. |
| Expanded replay's retained setup failure | `1 failed,2 passed in80.80s`: model-substitution fixture updated projects/workflow registries but omitted bootstrap's registry, so actual credential preflight correctly refused before a provider call. Bound the same offline test adapter consistently; no production change, real credential or private init bypass. |
| Standalone security replays | Offline539 passed in175.37s, zero skips/errors/failures; separate real Docker14 passed/4 deselected in133.52s, zero skips/errors/failures. These predate only the expanded installed-test fixture delta, not runtime changes; final frozen read-back remains required. |
| Required at that historical snapshot, superseded by accepted E7 evidence above | Final frozen default/unit/contract/integration/offline E2E/security/Docker/archive gates, independent final guide review, actual six-platform CI, exact residue read-back and final GitHub merge. Authored CI is not execution evidence. License/publication and actual live-provider gates remain unperformed. |

## Six product differentiators

| ID | Required observable property | Starting evidence | Remaining proof |
| --- | --- | --- | --- |
| D1 | Repository-aware bootstrap identifies boundaries/ecosystems/commands without executing repository code; produces provenance, ProjectKnowledge, reviewed configuration and disposable canary report. | Baseline: `adapters/repository/profile.py`, `application/projects.py`, `application/bootstrap.py`; repository-profile, bootstrap-security/report and real-Docker tests. | Repeat preview/no-write and real isolated bootstrap after policy/config changes; validate exact report/artifact bindings and publish only after successful cleanup. Demonstrate a fresh user's real repository journey. Q2, Q4, Q6, M1. |
| D2 | CoS proposes the smallest validated topology; direct, single Engineer, Engineer+Verifier, parallel Engineers and declared specialist DAG actually execute with bounded ownership/dependencies. | Accepted E5.2: planner/graph coordinator, exact SQLite child/driver state, normal offline/Docker graph journeys and scheduling/safety/CLI regressions. | Preserve accepted bounded overlap, deterministic joins, specialist dependencies and exact recovery through persistent chat. F5-03, F5-04, P5. |
| D3 | Every model-requested action crosses independent Gateway/Broker; once/run/exact persistent project trust, explain and revoke work. | Accepted Phase 4 (E4): policy/approval services, gateway, external trust, scoped receipts and exclusive dispatch. | Preserve the accepted boundary through future chat, graph execution and configuration evolution. E4 distinguishes simulated integration from real-Docker evidence and does not claim live-provider proof. |
| D4 | Exact SandboxProvider selection matches declared capabilities; Docker is isolated, fake simulated, local-unsafe explicit; harness cannot choose a boundary. | Baseline: `application/sandboxes.py`, sandbox providers and contract tests; composition root registers only fake/Docker/local-unsafe. | Preserve real inspection/cleanup tests and unsafe confirmations through all new flows. Approved modes must fail closed unless technically enforced. Remote providers are deferred. Q4, Q6, S02–S06. |
| D5 | Content-addressed evidence binds task/config/plan/base/patch/commands/verifier/cleanup; CompletionGate computes assurance and exposes proof gaps. | Accepted E5.1/E5.2: typed current criterion references, substantive direct output, cumulative budgets and exact joined/child-cleanup provenance, with independent Docker verification. | Preserve proof gaps and fake/unsafe non-verification through chat/evolution and the final installed-user journey. F5-04, F5-11, P5, S08. |
| D6 | Conversation yields a reviewed FleetPatch with semantic/textual diff, explicit apply and new audited rollback operation; protected policy cannot change. | Implemented candidate: `application/evolution.py`, CLI, native filesystem and durable journal, strict skills and proposal output; E6 focused native/CLI/Docker proof. | Final frozen full gates, release/platform proof and checkpoint remain open. Preserve immutable history, protected policy and actual command enforcement. F6-01 through F6-09, P6. |

## Phase 4 deliverables

All rows concern the roadmap's three-state permission lifecycle. Grants never expand a protected or effective task ceiling. **Accepted on 2026-09-05 under E4.** The observations below remain regression obligations; E5.1/E5.2/E5.3/E6 preserve them through budgets, graphs, chat and reviewed evolution. Final Phase7 release gates remain separate.

| ID | Deliverable | Starting evidence / missing work | Required proving observation |
| --- | --- | --- | --- |
| F4-01 | Canonical ToolIntent and resource types. | Accepted Phase 4 (E4): domain models, gateway and runtime-tool translation. | Structured executable/argv/cwd/environment/path/network identity is bound by trusted context; aliases and argument injection fail before execution. Q2, P4. |
| F4-02 | ALLOW, DENY, REQUIRE_APPROVAL evaluation with hard denies. | Accepted Phase 4 (E4): `PolicyPermissionBroker` composes the supported baseline ceiling with current policy and protected registry. | Table-driven outcomes plus real gateway execution/no-execution and persisted decision evidence; no grant or trust mode overrides a hard deny. Q2, P4. |
| F4-03 | Project/role/workflow/task intersection and reviewed user ceiling. | Accepted Phase 4 (E4): `PermissionPolicyService.context`, task-path validation, role/request/workflow checks, reviewed init/configure settings. | A CoS scope or repository permission request cannot exceed a separately reviewed ceiling; wrong role/stage/workflow/task/project fails even with a stored grant. Missing new-project registration fails closed; legacy compatibility cannot broaden authority. P4. |
| F4-04 | Exact capability grants with expiry, use counts and revocation. | Accepted Phase 4 (E4): strict exact scope, once/run grants, persistent rule and atomic per-use receipt; migration `0004` preserves old grants. | Once means one successful reservation and <=10-minute expiry; run grants survive request expiry but not run termination; expiry/exhaustion/revocation survive reopen; competing consumers cannot overuse. P4. |
| F4-05 | Matched-rule explanations. | Accepted Phase 4 (E4): rich decisions, rule inspection, current/historical request explanation and grant lifetime/status in list. No grant-ID explain or persistent-deny creation CLI. | Exact matched scope and denial/nonmatch reason remain secret-free. Terminal/changed-stage explanation must label history rather than fabricate current authorization; grant status alone cannot promise execution. P4. |
| F4-06 | Persistent user-owned trust outside repository, atomic validated writes. | Accepted Phase 4 (E4): `domain/trust.py`, `ports/trust_store.py`, `adapters/trust/filesystem.py`; external state-root trust file, strict revisioned schema. | Restrictive regular files, symlink/hardlink/no-follow safety, malformed/corrupt/concurrent writes and CAS failures; prepared evidence before publish, exact current/backup reconciliation after completion failure, no automatic rollback or lost updates. Unsupported POSIX features fail closed. P4. |
| F4-07 | Approval request binds exact intent hash. | Accepted Phase 4 (E4): exact hash binding retains original reviewed display reason on logical retry. | Changing executable, argv, environment, cwd, target path or trusted identity after approval invalidates execution; current policy is checked again. P4. |
| F4-08 | `approve --once`, `--run`, `--always --scope project`, and `deny`. | Accepted Phase 4 (E4): approval service and CLI; historical unscoped requests remain once-only. | Separate process invocations pause, review exact scope, approve/deny and resume; mutually exclusive/invalid mode combinations yield stable JSON errors. P4. |
| F4-09 | `permissions list`, `explain`, `revoke`, `reset --project`. | Accepted Phase 4 (E4): CLI and policy service plus `configure --mode/--allow-path`. | List survives restart; explain matches execution reason; revoke affects next execution; reset preserves other projects and reviewed settings, rejecting grants issued at/before its monotonic cutoff even if SQLite revoke fails. P4. |
| F4-10 | Safe, Balanced and Autonomous Sandbox trust defaults. | Accepted Phase 4 (E4): Safe prompts supported commands; Balanced and Autonomous-sandbox deliberately share the current reviewed-command ceiling. | Compare known/unknown commands and workspace operations; no arbitrary executable/network expansion or assurance upgrade. Unsafe/host/external/protected boundaries remain gated. P4. |
| F4-11 | Audit decision, request, resolution, grant, consumption and revocation. | Accepted Phase 4 (E4): prepared/publish/completed policy protocol and transactional derived-rule receipt events. | Ordered identities/redaction, denied/no-execution paths and crash/retry history. Later-run rule use has exact source rule/scope in issued/consumed events and no fabricated approval. Failed staged-rule activation stays dormant and retry is idempotent. P4. |
| F4-12 | Approval resume semantics. | Accepted Phase 4 (E4): current broker/target/configuration revalidation, both role checkpoints, exact verifier patch checks, logical sandbox rehydration and atomic permanent dispatch claims. | Revoke/deny/ceiling changes prevent execution. Both role identities survive pause; exact verifier context and execution semantics cannot change. Concurrent callers dispatch once; incomplete claims/outstanding execution leases never replay. Changed display reason does not invalidate an unchanged logical command. Provider usage/budget persistence across pauses remains open under Phase 5. P4. |
| F4-13 | Protected action registry; exact always-allow conditions. | Accepted Phase 4 (E4): protected action families and `ExactPermissionScope` validators. | No ordinary all-shell/network/files/projects rule; rules bind project/repository identity, principal, workflow/stage, sandbox and full command/path/network parameters. Protected trust/secrets/audit/approval ownership/sandbox limits cannot be granted through normal flow. P4, security cases 1–15. |

Accepted Phase 4 scenarios to retain as P4 regressions on subsequent changes:

1. Pause for an actual canonical verification command; approve once in a new CLI process; resume in another process. Assert one command result, matching intent hash, ordered events and no second execution on repeated resume.
2. Allow for the run, then submit another semantically identical intent with fresh IDs. It may match in the same run; changed executable/argv/cwd/environment/path/principal/stage/workflow/sandbox or a different run/project must not inherit authority.
3. Always-allow each exact Engineer and Verifier project command separately, recreate the process and start another run. Assert rule match, explanation, source-rule/scope-bound issued/consumed receipts and no fabricated approvals. A second repository and a broader command must still prompt or fail. Inject approval activation failure: the staged rule stays dormant and retry reuses its ID.
4. Approve, then revoke or strengthen hard deny/task/trust policy before resume. Assert fresh broker denial, no grant consumption that authorizes execution, no tool result and a stable audit reason. Also change the registered repository identity/base or configuration before resume: revalidate the trusted execution binding rather than relying solely on the old approval hash.
5. Advance an injected clock across expiry; exhaust use counts; race two consumers for a one-use grant. Assert only one execution and durable remaining-use state.
6. Exercise corrupt YAML/JSON, symlink/hardlink/non-regular trust paths, parent swaps, interrupted atomic publication, immutable-backup reconciliation and concurrent writers. Prepared audit failure prevents publication; publication failure leaves exact prepared evidence; completion failure can leave the published policy effective and must be reconciled by revision/hash. Compare-and-swap rejects stale writers; backups never automatically grant access or undo newer state.
7. Contrast Safe/Balanced/Autonomous defaults against exact fake/Docker/local-unsafe capability snapshots. An isolated-only grant never matches local-unsafe, and trust approval cannot manufacture unsupported network enforcement.
8. Reset project A while B has rules and paused runs. Preserve B and A's reviewed mode/path ceiling, record A's revocations, and reject all A grants issued at/before the durable cutoff even if the subsequent SQLite loop fails. Configure must preserve the cutoff. Search output, exceptions, trust files/backups, SQLite/WAL and artifacts for registered raw/encoded sentinels.

## Phase 5 deliverables

**Accepted on 2026-09-05 under E5.1/E5.2/E5.3.** The observations below are continuing regression obligations, not outstanding Phase 5 implementation. Organization-change proposals/application remain Phase 6; installed-user, platform and live-provider proof remain separate release gates.

| ID | Deliverable | Starting evidence / missing work | Required proving observation |
| --- | --- | --- | --- |
| F5-01 | `fleet chat` line REPL with durable conversation/run references. | Accepted E5.3: atomic turn/Run registration and durable project-bound history; `tests/unit/test_conversation_models.py`, `tests/contract/test_conversation_store.py`, `tests/unit/test_chat_cli.py`, `tests/e2e/test_persistent_chat_cli.py`. | Preserve exact identity, duplicate-submit protection and distinct new/resumed sessions in subsequent P5 regressions and release journeys. |
| F5-02 | CoS converts messages to validated TaskSpec drafts. | Accepted E5.3: normal conversational goals and bounded context pass through `_scope` to validated ScopeDecision/TaskSpec; normal application, subprocess and Docker journeys cover the route. | No raw history or agent-provided authority enters accepted tasks. Organization-change proposals use the separate Phase 6 contract. |
| F5-03 | Smallest valid adaptive team with all five strategies and explicit joins/assurance. | Accepted E5.2: real overlap/queue-capacity barriers, stable join under opposite orders, exact child/dependency binding and five operational strategies. | Preserve through chat; use current P5 execution targets, not plan construction alone. |
| F5-04 | Fresh Engineer each iteration, candidate extraction, fresh independent Verifier workspace, bounded repair, evidence mapping and summary. | Accepted E5.1/E5.2: bounded prior verdict feedback, text-only canonical patches, exact criteria and fresh parent verification/repair of joined code. | Preserve actual-versus-claimed patch and full original-task proof through chat and configuration evolution. P5. |
| F5-05 | CoS cannot use Engineer write/command tools. | Baseline role catalog isolation and empty CoS tools. | Test attempted direct mutation through chat/planning, custom roles and deferred batches; deny before any workspace change. Q2, P5. |
| F5-06 | Verifier modifications discarded and reported. | Baseline verifier mutation denial/disposable workspace evidence. | Repeat for simple, repaired and joined candidates; mutation cannot contaminate accepted patch and cannot be hidden by a PASS. Q2, P5. |
| F5-07 | Compact event-driven progress UI. | Accepted E5.3: bounded recorded-event pagination and responsive progress; `tests/unit/test_conversation_state.py`, `tests/integration/test_conversations.py`, `tests/unit/test_chat_cli.py`, `tests/e2e/test_persistent_chat_cli.py`. | Preserve cursor/no-replay behavior, responsiveness and secret-free projections without fabricated completion. |
| F5-08 | `/status`, `/artifacts`, `/permissions`, `/cancel`, `/help`, `/exit`. | Accepted E5.3: deterministic local controls, exact approval/deny/resume helpers and retained cleanup; `tests/unit/test_chat_cli.py`, `tests/integration/test_conversation_safety.py`, `tests/e2e/test_persistent_chat_cli.py`. | Preserve no-run/active/paused/terminal/restarted behavior, responsive cancel/EOF/exit and exact cancellation target in later regressions. |
| F5-09 | Restart/resume and approval pause. | E4/E5.1/E5.2 accept exact role/child approval and budget restoration. Accepted E5.3 adds shared durable conversation ownership and frozen context; `tests/contract/test_conversation_store.py`, `tests/integration/test_conversations.py`, `tests/integration/test_conversation_safety.py`, `tests/e2e/test_persistent_chat_cli.py`, `tests/docker/test_conversation_journey.py`. | Preserve the original turn/Run/ledger; uncertain ownership requires explicit recovery, never replay or invented free usage. Raw provider history is not restored. |
| F5-10 | Budget enforcement and usage summary. | Accepted E5.1/E5.2 for immutable run/child shared limits, logical role caps, usage/unknown accounting, concurrent reservations and active-time watcher. E5.3 conversation retry/resume preserves the same Run ledger and exposes its summary. | Preserve each Run's cumulative limits across chat retries/approval pauses; separate new goals receive distinct Run budgets, not a conversation-wide pooled allowance. Token usage is post-response accounting, not guaranteed pre-spend cost. P5. |
| F5-11 | INCONCLUSIVE and exact proof-gap presentation. | Accepted E5.1/E5.2: exact current verifier criterion references, substantive direct response and joined-provenance checks. | Preserve missing/contradictory/mutating/simulated non-verification and expose the same facts in chat. P5, Q2. |
| F5-12 | Bounded context selection. | Accepted E5.3: frozen recent summaries and exact same-project Run/artifact references, explicit truncation/omissions and bounded byte reads; `tests/unit/test_conversation_models.py`, `tests/contract/test_conversation_store.py`, `tests/integration/test_conversation_safety.py`. | Preserve deterministic bounds, original context on duplicate submission and rejection of corrupt/foreign/secret-bearing references; no whole-repository or raw-provider-history default. |

The Phase 5 proving suite must cover role tool isolation, CoS direct-write denial, claimed-versus-actual patch, verifier use of the original goal, verifier mutation, successful second repair, exhausted repair budget, chat cancellation, restart/approval, context limits, and final summary contents. It must additionally cover sibling failures/cancellation/approval, conflicting joins, disjoint concurrent ownership, dependency artifact substitution and aggregate budgets. Tests that only construct a FleetPlan do not prove graph execution.

## Phase 6 deliverables

All nine deliverables are accepted locally under E6 and checkpoint b42cdf9. The candidate descriptions below identify the implementation that passed those gates; the last column remains a regression obligation through Phase7 release work. Local acceptance is not Linux/native, fresh-user, live-provider or public-release acceptance.

| ID | Deliverable | Starting evidence / missing work | Required proving observation |
| --- | --- | --- | --- |
| F6-01 | Reuse typed FleetPatch and persist proposal/status/history. | Candidate: `domain/evolution.py`, OrganizationStore, migration 8, immutable journal/tree/proposal/version/admission tests. | Reopen preserves exact project/proposal/base/change/rollback bindings; corrupt/foreign/wrong-kind artifacts fail closed. P6. |
| F6-02 | Natural-language CoS semantic proposal and textual patch. | Candidate: trusted bounded evolution context, CoS output, pure hash tool, real offline FunctionModel and chat/CLI/Docker journeys. | Normal chat organization request produces a bounded validated proposal and inspectable rationale/diffs without target mutation. P6. |
| F6-03 | Stage complete proposed files separately. | Candidate: native OrganizationFileSystem with exact private sibling staging, descriptor identities and supported metadata. | Staging is Fleet-owned, bounded and separate; preview/show cannot mutate active config; proposed tree covers exact references and allowed auxiliary files. P6. |
| F6-04 | Validate paths, schema, references and runtime capabilities. | Candidate: strict WorkflowDefinition/VerificationSkill, closure and canonical command validation; pure/adapter/whole-result negative tests. | Malformed workflow/skill schema, missing references, file/descendant or case aliases, symlink escape and unsupported capabilities are rejected before publication. P6. |
| F6-05 | Reject protected settings, secrets and trust/audit/state paths. | Baseline allowed-path and whole-proposal registered-secret validation. | Apply/rollback repeat protection and secret checks over the whole resulting tree. A role/workflow/skill change cannot alter runtime credentials, hard denies, approval ownership or sandbox limits indirectly. P6, Q2. |
| F6-06 | Human semantic diff/unified diff and list/show/apply/rollback CLI. | Candidate: thin `cli/evolution.py`; exact new-process lifecycle, JSON and control-safe human presentation tests. | Separate processes inspect identical stored hashes/diffs; explicit user apply is required; invalid modes/IDs have stable JSON errors. No model tool applies its own proposal. P6. |
| F6-07 | Atomic application, before/after hashes and conflicts. | Candidate: one native exchange, durable prepared fence, Project CAS, current generation admission and exact recover; 17 joint recovery cases plus abrupt-process E2E. | Stale base/prior bytes/add-existing/remove-absent/concurrent edits fail without altering originals; injected failure/crash yields either known prior or known next tree with coherent Project/operation state. Unknown edits require safe recovery. P6. |
| F6-08 | Rollback is a new audited operation. | Candidate: current-head inverse reconstructs exact historical complete tree under a new proposal/operation/version; repeat and ABA tests. | Reopen and rollback restore prior content while retaining original proposal/application history and new before/after hashes; rollback conflicts never overwrite intervening user work. P6. |
| F6-09 | Require integration tests for backend changes. | Candidate: both TaskSpec and EvidenceAssembler recompute path-conditioned requirements; public real-Docker E6 proves mandatory independent execution. | Before proposal/apply/after apply/after rollback tasks show the expected command requirement changes; schema-only or documentation-only edits cannot satisfy this row. P6. |

Phase 6 must prove every roadmap negative case: invalid schema, traversal/symlink, trust/hard-deny/secret/audit mutation, base conflict, atomic failure preserving originals, rollback history, and model self-application denial. It must also prove that old runs retain their original configuration snapshots and that applying new configuration coherently updates the Project binding for subsequent runs.

## Phase 7 deliverables and release gates

| ID | Deliverable | Starting evidence / missing work | Required proving evidence |
| --- | --- | --- | --- |
| F7-01 | Linux/macOS E2E matrix; Windows limitations and available tests. | E7 final e413192 passed all nine jobs, including six OS/Python selections, full Linux default/security and separate installed/Docker opt-ins. | Actual job versions, native exchange and exact skip boundaries are recorded above; Windows/remote filesystems remain unsupported. Q1–Q6, M1. |
| F7-02 | SQLite migration upgrades. | Eight migrations; E7 realistic schema7 projection with paused approvals/active claims/leases/graphs/chat/budgets plus real organization-head reopen. | Preserve exact old rows/events/artifacts and current-head idempotency; older-version refusal without mutation. Q3, P4–P7. |
| F7-03 | Orphan Docker/worktree recovery. | Baseline exact-run recovery and repeated-cancellation cleanup. | Preserve existing real Docker recovery matrix; extend node/parallel/apply crash cases; reconcile only exact owned resources and record zero outstanding leases/container residue. Q4, Q6, P5, P6. |
| F7-04 | Stable CLI errors and JSON schemas. | Baseline versioned envelope/error enums/schema generation. | All new modes/slash operations/data/error surfaces have consistent persisted schemas and stable errors; compare generated schema files and package copies. Q1, Q3, Q5, P4–P6. |
| F7-05 | Reproducible versioned runner image. | E7 packaged canonical runner: pinned multi-platform OCI index and five required wheel hashes, exact installed bytes and actual local image build. | Preserve installed quickstart/inspection; input identity is not identical cross-builder layers or vulnerability attestation. Q5, Q6, M1. |
| F7-06 | Security checklist and adversarial test script. | Candidate `SECURITY.md` and `scripts/verify_adversarial.py`, explicit offline/Docker inputs and structured JUnit/hash/skip/verdict records. | Run named53-case mapping and new boundary regressions, sentinel/no-residue Docker proof; script existence is not a pass. Q2, Q6, M2. |
| F7-07 | Complete README quickstart and architecture diagrams. | Candidate16-chapter `docs/USER_GUIDE.md`, bundled canonical bytes, installed resource quickstart, architecture/boundaries/examples and release links. | Independent guide/readiness review and fresh-user flows; distinguish installed public flow from source-only comprehensive chat/evolution tests. M1. |
| F7-08 | Contribution guide and useful issue templates. | Expanded CONTRIBUTING with frozen setup, safety boundaries, all test layers and release procedures. Issue templates deliberately omitted as unnecessary for this minimal candidate. | Commands match actual CI; no mandatory missing-template gate. Q1, review. |
| F7-09 | Changelog and release process. | Candidate `CHANGELOG.md` and `docs/RELEASE.md`: migration/platform/security compatibility, freeze/review/merge and external release gates. | Verify exact evidence and final delivery; package publication is not implied. Review, Q5. |
| F7-10 | Generated configuration schemas. |82 generated schemas/eight migrations, source drift check and fresh installed wheel/sdist read-back passed. | Repeat after final metadata/docs freeze. Q1, Q5. |
| F7-11 | Event/artifact scale smoke. | E7 `tests/integration/test_state_scale.py` measures1000 events/256 artifacts, exact pagination/read-back/reopen and bounded storage/memory/latency. | Preserve full-suite regression; one fixed workload is not an asymptotic proof or production SLA. P7. |
| F7-12 | Optional local OpenTelemetry-compatible instrumentation. | Deliberately deferred: existing local structured events/artifacts support this MVP; no measured need for another telemetry path. | No mandatory exporter/service and no instrumentation claim. Optional, not a blocker. |
| F7-13 | Dependency review and lock policy. | `docs/DEPENDENCIES.md`, exact Hatchling/pip dev pins, lock55, hash-verified platform wheelhouse and no-config/no-index fresh installation. | Actual CI and final lock checks; no CVE scan or signed attestation claimed. Q1, Q5, review. |
| F7-14 | Explicit data handling/provider disclosure. | `docs/DATA_HANDLING.md` covers retained state/chat/trust/proposals/artifacts/provider context, coherent backup and no automatic TTL/deletion. | Current redaction/boundary regression and guide review; no claim that BYOK inference keeps all context local. Q2, review. |
| F7-15 | Owner license decision before public release. | Unproven: no LICENSE or explicit license selection in the active plan. | Record the owner's exact authorization and selected license, then validate metadata/package inclusion. Do not choose or imply a license from repository visibility. External gate L1. |

| Release gate | Starting status | Closing evidence |
| --- | --- | --- |
| R1 Default suite passes offline after dependencies are installed. | E7 repaired runtime:macOS2004/18 skips and Linux1997/25 skips passed; final cosmetic/doc refresh uses exact-head CI. | Q1–Q5 evidence is recorded by identity; no actual provider or public-release acceptance follows. |
| R2 Optional Docker integration suite passes. | E6:fourteen actual Docker cases passed with exact residue read-back; E7 rebuilt runner's separate14-case replay also passed. | Repeat Q6 for final freeze and inspect exact resource/inspection/candidate evidence. |
| R3 Manual live-provider canary recorded. | Setup repaired to require real Docker and independent live inputs; readiness negatives pass offline. Actual gate remains unrun: no supplied disposable credential. | L2 and M3. Fake runtime or TestModel/FunctionModel is insufficient. |
| R4 Every product MVP user-success criterion demonstrated. | U1–U12 have implemented automated paths under E4–E7, including installed real-Docker workflows with offline model responses; actual live-provider portions remain unperformed. | Preserve each mapped scenario; R3/M3 must separately prove real-provider behavior before public-release acceptance. |
| R5 Security release gates met or explicitly documented as blocking gaps. | Baseline security foundation; final candidate unproven. | S01–S11 and mapped cases below; documenting a mandatory gap does not count as passing it. |
| R6 README distinguishes enforcement/guidance and isolated/unsafe modes. | Baseline distinction exists. | Current guide/CLI review and M1; preserve honest fake/unsafe/loopback/host trust limitations. |
| R7 No placeholders, fake claims, plaintext secrets or machine-specific paths. | Needs new candidate and distribution inspection. | Q1, Q2, Q5; inspect tracked/distributed product files and user-visible examples. Historical private acceptance paths are not portable setup instructions. |
| R8 Fresh user follows quickstart successfully. | E7 independent fresh wheel/sdist and installed public Docker journey passed; runner/canary/guide are packaged resources. Organization proposal uses explicitly substituted offline FunctionModel, not a stock fake/live claim. | Refresh documentation-final bytes and keep real-provider M3 separate. No public registry publication is assumed. |

## All twelve MVP user-success criteria

| ID | Product criterion | Starting evidence / gap | Required closure |
| --- | --- | --- | --- |
| U1 | Install package and run doctor. | E7 fresh wheel/sdist installs and version/resources/schema checks; expanded installed public-Docker doctor explicitly asserts healthy=true and every required check. | Preserve Q5/M1 after final content freeze; doctor exit zero alone is insufficient. |
| U2 | Initialize Git repository and inspect profile, commands, ProjectKnowledge and proposal. | Baseline preview/profile/security/bootstrap paths. | Q2/Q4/M1: exact provenance/artifacts/diff and no preview writes; malicious repo content never executes. |
| U3 | Initialize explicit provider/model plus Docker; complete disposable canary. | Public Docker bootstrap exists; manual live-provider path unproven. | Q6/M3: explicit selected provider/credential reference, immutable Docker boundary and successful report with clean publication/cleanup. |
| U4 | Enter chat and request small change. | Accepted E5.3: `tests/integration/test_conversations.py`, `tests/e2e/test_persistent_chat_cli.py` and the public initialization/approval/verification/apply journey in `tests/docker/test_conversation_journey.py`, retained in the full Phase 5 gates. | Complete eventual fresh installed-user/live-provider gates; offline FunctionModel/Docker evidence does not establish those separate outcomes. |
| U5 | Inspect plan and observe only required roles run. | E5.2 accepts all five topologies, actual bounded concurrency, planned specialist dependencies, stable joins and public parent inspection. | Preserve current P5 execution evidence in the full chat/installed-user journey. |
| U6 | Approve once, run or exact project scope. | E4 accepted all three lifetimes; E5.2 retains separate child/parent principals and scopes across reconstruction. | Retain P4 and demonstrate the completed installed-user/chat journey; no wider authority from shared budgets. |
| U7 | Receive patch, tests, verdict, events and hashes. | E5.1/E5.2 accept typed criterion and joined-patch/cleanup bindings plus independent Docker verification. | Q2/Q4/P5/M3: preserve actual byte read-back and risks/proof gaps through chat and explicitly authorized live-provider acceptance. |
| U8 | Restart CLI and inspect/resume. | E4/E5.1/E5.2 accept exact role/graph approval restoration, accounting and exclusive ownership. Accepted E5.3 chat restart has `tests/contract/test_conversation_store.py`, `tests/integration/test_conversations.py`, `tests/integration/test_conversation_safety.py`, `tests/e2e/test_persistent_chat_cli.py` and `tests/docker/test_conversation_journey.py`. | Preserve accepted P5 restart behavior; P6 configuration-operation recovery remains separate. No generic replay safety or SDK history restoration follows from exact supported checkpoints. |
| U9 | Apply candidate only after explicit approval. | Baseline `patch apply` explicit command and dirty/diverged guards. | Q4/M1: no silent target writes, explicit reviewed apply changes expected bytes; verifier changes excluded; drift/config changes refuse safely. |
| U10 | Request fleet change, inspect and apply or reject. | E6 accepts actual CoS proposal, immutable diffs, native apply/new inverse rollback and required backend verification changes through public source CLI/Docker journeys. | Preserve P6 and release/platform evidence; ignoring a proposal leaves it unapplied. No model self-application or permission expansion. |
| U11 | Revoke persistent permission. | Accepted at the E4 supported scope: revoke/reset survives reopen and invalidates exact grants/rules. | Retain P4 through later phases and demonstrate in M1. Revocation does not remove underlying Balanced defaults; Safe mode exposes the next required approval. |
| U12 | Default suite needs no real model/network/Docker. | E5.2: 1344 ordinary tests passed; twelve Docker and one live-provider case skipped with opt-ins explicitly disabled. | Repeat Q4 on the full-MVP tree; retain offline adapter coverage and exact skip reasons. |

Cross-cutting product acceptance: `COMPLETED` is lifecycle state; `verified_complete` is independently derived assurance. No user journey, role result, code patch, schema or successful process exit can override missing required proof. In particular fake/local-unsafe and contradictory/mutating verifier results must remain unverified.

## Security release gates

| ID | SECURITY_MODEL section 21 requirement | Starting evidence / remaining proof |
| --- | --- | --- |
| S01 | All required security tests pass. | Baseline test targets below; Q2 and the full final Q4/P4/P5/P6 matrix must pass. Required cases cannot be closed by aggregate counts alone. |
| S02 | Real Docker verifies effective user/mounts/network/capabilities/environment. | Contract tests are not OS enforcement proof. Q6 must inspect real effective configuration and credential/host sentinels on the final candidate. |
| S03 | Threat model and limitations appear in README. | Baseline text exists; review changed trust/chat/config data flows and M1 disclosures. |
| S04 | local-unsafe is explicit and visually prominent. | Baseline separate confirmation/warnings; repeat init/run/chat/approval paths and JSON warnings under Q3/P5. Ordinary `--yes` is insufficient. |
| S05 | No framework-native shell/filesystem bypass outside Gateway. | Architecture/runtime/secret-boundary tests exist; extend to conversation, custom roles, proposal output and every new tool route. Q2/P5/P6. |
| S06 | Invocation contains no host path, sandbox handle, credential, grant or executor. | Baseline strict runtime request/context tests; extend node/dependency/repair/chat context and prove denied injection. Q2/P5. |
| S07 | Profiling cannot execute code; detected commands are unauthorized requests. | Baseline profiling/Git defenses; Phase 4 command trust must not equate detection with self-grant. Q2/P4. |
| S08 | CompletionGate uses authoritative evidence; simulated PASS cannot verify. | Baseline evidence gate; test graph joins and criterion mapping without trusting model claims. Q2/P5/Q6. |
| S09 | Dependencies/images reviewed and pinned under policy. | E7 packaged digest/hash-pinned runner, actual local build and installed byte checks; explicit lock/dependency/update policy. No CVE/signed attestation claim. Q1/Q5/F7-05/F7-13. |
| S10 | Manual adversarial bootstrap recorded. | Historical Phase 3 report exists; final changed candidate needs M2 with exact artifacts, sentinels and residual-resource checks. |
| S11 | Permission allowlists are never equated with OS isolation. | Baseline documentation is honest; review all new help, guide and completion summaries. Trust mode cannot upgrade fake/local-unsafe capabilities. |

## All 53 required security-test cases

Numbers below match `SECURITY_MODEL.md` section 20. Listed files are starting test targets, not proof that every assertion already exists or passes. Q2 runs the relevant existing unit/contract/integration security surface; P4–P6 identify mandatory new behavior tests. For each row, retain the case numbers in the eventual test/evidence record.

| Cases | Required assertion | Starting test targets and remaining proof |
| --- | --- | --- |
| 1 | Repository broad filesystem request cannot grant itself authority. | `tests/unit/test_permission_broker.py`, `tests/integration/test_security_gateway.py`; P4 must exercise effective requested-policy intersection, not only hardcoded baseline denial. |
| 2 | Forged agent ID/role cannot replace trusted context. | `tests/unit/test_runtime_tools.py`, `tests/contract/test_pydantic_ai_runtime.py`; extend to node/custom-role/chat tools in P5. |
| 3–4 | Traversal, symlink escape and prefix collision fail. | `tests/unit/test_path_security.py`, `tests/unit/test_workspace_files.py`, `tests/integration/test_security_gateway.py`; P4/P6 cover trust/config replacement paths too. |
| 5–7 | Exact command mismatch; isolated grant versus unsafe; expired/exhausted/revoked/wrong-run/project/stage. | Partial `test_permission_broker.py`, `test_security_gateway.py`; P4 must assert full new persistent/run-grant semantics and actual non-execution. |
| 8–9 | CoS cannot self-approve or mutate protected trust/hard-deny/audit. | Existing gateway/runtime role tests; P4 registry and P5/P6 routes must reject all new bypasses. |
| 10 | Secrets absent in events/logs/errors/command environment/inspection. | `tests/unit/test_secret_boundary.py`, `test_runtime_models.py`, `tests/integration/test_pydantic_ai_workflow.py`, Docker contract/real tests; include new trust/chat/proposal data and WAL in P4–P6/Q6. |
| 11–12 | Docker restrictions and no unsafe fallback. | `tests/contract/test_docker_sandbox.py`, `tests/docker/test_real_docker.py`, `tests/unit/test_project_runtime_integration.py`; Q6 is required for effective runtime enforcement. |
| 13–15 | Denial audit/no execution; exact approved intent; duplicate resume does not repeat effect. | `tests/integration/test_approval_recovery.py`, `test_security_gateway.py`, `tests/e2e/test_offline_cli.py`; extend current-policy revalidation/concurrent reservation under P4. |
| 16–17 | Verifier cannot change accepted patch; diverged/dirty target refuses without data loss. | `tests/integration/test_verifier_mutation_evidence.py`, `test_workflow.py`, `tests/e2e/test_offline_cli.py`; repeat joined/repair flow in P5. |
| 18 | Output obeys truncation/redaction/storage limits. | `tests/unit/test_process_runner.py`, `test_runtime_models.py`, sandbox/runtime contracts; P5/P7 add graph/context/history aggregate bounds. |
| 19 | YAML tags/unknown fields fail safely. | `tests/unit/test_config.py`; P4 trust and P6 workflow/skill/result-tree parsers require equivalent negative tests. Baseline Workflow YAML is not semantically parsed. |
| 20 | Worker environment excludes provider credentials. | Docker/unsafe contracts, `tests/unit/test_secret_boundary.py`; Q6/M2 inspect actual environment and encoded sentinels. |
| 21 | Profile cannot run hooks/scripts/Make/manifests/escaping symlinks. | `tests/unit/test_repository_profile.py`, `tests/unit/test_bootstrap_security.py`, repository contract fixtures; Q2 plus M2. |
| 22–23 | Runtime exposes no unmediated capabilities; verifier write denied and fingerprint unchanged. | `tests/unit/test_runtime_tools.py`, `test_architecture_boundaries.py`, `tests/integration/test_verifier_mutation_evidence.py`; custom-role/node variants in P5. |
| 24–25 | Simulated PASS cannot verify; invalid plans fail. | `tests/unit/test_evidence_gate.py`, `test_fleet_plan.py`, `tests/integration/test_workflow.py`; advanced execution/joins cannot weaken these invariants in P5. |
| 26 | FleetPatch rejects protected targets and unsupported skills. | `tests/unit/test_fleet_patch.py`; P6 may admit skills only with an explicit semantic/security contract and negative apply/rollback tests. |
| 27 | Repository PATH/Git config/hook/filter/diff surfaces cannot execute. | `tests/contract/test_phase1_adapters.py`, `tests/integration/test_repository_fsmonitor.py`, `tests/unit/test_repository_profile.py`; repeat runtime/preview use in Q2/M2. |
| 28–29 | Mutation and contradictory PASS remain visible and unverified. | `tests/integration/test_verifier_mutation_evidence.py`, `test_verifier_verdict_semantics.py`, `tests/unit/test_evidence_gate.py`; criterion/join paths in P5. |
| 30–31 | Referenced config drift invalidates; foreign/corrupt/missing/wrong-kind/task/config bindings fail. | `tests/unit/test_config.py`, `tests/integration/test_config_snapshot_binding.py`, `test_task_spec_binding.py`; evolution must extend snapshots without rewriting historical runs in P6. |
| 32–33 | Filesystem identity/case aliases and Git includes/promisor helper escapes fail. | `tests/unit/test_path_security.py`, `test_bootstrap_security.py`, `test_repository_profile.py`, `tests/contract/test_phase1_adapters.py`; record platform applicability rather than assuming identical filesystems. |
| 34–35 | Secret-bearing scope/intent rejected before persistence; repository/state roots disjoint both ways. | `tests/integration/test_security_gateway.py`, `test_cli.py`, `tests/unit/test_bootstrap_security.py`; P4 trust-root and P5 conversation/plan fields extend this. |
| 36–37 | Bounded regular snapshot reads; post-run drift and any status evidence-binding mismatch rejected. | `tests/unit/test_config.py`, `tests/integration/test_config_snapshot_binding.py`, `test_task_spec_binding.py`, `test_workflow.py`; P5/P6 add joined/evolved binding substitutions. |
| 38–39 | Protected case aliases and ancestry conflicts rejected; FleetPatch ID/path/whole-proposal secret contract. | `tests/unit/test_path_security.py`, `test_fleet_plan.py`, `test_fleet_patch.py`; initial probe shows FleetPatch file/descendant overlap is currently accepted: P6 must add and pass regression. |
| 40 | Incoherent or substituted sandbox capabilities fail before resource creation. | `tests/contract/test_fake_sandbox.py`, `tests/unit/test_project_runtime_integration.py`, `test_runtime_models.py`; preserve exact Docker/unsafe dispatch with new modes. |
| 41–42 | Secret-bearing repository/profile/options/diffs fail before preview/state/write; ProjectKnowledge source hash independently reproducible. | `tests/unit/test_bootstrap_security.py`, `test_repository_profile.py`, `tests/integration/test_cli.py`, `test_bootstrap_report.py`; P6 prospective-tree/diff scanning required. |
| 43 | FleetPatch raw JSON type/depth/node bounds and whole-proposal secret scan precede schema/errors. | `tests/unit/test_fleet_patch.py`; preserve through runtime proposal, persistence, show, apply and rollback in P6. |
| 44 | Attacker Git keys never enter executable argv; malformed secret config/errors remain generic/cause-free. | `tests/contract/test_phase1_adapters.py`, `tests/unit/test_config.py`, `test_bootstrap_security.py`, `tests/integration/test_config_snapshot_binding.py`; new parser paths need same behavior. |
| 45–46 | Provider preview is static; missing/invalid credentials/unsupported provider fail early; doctor inspect-only. | `tests/integration/test_cli.py`, `tests/unit/test_doctor_runtime_integration.py`, `test_project_runtime_integration.py`, `test_runtime_registry.py`; Q2/Q3, no live credential needed. |
| 47–48 | Exact gateway-backed role tools and offline TestModel/FunctionModel; live requires explicit inputs. | `tests/contract/test_pydantic_ai_runtime.py`, `tests/integration/test_pydantic_ai_workflow.py`, `tests/conftest.py`; extend custom roles and repair stale live smoke before M3. |
| 49 | Raw/URL/base64/base64url/hex/JSON-escaped secret forms absent throughout. | `tests/unit/test_secret_boundary.py`, `test_runtime_tools.py`, `tests/contract/test_pydantic_ai_runtime.py`, `tests/integration/test_pydantic_ai_workflow.py`; include chat/trust/backups/FleetPatch in P4–P6. |
| 50 | Differing init proposal cannot split repository and runtime registration. | `tests/unit/test_project_runtime_integration.py`, `tests/integration/test_cli.py`; P6 creates a distinct reviewed transaction with coherent Project rebinding, retaining init's safe contract. |
| 51–52 | Secret-free prompts/schemas/context/messages/serialized request; credential rotation covered before start/resume/apply parsing. | `tests/contract/test_pydantic_ai_runtime.py`, `tests/unit/test_secret_boundary.py`, `tests/integration/test_config_snapshot_binding.py`; new graph/chat/proposal paths must register current/relevant historical secrets before handling untrusted content. |
| 53 | Entire deferred batch validated before first side effect. | `tests/unit/test_runtime_tools.py`, `tests/contract/test_pydantic_ai_runtime.py`; P5 node identity/aggregate budgets and P6 proposal tools must not introduce partial prevalidation execution. |

The product's eight security-review demonstrations are covered respectively by cases 1/8/9, 3/4/32/38, 5/14, 10/20/49, 8, 26/39/43, 16/23/28 and 15/17 plus F7-03. These mappings preserve the product acceptance wording without treating a narrow unit test as proof of the entire user journey.

The table above preserves the initial audit's starting targets and regression obligations, not a claim that accepted Phase4–6 code still has those baseline bugs. Current routing for the added boundaries is:

| Security cases / later boundary | Current proving surface |
| --- | --- |
|1–9,13–15,34–35: effective ceilings, exact grants, revocation and one-winner dispatch | `tests/unit/test_permission_policy_security.py`, `tests/unit/test_dispatch_claims.py`, `tests/integration/test_persistent_permissions.py`, `tests/integration/test_gateway_concurrency.py` and the exact-approval Docker cases. E4 accepts these behaviors; subsequent full gates must retain them. |
|2,18,22–25,28–31,36–37,47–49,51–53: graph/chat/runtime context and authoritative evidence | Existing runtime/gateway/evidence tests plus `tests/integration/test_conversation_safety.py`, the graph/evidence suites and public graph/chat Docker journeys. E5.1–E5.3 accept bounded ownership, usage and actual independent verification, not arbitrary external exactly-once effects. |
|19,26,30–31,38–39,43–44,50: typed workflow/skill and complete organization publication | `tests/unit/test_verification_skills.py`, `tests/unit/test_fleet_patch.py`, `tests/contract/test_organization_publication.py`, `tests/contract/test_organization_journal.py`, joint recovery/interfaces and fresh-process evolution E2E/Docker. E6 closes the initial opaque-workflow/ancestry/init-replacement findings with persisted, native and negative evidence. |
|10–12,16–17,20–21,27,32–33,40–42: actual worker/bootstrap/Git boundary | Existing bootstrap/path/Git/process contracts plus complete `tests/docker`, including independent verifier, sentinel, cancellation and exact owned-resource recovery. Real execution and final residue inspection remain mandatory; mocked calls alone cannot close these cases. |
|45–49,51: release setup and credential boundary | Existing provider/doctor/runtime tests plus `tests/unit/test_release_prerequisites.py`, `tests/unit/test_release_tooling.py` and fresh installed CLI tests. Provider requests remain disabled; actual live-provider quality/compatibility is the separate unperformed L2/M3 gate. |

The standalone offline replay is a named subset, expanded from539 to734 cases with Docker contract/lifetime coverage; it is not all53 requirements proved by one aggregate count. Final security acceptance combines these mapped full-default tests, separately enabled real Docker, platform-specific native tests and exact artifact/resource read-back. Darwin-only metadata cases require actual macOS execution and are not counted as Linux passes.

## Known integration gaps discovered in the initial audits

| Gap | Concrete baseline path | Acceptance consequence |
| --- | --- | --- |
| Baseline approved-resume policy gap superseded in Phase 4 source; accepted in E4. | New `application/permission_policy.py`, updated approvals/gateway re-evaluate current policy. | P4 must prove revocation/deny/ceiling changes after approval affect actual execution on the frozen candidate. |
| Baseline user-ceiling/target-binding gap superseded in Phase 4 source; accepted in E4. | Reviewed trust paths and current repository identity/base/status/configuration checks now precede scope/approval/resume. | P4 must prove CoS cannot expand reviewed scope and approved resume rejects stale bindings; include partial initialization and legacy compatibility. |
| Phase 4 concurrent once-dispatch race reproduced; fixed and accepted in E4. | Two callers observed the same pending intent before consumption; idempotent SQLite reservation returned it to both. Gateway now requires permanent atomic dispatch ownership. | Shared-SQLite barrier test must prove one executor, one consumption and no restart replay of a claimed incomplete intent. |
| Phase 4 model-reason resume failure reproduced; fixed and accepted in E4. | Offline PydanticAI repeated the same command with changed reason; unchanged logical key conflicted with the full intent hash. Gateway now preserves the original reason and role checkpoints retain identity. | Offline PydanticAI once/run/always with new call IDs/reason must resume; changed command/resource/parameters still fail. Paused/failed provider usage remains a Phase 5 accounting gap. |
| Baseline three-strategy execution gap closed in E5.2. | Planner plus graph coordinator/workflow now execute all five strategies; normal offline/Docker, scheduling and CLI tests retain evidence. | Preserve actual overlap, deterministic joins and planned-role-only execution through chat. |
| Baseline singular-Run concurrency gap closed in E5.2. | Exact internal child Run/Task identities, graph/continuation CAS, per-child grants/workspaces and immutable dependency/join records preserve existing singular fields safely. | Ordinary Run saves remain non-CAS; only the exact graph owner can orchestrate. Unknown claims require explicit stopped-owner recovery, never replay. |
| Baseline role/delegation/step gap closed for supported roles in E5.1/E5.2. | Configured `mayDelegateTo`/`maxSteps` narrow hard ceilings; optional Researcher/Architect have readonly catalogs and bounded reports. | Arbitrary new role names do not acquire executors or tools; preserve ceilings through future configuration evolution. |
| Baseline repair/direct/criterion gaps closed in E5.1/E5.2. | Bounded prior verdict artifacts, substantive CoS response, typed current-verifier criterion references and joined-candidate evidence. | Missing/foreign/contradictory mappings and fake/unsafe evidence remain inconclusive; direct text is not execution evidence. |
| Baseline chat/restart gap closed at E5.3. | Persistent bounded conversation schemas/CLI, atomic turn/Run registration, exact original ownership/checkpoints and cumulative budgets are implemented. | Preserve supported resume/duplicate-read behavior through evolution; this does not promise durable arbitrary model internals or generic exactly-once external effects. |
| Baseline snapshot membership gap addressed in Phase6 candidate. | Separate complete OrganizationTree binds README, safe unreferenced files and metadata; the historical Project hash keeps its ConfigSnapshot meaning. | E6 native/journal/generation tests cover coherent publication and immutable old runs. Full acceptance remains separate from the implemented fix. |
| Baseline workflow/skill/ancestry validation gaps addressed in Phase6 candidate. | Strict WorkflowDefinition/VerificationSkill closure and case-folded ancestry validation now reject the initial in-memory probe failures. | Preserve permanent pure/config/proposal/apply/rollback negatives and execute E6 final gates. |
| Unsupported implicit registration remains intentionally denied. | Protected FleetSpec role/workflow registry remains immutable; existing workflow references activate only typed supported skills with known commands. | E6 proves required backend command evidence changes. Arbitrary new roles, executable skills and protected authority are not implicitly registered. |
| Baseline init replacement gap addressed by separate Phase6 publisher. | Native full-directory exchange, durable prepared journal, monotonic admission and explicit recovery implement replace/remove without reusing init. | Headed init cannot rebind even identical bytes/credential reference. Unknown source/tree/index changes are preserved and remain fenced. |
| Historical live-smoke setup mismatch repaired in Phase7. | The test now requires public PydanticAI+Docker initialization, actual independent evidence, separately gated provider/Docker inputs and credential redaction. | Offline prerequisite negatives pass; the actual live canary is still unrun, so this setup repair does not close L2/M3. |
| Historical distributed-runner gap repaired in Phase7. | Canonical packaged digest/hash-pinned runner, learning project and guide ship in both archives and are used in fresh installed journeys. | Preserve exact documentation-final package bytes; no public image registry or live-model success is implied. |
| Historical release/platform infrastructure gap implemented in Phase7. | Pinned read-only CI, upgrade/scale/adversarial scripts, changelog/release/dependency/data policies and detailed guide now exist; actual platform/installed/Docker results are in E7. | Full frozen and exact-head CI passed; PR #5 merged with exact tree read-back. The post-merge record is separate; owner license and actual live-provider gates remain open. |

## Proving commands and manual protocols

Commands below identify the proving surface. P4–P7 name present tests; E5.3/E6 record accepted local phases and E7 records release-candidate proof with outstanding final gates. No command has been run merely by being listed.

### Existing offline commands

Q1 — contributor checks, lock and schema drift:

```bash
uv lock --check
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m agent_fleet.schemas.generate --check
git diff --check
```

Dependency installation may use the network. After dependencies are installed, ordinary tests must run with live-provider and Docker opt-in flags absent. Record interpreter/Git/OS versions; Q1 alone does not prove cross-platform execution or dependency review.

Q2 — baseline unit/contract security and domain surface:

```bash
uv run pytest -q tests/unit tests/contract
```

Q3 — persisted integration surface, including files with imperfect marker coverage:

```bash
uv run pytest -q tests/integration
```

Q4 — subprocess E2E and complete default suite:

```bash
uv run pytest -q tests/e2e
uv run pytest -q
```

Q5 — build and archive verification:

```bash
uv build --offline
uv run pytest -q tests/integration/test_distribution.py
```

Q5 must be supplemented by the proposed installed-distribution test below and M1. Existing archive tests check runtime prompts, migrations and schemas, but do not install each distribution into a fresh environment or prove README runner assets are available to its user.

### Explicit real-Docker command

Q6 requires an operator-prepared local image and supported local Unix daemon. Set `AGENT_FLEET_DOCKER_TEST_IMAGE` to the reviewed preloaded image and `AGENT_FLEET_ENABLE_DOCKER_TESTS=1` explicitly before running:

```bash
uv run pytest -q -m docker_integration tests/docker
```

Record the image digest, Docker client/server versions, daemon identity, platform, effective user/mounts/network/capabilities/environment/resource constraints, command/cleanup evidence and exact managed-resource absence. Use the documented host-shared temporary directory on macOS/Colima. Do not pull/build images, access a remote daemon or silently select local-unsafe as a test fallback.

### Phase-specific automated acceptance targets

P4 — exact permission lifecycle and process recreation:

```bash
uv run pytest -q tests/unit/test_trust_policy.py tests/unit/test_scoped_grants.py tests/unit/test_permission_policy_security.py tests/contract/test_trust_store.py tests/integration/test_persistent_permissions.py tests/integration/test_permission_cli.py tests/integration/test_verifier_approval_resume.py tests/integration/test_gateway_concurrency.py tests/integration/test_pydantic_ai_approvals.py
```

P5 — accepted budget/evidence and graph execution regression targets:

```bash
uv run pytest -q tests/integration/test_workflow_role_bounds.py tests/integration/test_runtime_budget_workflow.py tests/integration/test_adaptive_workflow.py tests/integration/test_graph_scheduling.py tests/integration/test_adaptive_graph_safety.py tests/integration/test_graph_delivery_audit.py tests/integration/test_worktree_preparation.py tests/e2e/test_adaptive_graph_cli.py
```

P5 — accepted persistent-chat/restart regression targets (E5.3 focused and full aggregate evidence):

```bash
uv run pytest -q tests/unit/test_chat_cli.py tests/unit/test_conversation_models.py tests/unit/test_conversation_state.py tests/contract/test_conversation_store.py tests/integration/test_conversations.py tests/integration/test_conversation_safety.py tests/e2e/test_persistent_chat_cli.py
```

The public initialization/chat/approval/restart/verification/apply journey is `tests/docker/test_conversation_journey.py`. Its isolated case requires the explicitly prepared local real-pytest runner and Docker opt-in; ordinary test execution skips that case. E5.3 and the persistent-chat plan record its actual command/environment and distinguish offline FunctionModel responses from real Docker command evidence.

P6 — operational evolution, transactional apply/recovery, behavior and rollback:

```bash
uv run pytest -q tests/integration/test_fleet_patch_proposals.py tests/integration/test_fleet_patch_interfaces.py tests/integration/test_fleet_patch_recovery.py tests/integration/test_verification_skill_workflow.py tests/e2e/test_fleet_evolution_cli.py
```

P7 — fresh installed distributions and measured scale:

```bash
uv run --offline pytest -q tests/integration/test_state_scale.py tests/integration/test_release_upgrades.py
AGENT_FLEET_ENABLE_INSTALL_TESTS=1 AGENT_FLEET_TEST_WHEELHOUSE=/absolute/prepared/wheelhouse uv run --offline pytest -q -m 'installed_distribution and not docker_integration' tests/release
```

P4–P7 must run offline with generated fixture repositories and temporary Fleet state unless explicitly marked real Docker. Installed-distribution acceptance must exercise both wheel and sdist with declared dependencies in a fresh environment, outside the source checkout, using the installed `fleet` executable. Verify packaged schemas/migrations/prompts/runner/user assets through their installed access path and demonstrate representative JSON errors and a complete offline supported flow.

### Manual release evidence

M1 — fresh-user journey. An independent reviewer installs the frozen distribution in a fresh environment, follows the completed quickstart/guide verbatim, checks doctor readiness, prepares the documented runner, previews and initializes a disposable Git fixture, uses chat/approval/status/artifacts/apply, changes/rejects/applies/rolls back organization configuration, revokes trust and restarts/recovers. Capture exact commands, exit statuses, artifact hashes and resulting file bytes. Separate dependency/image preparation from ordinary Fleet execution. This protocol is incomplete until all required behavior and guide assets exist.

M2 — adversarial bootstrap. On the frozen candidate, use a disposable Git repository and disjoint state/trust directories with registered random raw/encoded secret sentinels and an outside-mount host sentinel. Exercise malicious repository instructions/config/hooks/paths, denied capabilities, verified Docker execution and interrupted cleanup. Record rejection before unauthorized effects, exact effective sandbox inspection, secret absence, intact outside sentinel and zero owned-resource residue. Run the eventual versioned adversarial script; a script name without a recorded execution is not evidence.

M3 — explicitly authorized live-provider journey. First repair the stale smoke and prove its setup offline. Obtain an explicitly supplied disposable credential plus selected provider/model/reference; do not discover or reuse ambient credentials. With documented opt-in inputs set, run:

```bash
uv run pytest -q -m live_provider tests/live/test_provider_smoke.py
```

Also record the complete real-provider+Docker user journey required by U3/U4, using a disposable fixture and the normal CLI path. If the repaired smoke covers only a fake sandbox, it proves provider integration only. The real-Docker combined journey must independently validate patch behavior and canary/report/evidence/cleanup bindings. Record provider/model metadata and reported usage without storing credentials or unredacted prompts. Live model quality, Docker enforcement and packaging are separate claims.

## Session-first extension — 2026-09-07

The confirmed Session/per-role-model/custom-role/local-dashboard extension has
its own [current acceptance ledger](SESSION_FIRST_ACCEPTANCE.md),
[living ExecPlan](../.agent/plans/2026-09-07-session-first-release.md) and exact
disjoint integration selections. Frozen default matrix:2283 passed,19 explicit
optional skips; separately enabled Docker15 passed; standalone adversarial736
passed. Package installation and GitHub delivery have their own receipts in that
ledger. Historical Phase6/7 CI or the package's0.1.0 label does not accept this
extension; L1/L2 and unperformed platform/provider checks remain separate.

## External gates and genuine post-MVP deferrals

Historical status note: the L1/L2 starting-state declarations and second-Harness
deferral below are retained from the earlier Phase7/Session-first snapshot, not
current gate declarations. The owner subsequently selected [Apache-2.0](../LICENSE)
and explicitly supplied/authorized bounded OpenAI test credentials. Current
implemented runtimes include OpenAI Agents SDK and restricted LangGraph with
offline conformance evidence; that does not qualify their broader live campaigns.
Use the current [README](../README.md), the dated evidence above and the active
P0/P1 plan for exact live results, unknown usage, authorization and delivery.
Historical missing-credential prose does not supersede those records, and an
old canary pass does not qualify a new candidate or provider/Harness combination.
The remaining productization deferrals and security boundaries below still apply.

- **L1 — owner license: unproven.** The active plan records no supplied license choice. Selecting a license or publishing a package is outside the current implementation authorization. Complete independent implementation and release artifacts first; do not label the public OSS release ready until the owner's exact license decision is recorded.
- **L2 — disposable live credential: unproven.** No explicit disposable provider credential is supplied by the active task. Ordinary tests, CI, builds, documentation and offline smoke repair can proceed. M3 cannot be marked passed from historical model-adapter tests, ambient variables, fake runtime or TestModel/FunctionModel.
- **Modal/Hosted/remote sandboxes and cloud control plane are deferred after MVP.** `SandboxName` and composition-root registration accept exactly fake, Docker and local-unsafe. Abstract capabilities or a negative test mentioning hosted do not constitute a hosted implementation. Their absence is not a Phase 7 blocker.
- Other explicit post-MVP work: second harness/conformance matrix, enforcing domain egress proxy, GitHub App/MCP/external connectors, daemon/scheduler, concurrent repositories/cross-machine scheduling, richer TUI/web/mobile interface, skill/plugin distribution, signed audit export and enterprise policy integration. Phase 6's local reviewed skill semantics remain in scope even though plugin distribution is deferred.
- Unsupported approved worker networking must stay rejected until an enforcing implementation exists. An exact permission rule may represent network conditions without claiming that Docker `network=none` or host execution implements domain allowlisting. Optional telemetry and useful issue templates remain optional under the roadmap.
- Git commits, push, PR merge and remote identity checks are separate delivery outcomes under the active plan. They do not prove release/security acceptance, and local passing tests do not prove remote CI or merge completion.

## Evidence register

| Date / candidate | Activity | Result and scope | Requirements closed |
| --- | --- | --- | --- |
| 2026-09-05 / Phase 3 baseline | Read-only spec/source/test audit; two in-memory validator probes. | Operational Phase 4–7 gaps mapped; malformed Workflow and file/descendant FleetPatch acceptance reproduced without writes or external services. Existing suites not rerun by this audit. | None; this initializes the ledger. |
| 2026-09-05 / concurrent Phase 4 working tree, not frozen | `uv run pytest -q tests/integration/test_persistent_permissions.py`; targeted Ruff and mypy checks. | Exit 0: 13 tests passed in 35.27s on local macOS. Fake-runtime/FakeSandbox lifecycle, separate Engineer/Verifier scopes, activation retry, current ceilings and exact later-run consumed receipts; no provider/Docker execution and no verified-complete claim. Later source changes to run-grant lifetime, reset cutoff and publication audit require a fresh full P4/Q1–Q4 run. | None; focused regression evidence only. |
| 2026-09-05 / concurrent Phase 4 documentation review | Four-document implementation/schema/CLI boundary refresh; in-memory Pydantic validation of documentation examples. | Complete UserTrustPolicy YAML, VerificationProfile YAML and labeled runtime/sandbox fragment validate (exit 0); Python sketches and future YAML are explicitly non-complete/target examples. Prepared/publish/completion, reset cutoff, checkpoint/rehydration and current versus historical inspection are documented. Phase 5–7 and external gates remain open. | None; documentation is not execution evidence. |
| 2026-09-05 / concurrent Phase 4 independent integration audit | Two source-unmodified probes in disposable local fixtures: shared-SQLite gateway concurrency and offline PydanticAI FunctionModel approval. | Before fixes: two simulated executor entries for one intent/one consumed grant; changed display reason caused an unchanged approved command to fail with zero dispatches. Fixes are wired; final named regression/full gates remain required. No provider or Docker operations were performed by this audit. | None; regression findings retained until final evidence supersedes them. |
| 2026-09-05 / E4 accepted local working tree | Final aggregate, layered, static, archive and real-Docker acceptance; post-metadata CLI/static/archive refresh. | Exact snapshot above: `1001 passed, 10 skipped`; Docker `9 passed`, zero managed-container residue; metadata CLI refresh `30 passed`. Prior Phase 4 provisional evidence and both regression findings are superseded. Live provider and full-MVP release remain unproven. | F4-01–F4-13 at the documented supported boundary. |
| 2026-09-05 / E5.1 committed and pushed | Frozen M1 budgets/evidence acceptance; commit `ab28aaa6192a8e4d92c78dada2413eb5606376b7`, development-branch remote read-back. | `1170 passed, 11 skipped`; Docker `10 passed`; exact criterion/new-module proof and durable accounting. Main remains `c700de1`; no release or final merge. | M1 supported role/budget/direct/repair/criterion boundaries only. |
| 2026-09-05 / E5.2 accepted, subsequently committed and pushed | Frozen graph full/static/Docker/E2E/package gates and independent delivery audit; unchanged source/test checksum recorded above; checkpoint `7a70b1a940209487deac5585583ba1f9924be8d9`, tree `bf75f1d681e36b30954235214ed641202945b060`. | `1344 passed, 13 skipped`; Docker `12 passed`, zero managed resources; E2E `9 passed`; independent audit `11 passed`; final archive/README tests `4 passed in 4.37s`, repeat `4 passed in 1.73s`. Retained pre-final `2 failed, 212 passed, 85 deselected` superseded by fixes and final gates. Remote main remains `c700de1`. | Graph-specific F5-03/F5-04/F5-09/F5-10/F5-11; not chat, whole Phase 5, Phase 6/7 or external gates. |

E4 supersedes the provisional Phase 4 statements in these historical entries: the two reproduced regressions are fixed and covered by the accepted final suite. It closes F4-01–F4-13 only, not Phase 5–7 or external release gates. Future entries must identify their evidence and supersede rows explicitly; this ledger must never turn a documented limitation into a whole-MVP completion claim.
