# Phase 7: installable, documented and auditable release candidate

This ExecPlan is a living document. Maintain Progress, Discoveries, Decision Log and Outcomes. It implements Milestone 5 of `2026-09-05-mvp-completion.md`. It is prepared while Phase 6's frozen acceptance runs; it does not authorize Phase 7 source changes before that gate passes.

## Purpose and user-visible result

A fresh user can install a built distribution outside the source checkout, obtain the documented runner assets, initialize a disposable project with an explicit isolation boundary, talk to CoS, approve exact actions, inspect/apply evidence-backed code and review/apply/roll back organization proposals. The detailed guide distinguishes simulated evidence, real isolated command execution and live-provider behavior. Release evidence maps every in-scope MVP criterion to actual current tests and preserves the unperformed external prerequisites.

The end state is an implemented and verified local MVP/release candidate, with `docs/USER_GUIDE.md`, supported-platform and packaging evidence, reproducible contributor/CI checks, and the accepted change merged into GitHub. It is not a package publication or an invented license/live-provider approval.

## Scope

### In scope

- Close F7-01 through F7-14 and U1–U12/S01–S11 in `docs/MVP_ACCEPTANCE.md`, with evidence-specific limitations rather than aggregate-only claims.
- Complete detailed user and contributor guides, packaged runner recipe/access instructions, changelog, release/security/data-handling/dependency policies and a useful minimal architecture diagram.
- Fresh wheel and sdist installation into separate environments, with declared dependencies, outside the source checkout; installed executable/resource/schema/migration/offline-flow checks.
- Linux/macOS CI for the declared Python 3.12–3.14 range where feasible, actual Linux native-publication/E2E execution, local Docker recovery and public journeys. Document Windows/remote-filesystem limits.
- Bounded event/artifact scale smoke with measured timings/storage/memory and exact ordering/read-back; realistic schema upgrade records; security/adversarial release command.
- Repair the stale opt-in live-provider test's setup and enforce independent Docker prerequisites, but do not run it without a separately supplied credential and explicit opt-in.
- Final frozen quality/default/offline/integration/Docker/package checks, release ledger, commit/push/PR/merge and remote identity/post-merge verification.

### Out of scope

- Choosing a license, publishing a package or tagging a public release without separate owner authority. No LICENSE will be invented.
- Finding/reusing ambient API keys or contacting an actual model provider. Dependency installation and GitHub CI coordination are distinct from inference and remain ordinary authorized implementation steps.
- Modal/hosted providers, domain egress, new harnesses, external connectors, autonomous remote writes, daemon/scheduler, signed audit or arbitrary executable skill distribution.
- Mandatory telemetry/exporters. Optional local OpenTelemetry-compatible instrumentation will be explicitly deferred unless a measured current need justifies a bounded implementation.

## Current repository state

The development branch is `codex/mvp-completion`, pushed through accepted Phase 5 checkpoint `a46b68800fb9725274db869f8c360b97a70c24ef` (tree `d99b632814b55d2a95b13e706b87d2017578c827`), while GitHub main remains `c700de1fc357844113426d3352cf29b6ffeae0f1`. Phase 6 code is implemented but acceptance/checkpoint is still running under `2026-09-05-versioned-fleet-evolution.md`; record its exact accepted commit/tree here before implementation.

The source package is `src/agent_fleet`, built with Hatchling and installed as `fleet`. `pyproject.toml` declares Python >=3.12,<3.15 and bounded runtime/dev dependencies; `uv.lock` pins the contributor environment. `tests/integration/test_distribution.py` builds wheel/sdist offline, compares every package source byte and README, validates schemas/migrations/prompts and imports wheel files against the existing locked dependencies. This is not a fresh dependency install. The current catalog has 82 schemas and eight migrations.

The only runner recipe is `tests/docker/Dockerfile.runner`, excluded from the sdist. It copies a `python:3.14-slim` base rootfs into `scratch` to strip inherited environment variables, then sets only the fixed allowed environment. The Docker adapter supplies the non-root user, command, no-network/read-only/resource limits and inspects effective state. The current base tag is mutable; the local cache identifies its image as `python@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6`, but that local observation alone does not establish a portable multi-platform manifest. The current Python/pytest acceptance runner was prepared offline and is not yet a packaged fresh-user recipe.

`.github/workflows` is empty. `CONTRIBUTING.md` is minimal. No user guide, changelog, release process, measured scale test or standalone adversarial script exists yet. `tests/live/test_provider_smoke.py` still attempts public init with FakeSandbox, which cannot pass the isolated bootstrap gate; repair its test setup without relaxing public init. Existing live-network tests must continue to skip without explicit inputs.

