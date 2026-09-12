# Deliver retained baseline output and six generated repository journeys

This ExecPlan is living. Maintain Progress, Discoveries, Decision Log and Outcomes.
It is the integration record for the D/E contracts already frozen before
implementation in `2026-09-11-p0-p1-completion.md`, not a new productization scope.

## Purpose and user-visible result

`fleet baseline show REVIEW_ID --json` and Session `/baseline show` expose the
actual retained bounded/redacted command observation. Six generated Python/Node
repositories prove public readiness, consent, isolated baseline execution and
durable output, including honest nonzero results. This is not model task success.

## Scope

### In scope

- Add nullable typed observation to BaselineShow with same-transaction validation.
- Standalone and Session output, corruption/redaction/no-redispatch regressions.
- Six generated fixture journeys and optional pinned Python/Node image recipe.
- Explicit optional cohort selection in the adversarial gate, docs and delivery.

### Out of scope

New models/Harnesses, external-repository24-task campaign, original-DB evaluation
finalization, dependency installation in project workers, new grants/migrations,
Dashboard/Memory/evolution, package publication or hosted CI execution.

## Current repository state

The preserved original baseline worktree included older A/B work and documentation.
Root first created this integration worktree at PR10 mergea96eb29, copied only
reviewed D/E files and focused documentation, then integrated accepted G/F bytes
without overwriting Foundry branding/license or A/B. After every combined full
test stopped, root preserved stash `9bfc8931fcd70163654a2788388b88da2cca6fa2`,
fast-forwarded to delivered PR12 merge
`e45d7e34bb01de94bada6fdd6a0a718c94af2f37` and reapplied cleanly. At that integration
snapshot only the22 reviewed D/E paths remained dirty; all554 source inputs still
equal the full freeze. Final documentation edits are separate from that source
binding. Other worktrees and the retained original evidence remain untouched.

## Security impact

No authority, execution port, migration or new raw capture is introduced.
Persistence loads and validates observation once with review/execution/report
and resources in the same SQLite read transaction. Public output contains only
retained redacted/control-escaped bytes/hashes, never raw secrets. Showing results
does not execute commands; CLI startup may still initialize/migrate state, so do
not claim universally zero writes. Business nonzero exits remain nonzero results.

## Proposed design and public contracts

Eight E paths own the additive BaselineShow field, store/CLI projection, generated
schema and contract/integration/standalone/Session regressions. Existing observation
schema, persistence tables and capture semantics stay unchanged. D adds static
fixture construction and six opt-in Docker cases with exact public commands:
Python `python -m pytest`, Node `npm run test`. Results are0/2/1/0/1/1 respectively.
Each requires absent-state readiness, independent scripted Docker bootstrap,
missing-consent rejection, one exact grant/dispatch, reopened observation equality,
spent retry without redispatch, source preservation and exact resource cleanup.

The adversarial runner's ordinary --docker/--image pair excludes the optional
cohort file explicitly. --baseline-cohort-image additionally selects all six;
empty/incomplete arguments fail before child dispatch. Existing skip/error/empty
gate failures and timeouts remain unchanged. CI changes only its existing Docker
step label and explicit cohort exclusion, with no new job/trigger/permission.

## Milestones

1. Preserve exact independently reviewed D/E/gate bytes in current Foundry tree.
2. Refresh docs and run complete current default/static/schema/lock/package gates.
3. Run separately selected physical standard Docker/cohort/adversarial gates;
   bind typed artifacts, leases and native cleanup through independent readback.
4. Commit/push/normal exact-head PR merge with [skip ci], then remote readback.

Acceptance is exact current-source evidence, not a sum of earlier overlapping
counts. Six generated observations do not substitute for six external projects.

## Detailed implementation steps

1. Integrate baseline_resources.py, persistence/baseline.py, cli/baseline.py,
   baseline-show.schema.json and four baseline contract/integration/E2E modules.
