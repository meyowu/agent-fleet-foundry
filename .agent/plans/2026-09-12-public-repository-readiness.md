# Six immutable public-repository static readiness observations

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log
and Outcomes. Written before acquisition or CLI execution. It is a bounded S2
evidence slice, not the S1 campaign, live qualification or a product-code change.

## Purpose and user-visible result

Measure what the existing `fleet readiness /absolute/repository --json` reports
for six real Python/Node projects instead of extrapolating only from generated
fixtures. Preserve unknown environment and unchecked baseline status. A successful
inspection is not a passing upstream test suite or permission to execute it.

## Scope

### In scope

- Acquire exactly six public immutable Git trees listed below into new private
  directories, with no project command, install, submodule, hook or filter run.
- Invoke the delivered public readiness CLI from the trusted Foundry checkout
  with fresh non-existent state paths and a minimal secret-free environment.
- Retain exact identities, tree bytes, command outputs, exit codes, boundedness,
  state non-creation and before/after source equality. Independently read back.
- Publish only concise redacted observations and limitations in this plan and
  repository documentation through a separate normal commit/push/merge.

### Out of scope

No project source edits, dependencies, model/provider/credential access, Docker,
bootstrap, business baseline execution, patch, Verifier, state mutation, package
release or native evaluation write. No additional target hunting, implicit retry,
retrospective sample replacement or claims about a 24-task campaign/cold start.

## Current repository state

Execution checkout is delivered c13a3f679222b5af5a6e6ab6fdf8a2504fdda502.
The concurrent Engineer terminal-contract candidate changes another worktree;
it is not the source of this readiness observation. Existing ReadinessService
and CLI already validate static metadata without executing target commands.
Six generated Python/Node Docker baselines were independently delivered in PR13;
they are distinct from the real public targets selected here.

The bounded metadata investigation examined eight repositories, selecting six
and rejecting two. All six GitHub recursive trees were complete and had no
symlink/submodule entries. That metadata is not execution or safety qualification.

## Security impact

Public source is untrusted data. Use only exact HTTPS GitHub remotes and immutable
commit IDs below, disable global/system Git configuration and hooks, disallow
other transport protocols, recursive submodules and credential prompting. Fetch
only one shallow commit per target, with bounded subprocess time/output; verify
the commit/tree and admitted blob limits before materializing raw admitted blobs.
Do not use checkout/smudge: bind only the private index/HEAD to the verified tree,
then materialize its original regular-file bytes with exclusive creation. Reject
escaping, .git-reserved, duplicate and case/normalization-colliding paths before
writing any target file. Only regular files and
ordinary directories are admitted. No target file is imported or executed on
the host. Set trusted CLI cwd outside the target, use isolated Python and verify
its import origin. Readiness runs with Internet socket connects rejected and
model requests disabled, no inherited credentials or writable state initialization.
Preserve every failed attempt; do not delete acquired repositories or fixtures.

## Proposed design

One private acquisition/measurement runner may orchestrate existing Git and public
CLI commands; it is not a new product framework. A fresh new directory per target
contains its disposable clone and distinct, initially absent state path. Save
all command metadata, exit status and safe output. Compare git object/tree identity,
tracked content hashes and working-tree cleanliness before/after readiness. Do
not treat mere exit0 as environment readiness. No target-local configuration is
created or committed.

Frozen targets (repository, commit, tree, blob count, summed blob bytes):