## Security impact

Preserve all AGENTS.md security invariants and ADRs 0001–0006. This phase does not expand model tools, project permission ceilings or sandbox selection. Packaged resource access must not execute Docker, install dependencies, pull images or run project code implicitly. Any resource export must be an explicit user request into a new safe destination, reject links/existing conflicting files and report exact output identities; prefer a small read-only installed-resource interface if that satisfies the usable quickstart.

Dependency/image preparation can access package registries only as an explicit operator/CI setup step. Ordinary tests remain offline with real model requests denied. CI uses minimum read permissions for checks, no secrets or live inference, pinned/reviewed action identities and frozen dependency resolution. Untrusted pull requests must not gain write tokens or Docker host secrets. The final GitHub merge is separately user-authorized delivery, not an agent workflow capability.

Performance and adversarial fixtures use disposable Git repositories and state directories; never touch user projects, home/credential roots or global Docker resources. Cleanup targets exact owned IDs/labels/paths, not prune/glob operations. Provider data disclosure and local retention must reflect actual bounded context/artifacts/conversations/proposals, not claim all project data stays local when BYOK inference is enabled.

## Proposed design

1. Freeze the accepted Phase 6 checkpoint. Consolidate release requirements and guide structure before implementation; preserve its complete-tree, generation, cleanup and protected-registration semantics.
2. Ship minimal install-accessible runner resources under `src/agent_fleet` with a reviewed version/digest policy and explicit operator build instructions. Verify resource access from wheel and sdist installations, not source-relative `tests/` paths. Choose pinned base and dependency hashes based on current primary registry/lock evidence; never imply a local architecture-specific image proves all platforms.
3. Separate online dependency preparation from offline installation/execution. Build a wheelhouse from exact exported locked requirements in an explicit setup step. Fresh installation tests use separate new environments, no system-site-packages, `--offline`/`--no-index` and the prepared wheelhouse. Both wheel and sdist must resolve all declared dependencies, launch the installed `fleet` outside the checkout and show exact packaged assets. The normal suite may gate an unavailable prepared wheelhouse explicitly, but the required release selection must actually run, not silently skip.
4. Add a bounded scale test using real SQLite and content-addressed artifacts. Record append/list/page/read/status timing, ordering, content hashes, database bytes and peak memory for a fixed documented event/artifact count. Broad conservative time ceilings catch pathological behavior without treating one host's latency as an SLA. If a real unbounded/quadratic path is found, document and make the smallest relevant repair with tests before acceptance.
5. Add realistic upgrade/reopen cases covering paused approvals, leases, budgets, conversation/graph claims and organization versions. Upgrade only a test-owned prior-schema fixture; preserve wire bytes and events. Older binaries refuse schema8+. Recovery must retain prior non-replayable ownership.
6. Add a standalone adversarial verification entry point that runs named offline security regressions and, only with explicit Docker inputs, a real canary/sentinel/no-residue journey. Reuse existing tested fixtures/services; do not implement a second execution engine or make ordinary commands quietly install tools.
7. Write the complete guide and CI/release policies, then execute guide flows from fresh installed artifacts. Repair the optional live test to require an explicitly prepared Docker image and live model credential; fake-only assertions cannot stand in for verified completion. Exercise the setup offline with FunctionModel where practical; leave actual inference unperformed.
8. Freeze all implementation/tests/assets. Run all local gates and Linux/macOS CI where available. Review exact final diff and packaged bytes for secrets/machine-local paths, update evidence, then commit/push/create the authorized PR, wait for actual checks and merge. Read back remote main and run proportionate post-merge smoke. Never infer merge from a pushed branch or visible PR.

## Public contracts

- Keep all existing CLI and v1alpha1 JSON/error contracts; add only the smallest useful installed runner-resource access surface if needed, with real behavior and tests.
- No new model/provider, permission action, network capability, executable skill or sandbox backend.
- Package runtime/guide resources with documented installed access, exact manifest/version/hash where appropriate. Keep developer fixtures/acceptance secrets/local paths outside distributions.
- A new opt-in installation-release marker/environment may select prepared dependency artifacts; no automatic network fallback. Define its exact name/inputs in this plan before test implementation.
- Repair live-provider prerequisites in `tests/conftest.py`/the live canary without changing default skip safety. No production test-only bypass switches.
- Advance whole-phase metadata only after corresponding acceptance; package version/tag/publication policy remains a separate explicit release decision.

