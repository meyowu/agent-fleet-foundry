# Deliver the verified S1–S3 foundations to GitHub

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log and Outcomes.

## Purpose and user-visible result

The owner now explicitly requests merging this development round to GitHub and
reporting completed progress and unfinished work. Deliver the verified foundation
through existing PR7, with small reviewable commits and authoritative remote
readback. This supersedes the prior stop only for delivery and its verification;
it does not reopen feature implementation, paid testing or the entire S1–S3 goal.

## Scope

In scope: preserve and commit the accepted Session11 and read-scope10 slices,
their documentation, fresh local static/package checks, push, PR update and merge,
and final delivery/result documentation. No implementation changes are planned.

Out of scope: new provider calls, Docker runs, dependency updates, new feature
work, automatic campaigns, license/package release, workflow or protection edits,
and treating unfinished OKRs as completed. Do not copy private evidence or keys
into tracked files. Keep all old failures under their original identities.

## Current repository state

Initial snapshot: branch `codex/s1-s3-verified-foundations` and PR7 head were `2eb44d8`;
main is `3fb0971`. There are sixteen existing foundation commits and thirty
accepted dirty/untracked paths. The index is empty. Live GitHub readback finds
PR7 OPEN/draft/MERGEABLE/CLEAN, no required checks on main, and zero Actions runs
for this branch. Recheck immediately before merge rather than relying on this snapshot.

The exact source/test/script/dependency closure is546 inputs, SHA256
`61e79cba174cd05a8ba019c53ec815b6c39800fea394041e89e066e4132d4a10`.
Fresh per-file comparison against the accepted freeze passes. Thus the existing
full4093-pass/23-skip matrix, Docker29, installed3 and actual live1/77.00s records
apply to this code, not to a reconstructed or changed candidate. The full matrix
has4116 unique identities and no omissions/duplicates/failures. Existing independent
live audit `a9681755` confirms the strict verdict, accounting and exact cleanup.

## Security impact

GitHub writes are now explicitly authorized for this repository and PR. Use normal
non-force push and merge commits, preserve branch history, and pin merge to the
observed head. Do not bypass branch protection or manufacture remote check results.
All new commit and merge messages use `[skip ci]` because Actions minutes are
exhausted. Existing workflow triggers are push/main, pull_request/main and manual;
do not dispatch workflows. Read back actual Actions state after delivery.

## Proposed design and public contracts

No runtime, schema, permission, model, storage or public command contract changes.
Split accepted changes into Session, read-scope, and documentation commits. Package
checks use the existing offline distribution test, existing locked dependencies and
fresh private output directories, without provider/Docker opt-ins. Final GitHub
and local main trees must agree. If main advances, inspect before reconciling.

## Milestones and detailed implementation steps

1. Reconcile exact source/evidence, scope and current PR/protection/workflow state.
2. Inspect accepted production diffs; update delivery scope in README and this plan.
3. Re-run static checks and offline wheel/sdist resource test without changing code.
4. Commit exact Session11 and read-scope10 path groups, then documentation; push.
5. Replace stale PR failure/draft-only description with actual current evidence and
   explicit remaining limitations, mark ready, merge with an exact-head guard.
6. Read back PR merge commit, main/ref/tree and Actions; fast-forward local main.
   Record final delivery status, commit/push that result documentation if needed,
   then report completion of delivery only and stop.

## Validation plan

Fresh local commands (expanded original output retained in private
`agent-fleet-github-merge.EdvRQ0`):

```text
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src tests scripts/run_live_canary.py
.venv/bin/python -B -m agent_fleet.schemas.generate --check
uv lock --check --offline --python .venv/bin/python
git diff --check
.venv/bin/python -B -m pytest -p pytest_asyncio.plugin -q tests/integration/test_distribution.py
```

The package invocation disables plugin autoload/live/Docker/install opt-ins and
uses explicit private basetemp/JUnit/cache paths and offline uv. It builds wheel
and sdist, compares packaged source/README/guide, and smoke-tests the wheel with
existing dependencies; it is not another fresh dependency installation.
Do not rerun the expensive unchanged full suite or paid canary merely to change
Git metadata. Revalidate the exact546-file closure before pushing and after merge.

