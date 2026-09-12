# Session-first acceptance — 2026-09-07

This ledger separates implemented behavior, current local verification, retained
failed attempts and GitHub delivery. It does not certify a public package release,
live-model quality or a platform that was not exercised. The living plan is
`.agent/plans/2026-09-07-session-first-release.md`.

## Candidate identity and scope

Baseline: `9276cbf44fa32adc8087d618e0ec4aeff60b877c`, branch
`codex/session-first-release`. Final source/test/scripts aggregate:
`de7ab84636c185e543dfd76b84cc9e97af64aa9ee9ef7ec63f12d3348f4b3135`.
The aggregate is SHA256 of sorted repository-relative file SHA256 lines, including
untracked feature files; it is not a Git commit or archive hash. Final collection:
2302 tests. Documentation is excluded from this aggregate and archive-bearing
README/USER_GUIDE changes require a final package refresh.

Exact aggregate command (run from the repository root; Git includes tracked
hidden fixtures that a default `rg --files` inventory can omit):

```bash
git ls-files -co --exclude-standard -z src tests scripts |
  sort -z | xargs -0 shasum -a 256 | shasum -a 256
```

Implemented: foreground session/onboarding and exact in-session review; opt-in
durable plan approval before execution; immutable per-role model profiles;
operational custom role templates with reviewed evolution; authenticated local
read-only agent/evidence dashboard. Existing Permission Broker, sandbox isolation,
single-winner execution ownership and evidence assurance remain authoritative.

## Current final-freeze gates

All default selections use `AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0`,
`AGENT_FLEET_ENABLE_DOCKER_TESTS=0`, `AGENT_FLEET_ENABLE_INSTALL_TESTS=0`,
`UV_PYTHON_DOWNLOADS=never` and `uv run --offline --frozen`. Exact integration file
groups are versioned in `session-first-test-partitions.json`; they are exhaustive
and disjoint, not additional tests. JUnit reports use the names below under the
operator's retained disposable evidence root.

| Gate / report | Final-freeze result |
| --- | --- |
| `uv lock --check --offline`; `uv sync --all-extras --frozen --offline` | PASS; 55 resolved,53 checked. |
| `ruff format --check .`; `ruff check .` | PASS; formatter reported312 files, no lint findings. |
| `mypy src tests` | PASS; 260 files. |
| `python -m agent_fleet.schemas.generate --check` | PASS; 92 schemas, migrations1–10. |
| `node --check` on dashboard and browser-probe JavaScript; `git diff --check` | PASS. |
| `pytest -q -ra tests/unit tests/contract`; `final-unit-contract.xml` | 1749 passed in228.82s. |
| Three integration file groups; `final-integration-1/2/3.xml` | 133 passed in1111.34s;182 passed in1072.79s;186 passed in997.53s —501 total. |
| `pytest -q -ra tests/e2e tests/docker tests/release tests/live`; `final-offline-e2e.xml` | 33 passed,19 skipped in742.64s; all three opt-ins disabled. |
| Standalone `scripts/verify_adversarial.py`; `final-security/evidence.json` | 736 passed in459.08s; script elapsed461.966s, no errors/skips; overlaps default tests. |
| Explicit full real-Docker selection; `final-docker.xml` | 15 passed,4 deselected in370.03s; same immutable image and fresh shared-root fixture. |
| Fresh wheel/sdist installation; separate `installed.xml` | 2 passed,1 Docker case deselected in99.60s; empty install caches, prepared locked wheels, offline/no-index. |
| Installed public Docker journey; `installed-docker.xml` | 1 passed,2 deselected in61.78s; actual public bootstrap/chat/approval/apply/evolution/recovery path. |
| Final archive/schema refresh; `final-archives.xml` | 6 passed in3.01s; offline wheel/sdist build succeeded. |
| Actual browser E2E | 17 assertions passed twice from source and again through the freshly installed wheel CLI; desktop/mobile/200-percent text and empty screenshots inspected. |

Default partition total:2283 passed,19 skipped across all2302 collected cases.
Skipped by default:15 actual Docker cases,3 fresh-install cases and1 actual
live-provider case. The separately enabled Docker and installation selections
are not inferred from those skips. Final adversarial script's own manifest
algorithm reports `73fe008c10e692b8ec4cb2e40d98b1dc6007a5380cbba56dd3424796be5c0976`;
it differs from the sorted shell aggregate by construction, not source drift.

Browser checks cover hostile literal task text, genuine child/agent records,
simulated-evidence limitations, patch inspection, bounded event replay, keyboard
navigation, no token persistence, offline/reconnect, disconnect and invalid-token
denial. A separate empty fixture contains zero tasks/agents. Actual CLI plan
approval appeared in the browser in approximately102ms on the fixture; this is
not a performance SLA. Both test-owned servers were stopped and their tokens
revoked, and the owned browser session closed.