2. Integrate tests/baseline_cohort_fixtures.py, its unit module, Docker cohort and
   tests/fixtures/baseline-image recipe/allowlist. Keep all actual source commands
   in Docker, no host project tests.
3. Integrate scripts/verify_adversarial.py, its selection unit tests and the two
   reviewed CI step fields; document separate optional selection.
4. Refresh USER_GUIDE, ARCHITECTURE, SECURITY_MODEL, RELEASE, BASELINE_COHORT,
   README and acceptance ledger with current limits/exact measured results.
5. Freeze, independently verify and deliver only after current gates pass.

## Validation plan

Use pinned offline dependencies and a cleared no-key environment. Run Ruff format/
lint, mypy src tests scripts/run_live_canary.py, schema generator --check, offline
uv lock check and git diff --check. Exhaustively reconcile default pytest groups
and unchanged serial cancellation/Session cases. Retain raw argv/JUnit/source maps.
Run final distribution smoke after README/packaged guide edits. Standard Docker
uses the prepared runner; cohort uses its separately inspected pinned local image.
Run `scripts/verify_adversarial.py --help` for exact selected gate arguments and
record exclusions; do not turn skips into passes. Final independent verdict binds
the current source, exact observations/receipts and cleanup, not merely mock calls.

## Rollback and recovery

Use a reviewed revert, not database downgrade or state deletion. Preserve all
failed fixtures/unknown results. The cohort helper's360-second watchdog exceeds
the unchanged300-second product limit. Watchdog/interruption/negative signal exit
means descendant quiescence unknown: do not automatically show or recover after
reaping only the CLI. Normal completed calls may invoke exact reviewed baseline
recovery. Never global-prune containers or remove evidence to pass a gate.

## Progress

- [x] Stopped current full gate `baseline-current-full-01` passed4291/32 with4323
  exact collected/JUnit identities, zero missing/extra/duplicate/failure/error and
  all554 source inputs unchanged. Collection-to-last-test interval
  2026-09-12T12:27:23.181872Z–13:02:57.986927Z,2134.805055s. Three exhaustive
  integration partitions passed267/252/249: pytest2089.20/1393.75/1371.64s,
  process2095.550333/1400.059610/1378.019690s. Default-other passed3521/32:
  pytest1761.65s, process1768.568405s. The two unchanged original serial cases
  ran only after all heavy groups stopped: cancellation1/9.85s
  (11.894497s process), baseline Session1/18.49s (20.343215s process).
  Those two passes are included in4291. The32 skips are28 Docker including six
  cohort,3 fresh-install and1 live; none is promoted to a pass.
- [x] All six full-run static checks passed: `.venv/bin/ruff format --check .`
  (479 files), `.venv/bin/ruff check .`, `.venv/bin/mypy src tests
  scripts/run_live_canary.py` (396 files), `.venv/bin/python -B -m
  agent_fleet.schemas.generate --check`, `uv lock --check --offline --python
  .venv/bin/python` (99 packages) and `git diff --check`. Full pytest prefix is
  `.venv/bin/python -B -m pytest -p pytest_asyncio.plugin -q`; collection and
  exact disjoint selectors/deselections/private basetemp/cache/JUnit argv are
  retained in `collect.result.json`, `partitions.json` and each named result JSON.
  Original warnings/logs remain. Summary SHA256
  `2c53c43438604443a276135d6b705ce8178a13157a4cf35873c701b6cf049e1c`;
  both554-input maps SHA256
  `990c82b4804e434132d1d950804f96e625116e1eb07d13577095792fec760788`.
- [x] After the full runner stopped, advance/reapply onto delivered F/PR12 as
  recorded above; all554 sources still match. F's exact head/merge tree and
  postmerge22-contract smoke are historical F delivery evidence in its plan,
  not current D/E standard-Docker/adversarial/install/package qualification.
