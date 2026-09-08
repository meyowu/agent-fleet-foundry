# Release-candidate procedure

An implemented local MVP, a GitHub merge, a live-provider pass and a public OSS
release are different outcomes. Current exact results live in `MVP_ACCEPTANCE.md`
and the living release ExecPlan. Package version0.1.0 is not evidence of a published
PyPI package or tag. No license has been selected by the agent and repository
visibility must not change implicitly. Public release remains blocked until the
owner license and explicitly authorized real-provider canary gates are resolved.

## Candidate preparation

Read AGENTS/specs and maintain the ExecPlan. Freeze source, tests, assets, build
configuration and lock before full acceptance. Record the commit/tree and a sorted
source/test content manifest. Documentation changes affecting archive content need
a final archive/fresh-install refresh after editing; do not label prior bytes final.

```bash
uv lock --check
uv sync --all-extras --frozen
uv run --offline ruff format --check .
uv run --offline ruff check .
uv run --offline mypy src tests
uv run --offline python -m agent_fleet.schemas.generate --check
uv run --offline pytest -q --durations=15
uv build --offline
git diff --check
```

The default suite includes units, contracts, SQLite/CLI/workflow integration and
fresh-process offline E2E. Report partitions as partitions, not extra test totals.
Actual Docker, installed-distribution and live-provider cases are separate explicit
opt-ins; a default skip is not their acceptance. The standalone adversarial script
and full Docker suite must run and leave exact-scope cleanup evidence.

## Fresh installation and documented journey

Use the dependency preparation script and environment variables documented in the
user guide; preserve its lock/interpreter/wheel manifest. Execute both wheel and
sdist in fresh isolated environments, outside the source tree, with empty install
caches and offline no-index runtime/build constraints. Verify installed package
paths, declared versions, all schemas/migrations/prompts/runner/guide resources,
read-only preview and honest fake failure. Test-only legacy seeding is not a public
bootstrap shortcut. Separately run the installed public learning project's real
Docker init, doctor, Safe/src policy, chat/approvals, duplicate submission read-back,
artifact/status inspection, independent test evidence, explicit code apply, exact
trust-rule revocation and confirmed no-op recovery. A separate installed public
registration may substitute only deterministic offline FunctionModel responses to
exercise CoS proposal/diff/apply/rollback through the installed CLI. Do not inject
stored proposals or represent this test fixture as a stock fake/live-provider feature.

## Platform and operational matrix

CI uses pinned read-only actions, disabled checkout credential persistence, frozen
dependency setup and no live key. Six jobs cover Linux/macOS with Python3.12–3.14:
unit/contracts, all offline E2E, native publication/recovery, new operational
checks and archive checks. One Linux3.14 job runs the complete default suite and
the overlapping standalone offline adversarial entry point with exact platform skips;
separate macOS fresh-install and Linux Docker/installed jobs cover those opt-ins.
This is not every integration test on every Python/OS combination. Record actual
job IDs/conclusions and tool versions; a YAML matrix alone proves no platform.
Windows, remote/TCP Docker, remote filesystems and unsupported metadata remain
outside the supported full-workflow boundary.

For the Session-first candidate, the complete default selection may be replayed
as exhaustive disjoint partitions: `tests/unit tests/contract`, `tests/integration`,
`tests/e2e tests/docker tests/release`, and `tests/live`. Preserve separate reports
and counts; the enabled optional suites overlap these default skips. This does
not imply new Linux/platform CI when only local macOS checks ran.

Record realistic schema7→8 preservation (including paused approval, leases,
budgets, chat/graph ownership), current organization history reopen, older-binary
refusal and bounded scale metrics. A projected prior-schema fixture is not execution
of an old binary. Keep failed attempts and repairs in the plan. The1000-event/
256-artifact smoke is a local regression check, not a production throughput SLA.

## Independent review and delivery

Obtain an independent evidence-backed review of authority/execution/evidence,
packaged behavior and the final diff. Check no secrets or machine-specific setup
paths entered product assets. Update README, user guide, ledger, changelog and plans
with exact commands, durations, passes/skips/failures and limitations. Advance a
phase marker only after that phase's actual gate.

When authorized, commit/push the candidate, open/review the PR, wait for actual CI
conclusions and merge only passing changes. Verify remote main's resulting commit
and tree and run post-merge smoke. Do not infer merge from a push or PR URL. A
private repository remains private. Record package/tag publication separately;
never publish automatically as a consequence of merge.

When the owner explicitly prohibits Actions-minute spending, a transparently
CI-skipped merge is permissible only after local acceptance and live read-back
confirm that no required check/rule would be bypassed. Preserve normal protection
and workflow configuration. Feature-head and merge commit messages must include
GitHub's skip marker before the corresponding push/PR trigger; draft PRs alone do
not suppress runs. Use an exact-head normal merge, never admin bypass or fabricated
statuses. Recheck rules immediately before merge; a required pending check is a
blocker, not permission to disable it. Record that hosted CI was not rerun.

## Rollback / incident response

Code rollback is a reviewed Git change; no force/reset operation is implied. SQLite
migrations are forward-only and older binaries refuse newer schemas. Preserve a
coherent stopped-state backup before upgrades; do not delete journal tables or edit
hashes in real user state. FleetPatch rollback creates a new inverse organization
version and cannot revive a stale code candidate. Unknown publication outcomes
require exact operation inspection and confirmed-stopped recovery, not a second
exchange. Retain prior immutable runner images while paused work references them.

Optional OpenTelemetry export, remote sandbox/harness integrations and background
services are deliberately deferred. Unperformed live inference, advisory scanning,
hostile-host resistance or untested platforms must stay limitations, not implied
by broad local test counts.