Independent review closed full-parent custom repair admission, absolute HTTP
header deadline, owned-connection shutdown, stalled-SSE detection and the final
Verifier audit regression. Final narrow audit replay: 4 passed in10.02s. This is
not a substitute for the complete final matrix.

## Frozen distribution receipts

Archive inputs stayed unchanged before and after installation:
README SHA256 `83cce25f66c4ed29e0e95730560f562c80308fd0ac1d7cf25b2ad0dffa1faea2`;
bundled USER_GUIDE `46263da2c12becec4331d86028437c8da40f5540b4c33e5e6a4746a59b345fcd`.
Direct builds, both fresh installations and the wheel rebuilt from sdist match:

- Wheel `agent_fleet-0.1.0-py3-none-any.whl`:
  `da81e444b8f0d2d56821050c242677cf0aa6ef0f111044cb58a12d44ad6de9f9`.
- Sdist `agent_fleet-0.1.0.tar.gz`:
  `a5f3f3cac6a205fbba3d65d59255c18e391f6206b52c232d416a3beacf0f2c3f`.

Wheel/sdist cases independently exercise installed model profile CAS/binding,
plan pause/show/wrong-hash denial, approval without worker effects, pinned model
revision across later edits, explicit resume and single consumption/replay denial.
All92 schemas,10 migrations, packaged source/guide/runner/prompts and four Dashboard
assets are checked. Fixtures using private fake registration remain explicitly
test-only; the separate installed Docker journey uses public initialization.

Final installed browser replay imported `agent_fleet` from the fresh wheel's
site-packages, not the checkout, prepared an explicit test-only fixture, and
launched the installed `fleet dashboard` executable with a sanitized environment.
All17 checked interactions passed. Its four console errors were exactly three
deliberately offline requests and one invalid-token401, not unexplained failures.
Final desktop/mobile screenshots were inspected. The exact owned server exited0
after Ctrl-C and its browser session was closed; its process token is revoked.

Reproduction uses the prepared wheelhouse from the user guide, explicit opt-ins
and new shared fixture subdirectories (never an existing project/cache root):

```bash
AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_ENABLE_DOCKER_TESTS=0 \
AGENT_FLEET_ENABLE_INSTALL_TESTS=1 uv run --offline --frozen pytest -q -ra \
  -m 'installed_distribution and not docker_integration' tests/release \
  --basetemp "$fleet_test_root/wheel-sdist"

AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_ENABLE_INSTALL_TESTS=1 uv run --offline --frozen pytest -q -ra \
  -m 'installed_distribution and docker_integration' tests/release \
  --basetemp "$fleet_test_root/installed-docker"
```

`AGENT_FLEET_TEST_WHEELHOUSE` and, for Docker, the exact already-local
`AGENT_FLEET_DOCKER_TEST_IMAGE` must be explicitly configured. No image pull/build
or provider-key discovery is hidden in these acceptance commands.

## Retained failures and superseded attempts

- Initial Dashboard tests: 27 passed,3 failed; fixture child-count/scenario errors.
  A later fixture called a nonexistent model-service method. The interrupted
  full default attempt was1 failed,838 passed,14 skipped in946.39s, exit2.
  Corrected focused Dashboard replay33 passed in81.74s; late live-child
  discovery1 passed in18.52s.
- First full Docker attempt:14 failed,1 passed,4 deselected in62.08s. The default
  private macOS temporary root was not shared with Colima; direct bind-mount
  errors explain creation failures. A fresh shared-root replay, before the final
  catalog audit fix, passed15 tests in204.64s. Independent read-back found112
  settled leases across27 databases, all36 leased worktrees absent, no extra
  registrations across17 surviving repositories and no managed containers.
  An earlier independent read-back found39 fail-closed outstanding leases across12
  original failed states. At the final read-back, that default `pytest-1070`
  temporary directory no longer existed; its disappearance mechanism was not
  established. The failed `docker.xml` report and historical audit observations
  remain, not an in-place database archive. No recovery of those39 records was
  proven and their disappearance is not successful cleanup evidence. No live
  container was observed in the same daemon inventory.
- First complete integration partition:4 failed,496 passed in1972.33s. Three
  assertions expected old delegation wording; the same forbidden teams were
  rejected before worker/resource creation. One genuine audit regression rejected
  a built-in Verifier write before Broker denial persistence. The narrow guard
  correction restores the exact denied intent/audit path without advertising
  write tools; custom/read-only catalogs remain strict. Original denial assertions
  were retained and strengthened; two custom-tool narrowing cases were added.
  Initial repair12 passed in10.39s; strengthened selection11 passed in3.43s.
- Earlier offline partitions1747 unit/contract,32 E2E/offline optional-directory
  cases and1 live-readiness case passed;18+1 optional cases skipped. Earlier
  adversarial734 passed in278.03s. These identify the pre-audit-fix candidate,
  are not final-freeze acceptance, and must not be added to final totals.

## Final coverage and cleanup read-back

