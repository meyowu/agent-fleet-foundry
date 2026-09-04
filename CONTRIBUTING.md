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

Normal tests must not need Docker, a network connection, an API key, or a real model. Do not add a license, publish a package, push a branch, or contact an external service without explicit repository-owner direction.
