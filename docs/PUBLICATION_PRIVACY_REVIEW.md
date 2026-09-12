# Publication privacy review

Review date: 2026-09-12. Base commit: `3bcf735`; this review also includes the
working files present during the documentation change. This is a source-disclosure
review, not a penetration test, dependency vulnerability audit or release verdict.

## Result

**No real API key, private key or password was identified by the scans and manual
triage described below. The existing Git history still contains personal data.**
The current working tree's confirmed personal machine paths have been sanitized.
Publishing the repository with its existing history would still expose old paths
and author/committer identities. A clean current-file scan cannot certify that
publishing the entire repository history is privacy-safe.

## Scope and method

- Scanned tracked and non-ignored untracked working files, including the existing
  uncommitted development changes. The initial inventory contained 615 files; the final inventory contained 619.
- Enumerated all locally reachable refs with `git rev-list --objects --all`:
  **49 commits and 1,230 unique file blobs**. Materialized blobs in a private
  directory outside the checkout and scanned from that directory.
- Used `detect-secrets` **1.5.0**, all default detector plugins, and `--no-verify`.
  Possible credentials were never tested against provider endpoints. Raw scanner
  baselines and extracted history remain outside the repository.
- Supplemented the detector with explicit OpenAI, Google, GitHub, AWS and private-key
  format searches; inspected email, local-user path and sensitive-filename matches.
- Inspected author/committer identities and commit messages separately. Checked
  source email matches against synthetic fixtures and public protocol examples.
- Checked archive contents and preservation of unrelated working changes.

The first history scan used an absolute external directory from the repository
working directory and returned no findings. That result was rejected as incomplete.
Rerunning from the extracted-history directory recovered the expected fixture
matches below. Only the corrected scan is used for this review.

## Findings and remediation

| Finding | Evidence and disposition |
| --- | --- |
| Credential-detector matches | Initial working tree: 55 candidates. Reachable history: 137 occurrences across 74 blob files, representing the same 55 distinct candidate lines. Reviewed matches are synthetic test credentials, example basic-auth URLs, hashes, or prose about secret-handling tests. No real credential was identified. |
| Additional provider-key format match | One historical synthetic launcher sentinel with an OpenAI-like prefix. Its source labels it as an offline test credential. It is not a supplied provider key. |
| Real machine paths in current documentation | Four lines in `.agent/plans/2026-09-04-phase-3-docker-sandbox.md` exposed a local username/home path and local acceptance location. Replaced the home component with `<local-user-home>`, preserving the historical observations. |
| Machine paths retained in history | Seven historical blobs across the phase-3 plan, `.agent/plans/2026-09-05-release-candidate.md`, and `docs/MVP_ACCEPTANCE.md` retain personal paths. They are still reachable through existing commits. A separate path in `tests/unit/test_runtime_models.py` is a synthetic negative-test example. |
| Git identity disclosure | Four distinct author/committer email values occur in the local history, including a personal mailbox and host-associated identities. Names and addresses are intentionally not reproduced here. Existing commits were not rewritten. |
| Accidental credential/state files | No tracked/reachable-history files with the inspected environment, private-key, credential-dump, SQLite or archive filename patterns were found. No tracked symlinks were found. This does not imply ignored local files are safe to upload. |
| Missing ignore safeguards | Added patterns for local environment files, common key/credential files and local Fleet database/state paths. Sanitized `.env.example`/`.env.sample`/`.env.template` remain possible; `.fleet/` project configuration remains versionable. Ignore rules do not sanitize already-tracked content. |
| Package license | The owner explicitly selected Apache-2.0. Added the canonical license and package license metadata. This resolves the license choice, not the remaining release or history-disclosure decisions. |

## Publishing without the historical personal data

Before changing repository visibility, choose one of these approaches:

1. **Publish a reviewed source snapshot with a new Git history.** Include only
   intended source/documentation files, including this task's reviewed changes.
   Do not copy `.git`, ignored local output, environments, state, caches, private
   audit reports or distribution build directories. Use a public-safe Git identity
   for the initial commit and scan the resulting repository again.
2. **Retain history and sanitize it deliberately.** Back up the repository, review
   an exact path/identity replacement map, rewrite every affected publishable ref
   in a separate copy, and rescan it. Rewriting changes commit IDs and requires
   coordination before replacing a remote's history. Hosting-provider caches,
   old pull-request refs and other clones may require separate handling.

No history rewrite, force push, remote deletion, visibility change or publication
was performed by this review. Changing Git's current `user.email`, adding an
ignore rule, or deleting a current file does not change old commits. If a genuine
credential is discovered later, revoke/rotate it as well as removing the content.

## Repeat the working-tree scan before publishing

Run from the repository root. Install the scanner from its package registry if it
is not cached. Keep the output outside the repository; this command does not verify
candidate credentials online:

```bash
umask 077
fleet_scan_report=$(mktemp)
uvx --from detect-secrets==1.5.0 detect-secrets scan --no-verify > "$fleet_scan_report"
```

The default scan covers tracked files. Also scan the exact files you plan to add,
review staged diffs, and review matches rather than treating every hit as a real
key or adding a broad test-file allowlist. Repeat the history scan on the actual
refs being published. Test fixtures intentionally exercise redaction with fake
secret-shaped strings and must remain part of the review.

## Limits

The scan covers the local refs and current publishable file inventory available
at review time. It does not inspect private local state outside the repository,
ignored environments/caches, unreachable or reflog-only objects, Git LFS payloads,
other clones, remote-only refs, GitHub issues/PR conversations, Actions logs,
release attachments or provider-retained data. Those surfaces need their own
review before being copied or made public. No network fetch was used to expand
the Git ref inventory.

Pattern/entropy scanning and manual review can miss unknown, fragmented or encoded
secrets and sensitive business content. The scoped conclusion is **no real
credential identified**, not an absolute guarantee of no private information.

## Rename delivery follow-up

The Agent Fleet Foundry rename is delivered from an isolated branch based on
`3bcf735`, excluding the original checkout's uncommitted Canary implementation.
The delivery inventory has 618 files. Its secret scan returned the same 55
previously reviewed synthetic/prose/hash candidates, with no newly introduced
candidate or known personal-identifier match. The original history findings above
remain unresolved. The GitHub repository name changes; private visibility stays
unchanged. New delivery commits use a GitHub noreply author address.