Independent comparison of all five final JUnit identity sets against a fresh
collection-only inventory found2302 exact identities with no overlaps, omissions
or extras. The manifest's43 integration files exactly match all43 files and the
three report partitions. Security736 is an overlapping subset of that union;
all15 final Docker cases correspond exactly to the default Docker skips.

Final Docker inspection:27 databases,112 settled leases (103 released,9 recovered),
zero outstanding, all36 leased worktree paths absent and no extra registrations
across17 surviving repositories. Managed-container inventory is empty on the
same Colima Unix daemon `815f9bce2b2930154aaaf49cf86667332a3b576d6b85a92ed070ff9d1a0971fb`,
using image `sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241`.
This is separate from the original failed temporary-fixture observation above.

Independent installation cleanup: the three passing cases exactly cover the
three default installation skips;3 state databases have54 released leases and
zero outstanding. All18 leased worktrees are absent and10 surviving repositories
have zero extra registrations. No active agents, pending approvals or retained
conversation claims remain; reviewed Fake plans are consumed. Installed Docker
uses the same verified image/daemon and leaves no managed container.

## Remaining boundaries

- No live provider request or ambient credential discovery. SDK mock-transport
  routing proves selected model/key/destination handling, not model quality.
- Actual host verification is macOS arm64/Python3.14.6 with local Colima Linux
  workers. Prior Linux/Python CI belongs to the earlier candidate; no new platform
  execution is inferred. Windows, remote Docker and hostile-host resistance are
  outside this release's support proof.
- Dashboard is foreground, IPv4 loopback-only, process-token authenticated and
  read-only. It is not a daemon, hosted service or browser control plane. Models
  are configured by separate explicit CLI commands, not `/models` chat messages.
- Additional providers/harnesses, Modal/hosted sandboxes, plugin distribution,
  automatic fallback and background/multi-machine scheduling remain deferred.
- Public OSS/package release still needs the owner's license and a separately
  authorized disposable live-provider canary. Neither is required or invented
  for this local Session-first implementation/merge.

## Delivery

All local final gates passed. Four module commits were pushed and merged:
`231ccd95e2d04ce872dd9db48eb4069fc3288a05` (contracts),
`c02043f29c31133c4a83161a592c3ee6ecfafdaa` (runtime/session),
`814b3ae7044a00f74c3713cb35900c2c95b180ca` (Dashboard), and
`c9e839a4899bb3b0e58d820640e181c0055c11e2` (release docs/installed journeys).
Each of the first three staged source trees also passed isolated archive-based CLI
import/help smoke, with Dashboard registration added only alongside its module.
Those small commit smokes do not replace final-tree matrix acceptance.

[PR6](https://github.com/meyowu/agent-fleet-foundry/pull/6) was normally merged
at `2026-09-08T00:45:57Z` (September7 local time), with exact-head matching and no
admin override. Merge commit `8e64fd893b68384868222ebad3b274787c9d89f8` has parents
the baseline `9276cbf44fa32adc8087d618e0ec4aeff60b877c` and feature head
`c9e839a4899bb3b0e58d820640e181c0055c11e2`. Its tree
`eab059c281eb9a78c1999be6835cc029a539c417` exactly matches the accepted feature
tree. GitHub PR/main and fetched local main were read back; the local checkout
fast-forwarded cleanly.

Fresh pre-merge REST showed main unprotected; GraphQL showed no branch protection
rule or inherited repository rulesets (empty list, no next page). The REST
ruleset endpoint was plan-restricted, not interpreted as proof of absence.
Workflow files and repository settings were unchanged; the repository remains
private. Head and merge commit carry `[skip ci]` under the owner's Actions-minute
constraint. Post-merge Actions total remains7, latest run33989500224 at the old
baseline, with no new run for this candidate. Hosted CI was intentionally skipped,
not reported as a pass. No tag, package publication or visibility change occurred.

### Post-merge read-back and smoke

On the exact merge tree, offline lock55/sync53, Ruff format (reported313 files),
lint, mypy260 files,92 generated schemas, both JavaScript syntax checks and Git
whitespace checks all passed. The source/test/scripts and README/USER_GUIDE
hashes above were unchanged. The offline build produced identical wheel/sdist
hashes to final acceptance. The focused post-merge command was:

```bash
AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=0 AGENT_FLEET_ENABLE_DOCKER_TESTS=0 \
AGENT_FLEET_ENABLE_INSTALL_TESTS=0 UV_PYTHON_DOWNLOADS=never \
uv run --offline --frozen pytest -q -ra \
  tests/integration/test_distribution.py tests/unit/test_schema_generation.py \
  --junitxml "$fleet_evidence_root/postmerge-archives.xml"
```

Result:6 passed in1.99s. This is a post-merge smoke, not a new full-matrix claim.
This final receipt changes only this ledger and the living ExecPlan, both excluded
from the distribution. Packaged README/guide, source, tests, schemas, dependencies
and assets remain frozen, so the complete accepted matrix and fresh-install
archive identity still refer to the delivered implementation.
