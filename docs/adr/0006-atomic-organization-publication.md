# ADR 0006: whole-tree organization versions and exact publication recovery

Status: accepted at the Phase 6 local macOS/Colima boundary on 2026-09-05; Linux and public-release gates remain separate.

## Context

Repository organization files are untrusted guidance and declarations. A user must be able to review a CoS proposal, explicitly apply it and undo the current change without silently changing permissions or losing unrelated configuration. The existing referenced-file ConfigSnapshot does not include README, unreferenced notes, modes or empty directories. A collection of atomic per-file writes is not an atomic organization version. Old Run admission must not become valid again when rollback repeats a prior configuration hash.

## Decision

Keep `.fleet/fleet.yaml`, credentials, trust, grants, sandbox ceilings, role registration and audit controls protected. Reuse the FleetPatch file-change wire contract. Typed `WorkflowDefinition` and `VerificationSkill` declarations may require existing canonical verification commands for overlapping code paths; they cannot grant execution. A CoS receives bounded visible configuration and trusted proposal/project/base identities. Its only additional tool computes a SHA-256 of supplied text without I/O or side effects. Models can persist a validated proposal through normal workflow output but have no publication tool.

Use a complete bounded `OrganizationTree` separately from the logical ConfigSnapshot. Persist exact original/proposed trees, immutable proposals, derived semantic/text diffs, versions and operation receipts in SQLite migration `0008`. A monotonic revision and full-tree hash bind each admitted Run in a separate table, preserving old Run/Project/claim wire hashes. Rollback is a new inverse proposal and version; only the current applied proposal can be rolled back. Original Run evidence remains immutable and cannot authorize code application under a later generation, even after an identical-byte rollback.

Hold an advisory descriptor-backed repository lock outside the repository, keyed by its canonical root across separate state clients. Stage privately in a same-filesystem sibling. Capture/revalidate canonical path identities, content, ownership, modes and supported metadata. Use `renameatx_np(RENAME_SWAP)` on macOS or libc `renameat2(RENAME_EXCHANGE)` on Linux for one complete directory exchange. There is no multi-file, symlink-pointer or host-execution fallback. Before exchange, durably prepare complete tree bytes, exact pinned directory identities, a pending project fence and the Git boundary. Recheck source status, index entries/flags and HEAD; publication never modifies the user index or source. Flush staged files/directories and exchanged parents, with full file synchronization on supported macOS filesystems. SQLite uses WAL and verified FULL synchronization, plus macOS fullfsync settings.

After observing the exact exchanged tree, validate the logical snapshot, create/read back its artifact and atomically commit Project rebinding, the version/audit record and fence removal. Project may change only its reviewed snapshot/hash, exact organization dirty-status allowance and update time. New ordinary/chat/graph Run registration checks admission in the same transaction as insertion. Reinitialization of a headed Project and stale code-patch application are rejected. Active/paused/applying Runs, unresolved descendant leases and unreconciled conversation/graph owners block publication. Owners never expire into takeover authority.

## Failure and recovery

- Before preparation: only positively known owned scratch can be cleaned, with exact manifest/identity checks. If staging failed before returning a receipt, preserve private unrecorded scratch for manual inspection; do not fabricate journal recovery.
- After durable preparation: any ambiguous exchange, flush or commit retains the fence and receipt. Never reverse the exchange automatically.
- `recover <operation-id> --owner-stopped` acquires the same lock. Exact original orientation can abort; exact exchanged orientation repeats durability synchronization and commits, **without another exchange**. Unexpected user edits, identities or state remain untouched and fenced.
- A committed/aborted operation and its cleanup are separate outcomes. Partial cleanup may resume only when every surviving backup entry matches the immutable expected manifest. Unknown entries stop deletion. `cleanup_complete` is true/false/null for observed complete/gap/not inspected. A committed apply repeat returns the original version, even after later history, without asserting cleanup.
- Current-head rollback restores historical content, modes, supported attributes and empty directories through a new operation. It does not erase audit history or revive stale work.

## Alternatives considered

Per-file writes expose mixed versions; pointer/symlink publication weakens the real-directory boundary; replacing protected FleetSpec permits authority changes; replaying a prior version number revives stale tasks; automatic timeout takeover or reverse rename guesses about uncertain effects. All were rejected. A separate trusted supervisor or transactional filesystem could strengthen ownership/durability but adds unsupported platform infrastructure.

## Consequences and limits

Publication requires local macOS or Linux atomic-exchange support, a writable same-filesystem parent, same-user/group safe entries, UTF-8 regular files (no hardlinks/symlinks), file modes `0600`/`0644` and directory modes `0700`/`0755`. Complete trees are bounded to 256 files, 256 directories, depth 16, 512 KiB per file and 4 MiB aggregate content. Supported opaque `com.apple.provenance` metadata is retained exactly, at most 4096 decoded bytes per entry; other attributes, ACLs and flags fail closed. New entries inherit the recorded root's supported metadata with fixed `0600`/`0700` modes. Unreproducible metadata fails before exchange; Fleet never normalizes the original tree to make staging succeed.

This is a local process-crash protocol, not tamper-proof audit, an adversarial same-user lock, remote-filesystem support or proof that hardware honors cache flushes. Read-only views are not proof of cleanup. Historical duplicate chat submissions return the original validated turn without provider calls, current-generation admission or budget/owner mutations. Public release/platform/live-provider claims remain separately gated.

## Evidence surface

`tests/unit/test_organization_tree.py`, `test_fleet_patch.py`, `test_verification_skills.py` and `test_proposal_tools.py` cover bounded pure contracts. Organization publication, journal, admission and repository contract tests cover native identities, durable state, flags and races. Integration proposal/interface/recovery tests exercise the joint native-filesystem/SQLite lifecycle and failure cut points. `tests/e2e/test_fleet_evolution_cli.py` uses actual fresh CLI processes and abrupt publisher exits. `tests/docker/test_fleet_evolution_journey.py` proves the applied requirement changes both Engineer and independent Verifier command evidence through real Docker, followed by code apply and exact organization rollback. Exact results and remaining gates live in `MVP_ACCEPTANCE.md` and the Phase 6 ExecPlan.
