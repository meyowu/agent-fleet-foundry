# Contributing

Read `AGENTS.md`, the specifications under `docs/`, `.agent/PLANS.md`, and the active ExecPlan before nontrivial changes. Keep domain and application code independent of CLI/provider/sandbox frameworks, preserve the security invariants, and add observable state/artifact assertions rather than mock-call-only tests.

Install and verify with:

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
```

Normal tests must not need Docker, a network connection, an API key, or a real model. Contributions are licensed under [Apache-2.0](LICENSE). Never include API keys, private state or personal machine paths in a contribution. Publishing packages and changing repository visibility are maintainer actions.

Use `uv sync --all-extras --frozen` for an unchanged checkout. Python3.12–3.14 and
Git>=2.45 are supported inputs; the full workflow requires the documented local
POSIX/Docker boundary. `uv.lock` includes the pinned Hatchling build toolchain.
After setup, use `uv run --offline` for checks and
`uv run --offline python -m agent_fleet.schemas.generate --check` for schema drift.

New model tools require typed bounded contracts, complete deferred-batch validation
and Gateway/Broker enforcement. Model output cannot grant authority. New adapters
need contract tests and actual boundary evidence; do not turn a mock call or a fake
receipt into a verified-completion claim. Preserve user-owned dirty work and use one
writer per overlapping implementation slice. Review proposed organization changes
without weakening protected FleetSpec/trust/credential controls.

The [user guide](docs/USER_GUIDE.md), [release process](docs/RELEASE.md),
[dependency policy](docs/DEPENDENCIES.md) and [security checklist](SECURITY.md)
describe separate installation, real-Docker and adversarial selections. A prepared
wheelhouse is an explicit setup prerequisite; ordinary tests must never fetch it.
Public learning assets are package data with independently executed pytest cases,
not Fleet runtime modules for mypy discovery. Scripts refuse existing destinations
and must never remove a user's directory to make a test pass.

CI checks six Linux/macOS/Python combinations at its documented selection boundary,
plus full default, fresh distribution and Docker jobs. Keep action SHAs pinned,
checkout credentials disabled and permissions read-only; never add live keys to
PR jobs. Record actual checks, source identities, failed attempts and remaining
limitations before claiming a phase accepted. Optional issue templates are deferred;
use a sanitized ordinary issue with version/platform/reproduction/evidence, and
follow SECURITY.md for confidential findings.

Keep the homepage focused on setup and usage. Record development progress in
`docs/DEVELOPMENT_HISTORY.md`, `docs/MVP_ACCEPTANCE.md` or the relevant ExecPlan.
Before opening a PR, inspect `git diff --cached` and follow the
[publication privacy review](docs/PUBLICATION_PRIVACY_REVIEW.md) for secret scans.
