# Restore exact paused sandboxes inside a persistent Session

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log,
and Outcomes. This is a P1 repair, not a new Session or productization feature.

## Purpose and user-visible result

A user in `fleet chat . --review-plan` can approve the Engineer and independent
Verifier commands and `/resume` them in the same process. A retained logical
Docker sandbox must not be mistaken for a second creation request. The original
checkout remains unchanged until explicit patch apply, and all command effects
still require the existing exact permission and durable execution reservation.

## Scope

### In scope

- An explicit project-owned sandbox restoration operation, for an already
  validated paused checkpoint, with exact retained-state reuse or strict restart.
- Contract, workflow, and actual same-process Docker Session regressions.
- Documentation, independent verification and separately gated GitHub delivery.

### Out of scope

New providers, relaxed create semantics, broad cleanup/recovery, altered ownership,
permissions, schemas/migrations, dependencies, model calls, or retry budgets.

## Current repository state

The historical starting base was Foundry PR9 `09c5a64`. `WorkflowService._resume_run` invokes
`ResourceService.rehydrate_paused_sandboxes` after approved pauses. The resource
service validates active parent leases and exact run/workspace/boundary bindings,
but originally called `create` unconditionally. `DockerSandboxProvider.create` correctly
rejects an ID already in its retained `_prepared` map. A persistent Session uses
that same provider. The original Docker conversation test recreated the application
container before each resume, so it did not cover this failure. The original
failed public reproduction is recorded in `docs/KNOWN_ISSUES.md` and retained.

The delivered F slice uses explicit exact restoration and covers both retained
and recreated providers. After independent physical03 acceptance, root integrated
the identical reviewed F source/test bytes atop PR11 merge
`5b09fea1c5fdb79066498496852adbb9e5239773` on
`codex/p1-session-restore-delivery`. Preserved stash
`4ad27af33ef7f5a5ae34cb8eb455d7b1afbef794` retains the pre-integration work.
The historical F integrated full gate `session-current-full-01` passed4246/26,
with4272 exact identities and all six static gates passed. Independent current
full and physical readbacks passed at12:07Z. Final packaged-document refresh
passed; terminal artifact review passed at12:48:11.175677Z. F was delivered in
PR12 at12:52:42Z with exact head/merge/tree and zero-Actions readback below.
Its frozen README/guide/archive identities remain historical F evidence. The
newer D/E candidate has separate current-source/document/package gates in
`2026-09-12-baseline-delivery.md`; F results cannot substitute for those gates.

## Security impact

Preserve all AGENTS/security invariants, especially exact Broker/Gateway grants,
single-winner continuation and execution ownership, immutable image/daemon/workspace
bindings and unknown-outcome recovery. Restoration never executes a command or
infers stopped ownership. It must not terminate, close/re-pin, or overwrite a
conflicting retained preparation. Missing state and invalid state are distinct.

## Proposed design

Add `SandboxProvider.restore(handle, spec)` and call it only after the resource
service's existing paused-lease checks. Docker verifies the complete expected
handle and immutable spec against any retained snapshot, current installation,
daemon/image, original workspace identity and held Git-shadow descriptor, with
identity rechecks after awaited validation. Reuse
that preparation without replacing its pinned resources. If no preparation exists,
use strict `create` with the persisted ID, then exact effective-boundary inspection.
Do not catch an inspection exception and assume missing state. Keep duplicate
`create` rejection unchanged. Fake and explicit local-unsafe implement the same
port using their existing capabilities and explicit unsafe confirmation; no
fallback to host execution. Existing Workflow ownership stays unchanged.

## Public contracts

One internal port method; no new CLI, stored schema, migration or permission.
Existing `sandbox.rehydrated` event and exact inspection continue. Corrupt/stale
bindings fail closed before command dispatch; unknown execution leases still
require recovery. Existing fresh-process resume remains compatible.

## Milestones

### Milestone 1: bounded implementation and offline regression

Acceptance: same-provider paused restoration succeeds, strict duplicate create
still fails, altered handle/spec/installation/workspace/shadow/daemon/image fail
without replacing retained state or executing commands, and missing preparation
can restore only the exact reviewed checkpoint. Existing recovery/owner tests pass.

### Milestone 2: physical Session and delivery

Acceptance: one real Docker Session process proceeds through plan review and
both exact command approvals, ends ready_for_review with independent real receipts,
no proof gaps, unchanged original source and exact resource cleanup. Preserve the
fresh-container resume test. Full default/static/schema/package and Docker gates,
fresh independent verdict and exact-head commit/push/merge precede completion.

## Detailed implementation steps

