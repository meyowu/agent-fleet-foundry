# Public README and repository privacy review

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log,
and Outcomes throughout the change.

## Purpose and user-visible result

A new contributor can fork this repository, install Fleet, prepare its Docker
runner, supply a local API key by environment reference, and review/apply a first
patch. The homepage contains the user journey; development and acceptance history
live in separate documentation. A scoped privacy report records findings without
copying credentials or personal identifiers into the report.

## Scope

### In scope

- Rewrite README using the actual CLI and packaged learning fixture.
- Preserve the current README's development evidence in a linked archive.
- Repair documentation links affected by the move.
- Scan publishable working files, reachable Git history and commit metadata for
  credentials, private identifiers, local paths and accidental generated data.
- Remove confirmed personal details from current files; add ignore safeguards.
- Verify the documented offline/Docker journey and package contents.

### Out of scope

Runtime changes, paid provider calls, unrelated continuation work, remote writes,
repository visibility changes and destructive Git history rewrites. The owner selected Apache-2.0 during this task; include the license in source
and package metadata.

## Current repository state

HEAD is `3bcf735`; the working tree already contains live-canary development and
README/plan updates. The original README is 1,047 lines. Preserve all existing
work. A private audit directory outside the checkout contains baseline hashes,
a README copy and the initial diff. Public initialization requires a committed Git
fixture, disjoint Fleet state and real local Docker bootstrap; the bootstrap uses
a deterministic model and does not require provider inference.

## Security impact

No authorization, sandbox, credential-flow or schema changes. Keep API key values
out of argv, files, logs and worker containers (SECURITY_MODEL section 12).
Scanners must not contact credential providers to validate possible secrets.
Current-file sanitization cannot remove prior Git objects or commit identities.
Never claim absolute absence of secrets from heuristic scanning.

## Proposed design

README presents a small packaged exercise before explaining use on another repo.
Use one activated virtualenv so `fleet` still resolves after changing directories.
Use a hidden terminal prompt to set the key. Preserve historical evidence with
correct relative links in docs/DEVELOPMENT_HISTORY.md, clearly marked as a snapshot.
A dedicated public privacy report contains counts, locations, remediation and
limits. Add targeted ignore patterns without hiding versionable `.fleet/` config.

## Public contracts

No CLI, schema, persistence or runtime contracts change. Documentation links and
ignore rules change. Apache-2.0 is added with explicit owner authorization.

## Milestones

1. Inventory the CLI, source, existing changes and privacy surfaces.
   Acceptance: archive source captured; scan scope and limitations recorded.
2. Rewrite and sanitize documentation; add ignore rules.
   Acceptance: complete fork-to-patch steps; no progress tables on homepage.
3. Validate and report.
   Acceptance: links resolve; package check and focused security checks pass;
   a disposable real-Docker exercise reaches reviewed evidence and patch apply.

## Detailed implementation steps

1. Copy current README to docs/DEVELOPMENT_HISTORY.md and rebase relative links.
2. Write README with prerequisites, fork/install, runner, exercise, BYOK,
   initialization, approvals, review/apply, troubleshooting and documentation links.
3. Inspect scanner findings without exposing values; sanitize confirmed current
   file identifiers and protect common local secret/state paths in .gitignore.
4. Update guide/status references to the relocated history.
5. Run documented commands on a fresh non-sensitive fixture and audit final files.

## Validation plan

- `uvx --from detect-secrets==1.5.0 detect-secrets scan --no-verify` on publishable
  files and materialized unique blobs from all locally reachable Git refs.
- Local regex review of paths, identities, commit metadata and sensitive filenames.
- README relative-link/heading checks and `.gitignore` representative checks.
- CLI help/preview/doctor, fake-model real-Docker bootstrap, permissions, resume,
  status, patch review and apply in a disposable fixture.
- Focused credential/redaction tests; current README/guide distribution check.
- `git diff --check` and baseline hash reconciliation for unrelated files.

## Rollback and recovery

Restore only task-owned documentation changes from the private baseline if needed.
Preserve existing user work. Keep failed run evidence; use exact resource recovery
if needed. Do not delete state, rewrite history, rotate keys or publish implicitly.