| Repository | Commit | Tree | Files | Bytes |
| --- | --- | --- | ---: | ---: |
| mahmoud/boltons | 961dcff3f42e73b245aef65e377fe82763b257bb | deecabe09497e038773523eb5124580799c9a3f9 | 113 | 981760 |
| dbader/schedule | 82a43db1b938d8fdf60103bd41f329e06c8d3651 | 113c0a93af441e26f0d7736ff48c5f1e60e03762 | 32 | 166428 |
| pallets/itsdangerous | 672971d66a2ef9f85151e53283113f33d642dabd | ef4287f82d8234404b58c7b29d38197e1f38e207 | 50 | 282547 |
| tj/node-cookie-signature | b7bd4cb9500bfa5e696143f51d61e5f24f7a625d | 3ecd7ab6bc005016965155d9be6bf1766bdecbcd | 8 | 6691 |
| lukeed/clsx | 925494cf31bcd97d3337aacd34e659e80cae7fe2 | 60bc06aea43565e8eeb6ede53cfcc636d8bae11f | 21 | 41998 |
| juliangruber/balanced-match | 1c781ffdd29e5c4840221e6bf1f201ce316de600 | a85b5edca51ad7b3ad8b2db0f6017946615894ba | 16 | 169211 |

Per target maximum:500 blobs,5 MiB summed regular-file bytes,1 MiB per blob;
reject unexpected identities or entry kinds. Network fetch timeout60s; each local
Git/CLI command timeout30s; each captured output at most2 MiB. No automatic second
fetch or CLI run after a failure. An observation may validly return exit1 for an
incomplete static inspection; preserve it, not a rewritten PASS.

## Public contracts

No product interface changes. `environment_status=unverified`,
`baseline_status=not_checked`, `commands_executed=0`, and
`execution_authorized=false` must remain true for every returned report. Discovered
test/build candidates are proposals, not exact upstream CI equivalence or grants.

## Milestones

1. Freeze targets, source identity and read-only acquisition/execution contract.
2. Acquire/verify original trees and observe public CLI exactly once per target.
3. Independent identity/output/state-noncreation/source-preservation readback.
4. Exact documentation, source-unchanged/static check and separate Git delivery.

Acceptance: six frozen observations, honest failures/omissions, no target command
or persistent Fleet state, unchanged originals, independent evidence-linked verdict.
This does not require or imply six successful business baselines.

## Detailed implementation steps

1. Root owns this separate worktree's plan/docs/Git. One bounded evidence worker
   may own only a new private runner, acquired clones and observation outputs.
   It cannot modify either Foundry checkout, access keys or write GitHub.
2. Inspect/admit Git trees before raw blob materialization; snapshot exact original
   tracked bytes. No checkout hook, external filter, attribute conversion or target
   program executes. Private index/HEAD binding is not a GitHub write.
3. Use the trusted root checkout's Python and existing `fleet readiness` command,
   minimal environment and fresh state paths. Record trusted import identity.
4. Freeze evidence and obtain fresh independent readback. Root writes exact results,
   explicit missing-dependency/tooling limits and remaining broader requirements.

## Validation plan

Use actual existing CLI; no mocked readiness service. Record runner hash, exact
argv/env key names, Git object IDs, source maps, reports and exit codes. Validate
returned data through current ReadinessReport schema. Assert no state
directory or .fleet creation, zero executed commands, unchanged target trees, no
model authorization. Check bounded stderr/stdout and all resource processes stopped.
No product code changes means historical product gates remain historical; run
focused existing readiness unit/integration/CLI regressions on the same source
and git diff --check for the docs candidate. Do not call remote CI passed when
[skip ci] causes zero Actions runs.

## Rollback and recovery

No product state or source mutation to roll back. Keep all private acquisitions
and failures, even if incomplete. On identity/time/output/admission failure, stop
that target without materialization or retry as appropriate; record NOT_RUN for any
unstarted CLI. Never use broader cleanup or fetch another revision to obtain PASS.

## Progress

- [x] (2026-09-12 15:07 UTC) Bounded public metadata selection completed; six pins
  and complete regular-blob tree counts frozen. No acquisition/execution yet.
- [x] (2026-09-12 15:14 UTC) Root created a separate docs worktree at c13a3f6 and
  verified isolated trusted CLI import origin before writing this plan.
- [x] (2026-09-12 15:29:29.301520 UTC) Six exact trees acquired and each public
  readiness command executed once. Full original closure frozen:1201 retained
  entries (1180 regular files and21 symlinks), manifest SHA256
  cc52059d5e79bd67075d98fabf09a8164e763d4932914327fddaf1e8c3a8bbc6;
  validated-observations.json SHA256
  34c7cf71949ea7b7911e321764e729ef7d5f837516a0f8c55a10588b1958bb4a.
  Exits1/1/1/1/1/0; all sources unchanged, Fleet/state absent, no project execution.