- [x] Independent full/source/static readback PASS/read release
  2026-09-12T13:11:38.548093Z. Fresh collection4323/3.59s matches all six JUnits
  with4291 passes/32 skips and no missing/extra/duplicate/failure/error. All six
  static argv/results pass; original serial JUnit9.855s/18.490s followed all
  four heavy groups/six statics and each other. All554 current inputs at PR12e45
  match both maps;15 held D/E source changes equal their earlier freeze, other539
  match PR12 including F11. CI/docs excluded from source hold; index/HEAD/source
  unchanged. The verifier-only syntax-error wrapper failure remains retained,
  with no candidate mutation. Verdict de-current-full-readback.tIgE2Reu/VERDICT.md
  SHA256 `173d805ca6d12cb46ed9883f305f00f503b9090dd00ae86d628923f921c8286c`.
- [x] All four final current-D runners stopped with exit0 and no failure/error/skip.
  Each before/after map contains the same556 source/README/guide inputs, SHA256
  `9a5777d3d7def14eee4563ca2b8b4cd160738dafee30798be8ee78487d260c10`.
  Exact argv/log/summary/JUnit remain in the separately named private runs below;
  these overlapping counts are not added to4291.

  | Run | Original entry point and result | JUnit SHA256 |
  | --- | --- | --- |
  | baseline-final-package-01 | `tests/integration/test_distribution.py`:1 passed/3.93s; wrapper5.919342995s. | `3e8bdca3273e8aa4290f2a388c30ef84746b7baf7ee6552de2585cbbfdb314a6` |
  | baseline-final-adversarial-01 | `scripts/verify_adversarial.py --output <new-private-gate>`:806 passed/277.11s; gate279.713s, wrapper279.785661936s. Original18-file offline selection. | `581083c86be5975b3b174675ee0c02b4c45bc4fbf21c1f904dedac71d367205a` |
  | baseline-final-docker-01 | Same script with `--docker --image agent-fleet-runner:0.1.0-py314-v1`:22 passed,22 deselected/339.43s; gate342.365s, wrapper342.505614996s. Explicit cohort exclusion retained. | `381c63e9c6c08e8beb86ec34cfc48a5f406af8d48d8f45f6f73eb380fdac2585` |
  | baseline-final-installed-01 | `tests/release/test_installed_distribution.py`:3 passed/379.37s; wrapper381.090124846s. | `5de135a0129d8cf9a7ac785761530934e1ce22b55c0fe23770e6c6c496d28098` |

- [x] Documentation preflight PASS/read release13:21:14.092425Z,17 checks;
  de-docs-preflight.YeFP53qX/VERDICT.md SHA256
  `b9b9c5cebcdc30257a90b3931da31e1087b9c6fb51da1c12d39e52812641e694`.
  Frozen README444552e1 and guide0452c2fa require no further edits. This preflight
  preceded the final runners; later factual updates are only un-packaged bookkeeping.
- [x] Independent stopped distribution-package PASS/read release13:26:35.964296Z,
  12 checks: two archives and one isolated installed tree match332 current runtime/
  resource files,115 schemas and frozen README/guide. Wheel SHA256
  `0e67f9305555017aec43a685c2f83a59be80b6dbddc1a52c5cf5da816fac59a9`;
  sdist `33e879296680a05fabd664ef86c0f0a8ad04b7b766cac77caf9782f45aa0686a`.
  de-package-verifier.gP1HqMis/VERDICT.md SHA256
  `6e8be37bc02c4ddcb7d33f60683832afd66a8ec852da0b7455a56cd600fa989b`.
  This is package-only acceptance, not the distinct fresh-install/public journey review.
- [x] Standard-Docker independent physical readback PASS/read release
  13:33:53.349491Z:22 passed/22 deselected,339.43s pytest,342.365s gate,
  342.505615s wrapper; all556 held inputs unchanged. Five immutable DBs yielded
  nine actual CompletionGate replays and20 real role receipts;56 released leases,
  18 absent workspaces,22 empty exact installation namespaces and20 absent native
  IDs were checked, with772 fixture files unchanged. Six-cohort evidence is separate.
  de-final-docker-readback.zCIrmCUq/VERDICT.md SHA256
  `5ffa894084233376f6671bef15fd9a78f2eea0dd39e7bdcbd59c0c06e9763227`.