## Milestones

### Frozen minimal distribution/resource contract (before source implementation)

Use standard `importlib.resources` from an explicitly activated fresh Fleet virtual environment; do not add a new resource-export command, filesystem writer or model tool. Package one canonical `src/agent_fleet/assets/runner/` build context containing `Dockerfile`, `requirements.lock`, `.dockerignore` and its operator README. The guide obtains its installed path using `python -c "from importlib.resources import files; print(files('agent_fleet').joinpath('assets/runner'))"`. The operator independently chooses to build from that context. No automatic image pull/build or dependency installation is introduced into Fleet.

The default recipe pins `python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6`. A fresh registry `docker manifest inspect` on 2026-09-05 established OCI index membership for Linux amd64 (`sha256:810da6270e43d30a1f3e0e1eabbeb6fbd9d78ad9dd2e754d5297a3d6cb42df46`) and arm64/v8 (`sha256:964225e67be639ec050dc6ce66ac0958b67e4ce0603e9847b2fae34cbf23f848`), among other platforms. Only observed test platforms will be claimed supported; manifest membership is not execution proof. The local Docker CLI has no usable buildx plugin, so the initial `buildx imagetools --raw` failed125; normal manifest inspection succeeded without pulling an image.

Install genuine runner-only Python test dependencies with exec-form pip invocation, explicit official index, isolated configuration, no cache/compile, exact versions and required wheel hashes: pytest9.1.1, iniconfig2.3.0, packaging26.3, pluggy1.6.0 and pygments2.21.0, taken from `uv.lock`. Then copy the resulting rootfs into scratch and set only the existing fixed PATH/LANG/LC_ALL. Keep the current source-only Dockerfile as an exact tested compatibility copy if needed; the packaged context is canonical. Record actual output image identity; reproducible reviewed inputs do not imply byte-identical layers across different builders/platforms or vulnerability-free images.

Package a small public learning fixture under `assets/canary/` with a deliberately broken text-only divide function, genuine pytest checks, pyproject test discovery and cache ignores. It contains no credential/sentinel/private developer state and has no executable setup hook. This explicit user example is distinct from the private bootstrap security canary. Users copy it only into a newly created destination, initialize Git and commit their own fixture before public Fleet init. Normal fake runtime can then demonstrate real-Docker approval/evidence/code apply without a model key. Do not register a test-only initialization bypass as a public workflow.

Keep `docs/USER_GUIDE.md` canonical. Build configuration may include this exact file in the wheel's `agent_fleet/assets/USER_GUIDE.md` and in the sdist without duplicating handwritten content; archive tests compare its bytes. Adjust the existing broad development-fixture archive exclusion only for the deliberately named public `assets/canary/` test files. Ordinary source tests, `.agent/` and machine state remain excluded. Source users read the repo guide; installed users can read the bundled copy through standard resources.

Use explicit marker `installed_distribution`, `AGENT_FLEET_ENABLE_INSTALL_TESTS=1` and `AGENT_FLEET_TEST_WHEELHOUSE=<absolute prepared directory>` for new fresh-install release cases. Default tests skip these cases; opt-in with incomplete inputs fails instead of silently skipping. Prepare wheels separately with frozen hash-bearing uv export and an exact pip tool (PyPI observed pip26.2.1, wheel SHA256 `71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e`). Each wheel/sdist case creates its own non-system-site-packages environment/cache and installs with offline/no-index/find-links and constrained dependencies; never fall back to the working `.venv`. A normal offline installed test can prove preview/refusal/migration/test-seeded fake flow, but must label that seed as test-only. Public installed bootstrap/approval/real code evidence requires a separately opted-in Docker case, using the packaged learning fixture and installed CLI.

Pin the reviewed build backend to Hatchling1.32.0 (PyPI observed wheel SHA256 `0e17c9c3b9aa7c625acc8d0f5b622f107d5049af9ecf5ada4de1aada5be7cdbc`) and include it in dev lock resolution so offline archive checks have their build toolchain prepared. Its declared build dependencies include packaging/pathspec/pluggy/tomlkit/trove-classifiers; record exact resolved versions/hashes with the wheelhouse and constrain the release build. No dependency/security claim is made just from reading PyPI metadata.