## Rollback and recovery

Preserve all uncommitted work and existing refs. Use no resets, force-pushes,
branch deletions or cleanup of prior evidence. A failed push/merge with uncertain
response requires remote readback before retry. Required checks/conflicts block
merge; do not disable protection. If new source appears, stop this delivery scope
and reassess its acceptance rather than reusing the old freeze.

## Progress

- [x] Current source freeze, clean index, accepted live/full evidence and remote
  PR/main/Actions state read back before mutation.
- [x] Owner's new delivery authorization recorded; broad S1–S3 completion remains false.
- [x] Fresh static checks passed: Ruff format reports463 files, lint passes,
  mypy390 files passes, schema check passes, offline lock99 packages/21ms and
  whitespace check passes. Original package parent61982 exited0 with1 passed/2.53s.
  It checked the current README/guide, wheel/sdist resources and installed-wheel
  smoke using existing dependencies. Exact commands and original terminal results
  are retained in private `premerge-checks.json`. Source count546 and every frozen
  file hash remain equal; repository key-pattern scan reports no match (exit1).
- [x] Exact reviewed commits created: Session `ecb668b` (11 source/test files,
  its plan and ADR) and read-scope `e522c93` (10 source/test files and its plan).
  Index membership matched each declared set before commit; staged whitespace
  checks passed. No production source was edited during delivery.
- [x] Documentation `ccf1f288386b6505aeae72091ab0fc180efda0d1` committed;
  normal branch push original parent67709 exited0. Remote PR head readback
  matched exactly, with unchanged main3fb0971. PR title/body updated to current
  accepted evidence and remaining limitations, then marked ready.
- [x] Exact-head merge exited0; GitHub reports PR7 MERGED at2026-09-10 04:03:03UTC,
  merge `cea291098780f39e9d985cea0b77a5687f7fda3f`. Remote main and local
  fast-forwarded main match that commit; merge and accepted head trees are both
  `ca7e54cfc84c9e3e5dd40d601b1008e9dec891a3`. All546 frozen source hashes still
  match. Exact head and merge Actions queries returned total_count0/runs[].
- [x] Final README and parent-plan merge/status wording updated. Post-merge
  existing distribution test exited0 (original result e0be9a):1 passed/2.57s,
  checking the actual final README, wheel/sdist and installed-wheel smoke.
  Same cleared/offline environment and opt-ins as pre-merge; new private paths
  are `postmerge-fixtures`, `postmerge.xml` and `postmerge-cache` under the
  existing delivery evidence directory. No expensive or paid gate was repeated.
  Whitespace and all546 frozen source hashes passed afterward. This plan is
  outside the package and its result-only update does not change checked archives.
  The result-only documentation commit is delivered separately on main; its exact
  remote ref/tree and Actions state must be read back before the final user handoff.

## Discoveries

- Initially PR7 described the predecessor30b8 live failure and excluded Session/read-scope.
  Its draft-only gate was based on older scope; the owner explicitly requested
  merging the currently verified foundation while reporting unfinished OKRs.
  The updated PR now records the actual accepted current-source live canary.
- The current paid canary passed, but only tests zero division. Other providers,
  mixed Harnesses, cold starts and campaign outcomes remain separately unverified.

## Decision Log

- Deliver the verified foundation without claiming completion of every S1–S3 KR.
- Reuse full-suite evidence only after exact source identity comparison; rerun
  static/package checks because result documentation has changed.
- Preserve `[skip ci]`, existing workflow/protection settings and all failure history.

## Outcomes

PR7 is merged and the GitHub/local tree identity is verified above. Final result
documentation's post-merge distribution check passed1/2.57s; no source or dependency was changed
and no new provider/Docker execution occurred during delivery. All new Git
messages retain `[skip ci]`; no workflow dispatch, protection bypass, force push
or branch deletion was used. The original-DB outcome writer remains NOT_GO;
Provider/Harness campaigns, broader Session/coldstart, Dashboard expansion,
connectors and project Memory/evolution are not completed by this delivery.