- [x] Offline-adversarial independent PASS/read release13:30:11.951208Z:
  15 checks,806 unique passing identities,277.11s pytest,279.713s gate,
  279.785662s wrapper; original selection/guard semantics and all556 inputs
  unchanged. de-adversarial-verifier.jr0KXSUU/VERDICT.md SHA256
  `da76c2eb2cf5c2258d5e76f162db5787fbf4d1d5ea70bae862e9b43cd15da738`.
- [x] Fresh-installed/public-journey independent PASS/read release13:36:39.943744Z:
  original three cases379.37s pytest/381.090125s wrapper, all556 inputs unchanged.
  Six fresh archives equal the accepted package pair; three installs each match
  332 resources/115 schemas/80 locked distributions. Seven immutable journals
  retain migrations1–13;10 CompletionGate decisions and18 code receipts bind215
  artifacts. Target `run_096b73b647264ceaaf25a3d0a1782348` is verified by two
  independent role pytest receipts/5 passes each, followed by explicit public apply.
  All54 leases are released,18 workspaces/six native IDs absent, and exact namespace
  `946fc4aa52da4954a3db128eb6cc244a` empty. A verifier-only initial test-name
  spelling assumption and corrected readback remain retained, not an artifact failure.
  de-installed-verifier.0bmfABzF/VERDICT.md SHA256
  `2b045ff24569cc8974990cb607d67bb94f7d7ffc373ea20865b55cfbe00467a4`.
- [x] Final terminal delivery review PASS/read release13:49:47.091626Z;
  de-final-terminal-verifier.xacbqQOz/VERDICT.md SHA256
  `9e1d7e0060a4ad34f9954af62b23c3019288ab37bb7ec431a81c363738a90424`.
  Exact28 changed paths/556 frozen inputs preserved. The PR draft alone corrected
  spent-grant rejection to spent retry without redispatch; original verifier
  line-wrap assertion failure is retained. Postrelease edits are only factual
  terminal-PASS/Git-pending and separate live03 readback bookkeeping; README,
  guide, source and accepted artifacts remain unchanged.
- [ ] Exact GitHub delivery and remote readback.
- [x] Current combined six-cohort physical run baseline-current-cohort-01 passed6,
  zero failure/error/skip (437.84s pytest,441.880657s wrapper), all554 source
  inputs unchanged. Independent physical audit passed/read release
  2026-09-12T12:24:48.236807Z: actual business exits0/2/1/0/1/1, exact one consumed
  authorization/owner/dispatch/observation/report per case, same-transaction typed
  store.show output, all18 leases/receipts released and6 workspaces absent.
  On matching daemon/image8bc1c28e,36 exact metadata calls confirmed6 installation
  scopes and6 recorded native IDs empty. Six stopped immutable DB admissions had
  no handles or sidecars; all960 retained entries and629 candidate entries unchanged.
  No cleanup/mutation/rerun/provider request. Report
  de-current-physical-readback.tNFUKO52/VERDICT.md SHA256
  b67e04703b6124f5f4ff4402945bfc72c59d485f4e722374580d16ef24b46553.
- [x] Ran the exhaustive current combined default/static matrix after F's active
  installed-distribution job stops. Keep all554 source bytes unchanged and leave
  Git base/index untouched while that runner is active. F's normal separate merge
  could occur meanwhile in its own checkout; this base advanced only after tests stopped.
- [x] September12 combined B+G+F+D/E static preflight passed: Ruff format479,
  lint, mypy396 files, generated schemas, offline99-package lock and whitespace.
  Exact commands/results retained in de-combined-static-01.json. No full/default,
  physical, installed-package or delivery result is inferred from these checks.