CI uses Ubuntu24.04 and macOS14 with Python3.12/3.13/3.14, explicit frozen setup followed by offline tests, no live key, checkout credentials disabled and contents:read only. Fresh GitHub release/tag read-back on 2026-09-05 resolved actions/checkout v7.0.1 to `3d3c42e5aac5ba805825da76410c181273ba90b1` and astral-sh/setup-uv v10.0.1 to `20cfd1bf945f4377ade1205e4dbc17946fc9a30d`; inspect their actual action inputs/runtime before authoring CI, pin exact hashes and uv0.12.9. A separate Linux Docker job builds the packaged recipe explicitly and runs native/Docker release cases. All resulting CI jobs remain unperformed until actual dispatch/read-back.

Primary preparation references: [Docker digest/build guidance](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions), [uv environment locks](https://docs.astral.sh/uv/pip/compile/), [uv CLI](https://docs.astral.sh/uv/reference/cli/). Runtime and test behavior must be verified against the installed tool's actual supported flags, not guessed from a newer online reference.

### Milestone 1: usable packaged quickstart and detailed guide

Acceptance: installed users can find runner assets and follow documented setup, preview, verified bootstrap and explicit credential boundaries. The guide covers architecture/modules, six differentiators, minimal team choices, permissions, evidence, approval/restart, code review/apply, FleetPatch lifecycle and recovery. Examples match actual help/JSON/config models and distinguish historical unperformed gates.

### Milestone 2: installation, upgrade, scale and adversarial proof

Acceptance: both distributions install with declared locked dependencies into fresh isolated environments and pass representative offline CLI/resource/schema/migration flows outside the checkout. Scale measurements and realistic upgrade/recovery tests pass. Adversarial script has explicit offline/Docker modes and retains an evidence-backed result. Live test setup is valid but cannot run without both gated inputs.

### Milestone 3: platform CI and final frozen release-candidate matrix

Acceptance: Linux/macOS/Python matrix executes where feasible; Linux native whole-tree exchange and CLI recovery are observed rather than mocked. Windows limitations are explicit. Full frozen formatting/lint/types/unit/contracts/integration/offline E2E/default/Docker/package gates pass; state and Docker residue read-back is clean. Any unsupported platform or environment failure is retained as a precise limitation/blocker, not hidden by retries or broad skips.

### Milestone 4: final GitHub delivery

Acceptance: completed docs and evidence are committed, branch pushed with identity read-back, PR/checks reviewed, change merged and remote main verified. Final post-merge smoke records the resulting commit/tree. No public release/license/live-provider success is claimed unless separately authorized and proved.

## Detailed implementation steps

1. Record the final Phase 6 commit/tree and inspect clean/dirty ownership before choosing the next single-writer file boundary.
2. Finalize runner-resource contract, file names, base/dependency identity and explicit export/read mechanism here. Add packaged assets and narrow tests; update source-only Docker recipe to reference the same canonical content without drift.
3. Add installation release tests and dependency preparation instructions, with exact frozen lock/wheelhouse validation and no undeclared/system dependency fallback.
4. Add `tests/integration/test_state_scale.py`, realistic upgrade tests and the security verification entry point; capture normal outputs as structured metrics/evidence without secrets.
5. Repair the optional live-provider Docker setup and add offline verification of its prerequisite enforcement; do not invoke a real provider.
6. Write `docs/USER_GUIDE.md`, runner/data/dependency/security/release documentation and changelog; refresh CONTRIBUTING, README and the acceptance ledger. Use minimal helpful diagrams/tables and executable examples, not placeholder features.
7. Add minimal GitHub CI, then run local/platform/fresh-distribution/Docker gates. Record actual action/interpreter/Git/platform versions and failed attempts.
8. Freeze final content, complete review, perform authorized commit/push/merge and exact remote/post-merge read-back. Update this plan, parent plan and final delivery evidence.

## Validation plan

Keep AGENTS.md quality commands valid: `uv lock --check`, `uv sync --all-extras`, Ruff format/lint, strict mypy, generated-schema `--check`, unit/contract/integration/E2E/default pytest, `uv build --offline`, distribution tests and `git diff --check`. Execute named new installation/scale/upgrade/adversarial tests separately with exact recorded inputs. Real Docker selections require an explicit already-local image and shared test location; no live key is inferred. Freeze source/tests/assets and report overlaps honestly rather than add selection counts.

Fresh installed smoke must prove imported package/CLI paths belong to the new environment and cannot resolve checkout modules, all schemas/migrations/prompts/resources match archive bytes, ordinary network/provider requests are disabled, fake evidence stays unverified, and representative JSON errors have stable codes. Installed Docker guide proof is separate from dependency-free fake CLI proof. Check all managed-container identities, distinct acceptance databases' outstanding leases and pending organization fences after execution.

## Rollback and recovery

All test/install/build locations are newly created and exact scoped. Preserve failed environments/logs when useful; never delete a broad cache or user worktree to make installation pass. Source recovery uses commits, not resets. State migrations are forward-only; do not run older Fleet binaries against a newer database. Users must preserve the entire organization/state/receipt set before recovery; FleetPatch rollback is not database downgrade. GitHub delivery uses normal non-force branch/PR operations; do not overwrite remote user work or merge failing checks.

## Progress

- [x] (2026-09-05) Read release deliverables/acceptance protocols, current package configuration, runner recipe, distribution smoke, live-provider setup and contributor instructions while Phase 6 gates run. Prepared this living plan before Phase 7 implementation.
- [x] (2026-09-05) Drafted `docs/USER_GUIDE.md` in Chinese with retained English commands/contracts while Phase 6 remains source/test-frozen. Checked current CLI help, permission/chat handlers, configuration defaults, budget/context models and recovery flags. The guide explicitly labels pending installed-resource/platform/live/release evidence; no Phase 7 source implementation or fresh-user acceptance follows from this draft. Finish its runner/install/live sections after the corresponding implementation, then replay documented flows.
- [x] (2026-09-05 17:08 UTC) Prepared a separate network-enabled dependency wheelhouse from the unchanged current hash-bearing uv export, with pip26.2.1/require-hashes/only-binary and official index. Download completed48 applicable packages (Windows/Emscripten markers excluded). Initial uvx default selected Python3.13, so wheels alone do not establish this workspace's Python3.14 fresh-install prerequisite. Repeated preparation explicitly selects the observed3.14 interpreter; the final script must bind and report its target interpreter/tags. This is preparation, not fresh-install execution, and build-backend additions remain pending the Phase 7 lock update. No actual provider key/request was used.
- [x] (2026-09-05 17:08 UTC) Fresh GitHub read-back confirms development branch still a46b688 and main c700de1, no existing PR for this branch, repository visibility PRIVATE and Actions/CI not yet run. Preserve visibility; user authorization to push/merge is not authorization to make the repository public. Choose standard hosted jobs with bounded time/concurrency, not paid larger runners.
- [ ] Accept/checkpoint Phase 6 and freeze the exact Phase 7 file/resource contracts.
- [ ] Packaged runner access and detailed executable user guide.
- [ ] Fresh wheel/sdist, upgrade, measured scale and adversarial proof.
- [ ] Supported-platform CI and final frozen local/Docker matrix.
- [ ] Independent final review and authorized GitHub merge/read-back.

## Discoveries

- Observation: current archive smoke imports wheel files using existing dependencies; prior clean-offline attempts lacked cached PyYAML. Consequence: prepare exact dependencies explicitly, then prove a new environment rather than relabel archive/import checks as fresh installation.
- Observation: README runner recipe lives only in excluded `tests/`, with a mutable Python base. Consequence: ship one canonical installed resource and reviewed digest/version strategy; distinguish base preparation from Fleet runtime behavior.
- Observation: the live canary still expects FakeSandbox public init and simulated completion. Consequence: repair setup/prerequisite enforcement, retain opt-in and never interpret offline responses as a live-provider pass.
- Observation: organization publication depends on POSIX/native directory exchange and supported metadata. Consequence: require actual Linux/native proof and document unsupported Windows/remote filesystems; do not weaken controls for a CI pass.

## Decision Log

- Decision: finish the authorized local MVP/release candidate and GitHub delivery while keeping owner-license and real-provider gates explicit. Rationale: neither authority was supplied, and the user requested no branding/license/provider-choice questions. Alternatives: invent license, reuse ambient keys or stop all independent work; rejected. Date: 2026-09-05.
- Decision: separate dependency/image preparation from offline execution and fresh-install acceptance. Rationale: ordinary tests must be offline; a cold dependency cache is an environment prerequisite, not proof of a bad package or permission to fetch during tests. Date: 2026-09-05.
- Decision: defer optional OpenTelemetry export/instrumentation unless measurements show a concrete need. Rationale: local structured events and retained evidence already serve this MVP, and mandatory external services are out of scope. Date: 2026-09-05.

## Outcomes

Planning only. No Phase 7 source change, installed-user/platform acceptance, live-provider call, release or final GitHub merge is claimed. Phase 6 must pass and be checkpointed before this implementation begins.