- [x] Separate authorized regression-only attempt stopped normally:61 passed,
  zero skips/failures/errors, pytest22.993s/process27.410s, exit0 and group absent.
  Exact61 JUnit identities match the first trial; all556 source/README/guide inputs
  unchanged and clean. JUnit SHA256
  bc008610612b7d0b3052dc48992531d539aea94219153442431dcbaefe9c6c8b.
  No original target command/fetch repeated; initial interrupted result remains.
- [x] (2026-09-12 15:42:41 UTC) Fresh independent evidence/document review PASS.
  All1201 original entries and462 new regression entries remained unchanged;
  exact240 original blobs total1648635 bytes. All556 product inputs match c13a3f6;
  all79 recorded original groups plus the new regression group are absent. Exact
  observations, original and new61-case results, three-document scope, four links
  and sensitive-pattern checks passed. Independent VERDICT-final.md SHA256:
  9935fac3f6082eb976e47871648795d69f0a9f5556ad1efac151bae8814a6329.
  The first audit wrongly rejected the exact read-only git --version event's
  cwd=None and exited1; the original script/log remain. A new audit admitted only
  that event and passed, without replaying acquisition, CLI or tests. Final
  postrelease edits only record this actual verdict and Git-pending bookkeeping.
- [ ] Exact documentation commit/push/normal merge and remote readback.

### Pre-release observations and regression scheduling

At15:24 UTC all six exact acquisitions and single public CLI observations had
stopped normally. Observed exits were1/1/1/1/1/0 in frozen table order. A private
postprocessor initially used strict Python-mode ReadinessReport.model_validate on
decoded JSON lists; preserve that harness failure. Validating the same retained
JSON bytes with model_validate_json and JSON Schema succeeded without another CLI
or acquisition. Independent identity/source/state readback remains required.

The separate four-module readiness regression process reached an overly broad
30-second outer local-command watchdog and was stopped as its owned process
group. The worker initially reported no completed JUnit, then corrected that
report before release: retained JUnit records61 passes/25.887s, but the wrapper
observed the process still alive at30s and killed it (exit-9), with no normal
exit0. Preserve both facts and the correction; passing JUnit alone is not a
successful process/cleanup gate. The frozen set contains61 cases. Root's separate
manual scheduling decision at15:25 UTC authorizes exactly one NEW retained
regression attempt with a300-second outer pytest-process watchdog. This does not
change any original test assertion, inner CLI30-second timeout, acquisition or
target CLI contract, and does not authorize another external-project observation.
No fixture deletion or further automatic retry. Record process quiescence before
the new attempt; keep original and new results distinct.

## Discoveries

All three Node targets require development tools beyond Node/npm; boltons has a
pytest-only dev group but its exact upstream tox/installed/doctest lane needs
additional build tooling. Schedule declares coverage/type/timezone tooling;
ItsDangerous needs freezegun and src-layout installation. Do not silently substitute
plain pytest, suppress npm lifecycle hooks or manufacture passing business tests.

## Decision Log

- September12: use real immutable projects for static readiness first. No positive
  execution outcome is preselected; all declared dependency/command gaps remain
  visible. Business baseline or live campaign execution needs a separate contract.
- September12 before acquisition: materialize exact admitted blobs and bind the
  private index/HEAD instead of ordinary checkout. This avoids smudge/hook and
  attribute conversion while preserving original commit identity and content.

## Outcomes

Six real static observations and a normally completed61-case focused regression
passed independent readback; Git delivery remains pending at this record. Five static
inspections are incomplete, one is complete, all six environments remain unverified.
See docs/PUBLIC_REPOSITORY_READINESS.md for exact issues and remaining discovery
coverage. This work cannot qualify native P0 finalization,
24 independent tasks, additional Providers/Harnesses or three real cold starts.