1. Writer owns only `src/agent_fleet/ports/sandbox.py`,
   `src/agent_fleet/application/resources.py`, and sandbox adapters `docker.py`,
   `fake.py`, `local_unsafe.py`. Add the explicit restoration seam without changing
   ordinary create or Workflow ownership logic.
2. Add the smallest regressions in existing sandbox contract modules,
   `tests/integration/test_approval_recovery.py`,
   `tests/docker/test_conversation_journey.py`, and
   `tests/docker/test_public_session_onboarding_terminal.py`, as needed.
   Keep asserted business outcomes, original failure evidence and time budgets.
3. Root merges focused architecture/security/known-issue/user documentation hunks
   into the current Foundry versions, never copying an old README wholesale.
4. Freeze implementation hashes; independent verifier reviews retained-state
   identity, cancellation, no execution/replay, and physical evidence.
5. Root integrates this separate slice, runs applicable whole-candidate gates,
   then makes an authorized normal GitHub delivery with `[skip ci]`.

## Validation plan

Use pinned offline dependencies and cleared no-key environment. Record exact argv,
JUnit and failure evidence for focused contracts/workflow tests. Root runs Ruff
format/check, `mypy src tests scripts/run_live_canary.py`, generated schema check,
offline lock check, `git diff --check`, complete disjoint default tests, actual
Docker Session tests and final distribution smoke. Root limits concurrent heavy
jobs to four. The initial schedule called for whole-gate serialization; after
integration-2 and all six static checks completed, root instead used the released
slot for the current standard Docker adversarial entry point. This scheduling
deviation changes no selection, assertion or original timeout. If a default
serial case runs before that Docker gate ends, repeat the unchanged serial cases
after all heavy gates stop and retain both results separately. No live provider
call is needed for this repair.

## Rollback and recovery

No database downgrade or user-state edit is needed. Revert only through a reviewed
code change. Preserve conflicting or unknown preparation and the failed Run;
follow exact stopped-owner recovery instead of automatically deleting resources.
No force Git operations or broad Docker/process cleanup.

## Progress

