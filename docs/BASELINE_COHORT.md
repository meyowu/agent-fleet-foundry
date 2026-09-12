# Six-repository baseline qualification

This optional cohort exercises six generated Git repositories through public
CLI processes and the real Docker provider. It does not use a live model,
mock command transport, direct project registration, or host-side business tests.
It is not the separate 24-task external-project evaluation campaign.

| Fixture | Detected command | Expected business result |
| --- | --- | --- |
| Python passing | `python -m pytest` | exit 0, one passing test |
| Python missing dependency | `python -m pytest` | exit 2, named missing module |
| Python existing failure | `python -m pytest` | exit 1, named assertion failure |
| Node passing | `npm run test` / `node --test` | exit 0, named passing test |
| Node missing dependency | `npm run test` / `node --test` | exit 1, named missing module |
| Node existing failure | `npm run test` / `node --test` | exit 1, named assertion failure |

All six expected results are conclusive *observations*. The four nonzero
business results must not become a successful test or a model completion claim.
The initial bootstrap Canary is a separate generated fixture: its passing
result never proves that the target repository's tests pass.

## Prepared image

Build the normal Python/pytest runner first using the repository's runner guide.
The optional tiny context in `tests/fixtures/baseline-image/` adds Node/npm to
that prepared runner; it installs no project dependencies and contains no
project source. Supply exact image identities, not mutable base tags. Building
may fetch a digest-pinned official Node image, but build commands and all
business execution have networking disabled. No image is published.

The initial local Linux/arm64 recipe used these exact inputs:

```sh
docker build --network=none \
  --build-arg FLEET_PYTHON_IMAGE=sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241 \
  --build-arg NODE_IMAGE=node@sha256:221018414babb9899e3c6dabcd035c1fd0e891ca44dac9cba1457d4f3083a524 \
  -t agent-fleet-baseline-cohort:20260911-arm64 \
  tests/fixtures/baseline-image
```

The Python ID is a local prepared image, not a downloadable public image.
Another machine must build that prerequisite and use its own inspected ID;
another architecture also needs the corresponding reviewed Node digest.
Do not add arbitrary image environment variables: the provider intentionally
accepts only `PATH`, `LANG` and `LC_ALL`. Docker applies its own non-root identity,
network-none, read-only root/source mounts, capabilities and resource limits.

## Run and inspect

```sh
uv run pytest -q tests/unit/test_baseline_cohort_fixtures.py
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_BASELINE_COHORT_IMAGE=agent-fleet-baseline-cohort:20260911-arm64 \
uv run pytest -q tests/docker/test_business_baseline_cohort.py
```

Use a fresh private pytest base directory on the same supported filesystem as
the project. Retain JUnit output and the generated state/fixtures for audit.
Without both opt-ins the six Docker cases are skipped, not passed.

For the standalone adversarial gate, supply a new absolute private output path:

```sh
uv run python scripts/verify_adversarial.py --output /absolute/new-private-gate \
  --docker --image agent-fleet-runner:0.1.0-py314-v1 \
  --baseline-cohort-image agent-fleet-baseline-cohort:20260911-arm64
```

The ordinary `--docker --image` route explicitly excludes this cohort file and
records that exclusion. Adding the cohort flag selects the standard Docker suite
plus all six cases; empty/missing companion arguments fail before dispatch. The
runner uses only the explicitly selected cohort image and never pulls one. All
selected tests must pass without skips/errors, and the selection must be nonempty.
Default CI excludes the cohort explicitly; it does not silently qualify Node.

Each case starts with an absent state home and confirms `fleet readiness`
executes nothing. Public `fleet init` registers the project only after its
isolated Canary succeeds. The fixture's generated Fleet configuration is
committed before `baseline plan`, then the test proves missing-consent rejection
and consumes the exact reviewed one-time authorization. A spent retry must not
dispatch again. Fresh `baseline show` and SQLite adapter readback bind the
review, observation, source, actual command, native handle, sandbox inspection
and cleanup receipts. The original Git source and configuration remain unchanged.
The public `observation` body must equal the validated durable observation,
including bounded redacted/control-escaped stdout/stderr, their retained hashes
and truncation flags. Before capture it is null. Showing retained output does
not run a command, call a model, disclose raw secrets or change a failed business
test into a passing one. The same additive field is available in Session output.

Failure recovery uses only the exact test-owned baseline scope after an ordinary
completed CLI invocation. A watchdog, interruption or negative signal exit makes
descendant quiescence unknown: the helper fails and retains the state without
automatically invoking show or owner-stopped recovery. Reaping the CLI alone
does not prove that separately-sessioned Docker/Git clients have stopped. The
external test watchdog is360 seconds, above the unchanged300-second product
attempt limit; it is not a product timeout extension. It never applies a patch
or deletes unrelated containers. A cleanup failure remains a test failure with
retained evidence; do not use global Docker prune or erase state to make it pass.

## Current result boundary

The current integrated cohort `baseline-current-cohort-01` passed **6 cases in
437.84 seconds** (wrapper441.880657s), zero failures/errors/skips and all554
source inputs unchanged. Fresh independent physical readback passed at
2026-09-12T12:24:48.236807Z. It confirmed actual business exits0/2/1/0/1/1,
one exact consumed authorization/owner/dispatch/observation/report per case,
durable public-output equality and unchanged original source. All18 baseline
leases and their receipts were released; six workspaces and six exact native
IDs were absent. Thirty-six metadata-only queries confirmed the matching daemon
and six empty exact installation scopes. All960 retained evidence entries stayed
unchanged. This is not a global Docker or bootstrap-resource inventory.

Report `de-current-physical-readback.tNFUKO52/VERDICT.md` SHA256:
`b67e04703b6124f5f4ff4402945bfc72c59d485f4e722374580d16ef24b46553`.
Current JUnit SHA256:
`466be03f5d0aab60bfd9dbfaff7eea8b0fe5467f3fcbeb3e0e6e7dff8b5a9ef1`.
The separately reconciled current default gate passed4291/32 with4323 exact
identities and554 unchanged inputs; all six static checks and independent full
readback passed. Final optional/artifact/Git gates are separate entries in
the [delivery plan](../.agent/plans/2026-09-12-baseline-delivery.md), not inferred
from six passing cohort tests. F was delivered separately in PR12; its frozen
archives and physical tests do not substitute for current D/E gates.

The earlier isolated-candidate D04 cohort passed **6 cases in746.49 seconds**
(process752.559887s), with553 source/test inputs unchanged. It used the already
prepared image
`sha256:8bc1c28eb85f3257ab5f2b92d72a7b9cc7ce00de064c7e6ef898dc1605ff4c9a`.
Independent physical readback confirmed18 released leases,36 exact native metadata
queries and six stopped immutable SQLite reads without sidecars; retained evidence
and candidate files were unchanged. The six expected exits were0/2/1/0/1/1.
Earlier failed retry/cleanup/signal-exit assumptions and all raw trials remain
retained; normal-path passes alone did not establish exceptional-path safety.

Separate gate-selection verification passed22 focused checks and25 synthetic
child-JUnit probes without Docker, proving selection/rejection/report behavior,
not physical execution. These historical isolated-candidate results remain
separate from the current combined gates above. Neither qualifies six external
projects, the24-task campaign, three actual cold starts or cross-platform proof.
Generic cold-start slots and campaign reservation/execution already exist; actual
qualified identities and completed campaigns, not duplicate infrastructure,
remain the missing evidence. Native P0 finalization remains NOT_GO.