- [x] September12 independent focused D/E acceptance passed at11:38:10Z:
  54 existing tests/14.507s,19 schema/identity/projection/one-transaction probes/
  3.298s and25 real-main/synthetic-child gate probes/1.155s. All16 E8/D5/gate3
  hashes,628 candidate files and ignored/index/HEAD inventory were unchanged.
  Evidence de-focused-review.tsbQXudR/VERDICT.md, SHA256
  2edbf689334882244cc6e9de546774d10c89e74f04b265184ed04b6ee5d44e47.
  A verifier-only Python-alias assertion failed before its canonical-byte oracle
  correction; the original failed source/fixture/results remain retained.
- [x] September12 root preserved exact D/E edits in retained stash
  7f40a7c2100593cc39a53b7e39b2fcfbf37d06b6, fast-forwarded to accepted PR11 merge
  5b09fea1c5fdb79066498496852adbb9e5239773 and reapplied D/E without conflict.
- [x] Before combined gates, mechanically overlaid only the11 separately accepted
  F source/test paths from the root candidate through apply_patch. All11 SHA256
  comparisons match; they have no D/E path overlap. Preserve exact hashes from
  physical03 and do not edit their implementation.
  F's full matrix and own delivery were separate prerequisites to this
  slice's eventual Git delivery. After F merged, advance the base preserving
  identical tested combined source; integrate F documentation without replacing
  D/E hunks. Do not count an unmerged overlay as delivered F or accepted D/E.
- [x] September12 independent integration continuity PASS/read release
  11:43:51.545835Z. All16 D/E/gate hashes and11 F files match accepted freezes;
  remaining526 tracked src/tests/scripts blobs equal PR11, with zero shared-path
  collision. Exact33-path integration,629 candidate entries and ignored/index/
  HEAD inventory unchanged; retained stash independently checked. Report
  de-integration-continuity.N7JP5jRp/VERDICT.md SHA256
  a0c72e1c3427d0216166d09fdcb008f3acc0632f9558e91141ef70adb8c473d7.
  This read-only source check did not run combined tests or deliver either slice.
- [x] September12 root integrated only reviewed D/E source/test/gate paths into
  a separate current-B worktree. Fifteen checked implementation/test hashes match
  the frozen candidates. Small guide/architecture additions retained; old README,
  A/B infrastructure and session manifest were not copied wholesale.
- [x] Prior final physical D04:6 passed746.49s, wrapper752.559887s,553 source
  inputs unchanged. Independent baseline-D04-physical-verify.cJiLwA confirmed
  18 released leases,36 metadata queries, six admitted immutable DBs/no sidecars,
  960 retained entries and620 unchanged candidate files. This is historical
  isolated-candidate evidence until current integration gates pass.
- [x] Prior gate compatibility review adversarial-selection-independent.uMJqrg
  passed22 focused checks plus25 synthetic child-JUnit probes. Three exact gate
  file hashes retained; no actual Docker or hosted CI was run by that review.
- [x] Current exhaustive default/static matrix completed as recorded above.
- [x] Final terminal documentation/diff check as recorded above.
- [ ] Exact Git delivery.

- [x] September12 current-B integration preflight:37 focused fixture/selection
  tests passed3.15s, configured mypy396 files, Ruff format478 files/lint and
  whitespace passed. Evidence baseline-current-preflight.avzgE914/focused.xml.
  These are preliminary checks, not the current full/physical/packaging matrix.

## Discoveries

- Generic EvaluationCase cold-start slots, manifests, registration/reservation,
  preflight NOT_RUN accounting and reserved Workflow execution already exist.
  Six generated repositories and the synthetic24-case manifest do not qualify
  actual external repo/task/oracle/profile identities or campaigns. The remaining
  work is real bounded qualification, not a duplicate controller or new production
  campaign framework. Native original-DB finalization remains NOT_GO and rejects
  with write_boundary_unqualified; no bypass or alternate success ledger is added.
- Prior cohort assumptions about spent retry exit2, cleanup scope and negative
  signal exits were independently rejected and repaired. All failed trials remain.
- E's prior independent batch had13 passes/one timeout; isolated original case
  passed16.26s. The performance cause was not proved; preserve original deadline
  and rerun that case serially after heavy current gates, not a larger timeout.