## Progress

- [x] 2026-09-12: inventoried repository and preserved current changes privately.
- [x] 2026-09-12: verified runner image exists and read actual install/BYOK contracts.
- [x] 2026-09-12: rewrote README, preserved history, corrected guide links,
  sanitized current machine paths and added Apache-2.0 plus ignore safeguards.
- [x] 2026-09-12: completed current/history credential and identity scans.
- [x] 2026-09-12: separate-process CLI journey reached verified completion,
  retained unchanged source before apply, then applied the exact patch.
- [x] 2026-09-12: final archive check passed1/7.77s; final privacy, links,
  whitespace and baseline-preservation readback passed.

## Discoveries

- A private initial check incorrectly expected no state database after `doctor`.
  Doctor had already created it; the corrected preview check compares before/after
  state bytes and proves preview adds no writes. Initialization then passed.
- Scanning an absolute external history directory from the repo returned zero
  candidates; scanning from the extraction directory recovered the expected test
  matches. The initial zero was rejected, not accepted as clean-history evidence.

- LICENSE was initially absent. The owner explicitly selected Apache-2.0.
- Existing guide links point to old or absent README status anchors.
- The ignore file lacks environment/credential/local-state protections.

## Decision Log

- 2026-09-12: preserve the whole current README snapshot instead of dropping or
  summarizing away uncommitted acceptance evidence.
- 2026-09-12: verify onboarding with deterministic models and real Docker; do not
  infer renewed paid-model authorization from historical plans.

## Outcomes

README reduces the 1,047-line homepage to 304 lines with eight onboarding steps. The old
homepage is preserved with rebased links; guide/status references now resolve.
Apache-2.0 is owner-authorized and present in the source, wheel/sdist and metadata.
The nine pre-existing continuation code/test/plan files are unchanged from the
initial working snapshot. Thirteen existing documentation/configuration files
were updated; the untracked canary-selection guide only changes its history link.

- `uv sync --frozen --offline --all-extras --python 3.14` in a new dedicated
  virtualenv installed 96 packages; it reused the pinned dependency cache.
- Ruff format (470 files), Ruff lint, offline lock validation and diff whitespace
  passed. Twelve ignore-rule probes passed; current documentation links/anchors
  and Bash/Zsh quickstart syntax passed.
- Focused credential-store/redaction/release-tooling/distribution checks:
  `49 passed in 9.92s`; after replacing the Session guide with the validated
  CLI route, the final distribution check passed1/7.77s.
- `uv build --offline` produced wheel and sdist; exact README and Apache-2.0
  license bytes plus License-Expression/License-File metadata were checked.
- Initial/final working scans each yielded 55 reviewed synthetic/prose/hash
  candidates, with no newly introduced credential candidate. All 49 local-ref
  commits and 1,230 unique blobs were inspected: corrected history scan found
  137 occurrences of the same 55 candidate lines; strict-format supplement found
  one explicitly synthetic launcher fixture. No real credential was identified.
- Four current personal path lines were sanitized. Seven historical blobs and
  Git author/committer metadata still disclose personal data. Publication of the
  existing history is not privacy-cleared; see PUBLICATION_PRIVACY_REVIEW.md.

The same-process Session journey failed at the second resume with
SANDBOX_CREATION_FAILED. The original process exited; exact public recovery marked
the run failed, recovered two leases and returned zero outstanding leases. Evidence
is retained, and KNOWN_ISSUES.md documents the reproduction. README now uses separate
CLI processes for every approval/resume. The complete replacement journey passed:
two exact allow-once approvals and two resumes, ready_for_review with
verified_complete=true, no proof gaps, separate Engineer/Verifier Docker exit-zero
pytest receipts, unchanged target source before explicit apply, then successful
patch application. All resource leases from both fixture states are terminal.
The budget records zero model requests. Runner image v1 was reused from the local
cache; this is not a fresh-image build or live-provider qualification. A separate
PydanticAI/OpenAI preview passed with an unset selected credential reference and
no state writes, establishing the documented preview contract only.
No paid model calls, remote writes, history rewrite or visibility changes occurred.
