# Data handling and provider disclosure

Local-first means the control plane and durable state run locally. It does **not**
mean a BYOK model sees no source code or that Docker protects against its host.

| Data | Location / destination | Boundary |
| --- | --- | --- |
| FleetSpec, role/workflow guidance, knowledge, verification skills | Project `.fleet/` | Untrusted declarations; complete versions are bound and reviewed. No keys or trust grants. |
| Projects, Runs, tasks, approvals, grants, leases, budgets, chat ownership, FleetPatch versions and events | User-owned `<state>/state.db` with SQLite WAL | Durable local audit/state, not signed or tamper-proof against its owner. |
| Patch, transcript, inspection, verdict, summaries, proposals and configuration/tree snapshots | `<state>/artifacts/` plus hash-linked SQLite metadata | Can contain sensitive code, command output and project descriptions. Treat the entire state as confidential. |
| User trust settings, precise persistent rules and recovery backups | `<state>/trust/` | Outside repository; model guidance cannot grant permission. Revocation retains history. |
| Credential reference (`env:NAME`) | User-command registration in local Project/Run state | An identifier, not the value; not a repository FleetSpec setting. |
| Resolved API key | Control-plane process memory and explicit provider Authorization header | Never mounted into a worker or intentionally persisted in prompts, logs, events or artifacts. Same-user/host inspection is outside the threat model. |
| Provider input | Explicit supported model endpoint over control-plane HTTPS | Bounded task/role guidance, selected source/artifact excerpts, summaries, tool results and requested structured output. Provider privacy/retention terms apply independently. |
| Worker files / output | Exact candidate/verifier worktree bind and bounded command artifacts | No home, Docker socket or credential-directory mount; networking disabled. Host kernel/daemon remain trusted. |

The runtime supports the explicitly wired OpenAI Responses and Chat Completions
families; it pins the supported endpoint, disables redirects/retries and ambient
proxy/endpoint/identity overrides, and validates requests. It is not a generic
arbitrary OpenAI-compatible endpoint relay. Ordinary tests deny provider requests.

Registered credentials and their supported encoded representations are redacted
or rejected at defined boundaries. This is not general secret discovery: an
unknown credential pasted into source or user text may be ordinary data until
registered. Do not paste passwords into goals or commit keys to a repository.
Low-level third-party/OS debugging, crash dumps and hostile same-user programs are
not made safe by application redaction. Use disposable least-privilege model keys
and normal secure environment handling; do not put values in CLI arguments.

By default Fleet records structured local events and bounded usage/evidence, not
complete raw provider conversation history. Durable CoS context uses bounded
summaries and validated artifact references; it is not full provider-history
restoration. Token/cost observations may be estimated or unknown. No mandatory
hosted telemetry/exporter exists; optional OpenTelemetry instrumentation is
deliberately deferred. Dependency packages alone do not imply telemetry export.

## Retention, backup and deletion

There is no automatic retention TTL, cloud sync, purge command or complete audit
export API. Inspect with `status`, `logs`, `artifacts`, `patch show` and organization
commands. Artifacts, trust revisions, consumed approvals and old organization
versions remain until the operator manages the local state. Published-history
rollback adds a new version; it does not erase previous evidence.

Before backup, stop the exact owner processes and resolve or preserve outstanding
workspaces, leases and publication scratch. Back up the complete selected state,
repository/Git boundary, `.fleet/` and any pending publication receipt/scratch as a
coherent set. A copied SQLite file while WAL writers run is not necessarily a
consistent backup; use a stopped state or SQLite's backup facility. Retain the
same local runner image IDs needed by paused work. Never downgrade a database or
edit hashes to bypass an upgrade/recovery refusal.

For removal, first inspect/cancel/recover exact owned resources. Confirm exact
paths and keep a recoverable backup before removing only that project's selected
state. Never recursively delete a home, cache root, repository root or another
installation to "reset" Fleet. Deleting state destroys approval and organization
history and may strand resources; moving `.fleet/` aside does not reset an existing
head. Provider-retained data and external backups require their own deletion
process; local deletion makes no claim about them.