- The image's .dockerignore is inside tests/fixtures/baseline-image, not repository
  root. Only that exact Dockerfile is admitted into the optional build context.

## Decision Log

- September12: integrate into a fresh current-B checkout rather than copy a stale
  whole worktree. Preserve all original evidence and Foundry/publication changes.
- September12: ordinary adversarial Docker explicitly excludes the separately
  opt-in cohort; only a selected cohort image includes it. Do not weaken skip gates.

## Outcomes

Current D/E functionality and six generated public real-Docker observations have
independent focused/physical acceptance. The complete local default matrix passed
4291/32,4323 exact identities and554 unchanged inputs, with all six statics passed;
the unchanged two serial cases passed after all heavy groups stopped. The current
source is preserved exactly atop delivered F/PR12, with both stashes retained.
Independent full/source/static readback passed at13:11:38.548093Z. Current-D final
package1, offline adversarial806, standard Docker22 and fresh-install3 runners
all stopped PASS with556 unchanged inputs; exact timings/hashes are above.
Docs preflight, stopped-package, standard-Docker physical, offline-adversarial and
fresh-installed/public-journey independent reviews passed. Final terminal
documentation/diff review passed13:49:47.091626Z; Git delivery remains pending.
Physical cleanup
acceptance is bounded to the exact reviewed standard-Docker fixtures/namespaces.
Historical F artifacts do not substitute
for these current D/E records; frozen README/guide remain unchanged.

Historical D04, every rejected driver/gate/retry/cleanup/signal assumption and
the separately documented738-deleted-fixture gap remain retained, not relabeled.
Six conclusive observations include four failing business commands; they do not
qualify six external repositories, actual cold starts or the24-task/provider/
Harness campaigns. Existing campaign machinery is not missing implementation.
Native P0 remains NOT_GO, live02 remains failed with unknown charge, and no
additional-provider credentials, paid campaign or whole P0/P1 PASS is implied.

Separately, the manually authorized finite live03 diagnostic replay on clean
delivered PR12 (not D/E) stopped NOT_PASSED at13:34:07.112382Z, after starting
13:33:03.149828Z (63.962s wall; pytest1 failed/62.23s,13 warnings). Target
`run_8f2d52ea5c4c4648a8deb56b543beded` completed two CoS requests with14911 input,
6538 output and21449 total tokens; the Engineer's one reserved response remains
UNKNOWN. Three request reservations/two agent invocations produced zero target
tools, commands, patch or Verifier invocation. The exact CLI/run.failed message
is `The Agents SDK response model did not match the selected model.`; code
`PROVIDER_FAILED`, category `provider_sdk` and cause `response_policy` are unchanged.
This confirms live03's model-identity guard branch, not the unretained returned
model or a dated-snapshot explanation, and does not disambiguate historical
live02 retroactively. Independent failed-attempt readback passed/released
13:44:44.347799Z; report mixed-live03-readback.tm0PwoSS/VERDICT.md SHA256
`bb8ef5f08f37d739ee05627ae15690f424b93bdadb97b0925a70b18c2dc2b47a`.
All8 leases released/3 workspaces absent, exact installation namespace empty,
2 bootstrap native IDs absent on the matching daemon;140 fixture files and
PRIMARY550/BASELINE556 inputs unchanged. All33 stored artifacts validate,21
run exports match and12 project-scoped artifacts remain separate. Preserve the
verifier's initial21-versus33 assumption failure. The original failure bundle
stays inconclusive/cleanup_unproven; later physical cleanup supplements it
without changing its assurance or unknown cost. Bootstrap fake-agent/real-Docker evidence is
not target-provider proof. No D/E source changed and no attempt04/model change
is authorized by this record. The initial launcher03 raw/canonical selection-hash
preflight failed before credentials/output/request; the separately authorized03b
used unchanged selection. Retain `mixed-live03-preflight-failure.md`, live02's
FAILED/unknown-charge result, and all live03 evidence without relabeling success.
