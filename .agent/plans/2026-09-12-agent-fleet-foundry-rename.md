# Rename and deliver Agent Fleet Foundry

This ExecPlan is a living document. Keep Progress, Discoveries, Decision Log and
Outcomes current as the change is verified and delivered.

## Purpose and user-visible result

The user approved the name Agent Fleet Foundry and requested commit/merge delivery.
The repository becomes `meyowu/agent-fleet-foundry`; the public homepage explains
fork-to-patch usage and links to the relocated development history. Apache-2.0 and
the privacy review from the preceding task ship in the same scoped delivery.

## Scope

### In scope

Public branding, current repository URLs, CLI presentation text, the already
reviewed README/privacy/license files, local validation, repository rename,
ordinary branch push, pull request, merge and authoritative remote readback.

### Out of scope

Uncommitted canary/runtime work in the original checkout, package/import/CLI/state
identifier migrations, provider inference, public visibility changes, destructive
history rewrites, force pushes, branch protection changes and unrelated fixes.

## Current repository state

Fresh origin/main is `3bcf735329d4af312c3fe58f408b3f10f901b29e`. The original
checkout is on `codex/p1-canary-selection-delivery` with unrelated uncommitted
runtime/tests and a continuation plan. This delivery uses a separate worktree and
branch based on origin/main; only the previous task's owned documentation,
license and packaging changes were copied. The repo is currently private.

## Security impact

No permission, sandbox or credential boundary changes. No private-key verification
requests. Use a GitHub noreply author address for new commits and the merge.
Historical personal data remains a separately documented publication blocker.
Repository rename does not authorize making the repository public.

## Proposed design

Use Agent Fleet Foundry in public-facing prose, CLI help/error panels and current
product documents. Use the new repository slug in navigation/clone links. Preserve
historical product names in acceptance records and ADRs. Keep `fleet`, `agent-fleet`,
`agent_fleet`, `.fleet`, schema identifiers, Docker labels/images, generated
configuration and runtime prompts stable to avoid changing persisted bindings.

## Public contracts

Repository URL changes; CLI presentation text changes. CLI arguments, version JSON,
Python distribution/import names, package version, database schema, immutable
configuration/prompt bytes and runtime behavior remain unchanged. Apache-2.0 is
recorded in package metadata and included in wheel/sdist.

## Milestones

1. Isolate owned changes and update public naming.
   Acceptance: unrelated original work stays byte-identical; no unrelated runtime
   changes enter the delivery branch; all current onboarding links use the new URL.
2. Validate the frozen delivery candidate.
   Acceptance: focused CLI/package/security checks, static/schema/lock checks,
   documentation links and a scoped secret scan pass on this branch.
3. Rename and merge.
   Acceptance: repository identity/private visibility preserved; PR merged with
   the checked head; remote main and merge contents read back successfully.

## Detailed implementation steps

1. Update README, current docs, contributor/security pages and CLI branding.
2. Add package project URLs and a compatibility note in release documentation.
3. Clarify that archived unmerged-canary notes are not shipped code; avoid linking
   to documentation that exists only in the other uncommitted worktree.
4. Verify with an isolated pinned environment and frozen candidate manifest.
5. Rename the GitHub repository, update origin, commit/push the scoped branch,
   create and merge the PR with an exact-head guard, and inspect remote results.

## Validation plan

Use offline Ruff format/lint, mypy, schema freshness and lock checks. Run focused
CLI/version/session-presentation, credential-store/redaction and distribution
checks. Rebuild wheel/sdist and check license/README bytes. Validate Markdown
links and Bash/Zsh examples. Scan all intended tracked/new files with
`detect-secrets==1.5.0 --no-verify`; inspect new candidates against prior reviewed
synthetic matches. Compare original checkout hashes before/after delivery.

The preceding Docker exercise is historical evidence; replay it on the isolated
branch if code/source composition differences affect onboarding acceptance.
No live model calls are authorized by this rename.

## Rollback and recovery

Keep original dirty work untouched. A failed remote operation is read back before
retrying. Preserve the delivery branch/worktree and private evidence on failure.
Do not force-push, rewrite history, discard work or relax merge requirements.

## Progress

- [x] 2026-09-12: confirmed owner name/merge authorization and private repo state.
- [x] 2026-09-12: created an isolated branch from fresh origin/main; copied only
  the README/privacy/license task's owned changes.
- [x] 2026-09-12: updated naming, repository URLs, CLI presentation and
  compatibility documentation; local validation passed.
- [x] 2026-09-12: GitHub repository rename completed; private visibility and
  repository identity were preserved.
- [ ] Push PR, merge and read back (use GitHub PR/main as the terminal ledger).

## Discoveries

- The first archive readback accidentally treated uv's generated `.gitignore` as
  a tarball. The collector now selects only wheel/tar.gz files; both actual
  archives passed. The attempted commit had no staged changes; an initial push
  therefore only created a branch at main, and PR creation correctly rejected
  the empty diff. No PR or merge resulted from that failed attempt.

- The original branch contains unrelated uncommitted Canary code. Its new guide
  must not be silently included in a documentation-only delivery.
- Existing user instructions preserve `[skip ci]` to conserve Actions minutes.
  Use that marker for commit and merge; do not claim skipped remote CI passed.

## Decision Log

- 2026-09-12: use the user's latest name Agent Fleet Foundry / agent-fleet-foundry.
- 2026-09-12: keep established package/CLI/state identifiers compatible; rename
  public presentation and repository identity only.
- 2026-09-12: keep the original checkout path stable for ongoing tasks/worktrees.

## Outcomes

The candidate is ready for approved GitHub delivery. Offline pinned setup installed
96 packages. Ruff format (470 files), lint, mypy (390 files), schema freshness,
offline99-package lock and whitespace checks passed. Focused CLI/chat/security/
release-tooling/distribution tests passed127/46.46s; the disjoint onboarding/runtime-
warning group passed48/0.13s, totaling175 tests. Markdown links and Bash/Zsh examples
passed. The 618-file scan found55 already-reviewed candidates and no new secrets.

The exact branch's fake-model real-Docker CLI journey passed two allow-once
approvals/resumes, verified_complete=true, no proof gaps, separate Engineer and
Verifier exit-zero receipts, unchanged source before explicit apply, then successful
application. All12 resource leases were released and fixture worktrees removed.
Model requests were zero. The prepared local runner image was reused.

The GitHub repository rename succeeded with the same repository ID1356788876 and
private visibility. Origin now uses the new URL. The original checkout's source
files remain byte-identical at this checkpoint. The remaining push/merge outcome
must be read from the actual GitHub PR and main ref, not inferred from this
pre-merge candidate record. Runtime/prompt/configuration semantics are unchanged.