- [x] (2026-09-12T12:52:42Z) Normal exact-head
  [PR #12](https://github.com/meyowu/agent-fleet-foundry/pull/12) delivery complete.
  Head `b07382369f705b4d76661e17348c04e12dbbb245`, merge
  `e45d7e34bb01de94bada6fdd6a0a718c94af2f37`, identical tree
  `d02b0447ddabf20923f5b44f0eb44a0599150ea6`. Immediate guard readback had
  protected=false, rules[], checks0 and statuses0. No admin bypass, rule changes
  or branch deletion; `[skip ci]` on head/merge and Actions0 for both, not hosted
  CI success. Exact readback retained in `session-github-delivery.json`.
  Postmerge restore contracts passed22,211 deselected in0.28s; overlapping smoke,
  not additional unique full-suite cases. Historical F packaged README/guide and
  all archive hashes below remain frozen, not refreshed by newer D/E docs.
- [x] (2026-09-12T12:48:11.175677Z) Final independent F acceptance PASS/read
  release. Exact sentence-only recheck f-final-sentence-recheck.PIEGQyGw passed8
  checks, preserving550 source/README/guide inputs and all prior artifact evidence.
  Verdict SHA25645f9cb7519ddc1f33d869c5702eed85247c62ca410e404e8bd750747a03ca836.
  Prior f-final-artifact-verifier.YWSlKBNF FAIL remains retained (SHA256
  56912a17d880d2a2e3533f67fc077df0163871892613c6da481a777e91b8c790): its only
  candidate failure was an un-packaged G Outcomes sentence, now corrected.
  All artifact/security checks had passed:8 archives,4 installed trees with332
  runtime files/115 schemas,7 immutable migration journals1–13 and10 replayed
  completion decisions (9 code,1 correctly unverified organization). All54
  leases released,18 workspaces absent,6 exact native IDs absent and one exact
  installation namespace empty. Final installed target run_5c2f94ac1fc64566887389b22d4f9d34
  has two independent real python-test5-passed receipts and explicit patch apply.
  All four wheel hashes6f0de47097df290e6140a3f8ddef76162e85957f11163572899e82e233f3f138;
  all four sdists0e1b4f547e10c3320d8bfabd8ded44fd7378ac653a0e24d9f53d94286b48e37c.
  Verifier-only projection/count/line-wrap failures remain retained; no candidate
  source, test, permission, timeout or archive change. Root's postrelease writes
  were only factual PASS/delivery-pending bookkeeping in this plan, master and ledger;
  the later exact Git delivery is recorded above.
- [x] September12 final packaged README/guide correction recheck passed22 checks
  with548 source inputs unchanged; read release12:25:13.412513Z. Remaining
  non-packaged status records were then corrected without changing frozen README
  ac5f428ee40a8b30a330741bb8ff16d149010df37482ce36c1dfe85d1a5cd62d or guide
  ee3643371a817c86c8ca52b6e986e3261cfbacdbf1fd75c04ff5a0fb8ac58c0d.
- [x] Final-doc distribution check session-final-package-02 passed1/3.35s
  (5.009104s wrapper), all550 inputs unchanged. JUnit SHA256
  c4cd0d98fbb518571ecdfe51a4a0e231e8153d51a8cda5df16289ccb329c42e4.
  Distinct final fresh-install run session-final-installed-02 passed3/270.05s
  (271.984476s wrapper), zero failure/error/skip and550 unchanged inputs, using
  the same frozen README/guide and original three-case entry point. JUnit SHA256
  e314f022e294fb1e0a10eaa6b2bf3d75a4d4fecdb3292878f6eba33eba55a5b5.
- [x] Standalone offline adversarial gate passed806/285.69s (288.595s gate,
  288.692113s wrapper). Independent session-adversarial-verifier.tH7c6E3a
  PASS binds806 unique identities, original18-file selection/guards, all550
  before/after inputs, current548 code/config unchanged and only the two later
  packaged-document differences. Verdict SHA256
  560f5b48d1ec377912f9159da0fe8b3556ab4ef4c0151935d0885550367ae744.
  This overlaps the full matrix, not806 additional unique tests.
- [x] Independent current physical readback PASS/read release12:07:33.940349Z.
  All22 unique identities and550 held source/README/guide inputs match. Deepfive
  stopped immutable DBs replay9 completion decisions and20 typed receipts; actual
  positive two-role pytest5-passed and negative four-command build1/test2 matrix
  match the oracle. Conversation changes follow explicit apply; terminal originals
  remain unchanged. All56 leases released,18 workspaces absent,20 exact native IDs
  absent and22 installation namespaces empty on matching daemone470601e. All772
  deep-fixture files and five DB identities unchanged, no handles/auxiliary files.
  Initial verifier scope-count omission was retained and corrected before native
  queries; no source/fixture mutation or rerun. Report
  f-current-physical-readback.Qj0IIVgX/VERDICT.md SHA256
  f7fce493a1bdfff94c56a63e9dcf753ca22433b1d78579750b8cf30a2bcd6784.
  Root then updated README to current4246/26 and physical22; artifact/adversarial
  gates were then pending and their subsequent results are recorded above.
- [x] Independent current-full/static/source reconciliation PASS/read release
  12:07:04.862044Z. Fresh4272 collection matches all six JUnits4246/26 exactly;
  548 source inputs and all six static argv/results match. All15 independent
  checks pass; separate original2-case serial XML passes without increasing the
  total. Global after-heavy scheduling is root-reported and distinguished from
  independently observed timestamps. No fixture/DB/package/current-doc/Docker
  read was included in this bounded review. Report f-full-verifier.NEXvzSz5/
  VERDICT.md SHA2564bb76964ce14b834e4cc79ad3ab07cd436299349763e17189cb6e8217b386bdb.
- [x] Current combined B+G+F default gate session-current-full-01 passed4246,
  skipped26, with4272 exact collected/JUnit identities: zero missing, extra,
  duplicate, failure or error. All548 source inputs unchanged. Collection-to-last
  test11:29:00.673Z–12:00:42.366Z,1901.692739s. Partitions1/2/3 pass253/248/265
  in1850.78/1363.88/1733.55s; default-other3478 passes/26 skips in1746.83s.
  Original serial cancellation/baseline cases each pass (15.619510/28.171539s
  process time). Warnings retained:2/25/24 in integration groups and14 SDK warnings
  in default-other. Skips are22 Docker,3 fresh-install and1 live, never passes.
  Six static checks passed: Ruff474 files/lint, mypy392 files, generated schemas,
  offline lock99 packages and whitespace. Summary SHA256
  48c0f7aba67e0750ef1fb9d9837702d8c1d74815f38363ffc9b4c90fe51d4dfc;
  both source-map hashes
  5984ecc84190c8e10c4701c6621da8b322b2ef9b3679529bc2f376a713d12957.
- [x] Current-source standard Docker gate passed22, with22 deselected and zero
  failure/error/skip, through the unchanged public
  `scripts/verify_adversarial.py --docker --image agent-fleet-runner:0.1.0-py314-v1`
  entry point in session-current-docker-01 (pytest461.18s, gate465.855s,
  wrapper466.009177s). All550 frozen inputs (548 source plusREADME/USER_GUIDE)
  unchanged. Summary SHA256
  a2c710677c25b0a49ad10cd9501c3df4f3dfe0a10fa035717cea5b6818667c87;
  JUnit SHA2564afdbd2fb251be6b31fc483e15b3f788ccba840f54e7ae40d0f4a4bd49bb11fb.
  The same local image2afebd51 and
  daemone470601e were inspected immediately before launch; no pull/build or key.
  The wrapper records exact argv, JUnit and source+README/guide hashes. It started
  only after full integration-2 and all six static jobs exited0; three default
  partitions were still running. Current independent physical readback subsequently
  passed at12:07:33.940349Z; its exact scope is recorded above.
- [x] Because default serial cases overlapped the ending Docker job, root repeated
  those exact two original cases only after both whole jobs had stopped. Separate
  session-isolated-serial-01.xml records2 passed24.66s, no changed deadlines or
  assertions and no other heavy test jobs. These overlap4246; do not add them.
- [x] (2026-09-12T11:39:28Z) Independent combined B+G+F source integration PASS:
  all548 current inputs match the full-gate freeze;11 F inputs match accepted
  physical03 and the other537 match PR11, including all five G paths. All17
  source/AST checks passed twice;55 existing Docker provider functions are unchanged.
  Source diff SHA256
  `797b37c8dcd458f20adc6d8ceca3b4f3db30cd8aad01a6923655fddbcfc2fe91`;
  `bgf-source-verifier.cm9BlI/VERDICT.md` SHA256
  `e05a4f2f921825fbdc5ae9ae8d500578c2f3ff017c95b5c983a43bfa4225acbd`.
  This verdict excludes docs, full tests and package acceptance; those remain
  separate gates, not inferred passes.
- [x] (2026-09-12T11:20:08.137149Z) Independent physical03 acceptance PASS/read
  release. `session-docker-full-03` returned 22 passed, 22 marker-deselected,
  zero failure/error/skip, pytest 246.90s and wall 248.916883s. All 547 physical
  source inputs were unchanged before/after/current. All 619 held candidate files
  and Git state were unchanged during independent readback. Verdict
  `f3-physical-readback.IRwinLHh/VERDICT.md` SHA256
  `6460cbb8d1f841a1b9ef430eb04e4fa90ab3113462939b397163d22f33b021ab`.
  Summary SHA256 `2fbd8d4d215890e70381d18a3f89df56fc13454ce3b957fba0f58095c95bc7dd`;
  JUnit SHA256 `7df44f76ddaacd538346b09c1f88e60a9343f41d8b513c22dac40a08cabe5ff2`;
  pytest log SHA256 `2c621f1a656473f073f7459ef90bcad309584b9a2d320d9c31b5a61e04b430e6`;
  both physical source-map hashes
  `35a622cd6564332fe4b642f3070b94ed8dd10ba0b47ab2885b4b1bf25af16d38`.
- [x] Physical03 deep ledger readback covers five Session/onboarding fixtures:
  9 bootstrap/target Runs, 20 typed command receipts and 56 released leases.
  All 18 recorded workspace paths and 20 exact native container IDs are absent;
  all 22 attempt-specific installation-label inventories are empty on the matching
  daemon. The other 17 physical cases have named passing JUnit evidence, not an
  expanded global cleanup claim. `ledger02.json` SHA256
  `eaa634e5270b529e45aae15a8584c37c3afe8f1b1e914d6504eebd24d0285729`;
  `closeout.json` SHA256
  `4c8dbd732c0997a098d458f665664a1107aebcb13e9b891744a7ee6d8dda304d`.
- [x] Physical03 positive same-process terminal Run
  `run_eb2563bd1ae24f27a1589d6a7f9579c9` reaches ready_for_review/presenting,
  verified_complete=true, with two distinct approvals and Engineer/Verifier
  exit-zero pytest receipts, each reporting 5 passed; no gaps/reason codes.
  The negative synthetic Run `run_42b9e1c8d37e4809b695bdb6c3f4a3f2` correctly
  refuses completion: four distinct build/test approvals and receipts, each
  role's build exit1 and pytest exit2, with COMMAND_EXECUTION_FAILED and
  CRITERION_NOT_PASSING. Its missing build/canary_calc import failures remain
  task failures, not successful task evidence. Onboarding-only has two bootstrap
  receipts and no target task. All three terminal source trees remain unchanged;
  the positive fixture preserves all six packaged asset bytes.
- [x] Physical03 retained and recreated conversations each independently verify
  two structured criteria with two role-owned exit-zero pytest receipts reporting
  3 passed, no gaps and verified completion. Only AFTER the existing explicit
  public canonical patch apply do the intended FIXED_CANARY core and new metadata
  module change; all other tracked files remain unchanged. The first verifier
  ledger assertion wrongly required post-apply originals to equal HEAD; its failed
  `ledger.py` is retained. `ledger02.py` corrects that source-boundary assertion,
  not production or test gates. No provider calls were made by these gates/reviews.
- [x] Root integrated exact reviewed F bytes atop PR11 as recorded above, retaining
  the stash and all prior physical/driver/asset failures and cleanup evidence.
- [x] Current integrated full/default/static gate `session-current-full-01`
  passed4246/26 with independent exact-identity acceptance. Package refresh,
  final independent artifact review and F GitHub delivery were separately gated;
  G's historical4211/23 does not qualify this candidate.
- [x] (2026-09-12T10:58:46Z) F3 six-asset driver recheck PASS/read release.
  Twelve fresh focused cases passed1.13s;21 actual InspectionService/current final
  oracle controls plus the complete asset/scope gate passed22 probes. All619
  candidate files/ignored inventory/Git state unchanged. All six positive working
  files AND committed HEAD equal packaged assets; all five synthetic-negative
  files remain unchanged. Terminal SHA256
  `9a1739d6af577af5f6fcc2896b5467da075c6183e756d7ac25c9f25366a7e583`;
  only this driver and its plan differ from F2. Root integrated exact driver bytes;
  physical03 and current full gates were then pending, no new provider request.
- [x] F3 root tests retained the synthetic four-command environment failure and
  added the separate actual public learning fixture success path. Typed command
  artifacts, not fictional public principal_role fields, establish role evidence.
  First F3 fixture/profile test used RepositoryCommand.command_id instead of name;
  fixed while preserving profiler. Mypy required a covariant Sequence for the
  outcome oracle. Final focused05 passed10/0.86s,3 physical deselected; configured
  mypy391/Ruff checks passed. Raw failures and source snapshots remain retained in
  session-fixture-repair.ORoJKkl2. Independent first F3 review then found the
  omitted sixth .gitignore; five-asset source/plan and failed report remain intact.
  Only that asset and a complete tracked-asset-set regression were added for the
  successful recheck. No production/gate/dependency/runner/timeout change.
- [x] (2026-09-12T10:17:32Z) Fresh bounded test-driver review passed: eight
  repository regressions plus eleven independent adversarial probes, no Docker
  or provider calls. All619 held files and five production hashes were unchanged.
  Verdict `f2-driver-recheck.b7Qkp1lI/VERDICT.md` SHA256
  `76361d60bdbfcb88f00aedbcf9f39089578680ed46f72ddb9c1ef8b709168ed5`.
  Only the two repaired test drivers and this plan differ from the previous
  production freeze. The first physical failure remains a failure.
- [x] September12 root integrated the eleven reviewed source/test paths into
  the current Foundry tree after PR10 merge `a96eb29`; there was no overlap with
  PR10's changes. Architecture/security docs now describe the restore boundary.
  A separately identified `session-docker-full-02` physical suite finished with
  20 passes and1 failure/231.20s (process233.268089s),21 physical cases,18
  deselected ordinary cases,0 skips/errors. All547 source inputs stayed frozen.
  Retained and recreated conversation variants now pass; the terminal variant
  reaches ready_for_review but verified_complete=false. This remains a failed
  acceptance; separate proof-gap diagnosis followed. Integrated full/default/
  package gates and delivery were then pending; no live request was authorized here.
- [x] (2026-09-12T10:34:59Z) After preserving the complete physical01 terminal
  fixture archive, root used one exact public cancellation. Independent readback
  confirmed cancelled/verified_complete=false, all8 leases released, the exact
  candidate workspace absent and both bootstrap containers absent on the bound
  daemon. Archive SHA256
  `471c26c7b82ea394d5316d1f5d96a8ab6b1c14c0673c9a96e9197836c9b88597`
  retains528 members including32 candidate descendants; archived DB equals its
  pre-cancel hash. Post-cancel immutable DB reads made no sidecars or edits.
  Raw physical01 JUnit/log/source maps remain unchanged; cleanup does not repair
  its failed result. No broad cleanup or provider call occurred.
- [x] September12 root repaired only the two test drivers after independent read
  release. Scripted responses derive their counter from the current invocation's
  ModelResponse history, so retained providers no longer share prior invocation
  state. Terminal exact-ID approval waits for the actual direct grant, excludes
  the just-approved pending ID after resume, and checks the frozen python-build/
  python-test set with all four independent-role receipts and approvals.
  Eight zero-Docker regressions passed/0.11s (5 deselected). Configured mypy
  src/tests/launcher passed391 files; both changed files pass Ruff format/lint
  and whitespace. Five production hashes still exactly match the independent
  offline candidate. Evidence session-driver-repair.sYKcgTIl/focused03.xml.
  Intermediate collection error used a WorkflowStage name as RunStatus; the next
  fixture omitted mandatory canonical_patch (2fail/6pass). Both remain retained;
  no product validator, deadline, production source or old evidence was changed.
  Repaired driver independent review and new physical acceptance were then pending.
- [x] September12 fresh independent offline recheck PASS:233 sandbox contracts,
  17 ownership/recovery cases and22 independent adversarial cases, no skips/errors.
  All candidate bytes unchanged. New1651 raw fixture files retained; this does
  not recover the prior738 deleted files. Evidence session-restore-recheck.u6EWioYi.
- [x] September12 physical full01 FAIL:21 selected Docker cases,19 passed,
  2 failed,10 deselected/336.01s, wrapper338.041403s. All547 source inputs
  unchanged; retain session-docker-full-01. Retained-provider conversation fails
  at a fresh Verifier invocation; recreated-provider case passes. Real terminal
  same-process case waits for a confirmation code after direct exact-ID approval.
- [x] Independent diagnosis reproduced test-model counter leakage across fresh
  invocations (Verifier KeyError; Engineer can omit its pending command), while
  production PydanticAI resets message history per invocation. Exact-ID terminal
  approval returns a grant directly; only implicit-ID review requires confirmation.
  The terminal fixture's frozen Task requires python-build and python-test for
  each of Engineer/Verifier, so its hardcoded two receipts is also incorrect.
  Candidate read release09:56:16.393290Z; no production repair is inferred here.
- [x] Completed bounded test-driver repair under this frozen contract: reopen ONLY
  the two Docker test-driver modules and this plan. Keep all
  five production files and other tests byte-identical. Make scripted model state
  invocation-local (fresh request history), consistent with the existing
  reconstructed-container control. Follow actual exact-ID approval semantics,
  and exclude a just-approved pending ID while waiting after resume. Assert the
  fixture's exact frozen required-command set and both independent role receipts;
  require all reviewed commands, not an arbitrary minimum or omitted build.
  Add bounded zero-Docker regressions for invocation reset and stale pending-ID
  filtering/direct approval orchestration within these owned modules. Preserve
  all existing deadlines, public path, plan review, source non-application,
  final verification and cleanup assertions. Archive pre-repair bytes/failures,
  freeze repaired hashes for review, then run a NEW physical acceptance attempt.
- [x] Resolved by the exact 10:34:59Z cancellation/readback recorded above.
  The initial physical01 terminal failure snapshot had outstanding 2 active parent
  leases/one retained candidate workspace, no native target execution receipts.
  Original terminal owner has exited. Preserve stopped-state failure evidence;
  root first had to inspect exact ownership before normal bounded cancellation.
  No deletion/recovery was done by that initial verifier. The stopped-state
  archive and original failed result remain retained after later cleanup.

- [x] September12 independent review rejects candidate e9acf7bc: absent
  local-unsafe restore calls create after an awaited path validation; a concurrent
  create can install another run's same-ID handle during create's awaited work,
  and restore then overwrites it. The retained synthetic reproducer makes zero
  command calls. Reopen ONLY `adapters/sandbox/local_unsafe.py`, its existing
  contract test and this plan. Separate non-mutating validation from publication
  as needed; absence must be rechecked at the final no-await publication point.
  Preserve the concurrent handle/spec exactly, reject the losing restore, and
  do not delete/recreate/roll back another owner's state. No new authority or
  ordinary execution/recovery change. Add the exact deterministic two-await
  counterexample and focused controls, then freeze new hashes for fresh review.
  Keep the original five-production/six-test snapshot and failure evidence.
- [x] September12: archived byte-exact pre-repair copies of `local_unsafe.py`,
  its contract test and this plan under the private user-cache evidence directory.
  The added second-await regression then failed the old candidate as required
  (`1 failed in 0.09s`) with zero runner calls. Local validation is now separated
  from strict no-await publication; both ordinary create and absent restore reject
  a concurrently installed identity without changing its handle/spec. The full
  local-unsafe contract file passed (`9 passed in 0.03s`), with real JUnit, log and
  command records retained under `session-docker-resume-evidence/local-unsafe-race/`.
- [x] 2026-09-12: independent read-only diagnosis found the exact create/restore
  lifecycle mismatch and the fresh-container-only test gap.
- [x] 2026-09-12: isolated worktree and this contract created before implementation.
- [x] 2026-09-12: writer added the explicit restore port, exact retained/absent
  adapter behavior, ResourceService wiring and focused regressions. Offline
  restore contracts passed 21 cases with 210 deselected; retained and rebuilt
  approval-resume checks passed 2 cases. Ruff and focused mypy passed.
- [x] Fresh independent offline review and physical same-process replay passed
  under the exact separately identified evidence above.
- [x] Current Foundry README, user guide, known issues, ledger and plans distinguish
  independently passed full/static/physical gates from artifact/GitHub delivery.
- [x] Final independent artifact review passed with exact retained evidence above.
- [x] Exact GitHub delivery/readback completed as PR12 above. This completes F's
  bounded delivery, not current D/E gates or all P0/P1 work.

## Discoveries

- September12 README preflight found stale pending-full sentences in README,
  guide, this plan, master plan and ledger. The new numeric/physical block was
  accurate; no code failure or scope change. Retained FAIL report
  f-readme-preflight.za9P7VIo/VERDICT.md SHA256
  b2b5b76e3e7a15e16f15cae86601b4c68c38dbd0489e3e29879433135eccb80e,
  read release12:15:57.560417Z. Root waited for both optional wrappers to stop
  before correcting packaged README/guide. Pre-final-documentation installed
  suite passed3 (415.815736s wrapper), and standalone offline adversarial passed806
  (288.692113s wrapper), both550 unchanged inputs and no errors/skips. Their
  preserved session-current-installed-01/session-current-adversarial-01 records
  remain valid source evidence, not exact final-documentation archive proof.
  A distinct final-doc package/install run follows without deleting old fixtures.
- September12 bounded documentation review rejected the inherited top-level
  external-gates section for unqualified historical L1/L2 and second-Harness
  deferral claims. All new F/G evidence statements passed that review. After
  read release11:49:26.146415Z, root added an explicit historical/superseded
  preface with current LICENSE/README/ledger pointers, preserving old bullets
  and true security/productization limits. No source/test/README bytes changed.
  Original FAIL retained at f-docs-verifier.3TdjR3nY/VERDICT.md SHA256
  9bb7ff17f7f8be2a5138b61fe2534537fb4f8a371375e8b210a1aee2d3965360.
  Exact two-doc recheck passed11 checks and released reads at11:52:15.487540Z;
  removing the two reviewed insertions reconstructs prior hashes. Report
  f-docs-recheck.hBjihApm/VERDICT.md SHA256
  8a7738ca9fa56a5d438c1940686e61a129988e89917172e1cd4212a15d1b6868.
  Current full/package/terminal/delivery gates remain separate.
- Ordinary recovery rejects durable approval pauses; the supported explicit
  operation for abandoning this failed fixture is cancellation. Do not change
  status/ownership to force the interrupted-run recovery path. The original
  failed fixture is archived before any such lifecycle mutation.
- The physical terminal timeout came from wrong API expectations on its first
  explicit-ID approve, not the separately identified stale pending-ID risk.
  Fix both driver assumptions without changing the product permission contract.
- A retained FunctionModel object's mutable per-output counters are not an
  invocation identity; after a pause a new message history needs fresh scripted
  state. Tests must not silently skip commands or read absent tool returns.
- Independent ownership test probes first failed under an unsuitable system-temporary
  parent (gid0 versus process gid20); preserve those failures without calling them
  product regressions. A subsequent user-cache retry was interrupted after seven
  passes and is incomplete. Its verifier deleted738 raw fixture/state artifacts
  without a recovery copy; only manifest/log/JUnit remain. This is an evidence gap,
  not acceptance. No more deletion is permitted. The separate blocking restore
  race reproducer, source, command and log remain intact.
- A successful bootstrap or separate-process approval/resume does not cover a
  retained same-process provider. Reuse and restart need distinct exact semantics.
- Docker restoration must validate the `_prepared` object identity again after
  every daemon/image await. Otherwise concurrent termination or replacement can
  turn a previously valid retained snapshot into a different execution boundary.
- The Docker contract runner's existing post-create info barrier applies to
  command-container creation, not logical sandbox preparation. The first new
  in-flight restore test timed out at that unused barrier; a restore-specific
  info barrier now exercises the intended await and map-change rejection.
- The initial local-unsafe restore validated the path once, observed absence, then
  delegated to `create`, which awaited path validation a second time. That second
  yield separated absence observation from publication. A foreign same-ID create
  could therefore publish first and be silently overwritten. The repair snapshots
  initial map identity, performs one non-mutating validation await, and rechecks
  both maps immediately before a no-await strict publication.

## F3 frozen terminal fixture contract

Root reopens only `tests/docker/test_public_session_onboarding_terminal.py` and
this plan after independent physical02 read release2026-09-12T10:43:36Z.
Physical02 is FAIL20/1, not a passing run: both target python-build commands exit1
because build is missing, and both python-test commands exit2 because canary_calc
cannot be imported. The synthetic bootstrap fixture has a placeholder builtins
backend and no pytest source path. Four exact approvals/receipts and restoration
worked; CompletionGate correctly refused success. All14 leases and four workspaces
were released; six exact native IDs were independently absent. Preserve this run.
The driver also incorrectly expects principal_role in public command_results;
that field lives in typed CommandEvidence, not the public projection.

Preserve onboarding-only. Retain the original synthetic four-command task as an
explicit negative environment journey: exact build/test exit codes, transcripts,
four unique approvals and independently bound role receipts, failed assurance,
COMMAND_EXECUTION_FAILED plus CRITERION_NOT_PASSING, no false completion, unchanged
source and exact cleanup. Add a separate positive journey seeded with all six
actual packaged learning-canary asset bytes before public registration and a Git
baseline commit. Its actual frozen profile must require only python-test, with
two unique approvals and independent real exit-zero role receipts, verified_complete
and no proof gaps. Do not remove checks from the negative fixture to make it pass.

Reconstruct typed CommandEvidence from each public evidence_artifact_id; bind IDs
to the original Run list/public projection before role/command comparisons. Never
add a fictional public field. Both journeys use the same production CLI, profiler,
Gateway, CompletionGate, runner image and original timeouts. No production/runner/
dependency/config/schema change, mock sandbox, host business-test execution or new
provider call. Add offline fixture-byte/profile and exact outcome-oracle negative
regressions; independently freeze/review before a fresh physical03. Physical test
count increases by one; previous failures and raw evidence remain distinct.


## Decision Log

- September12: add explicit restoration rather than weaken duplicate create or
  terminate/recreate retained resources. This preserves the provider boundary and
  makes absent versus conflicting retained state testable.
- September12: keep `restore` responsible only for logical preparation. It never
  catches inspection failure as absence and never creates, starts, removes or
  reconciles a command container. ResourceService retains the existing exact
  paused-run, parent-lease, run/workspace and effective-inspection checks.
- September12: local-unsafe ordinary creation and absent restoration share one
  final `_publish_new` guard. Restoration does not call `create`; a concurrent or
  internally inconsistent handle/spec pair is preserved and the losing restore
  rejects. Explicit unsafe confirmation and unrestricted-host capability checks
  remain in the non-mutating validation phase.

## Outcomes

The delivered F repair restores an exact retained preparation with the same
open Git-shadow pin, or uses strict persisted-ID creation only when the provider
map is absent. Fake and explicit local-unsafe implement the same port without a
fallback. Local-unsafe no longer has an awaited gap between absence validation and
publication, and it preserves a concurrent foreign handle/spec. Focused offline
evidence and a fresh independent offline recheck are green. Physical01 remains
FAIL19/2 for driver protocol/lifetime defects; physical02 remains FAIL20/1 with
terminal verified_complete=false. The separately repaired drivers preserve those
failures and include the real packaged fixture positive control plus the synthetic
negative control; fixture/profile/type/asset failures also remain retained.

Physical03 passed22 cases with22 deselected, no failure/error/skip and547 unchanged
inputs. Independent readback at11:20:08.137149Z confirmed actual same-process
terminal completion, retained/recreated conversation completion followed only by
explicit canonical apply, negative-case refusal, exact original-source boundaries
and the bounded cleanup inventory above. No provider was called. Root integrated
identical F source/test bytes atop PR11 merge5b09fea; the preserved stash and old
evidence remain intact. Historical F integrated full/default/static gates passed4246/26
with4272 exact identities/548 unchanged inputs; current standard Docker passed22,
and a separate after-heavy serial replay passed2/24.66s. Independent full/static/
source terminal readback passed at12:07:04.862044Z; current physical readback
passed at12:07:33.940349Z. Standalone offline adversarial806 and final-doc
distribution1/3.35s and fresh-install3/270.05s passed. Final independent artifact
acceptance passed at12:48:11.175677Z after the exact un-packaged sentence correction.
PR12 delivery completed at12:52:42Z with identical head/merge tree and zero Actions;
postmerge22-contract smoke passed. All prior failures and the738-deleted-fixture
evidence gap remain unchanged. F README/guide and archives retain their frozen
historical identities; later D/E documentation does not update those packages.
These results do not qualify current D/E gates or close all P0/P1 work.
