# Agent Fleet

Agent Fleet is a **local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization**. A user gives goals to one Chief of Staff (CoS); the control plane assembles the smallest valid team, constrains its authority and execution boundary, and delivers reviewable changes with evidence.

It is deliberately not a generic multi-agent chat framework or a permanent roster of named bots. Models propose scope, plans, actions, and organizational changes. Deterministic application code validates those proposals, owns permissions and sandbox selection, computes the canonical patch, and decides what the available evidence can prove.

This repository implements **Phase 0 through Phase 6**: deterministic repository profiling, all five bounded adaptive strategies, independent exact permissions and user-owned persistent trust, content-addressed evidence, real Git worktrees, guarded patch application, explicit BYOK PydanticAI, a hardened local Docker execution boundary, durable cumulative budgets, persistent CoS chat and reviewed versioned organization evolution. The deterministic fake runtime remains available for offline development and tests; no live model-provider call is required for the bootstrap canary.

**Phase 6 behavioral acceptance passed on 2026-09-05:** the frozen default suite passed 1,973 tests with 15 explicit skips, and the separately enabled real-Docker suite passed fourteen. Phase 7 remains open; this is not a completed MVP release. The [completion plan](.agent/plans/2026-09-05-mvp-completion.md) and [acceptance ledger](docs/MVP_ACCEPTANCE.md) distinguish accepted behavior from remaining requirements, including the unrun live-provider gate and owner license decision.

The development branch contains three accepted [Phase 5 milestones](.agent/plans/2026-09-05-adaptive-workflow-chat.md): budgets/evidence (`ab28aaa`), [adaptive graphs](.agent/plans/2026-09-05-adaptive-graph.md) (`7a70b1a`), and [persistent chat](.agent/plans/2026-09-05-persistent-chat.md) (`a46b688`), followed by accepted organization evolution (`b42cdf9`). All are committed and pushed to `codex/mvp-completion`, with exact remote read-back. `main` remains `c700de1`. Local acceptance is not a main-branch merge or completed public MVP release.

**Phase7 candidate proof:** fresh wheel/sdist and installed public-Docker checks passed **3 tests in92.32s**, covering installed resources/schemas/migrations, doctor, Safe/src initialization, chat with cross-process approval/retry, independent five-test command evidence, explicit code apply, persistent-rule revocation and no-op exact recovery. A separate public registration substitutes only offline FunctionModel responses to prove installed CoS proposal/diff/apply/rollback; this is not a stock fake capability or live-provider pass. Standalone offline security replay passed539 tests in175.37s; separate Docker replay passed14 in133.52s. The [release plan](.agent/plans/2026-09-05-release-candidate.md) retains failures and evidence boundaries. Final frozen full/platform CI, independent final review and GitHub merge are still pending.

The [detailed user guide (简体中文)](docs/USER_GUIDE.md) explains installation, initialization, BYOK, chat, adaptive teams, exact permissions, evidence/code review, organization evolution and both recovery procedures. It is also bundled in the distribution. Phase7's first fresh wheel/sdist and installed public-Docker journeys passed locally; final frozen/platform/release evidence remains separate.

Three sandbox providers are registered. `DockerSandboxProvider` is the isolated path and creates one inspected, resource-bounded, network-disabled container per reviewed command from an already-local immutable image. `FakeSandboxProvider` records commands without executing them. `LocalUnsafeSandboxProvider` executes directly on the host only after a separate `--allow-unsafe-local` confirmation and can never count as isolated evidence. Provider selection is exact and immutable for a project/run; Docker failure never falls back to host execution.

## Product north star

Six capabilities determine whether Agent Fleet provides differentiated value:

| Capability | Current implementation boundary | Remaining target |
|---|---|---|
| Repository-aware bootstrap | **Enforced:** bounded static inspection finds supported ecosystems, build systems, boundaries, exact candidate commands, provenance, confidence, and ambiguities; preview is read-only; init stages the proposal, runs a disposable canary through the normal Docker workflow, validates a hash-linked `BootstrapReport`, proves cleanup, and only then publishes `.fleet/`. | The canary is a deterministic Fleet-owned fixture; executing arbitrary target-repository setup or networked commands remains out of scope. |
| Adaptive Fleet | **Phase 5 accepted:** persistent project-bound CoS chat; every run has a validated `FleetPlan`; direct/single/pair create only planned roles. Parallel Engineers use scoped child runs and stable joins; read-only Researcher/Architect reports follow declared dependencies. | Preserve exact authority/context/evidence through operational configuration evolution. |
| Independent permission control plane | **Phase 4 accepted:** ToolGateway re-evaluates current role/workflow/task/user/sandbox ceilings; exact once/run/project rules, explain/revoke/reset, private user-owned trust and durable single-winner dispatch are verified. Phase 5 Milestone 1 preserves cumulative budgets across approval pauses. | Arbitrary shell and approved isolated-worker networking remain unavailable; general provider-history restoration is not implemented. |
| Independent sandbox abstraction | **Enforced local slice:** strict `SandboxRequirements` matching dispatches exact fake, Docker, or separately confirmed local-unsafe providers. Docker pins a local Unix daemon and image ID, inspects effective configuration before start, bounds execution, and recovers exact labeled resources. | Modal and hosted providers, approved network modes, and a multi-user/remote-daemon trust model remain unimplemented. |
| Evidence-first delivery | **Enforced:** exact ConfigSnapshot, TaskSpec, FleetPlan, patch, command inspection/transcript, verdict, cleanup, BootstrapReport, risk, and proof-gap links form content-addressed evidence. Accepted M1 resolves typed criterion references; accepted M2 binds joined-candidate and descendant-cleanup provenance. Only fresh non-mutating Docker evidence can verify; fake/local-unsafe cannot. | Preserve these boundaries through chat and configuration evolution; broader project command/tool coverage remains tracked work. |
| Versioned Fleet evolution | **Phase 6 locally accepted:** CoS delivers immutable proposals and semantic/text diffs; explicit CLI application publishes a whole organization version; current-head rollback creates a new audited inverse. Typed path-conditioned verification skills change required command evidence. | Full offline and macOS/Colima Docker acceptance passed; Linux publication execution remains a release gate. No model self-application, permission expansion or protected FleetSpec mutation is supported. |

“Enforced” means a property is checked by code and tests at the named boundary. “Partial” means a real subset exists but does not yet satisfy the complete product claim. “Roadmap” means documentation or schema direction only; it must not be presented as executable behavior. See [ADR 0001](docs/adr/0001-product-north-star.md) for the decision and tradeoffs.

## Reviewable organization evolution

Phase 6 has passed local behavioral acceptance, not public-release acceptance. In a registered project, ask CoS for an organization change such as “For backend changes, always run integration tests.” The response contains a proposal ID; it does not apply the change. Inspect the complete proposal and both derived diffs before authorizing it:

```text
fleet fleet-patch list --path .
fleet fleet-patch show <proposal-id>
fleet fleet-patch diff <proposal-id>
fleet fleet-patch apply <proposal-id>
fleet fleet-patch rollback <current-applied-proposal-id>
```

Every command supports `--json`. Code delivery remains separate: `fleet patch show <run-id>` and `fleet patch apply <run-id>` operate on code, not organization proposals. Fleet never stages or commits user source as part of organization publication.

A workflow may reference a declarative `.fleet/skills/backend-integration.yaml` that requires named verification commands when a code-change task's allowed paths overlap the backend. Requirements are recomputed from the immutable configuration during both TaskSpec creation and final evidence assembly. They are **requirements, not grants**: the exact command still passes through the PermissionBroker and the selected sandbox. A broad scope such as `src` cannot evade a narrower backend requirement. Skills cannot contain executable scripts, change the fixed stage order, grant network access, or add unregistered agents.

Publication binds both the logical ConfigSnapshot and the complete bounded `.fleet/` tree, including safe unreferenced files, modes and empty directories. The generation increases on apply and rollback, even if previous bytes return. An older ready-for-review code candidate therefore becomes stale; request a new run after changing organization rules. Once a project has an admitted Run/history, `fleet init` cannot replace or rebind that organization, including its credential reference. Moving `.fleet/` aside does not erase the version fence. Protected runtime/sandbox/credential configuration is outside FleetPatch; preserve the existing project/state and use a separately initialized registration when a different protected setup is required.

Supported native publication requires a local macOS or Linux filesystem with same-filesystem atomic directory exchange, writable private staging beside the repository and supported exact metadata. Unsupported ownership, links, ACLs, special flags or extended attributes fail closed. This is local process-crash recovery, not a hardware power-loss or hostile-host guarantee. See [ADR 0006](docs/adr/0006-atomic-organization-publication.md).

An interrupted publisher retains its exact operation and fence. After confirming that the original process has stopped:

```text
fleet fleet-patch operation <operation-id>
fleet fleet-patch recover <operation-id> --owner-stopped
```

Recovery inspects the known original/new orientation; it never exchanges directories again or overwrites unexplained user edits. Publication status and cleanup are separate: `cleanup_complete=true` means inspected complete, `false` records a cleanup gap, and `null` means not inspected by that invocation. Repeating a committed apply returns its original version without applying again or claiming historical cleanup. Failure before a staging receipt exists retains unrecorded private scratch for manual inspection; it cannot be recovered automatically using an invented journal entry. Preserve state and scratch on uncertainty.

Focused evidence as of 2026-09-05: the joint proposal/publication/recovery/CLI/schema group passed **30 tests in 81.38s**; three fresh-process CLI tests passed **in 28.99s**, including abrupt exits immediately after durable preparation and after native exchange. The strengthened real-Docker evolution journey passed **1 test in 32.41s**: actual backend TaskSpecs before the rule and after rollback require only the baseline, while Engineer and independent Verifier under the applied rule each ran five baseline and two integration tests, producing four receipts with no proof gaps. Explicit code apply and organization rollback remain separate. These use an offline FunctionModel, not live-provider inference.

Final behavioral freeze: `e1d946ceeeb2b5ec7f3a47d7c6353ce6b6a0b5f35b740f818040188d386c9ffb` (sorted source/test SHA-256 aggregation). `uv run pytest -q --durations=15 --junitxml=<temporary-report>`: **1973 passed, 15 skipped in 1499.51s**. Its JUnit partitions are unit1010, contract567, integration369, offline E2E22, four offline cases under Docker and one live-readiness-only test; these are partitions of one run, not independent additional suites. Fourteen real-Docker cases and one live-provider case are explicitly skipped by default. The separately enabled complete Docker suite passed **14 tests, 4 deselected in 178.84s**, and focused workflow/configuration compatibility passed **57 tests in 291.68s**. Independent integration review: PASS with fresh **36 passed in 226.85s**, followed by unchanged-hash delta reviews and six fresh error/lock-boundary probes. The final Docker audit found no outstanding leases/pending organization heads across26 databases and no managed containers; nine historical recovered leases remain. Ruff249, mypy213 and82 schemas passed. These selections overlap. The [living plan](.agent/plans/2026-09-05-versioned-fleet-evolution.md) retains failed attempts and the narrow public error-compatibility repair. Metadata/package refresh, fresh installed-user and platform release proof are separate gates; live inference is unrun.

Post-acceptance metadata refresh changed only the phase5→6 marker and its two assertions: source/test checksum `6450c9c4d85bf1f9cf091de152389abcf0740dd0f2140f882c574c00478cb244`. CLI/archive/schema checks passed **36 tests in 30.70s**; Ruff249/lint, mypy213,82-schema drift and whitespace checks passed. The archives are checked against existing locked dependencies; fresh dependency installation remains Phase7 work.

## Installed quickstart

No PyPI publication or public runner registry is assumed. Build the reviewed checkout with `uv build`, or obtain the exact reviewed local wheel. Install it into a new environment outside your target project:

```bash
uv venv /absolute/path/to/fleet-cli --python 3.14
source /absolute/path/to/fleet-cli/bin/activate
uv pip install /absolute/path/to/agent_fleet-0.1.0-py3-none-any.whl
fleet version --json
python -c "from importlib.resources import files; print(files('agent_fleet').joinpath('assets/runner'))"
```

The last command prints the installed build context. Build explicitly with `docker build --pull -t agent-fleet-runner:0.1.0-py314-v1 /printed/runner/directory`; dependency/image preparation may use the network, but Fleet never performs it automatically. The runner pins the Python base by OCI digest and five pytest wheels by version/hash. [Runner policy](src/agent_fleet/assets/runner/README.md) states the actual reproducibility limits.

For a first exercise, use the [packaged learning project and step-by-step guide](docs/USER_GUIDE.md#公开学习项目无需模型-key). Copy into a new directory, create its initial Git commit, select a disjoint state directory, and use fake runtime plus real Docker. Review exact approvals, inspect `verified_complete` and command evidence, then apply the code explicitly. This is genuine isolated testing with a deterministic model, not live model reasoning.

## Development setup

Python 3.12–3.14 and Git 2.45 or newer are required. The Git floor is needed for the hardened `--no-lazy-fetch` execution ceiling. `uv` is the preferred contributor tool.

```bash
uv sync --all-extras
uv run fleet version
uv run fleet doctor --json
```

Use `AGENT_FLEET_HOME` to place local state somewhere explicit. Tests always point it at a temporary directory.

## Docker sandbox and verified bootstrap

Docker mode requires a local Linux Docker daemon reachable through a local Unix socket and an image that already exists locally. Fleet never pulls or builds an image, accepts a remote/TCP daemon, or falls back to another provider. The supplied test runner image can be built explicitly by the operator:

```bash
docker build --pull \
  -t agent-fleet-runner:0.1.0-py314-v1 \
  src/agent_fleet/assets/runner

export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet doctor \
  --path /path/to/repo \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --json

uv run fleet init /path/to/repo \
  --runtime fake \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --preview --json

uv run fleet init /path/to/repo \
  --runtime fake \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --yes
```

The final init command first runs a disposable fake-runtime/real-Docker canary through the ordinary workflow. It publishes `.fleet/` only after the final patch, independent verifier command, terminal container inspection, cleanup receipt, completion decision, and `BootstrapReport` hashes all validate. A fake or local-unsafe sandbox can preview the proposal but cannot satisfy this publication gate.

The opt-in real-Docker suite never runs implicitly:

```bash
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE='<preloaded-local-runner-with-python-and-pytest>' \
uv run pytest -q -m docker_integration tests/docker
```

The full Docker suite includes public profiler-detected pytest execution. Runner v1 now includes the genuine required pytest dependencies. The historical Phase5/6 acceptance image `agent-fleet-runner:phase5-chat` and the new runner v1 are local builds, not published images. An unrelated project may require additional reviewed tools; Fleet never installs them during a run.

On macOS with Colima, pytest's temporary root must be under a host path shared into the VM; pass `--basetemp="${HOME}/.cache/agent-fleet-docker-tests"` when the system temp directory resolves beneath `/private/var`.

## Runtime selection and BYOK

The two registered runtimes are `fake` and `pydantic-ai`. The real adapter accepts only explicit `openai:<model>` and `openai-chat:<model>` identifiers. There is no provider inference or fallback: every other prefix fails closed before credential resolution or network access.

BYOK configuration uses a strict `env:NAME` reference. The reference comes from the user's `fleet init` command and is persisted only in Fleet-owned local state; `.fleet/fleet.yaml` records the runtime and opaque provider/model ID, never the credential reference or value. Resolved values must be 8–16384 bytes of visible ASCII, which rejects control characters before HTTP-header construction. The raw value remains in trusted control-plane memory, is registered with the shared redactor, and is passed explicitly to the provider client. It is not put in repository configuration, prompts, artifacts, events, worker input, or the process environment by Agent Fleet.

Preview validates the runtime/model/reference shape and the complete proposed `.fleet/` patch, but does not read the referenced environment variable, migrate or write Fleet state, write the repository, construct a provider client, or use the network. Initialization resolves the environment reference before any project state or `.fleet/` write; it does not make a model request. `fleet run` revalidates the exact registered runtime/model/reference, resolves the credential, and only then may cross the trusted control-plane HTTPS boundary to the selected provider.

Initialization is fail-closed rather than an in-place `.fleet/` reconfiguration command. Before any Run has established an organization head, an identical generated tree can be reused and a credential-reference-only update does not alter repository files. Once a head exists, **all reinitialization is rejected**, including identical bytes and reference-only changes; moving `.fleet/` aside cannot bypass the recorded head. Rotate a key's value through the same recorded environment reference when needed. Supported organization edits use reviewed FleetPatch; a different protected runtime/provider/reference/sandbox setup requires a separately initialized project registration with the old project and state preserved. Fleet never overwrites a mixed or partially changed tree.

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
# Set OPENAI_API_KEY through your normal secure environment mechanism.

uv run fleet init /path/to/repo \
  --runtime pydantic-ai \
  --provider-model openai:gpt-5-mini \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --preview --json

uv run fleet init /path/to/repo \
  --runtime pydantic-ai \
  --provider-model openai:gpt-5-mini \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --yes

uv run fleet doctor --path /path/to/repo --json
uv run fleet run "Fix the canary behavior" --project /path/to/repo --sandbox docker
```

Use `openai-chat:<model>` only when the OpenAI Chat Completions model path is intended; `openai:<model>` uses the Responses model path. Run-time provider flags are optional when they match the reviewed project registration; if supplied, they must match exactly. `--fake-scenario` is rejected for `pydantic-ai`.

`fleet doctor` inspects whether the selected environment reference is configured and valid without resolving/returning its value and without contacting a provider. The Phase 2 OpenAI client pins `https://api.openai.com/v1`, disables SDK redirects, retries, and ambient proxy/CA discovery, clears ambient OpenAI organization/project/admin/webhook selections, and supplies the explicitly resolved authorization value. A final request hook validates the SDK-merged method, endpoint, headers, content length, and serialized body before send; a response hook rejects registered-secret material and removes provider-controlled headers before OpenAI SDK parsing/logging. `OPENAI_BASE_URL`, proxy variables, and unrelated OpenAI identity variables cannot redirect the selected BYOK credential. A generated doctor report exits zero even when `data.healthy` is false: exit zero means diagnostics completed, while readiness is expressed by `data.healthy` and the individual required checks. A missing PydanticAI credential is a failed required check; the fake runtime reports `not_selected` and does not require a provider credential. A command-level Fleet error still returns its documented nonzero category.

The live smoke test is deliberately opt-in and destructive only to its generated disposable fixture. Configure the referenced variable through a secure environment mechanism, then run:

```bash
export AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS=1
export AGENT_FLEET_ENABLE_DOCKER_TESTS=1
export AGENT_FLEET_DOCKER_TEST_IMAGE='agent-fleet-runner:0.1.0-py314-v1'
export AGENT_FLEET_LIVE_PROVIDER_MODEL='openai:gpt-5-mini'
export AGENT_FLEET_LIVE_PROVIDER_CREDENTIAL_REF='env:OPENAI_API_KEY'
uv run pytest -q -m live_provider tests/live/test_provider_smoke.py
```

Without the live opt-in, pytest skips this case. Explicit live opt-in with missing provider or Docker inputs fails setup; readiness checking alone cannot enable requests. The canary now requires genuine isolated command/verifier evidence, approves only observed exact disposable-run requests, and checks credential redaction. It is unrun: no explicit test credential was supplied. Offline FunctionModel or bootstrap tests do not substitute for this release gate.

## Offline preview and fake test mode

Start from a Git repository with at least one commit. Preview performs repository-aware discovery without executing repository code or writing Fleet state:

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet init /path/to/canary-repo --preview --json
```

`fleet init --preview --json` returns RepositoryProfile, ProjectKnowledge, every proposed `.fleet/` file, and a unified diff without creating `.fleet/` or `AGENT_FLEET_HOME`. Semantic profile hashes and serialized artifact hashes use explicitly different fields. Registered secrets in repository-derived profile/configuration data are rejected before parsing, output, or any Fleet write; malformed YAML errors do not retain registered values in their exception chain.

Fake mode remains deterministic test infrastructure and supports legacy Phase 0–2 project registrations, but it cannot prove an isolated bootstrap. A public `fleet init --runtime fake --sandbox fake --yes` therefore runs the canary, returns `BOOTSTRAP_CANARY_FAILED`, and leaves the target `.fleet/` unpublished. Use the Docker quickstart above for a new verified registration.

The init/run path safely tolerates only the exact unchanged `.fleet/` status and referenced configuration contents produced by initialization. Configuration loading accepts only bounded regular non-symlink files. A changed referenced file is rejected before run creation even when Git's untracked-file status is textually unchanged, and explicit patch apply rechecks the run-bound ConfigSnapshot as well as repository/base/status identity. Differing `.fleet/` reinitialization also fails before Fleet state changes rather than overwriting the existing tree. Repository and Fleet-state roots must be disjoint in both directions. Real and fake runtimes use the same workflow, artifacts, gateway, permission broker, and completion gate.

The code-change scripted workflow expects `src/canary_calc/core.py` in the target repository. It changes `divide(a, b)` so division by zero raises `ValueError("division by zero is not allowed")`. `--fake-scenario direct` creates no specialist workspace, `single_engineer` creates one Engineer, and the default creates Engineer plus fresh Verifier. `parallel_engineers` additionally creates a separately scoped `metadata.py`; `specialist` runs the declared read-only research/architecture chain before one Engineer. `repair`, `fail`, `approval`, `inconclusive`, and `verifier_mutation` exercise bounded negative paths. The mutation scenario is denied by PermissionBroker before a write. These are test/demonstration scripts, not model judgments; arbitrary repositories require the real runtime and reviewed command profile.

For an existing fake registration or the test harness, the approval scenario is:

```bash
uv run fleet run "Fix the canary behavior" --project /path/to/canary-repo --fake-scenario approval
uv run fleet approve <request-id> --once
uv run fleet resume <run-id>
```

`fleet deny <request-id>` followed by `fleet resume <run-id>` rejects the run. Repeated resume does not repeat the recorded logical side effect.

## Exact permissions (Phase 4 accepted)

Use Safe mode to require an explicit approval for each new exact command scope. A run grant covers the same action only within its owning run; an always rule covers the same project, role, workflow stage, command arguments, workspace and sandbox conditions in later runs. Engineer approval never grants Verifier approval, and changing a command does not inherit its earlier permission. A durable per-intent dispatch claim permits only one execution owner, even across concurrent CLI processes. An incomplete claim is not replayable.

```bash
uv run fleet permissions configure --project /path/to/repo --mode safe --allow-path src
uv run fleet permissions list --project /path/to/repo --json
uv run fleet permissions explain <request-id> --json
uv run fleet approve <request-id> --once
# Alternatives to --once, not additional flags:
uv run fleet approve <request-id> --run
uv run fleet approve <request-id> --always --scope project
uv run fleet resume <run-id>
uv run fleet permissions explain <rule-id> --json
uv run fleet permissions revoke <rule-id> --json
uv run fleet permissions reset --project /path/to/repo --json
```

Choose exactly one approval lifetime per request. `--allow-path` is repeatable and sets the upper candidate-path ceiling; CoS can narrow it but cannot widen it. Omitted paths preserve existing settings. New init previews show the proposed user policy; repeat init preserves omitted trust mode and paths. Trust lives at `<Fleet state root>/trust/trust.yaml`, using `AGENT_FLEET_HOME` when set or the platform's user-data directory otherwise. Repository `requestedPermissions` cannot grant it. Do not manually edit grant records or the SQLite database.

Approval pauses retain the current Engineer or Verifier identity and exact workspace/sandbox. A fresh CLI process revalidates those bindings before continuing. Verification also checks the canonical patch hash so changed code cannot reuse earlier evidence. Model-call IDs and display prose may change on reconstruction; the original reviewed intent explanation is retained, while execution-bearing fields must remain identical. Milestone 1 durably retains usage and immutable budgets across paused, failed and cancelled invocations; a new physical attempt does not reset its logical agent's step ceiling. General provider-history restoration remains unimplemented.

Historical once-only checkpoint compatibility can restore only the exact persisted original agent after validated state lookup; it does not grant run-wide or persistent authority or override accounting checks. Runs without a reliable budget ledger report `legacy_unknown` and fail closed rather than resume with invented zero usage. Claims remain permanent across restart: grant consumption alone is not permission to dispatch a second time.

Safe mode still permits bounded candidate file operations inside the reviewed scope, while commands prompt. Balanced permits the supported exact reviewed verification commands. `autonomous-sandbox` currently has the same supported-command ceiling as Balanced; it does not enable arbitrary shell, networking or host execution. Local-unsafe commands continue to require exact approval. Revocation removes a grant/rule, not the underlying trust-mode defaults; in Balanced a command may still be allowed by the reviewed baseline. `reset` revokes project grants/rules while preserving its reviewed mode and path ceiling.

After a control-plane crash, recovery is deliberately scoped to one known Run and is not
performed as a blanket startup sweep. First confirm that no other Fleet process still owns the
Run, then invoke:

```bash
uv run fleet recover <run-id> --confirm-owner-stopped --json
```

The command marks an interrupted `RUNNING`/`APPLYING` Run failed and reconciles only its
persisted leases. It is idempotent for an already terminal, fully cleaned Run and refuses durable
ordinary states such as `PAUSED_FOR_APPROVAL`, which must use `resume` or `cancel` instead. An adaptive parent with a retained uncertain driver/continuation claim is an exception: after confirming its owner stopped, recovery may abandon the claimed pause and clean its exact descendants. It never takes over the old execution.

## Adaptive graph execution (Phase 5 Milestone 2 accepted)

CoS proposes a strategy; trusted code checks the reviewed role, scope, delegation, step and concurrency ceilings. Parallel assignments must have explicit subgoals, non-overlapping paths and complete acceptance-criterion coverage. The reviewed workflow `maxParallelAgents` (default 2, maximum 8) limits active children, not total queued tasks. Legacy advanced plans without operational subgoals/criteria remain readable but cannot execute.

Each worker has its own durable Run, TaskSpec, approval principal, workspace and artifact ownership. All workers share the parent's cumulative budget, but not once/run grants. Researcher and Architect may list/read/search/diff their candidate view; they cannot write files, execute commands or request an approval through their tool catalog. Their bounded reports are explicitly untrusted reasoning, not test evidence.

Inspect the parent with `fleet status <parent-id> --json`. The graph includes node/dependency state, child IDs, ordered join receipts and the exact `pending_child_approval_ids`. Approve each displayed child request, then `fleet resume <parent-id>`. `WAITING_FOR_CHILDREN` does not invent a parent approval. Public child resume/apply/cancel/recover are refused; lifecycle operations use the parent. Approved requests preserve original child agent/workspace/sandbox identities across reconstruction.

Independent writers finish in any order; patches join in stable node-ID order into a fresh parent candidate. The parent Verifier checks the complete original task in another clean workspace. A child's full test suite may fail because another child's file is absent; only the joined parent verification can establish completion. Bounded sequential parent repair is explicitly audited and never replays successful children. Explicit `fleet patch apply <parent-id>` still changes only the target working tree.

Driver and parent-continuation claims are durable and have no automatic expiry. Duplicate resume cannot acquire the same work or clean the winning owner's resources. If an owner crashes after dispatch or resume preparation, use exact operator-confirmed recovery, not an automatic retry. Cancellation fences the graph and retains dependency-ordered cleanup; cleanup failures remain recoverable leases. EvidenceBundle includes typed graph/join/child-cleanup provenance, while its verification commands remain parent-owned.

## Persistent CoS chat (Phase 5 accepted)

After successful initialization, use the registered runtime and sandbox:

```bash
uv run fleet chat /path/to/repo
# At the chat prompt:
/help
/status
/permissions <request-id>
/approve <request-id> --once
/resume
/artifacts
/exit
```

Natural-language lines submit a goal; slash commands are deterministic local controls. Approval does not resume automatically. `/deny <request-id>`, `/cancel`, and `/approve <request-id> --run` or `--always --scope project` use the same exact permission service as ordinary CLI commands. `/permissions` without an ID lists the selected project's rules. Inspect and explicitly apply the resulting candidate using `fleet patch show <run-id>` and `fleet patch apply <run-id>` outside chat. A delivered turn does not mean the patch was applied or independently verified: inspect its Run evidence and warnings.

Reopening `fleet chat /path/to/repo` selects the latest project-bound conversation. Use `--conversation <conversation-id>` to select an exact conversation or `--new` for a new one. Automation can submit one goal:

```bash
uv run fleet chat /path/to/repo --conversation <conversation-id> \
  --message "Explain the validation path" --submission-id review-validation-1 --json
```

The submission key is scoped to the conversation. Retrying identical content returns the original turn/Run, even after later turns, without another execution or budget reset; different content under the same key fails. Only one active turn is allowed. New goals are not queued while running or awaiting approval. Public `fleet resume <run-id>` enforces the same conversation ownership as `/resume`.

History contains bounded summaries and authoritative artifact references, not raw provider histories: at most eight recent settled turns and 32 KiB of serialized context. Omitted/truncated context is explicit. Lines are bounded to 16 KiB UTF-8; a conversation holds at most 1,000 turns. Interactive input supports POSIX terminals and pipes with bounded buffering; unsupported descriptors/platforms fail clearly. `--json` and `--submission-id` require `--message`.

While a role is working, `/status` remains responsive. EOF, `/exit`, and repeated Ctrl-C retain and await cancellation/cleanup of locally active work; an already paused approval turn remains available for restart. Use `/cancel` explicitly to cancel a waiting turn. A delayed cancellation stays bound to its original Run and cannot cancel a newer turn. Unknown ownership after a crash never expires into a right to replay; stop its original process, inspect the Run, and use `fleet recover <run-id> --confirm-owner-stopped`. Recovery can fence a conversation-owned interrupted CREATED or PAUSED state, preserves budgets, and releases the turn only after exact root/descendant cleanup. Each new chat invocation must explicitly select `--allow-unsafe-local` before host execution; `/resume` uses that session's choice.

## What is enforced now

- strict Pydantic v2 persistent/external models and safe YAML loading;
- type-specific stable ID prefixes for persistent and public identity fields, including project, run, task, agent, event, approval, grant, artifact, intent, lease, workspace, sandbox, plan, and FleetPatch IDs;
- explicit workflow transitions with transactional per-run events;
- SQLite migrations `0001`–`0007`, durable exact once/run/always approval grants, per-action persistent-rule capability receipts, provider/image/daemon-bound Projects and Runs, cumulative budget accounting, graph/conversation ownership and recoverable worktree/sandbox/execution leases;
- repository-aware no-execution profiling with provenance, ambiguity, read/entry/depth limits, and symlink defenses;
- repository-specific FleetSpec/verification proposals plus immutable profile/knowledge artifacts;
- exact content-addressed ConfigSnapshot and TaskSpec bindings for each run, status inspection, and patch apply;
- validated per-run FleetPlans, dynamic direct/single/pair roles, accepted bounded parallel/specialist child graphs and deterministic parent joins;
- model-style writes routed through ToolGateway and an independently injected PermissionBroker;
- permission-decision events and exact role/stage/action/resource/sandbox matching;
- intrinsically coherent sandbox capability reporting and exact requirement matching across fake, Docker, and separately confirmed local-unsafe providers, with no fallback;
- fixed-path Docker CLI resolution; local-Unix/Linux-daemon, API/capability, immutable-image, and image-environment preflight; one container per command with non-root identity, dropped capabilities, no-new-privileges/seccomp, read-only root, network none, private namespaces, exact mounts/tmpfs/environment, and CPU/memory/no-swap/PID/shm/file-descriptor bounds;
- effective Docker inspection before start, direct argv only, bounded output and single-task process-group timeout/cancellation handling, retained dependency-ordered execution/sandbox/worktree cleanup, exact full-ID/11-label recovery, and a durable pre-dispatch checkpoint that prevents command replay after crashes;
- descriptor-relative, no-follow workspace reads/searches/writes/deletes with inode/type/size/path ceilings; `.git` is shadowed from containers and remains control-plane-only;
- canonical repository-relative path checks with traversal, symlink, filesystem-identity, case-folded protected-path, and bidirectional state/repository containment defenses;
- structured Git subprocess argv with no shell, reset, clean, stash, push, or implicit commit;
- separate candidate and verification worktrees; verifier mutation intents are denied;
- control-plane-computed patch/hash and explicit apply with repository/base/status guards;
- content-addressed artifacts with read-time integrity checks;
- canary-before-publication bootstrap staging with a hash-linked `BootstrapReport`; target `.fleet/` publication requires independently verified Docker evidence plus complete cleanup and never accepts fake/local-unsafe claims;
- structured command evidence and EvidenceBundle/CompletionGate assurance, expanded in `fleet run/status` as changed paths, command results, verdicts, risks, proof gaps, and reason codes;
- recursive registered-secret rejection across mapping keys and values before bootstrap preview/configuration, package prompt/tool/output-schema model input, provider response/tool execution, final serialized provider request, ToolIntent, task, event, approval, or artifact persistence, plus redaction for trusted user-authored diagnostics;
- exact runtime selection with typed capability preflight and no implicit fallback;
- strict `env:NAME` BYOK references, environment-backed inspection/resolution, opaque secret values, and dynamic redaction of raw and common encoded forms;
- strict PydanticAI `ScopeDecision`, `ImplementationReport`, and `VerifierVerdict` outputs plus provider-neutral usage records and bounded provider metadata;
- role- and stage-bound PydanticAI tools whose execution always crosses `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`; whole deferred batches receive side-effect-free catalog schema validation first, then authorized candidate writes use the Fleet-owned candidate-worktree primitive while fake command/approval fixtures use `FakeSandboxProvider`;
- provider errors, timeouts, invalid output, and budget/retry exhaustion mapped to stable Fleet errors without persisting raw provider responses or SDK objects;
- ordinary adapter, integration, CLI, and E2E coverage with live model requests and sockets denied.

## Honest security limitations

`FakeSandboxProvider` is a recorder with `security_level=fake`, `isolation_enforced=false`, and `executes_code=false`; it is not a security boundary. `LocalUnsafeSandboxProvider` executes with the Fleet process's host authority and is also not isolation. Neither can publish a verified bootstrap or turn a model Verifier PASS into `verified_complete=true`.

Docker isolation assumes the local OS account, Docker CLI/configuration, daemon, kernel/VM, and preloaded runner image are trusted. Docker daemon access is itself highly privileged. Fleet accepts only a pinned local Unix endpoint and Linux daemon, but it does not isolate against another process running as the same host user. Workspace and `.git` shadow inode identities are checked at logical sandbox creation, before command preparation, and again after the final daemon probe immediately before dispatch; there remains an unavoidable same-user bind-source replacement window before the daemon consumes the mount request. The Phase 3 real gate was run on one macOS arm64/Colima Linux configuration, not every Docker/kernel/filesystem combination.

On POSIX, the bounded Docker CLI runner starts a private process group, sends at most one immediate destructive group signal, reuses one child waiter, and requires bounded leader reap plus a non-destructive group-absence probe before cancellation can succeed. The proof still identifies the group by a numeric PGID; it is not a cryptographic identity and cannot defend against a hostile same-user process deliberately racing PGID reuse. Removing that residual boundary requires a supervisor, cgroup, or pidfd-class design. In-process cleanup calls with the same terminal target coalesce and survive repeated caller cancellation; conflicting `RELEASED`/`RECOVERED` requests fail closed, but this is not a cross-process ownership lock. Cleanup or termination failure takes precedence over an ordinary cancellation result.

Only `network=none` is accepted by the isolated Phase 3 path. Images must already exist locally and may expose only the allowlisted environment defaults; Fleet does not build, pull, patch, or attest their supply chain. Cgroup-v2 daemons may report `MemorySwappiness=null`; Fleet accepts that only while the inspected memory and memory-swap hard limits are equal, which proves no container swap allocation. A crash after the durable create-dispatch checkpoint but before an exact Docker ID is persisted is intentionally conservative: zero label matches remain `FAILED`, parent resources stay intact, and no command is replayed. If the resource appears later, the operator reruns exact-run recovery after confirming the old owner stopped; a permanent zero remains outstanding for diagnosis rather than becoming an unsafe absence claim. Phase 3 has no cross-process owner-liveness lock, so it intentionally does not run destructive recovery automatically on every CLI startup.

One overall model verdict cannot independently establish multiple acceptance criteria. Milestone 1 adds `structured_criterion_results` with exact current independent-verifier command/artifact references; missing mappings remain inconclusive with `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`, and invalid mappings cannot establish PASS. The normal two-criterion/new-module Docker journey proves this boundary; the same fake-sandbox mapping remains inconclusive. The policy surface covers bounded candidate operations, exact reviewed verification commands, and one explicit fake approval fixture. Phase 4 adds a separately reviewed user path ceiling, not an inference of path intent from natural language; target-checkout mutation still requires explicit patch review/apply. There is no approved isolated-worker networking, remote/hosted sandbox, arbitrary shell surface, external write, or keyring/second-provider integration. Persistent CoS chat is accepted; the working-tree FleetPatch lifecycle and its remaining gates are described above.

The Phase 5 candidate delivery path is intentionally text-only: changed or deleted binary files, unsafe file types, protected paths and changed Git indexes fail closed. New regular UTF-8 files are included in canonical patches; unchanged binary assets may remain in a repository. This avoids concealing registered secrets inside Git's encoded binary-patch format. Ignored paths retain Git ignore semantics; there is no global cache-name exclusion. Generated test fixtures explicitly ignore their Python test caches. New-file snapshots are bounded to 1,024 files, 2 MB per file and 8 MB total; emitted patches are limited to 16 MB, while model patch context retains its smaller 120 KB bound.

The BYOK external boundary is provider HTTPS from the trusted control-plane process. Model prompts and selected project/task context are therefore disclosed to that provider according to its terms. `max_total_tokens` is enforced from provider-reported usage after each response and before continuations/tools; it is not a pre-spend billing ceiling, so a first or final request can report more total tokens than remained. `max_tokens` still bounds requested output. The response hook runs before OpenAI SDK response handling, but Fleet does not install global logging filters: a caller that programmatically enables low-level transport (`httpx2`/`httpcore2`) DEBUG logging may log transport metadata before that hook. Normal Fleet CLI operation and `OPENAI_LOG` do not enable those low-level loggers. Provider-native shell, filesystem, MCP, hosted tools, and arbitrary model-selected network tools are disabled. Installed adapter code shares the control-plane process's OS authority; isolation from arbitrary third-party adapter code is not claimed.

Local SQLite/events are append-only through the application API but are not tamper-proof against the local OS user. Git worktree cleanup force-removes only Fleet-owned paths beneath `AGENT_FLEET_HOME`; it never resets, cleans, stashes, or discards the target checkout.

Git subprocesses resolve an absolute executable outside repository/Fleet-state-controlled `PATH` entries using lexical, canonical, and filesystem-identity containment; require stable top-level/git-dir/common-dir identity; ignore global/system config; disable hooks, fsmonitor, replacements, lazy fetching, credentials, signing, and external diffs; reject any repository-local executable filter/diff/hook/include surface without copying its name into a later argv; and use only an explicit subcommand allow-list. Invalid repository errors omit unresolved canonical paths and underlying untrusted exception chains. This is a strong Phase 1.5 ceiling, not a multi-user isolation boundary: a same-OS-user process can still race repository-local config between the non-executing config probe and a later Git command. Git output is not yet byte-capped, and a parent-process timeout does not prove that malicious descendants were reaped. A future shadow Git metadata/index boundary plus process-group/output enforcement is required before hostile multi-user repositories are in scope.

Patch application updates the original working tree only. It does not stage, commit, merge, push, or create a pull request.

## Roadmap boundary

- Phase 1.5: completed offline foundation—repository profiling, validated adaptive FleetPlan, independent PermissionBroker, sandbox capabilities, EvidenceBundle/CompletionGate, and FleetPatch schema validation.
- Phase 2: implemented explicit BYOK `env:NAME` references and the PydanticAI runtime behind the project-owned runtime/tool contracts.
- Phase 3: completed local Docker sandbox, bounded file/command tools, deterministic recovery, and evidence-gated bootstrap.
- Phase 4: accepted three-state policy, exact once/run/project trust, audited revocation and safe approval resume.
- Phase 5: accepted cumulative budgets, all five adaptive strategies and persistent bounded CoS chat.
- Phase 6: accepted reviewed FleetPatch publication, required verification rules and audited rollback/recovery.
- Phase 7: implemented release candidate; final full/platform gates and GitHub delivery pending. Owner license and live-provider proof remain separate public-release gates.

Phase0–6 establishes local execution, exact permissions, evidence, durable budgets, adaptive execution, persistent chat and reviewed FleetPatch evolution. Phase7 release hardening/platform proof and live-provider/license gates remain distinct. See [release procedure](docs/RELEASE.md), [data disclosure](docs/DATA_HANDLING.md), [dependency policy](docs/DEPENDENCIES.md) and [security checklist](SECURITY.md).

## Quality gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python -m agent_fleet.schemas.generate --check
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:phase3 \
uv run pytest -q -m docker_integration tests/docker
```

## Verification snapshot (Phase 5 accepted, 2026-09-05)

The frozen chat/workflow implementation passed on macOS arm64/Colima. Source/test aggregate `2f806013a7e029b5dea20c08ca64a94a4dd135a156a65662bfa31a859ec8b3f3` remained unchanged through all behavioral gates. This is a byte-checksum, not a Git commit. After those gates passed, only the CLI whole-phase marker and its two assertions changed from 4 to 5. Final source/test checksum is `f7e5d377c89c21876052841809c7efa454cbd20764420a5465b7f0a868ec89f6`; the focused metadata/package/static refresh passed as recorded in the [chat acceptance log](.agent/plans/2026-09-05-persistent-chat.md#final-acceptance-command-log).

| Gate | Exact result |
| --- | --- |
| Complete default suite | `1472 passed, 14 skipped in 1354.35s`; thirteen Docker and one live-provider case gated. Both opt-ins disabled. |
| Separately enabled real Docker | `13 passed, 4 deselected in 101.98s`; zero managed containers and zero outstanding leases across 24 state databases. Nine recovered historical leases remain as audit records. |
| Unit / contract | `716 passed in 67.88s` / `396 passed in 9.57s`. |
| Marked integration / subprocess E2E | `251 passed, 85 deselected in 952.14s` / `19 passed in 255.40s`. |
| Fresh independent conversation safety | `29 passed in 51.59s`; root replay `29 passed in 51.80s`. |
| Dependency/static/schema | Lock resolved 51, sync checked 49; Ruff format checked 217 files, lint passed, mypy passed 186 files, all 65 schemas and whitespace checks passed. |
| Initial archives | Offline wheel/sdist and schema tests: `5 passed in 3.29s`; each archive has 178 package files, 65 schemas, seven migrations and five prompts. Documentation-final refresh follows the metadata update. |
| Post-acceptance phase marker | CLI/archive/schema group `35 passed in 32.52s`; final Ruff format checked 219 files, lint passed, mypy passed 186 files, schema and whitespace checks passed. |
| Documentation-final archives | Wheel/sdist rebuilt and schema/archive read-back: `5 passed`. Archives match source and README bytes. A preceding README-frozen repeat took 1.99s; the acceptance log records the final refresh after this result entry. |

The normal public bootstrap→chat→Safe approvals→restart→real pytest→independent verdict→explicit patch apply journey passed in Docker with offline FunctionModel responses. Both Engineer and Verifier ran three actual tests, target files remained unchanged before apply, and exact turn/Run/ledger identities survived reconstruction. The local pytest runner image is `sha256:15245c81b1efb7a68bad269f03737955eb5e6a2b7fc79aa98faa49c93a899851`, explicitly built without pull/network from genuine cached dependencies. It is not a published image or fresh-user install proof.

Independent review found and fixed a cancellation race that could target a newer turn and a terminal-fence reconciliation gap. The failing regressions and initial fixture-assumption failures remain in the living plan and are superseded by the frozen passes above. No live provider or actual provider credential was used. Phase 6/7, detailed guide, fresh-user/platform installation proof, final GitHub merge and owner-license/live-provider release gates remain open.

## Verification snapshot (Phase 5 Milestone 2 accepted, 2026-09-05)

The frozen graph slice passed on the local macOS arm64/Colima environment. Its source/test aggregate checksum remained `4cbef9616084ad1465ee5fd84b97f81763f282bc95b96c11b5bb7d35cfeafeb9` throughout final testing; this is a byte-checksum, not a Git commit. The [graph acceptance log](.agent/plans/2026-09-05-adaptive-graph.md#final-acceptance-evidence) records the gates without adding overlapping test counts.

| Gate | Result |
| --- | --- |
| Complete default suite | `1344 passed, 13 skipped in 1160.72s`; twelve gated Docker cases and one gated live-provider case. Both opt-ins were explicitly disabled. |
| Separately enabled real Docker | `12 passed, 3 deselected in 140.05s`; zero managed containers and zero active leases across all 22 test state databases. |
| Subprocess E2E | `9 passed in 214.64s`. |
| Artifact/delivery/normal graph regression | `16 passed in 164.85s`; independent delivery audit separately passed `11 passed in 144.48s`. |
| Static/dependency/schema gates | Lock resolved 51 packages; sync checked 49; final Ruff format refresh checked 203 files (202 at initial freeze), lint passed, mypy passed 172 source files, and all 55 schemas passed drift checking. |
| Package checks | Documentation-final archive/schema checks: `4 passed in 4.37s` (preceding source-only refresh: `4 passed in 2.82s`). Both archives match source and README bytes; the installed-wheel smoke passes against existing locked dependencies. Archives contain 161 package files, 55 schemas, six migrations and five prompts. |

The pre-final marked integration attempt failed (`2 failed, 212 passed, 85 deselected in 823.08s`): terminal rehydration could not release its owner, and missing child evidence leaked a raw filesystem error. Those defects and embedded plan/join/cleanup consistency gaps were repaired and re-proved by the focused and final frozen suites. The failed attempt is retained, not counted as acceptance.

Normal offline FunctionModel and real-Docker journeys prove scoped parallel/specialist execution, fresh joined-patch verification and explicit parent-only application. Child test results cannot replace parent evidence; FakeSandbox remains INCONCLUSIVE. Unknown dispatched ownership is not replayable and requires operator-confirmed recovery. No live provider or actual provider credential was used. M2 was subsequently committed and pushed as `7a70b1a`; chat/full Phase 5 acceptance, Phase 6/7, fresh-user/cross-platform installation, final GitHub merge and owner-license/live-provider release gates remain open.

## Verification snapshot (Phase 5 Milestone 1 accepted, 2026-09-05)

This frozen development-slice acceptance covers simple-path budgets and evidence, not the whole Phase 5 or an MVP release. The [Milestone 1 command log](.agent/plans/2026-09-05-adaptive-workflow-chat.md#milestone-1-command-and-evidence-log) records the exact commands and earlier intermediate results.

| Gate | Result |
| --- | --- |
| Complete default suite | `1170 passed, 11 skipped in 648.79s`; ten gated Docker cases and one gated live-provider case. |
| Separately enabled real Docker | `10 passed, 1 deselected in 62.24s`; zero managed containers and zero outstanding leases across 18 test state databases. |
| Static/dependency/schema gates | 181 files formatted; lint passed; mypy passed for 155 source files; offline lock/sync, schema drift and whitespace checks passed. |
| Offline archives | Wheel/sdist each contain 140 package files, 43 schemas, five migrations and three runtime prompts, with exact checkout-byte identity. |
| Wheel-content smoke | Direct wheel import, CLI version `0.1.0`/whole-phase metadata `4`, schema resources and fresh migration through schema 5 passed against locked dependencies. |

The new normal PydanticAI protocol test uses an offline FunctionModel with actual gateway operations. Separate Docker Engineer and fresh Verifier commands each run three fixture tests; exact references establish two PASS criteria and verify a new text module in the canonical patch. The target remains unchanged until explicit apply after control-plane reconstruction. FakeSandbox remains INCONCLUSIVE. Budgets survive restarts and unknown requests; they are not a guaranteed pre-spend billing cap.

No live provider or actual provider credential was used. A clean network-disabled installation was attempted but remains unproven because required packages, including PyYAML, are absent from the local cache. This historical snapshot predates graph acceptance, which is recorded above. M1 was committed as `ab28aaa` and subsequently pushed to the development branch; persistent chat, full Phase 5, Phase 6/7, fresh-user/cross-platform release proof and the owner license decision remain open. No main-branch merge or published release is claimed.

## Verification snapshot (Phase 4 accepted, 2026-09-05)

The final Phase 4 source acceptance passed on the local macOS/Colima setup and was subsequently committed as `2e93092`. Results below are retained as historical Phase 4 evidence from the [completion plan](.agent/plans/2026-09-05-mvp-completion.md), not the newer Milestone 1 counts or a published release claim.

| Gate | Result |
| --- | --- |
| Complete default suite | `1001 passed, 10 skipped in 431.79s`; exactly nine opt-in Docker skips and one opt-in live-provider skip. |
| Unit / contract | `510 passed in 53.30s` / `281 passed in 4.47s`. |
| Marked integration / subprocess E2E | `156 passed, 49 deselected in 311.72s` / `4 passed in 44.40s`. |
| CLI after Phase 4 metadata synchronization | `30 passed in 22.52s`; static/schema checks and offline archives were rebuilt successfully afterward. |
| Static checks | Ruff format: 165 files; lint passed; mypy: 141 source files; generated-schema and diff checks passed. |
| Separately enabled real Docker | `9 passed in 42.32s`; zero remaining Fleet-managed containers. |
| Offline archive build/inspection | Wheel and sdist each contain 129 package files, including 37 schemas, four migrations and three runtime prompts. |

The regressions cover once/run/always across rebuilt processes, exact current-policy intersections, mutation-audit/reset failures, one-winner dispatch, stable role checkpoints, model-reason continuity and fresh Docker verifier evidence. Archive inspection is not a fresh-user installation or cross-platform release proof. **No live provider was run or live credential used.** Phase 5–7, the detailed user guide, live-provider acceptance and owner license choice remain open. Earlier snapshots below are retained as historical evidence, not current Phase 4 counts.

## Verification snapshot (Phase 1.5 baseline, 2026-09-04)

The Phase 0/1.5 acceptance suite passed offline on Python 3.14.6, Git 2.50.1 (Apple Git-155), `uv` 0.12.9, Ruff 0.16.6, mypy 1.20.2, and pytest 9.1.1:

- dependency reconciliation: `uv sync --all-extras` passed with 29 packages resolved and 28 checked;
- formatting: `ruff format --check .` passed across 107 files;
- lint: `ruff check .` passed;
- type checking: `mypy src tests` passed across 91 source files;
- tests: an independent read-only acceptance run reported unit `188 passed in 1.41s`, contract `18 passed in 1.52s`, integration `95 passed in 85.02s`, offline subprocess E2E `3 passed in 8.41s`, and the combined suite `304 passed in 99.23s`;
- schema drift: `python -m agent_fleet.schemas.generate --check` passed;
- packaging: `uv build` produced `dist/agent_fleet-0.1.0.tar.gz` and `dist/agent_fleet-0.1.0-py3-none-any.whl`; archive inspection confirmed the CLI, migration, and new ConfigSnapshot/TaskSpec/FleetPlan/sandbox/command/evidence/FleetPatch schemas are included;
- patch hygiene: `git diff --check` passed.

The independent verifier also reran the UTF-8 output-boundary attack, Git/YAML/FleetPatch security probes, package archive inspection, and implementation/path/credential scans. It returned PASS with candidate identity `8be5e049a0af0220202b2ca6472e316718a436ee9e3f00a23f7640f2e0f03e21` unchanged from the start through the end of the review.

A separate disposable manual run exercised Python and Node repository previews, `doctor`, `init`, `run`, `status`, `logs`, `artifacts`, `patch show`, and `patch apply`. Both previews identified the correct ecosystem and wrote no repository or state files. Doctor reported healthy. The fake run reached `READY_FOR_REVIEW` with `engineer_verifier`, persisted 48 ordered events and 12 run artifacts, reported `verified_complete=false` with `PROOF_GAPS_PRESENT` and `SIMULATED_EVIDENCE_ONLY`, and produced patch SHA-256 `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`. Applying it changed only `src/canary_calc/core.py`; independent behavioral assertions and `git diff --check` passed.

## Verification snapshot (Phase 2 local candidate, 2026-09-04)

The Phase 2 candidate passed the required offline matrix on Python 3.14.6, Pydantic 2.13.5, PydanticAI 2.39.0, OpenAI SDK 3.8.0, Git 2.50.1 (Apple Git-155), `uv` 0.12.9, Ruff 0.16.6, mypy 1.20.2, and pytest 9.1.1:

- `uv lock --check` and `uv sync --all-extras`: passed; 51 packages resolved and 49 checked;
- `uv run ruff format --check .`: 129 files already formatted; `uv run ruff check .`: passed;
- `uv run mypy src tests`: passed across 108 source files;
- unit: `279 passed in 8.70s`; contract: `68 passed in 2.40s`; marked integration: `84 passed, 38 deselected in 87.89s`; offline subprocess E2E: `3 passed in 17.90s`;
- combined `uv run pytest -q`: `473 passed, 1 skipped in 133.23s`; the one skip was the explicitly gated live-provider canary;
- schema drift and `git diff --check`: passed;
- `uv build --offline`: passed; wheel and sdist each contain 97 files, including 3 runtime prompts, 17 JSON Schemas, and migrations `0001`/`0002`, with no tests or `.agent` plan files;
- the newly built wheel imported directly and `fleet version --json` returned `0.1.0` against the locked dependency environment; a dependency-cold, network-disabled venv install was not claimed because the local uv cache lacked PyYAML.

The opt-in live-provider smoke was **NOT RUN: no explicitly supplied credential**. Fleet did not discover or reuse an ambient credential. These results establish the adapter, control-plane, persistence, security, packaging, and offline workflow behavior—not live model quality, provider availability, Docker isolation, real project-test execution, a pre-spend token ceiling, hostile low-level transport logging protection, deterministic natural-language path intent, or cross-platform release coverage. The living Phase 2 ExecPlan records the final frozen identity and independent-verifier result before delivery.

## Verification snapshot (Phase 3 candidate, 2026-09-04)

The initial Phase 3 candidate passed the matrix below and was merged through PR #3. A later post-merge completion audit exposed a real Docker CLI cancellation race (`1 failed, 5 passed`), so this historical snapshot is not the final acceptance claim; the 2026-09-05 follow-up snapshot below supersedes it.

- `uv lock --check` and `uv sync --all-extras`: passed; 51 packages resolved and 49 checked;
- `uv run ruff format --check .`: 148 files already formatted; `uv run ruff check .`: passed;
- `uv run mypy src tests`: passed across 126 source files;
- unit: `330 passed in 11.10s`; contract: `250 passed in 3.20s`; marked integration: `87 passed, 47 deselected in 106.02s`; offline subprocess E2E: `4 passed in 23.17s`;
- combined `uv run pytest -q`: `719 passed, 7 skipped in 173.04s`; six skips were the separately gated real-Docker cases and one was the explicitly gated live-provider canary;
- schema drift and `git diff --check`: passed;
- `uv build --offline`: passed; wheel and sdist each contain 118 files, including 28 JSON Schemas, migrations `0001`–`0003`, and all three runtime prompts, with no tests, `.agent` plan files, local project path, or registered acceptance-secret sentinel.

The opt-in real-Docker suite then passed `6 passed in 12.72s` against Docker CLI 29.8.0, Docker server 29.5.2, Colima's local Unix endpoint, Linux/arm64 daemon identity `815f9bce2b2930154aaaf49cf86667332a3b576d6b85a92ed070ff9d1a0971fb`, and immutable image `sha256:08a5a9124f184f29018f59c1abbe7015a0498a447d5aecd60b18029316465379`. A post-suite exact-label query found zero Fleet-managed containers.

A disposable fake-runtime/real-Docker bootstrap acceptance on the repaired composition root produced read-only proposal hash `b82322ef1bf9ee67902aac22921b1400d2065b7d35fe46095804fb0053960a48`, canary Run `run_b610d8af67ce4e549534dd37bcd4ed32`, final patch hash `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`, capability hash `7091e20f0d4fdbca15834b94c4d67c132f51ac0b122891b164c6a669a8915853`, and command-spec hash `ef810445d282c54d3adb9eb3cd8100287268a496aa547c323ca06f401865cfc1`. Fresh Engineer execution `exec_f3e092b89e3f4c1e8da8e9b6e68adaa3` and Verifier execution `exec_c1fcb4780b9f4353b18a2b53a844bae6` both exited zero and each emitted exactly one Fleet-owned boundary marker. EvidenceBundle `art_3a9a3ec4507b448fa4ce057374da6d62` had hash `c6bb00fc640a41c35170d70f08c41015247cc45090c05178e385cfa6d7505dd3`; BootstrapReport `art_5fe0d82e02df4fa898bcd63c1767b7ab` had hash `2055c34a4e52d54974fd0f2bebce009a4b16f8cd622c000258b804f2533d55b1`. The result was `verified_complete=true`, verdict `pass`, zero proof gaps, 72 ordered events, 16 run artifacts, zero outstanding leases, zero remaining managed containers, target `.fleet/` publication only after success, an intact outside-mount host sentinel, and no raw or base64-encoded registered-secret sentinel in target or state bytes.

This establishes the Phase 3 local Docker boundary on the tested macOS arm64/Colima configuration, not every Docker/kernel/filesystem combination. Docker still shares the host kernel rather than providing a VM boundary, Fleet has no portable disk quota for the writable workspace bind, and `network=none` retains container loopback. Exact-run crash recovery is deliberately operator-confirmed because Phase 3 has no cross-process owner-liveness lock. The opt-in live-model-provider smoke was **NOT RUN** and no live credential was used; Phase 3 acceptance used the deterministic fake runtime to test the real sandbox and evidence path.

## Verification snapshot (Phase 3 cancellation repair, 2026-09-05)

The follow-up acceptance repair addresses the post-merge race rather than accepting a passing rerun. `BoundedProcessRunner` now owns one retained termination task across timeout, output overflow, pipe drain, and cancellation; uses one waiter; proves process-group absence after bounded reap; and reports typed invocation versus termination failures. Docker, gateway, sandbox creation, public cancellation/recovery, whole-run cleanup, and direct lease cleanup all retain their exact cleanup task through repeated cancellation. Cleanup errors win over cancellation, same-target callers coalesce, conflicting terminal targets fail closed even in the completed-before-registry-removal window, and public cancellation retries outstanding leases from a previously failed attempt.

The exact repair candidate passed:

- supported Python process-runner matrix: Python 3.12.14, 3.13.15, and 3.14.6 each passed `13 passed`;
- dependency/static gates: `uv lock --check` resolved 51 packages; `uv sync --all-extras` resolved 51 and checked 49; Ruff reported 148 formatted files and no lint findings; mypy reported no issues in 126 source files; generated-schema drift and `git diff --check` passed;
- focused cancellation/provider/gateway/resource matrix: `226 passed`; the 12 highest-risk cancellation cases then passed 25 consecutive runs (`300/300` aggregate);
- unit: `341 passed in 13.61s`; contract: `257 passed in 3.64s`; marked integration: `93 passed, 49 deselected in 131.49s`; offline subprocess E2E: `4 passed in 26.52s`;
- combined offline suite: `745 passed, 7 skipped in 225.97s`; the skips were exactly six separately enabled Docker tests and the explicitly gated live-provider canary;
- real Docker: the six-test suite passed `6 passed in 14.21s`; the original timeout/output/cancellation/orphan scenario then passed 25 consecutive runs on the same final tree, and the global `agent-fleet.managed=true` query returned zero containers;
- packaging: `uv build --offline` produced wheel and sdist with 118 files each, 28 JSON Schemas, migrations `0001`–`0003`, and three runtime prompts. Neither archive contains tests, `.agent`, a local acceptance path, or a known acceptance sentinel; the five repaired source modules match both archives byte for byte. The wheel imported directly and `fleet version --json` returned Phase 3/version 0.1.0 against the locked environment.

The final standalone manual acceptance again used a generated Git repository, deterministic fake runtime, real Docker, a random registered provider-secret sentinel, and a host sentinel outside every mount. Read-only preview produced proposal hash `b82322ef1bf9ee67902aac22921b1400d2065b7d35fe46095804fb0053960a48`. Verified initialization created target Project `prj_9cfd0dafd47749188e07a3e49c893cda`, canary Project `prj_d96ac8d97c144a1298037a340e19b754`, Run `run_82821c1c885c442fa93c5f80065a1131`, Task `task_3bcd307dc28e4cb48d64d5850896f879`, Engineer `agent_747893bad02d4521abcc79e500e8c7c3`, and fresh Verifier `agent_382cb26765d64936843fe08e801c4353`. Engineer execution `exec_cc3c06632e6c4e0cbc7163c8977e06ca` produced observed evidence; Verifier execution `exec_b100217ded4048fc96f0e050a5e13898` produced independently verified evidence. Both exited zero and emitted exactly one Fleet-owned sandbox-boundary marker.

The final patch hash was `11c4bbdd87dabff7d9f98d68c7e5c20642d00ba26c68e1b192eef60873629ac5`; capability hash `7091e20f0d4fdbca15834b94c4d67c132f51ac0b122891b164c6a669a8915853`; command-spec hash `ef810445d282c54d3adb9eb3cd8100287268a496aa547c323ca06f401865cfc1`. Verifier verdict `art_9cddb168962a4f9099c97424178e52d5` had hash `581ba27391d78c0e431f8f1e5424f558bd1ded146e4adc1667d767c3aace2a2f`; cleanup receipt `art_efafdc64433c483f936e9b30878b71a3` had hash `29a84bb8182f294c5fe939c865ee4b813a9b85aa38bb802310123250f89b809e`; EvidenceBundle `art_d889b4685b634d8f8772847eb6b50aa0` had hash `3a0dc52496c4c04b997a1298e4b1b224ce4d20409ff352c8209c28dac46757d1`; and BootstrapReport `art_dc375e971c0f47a486435e231e5783dc` had hash `f23d68e8676bef7630f5268831259eef82dccff3f642d4b4bc702284aad27963`. The result was `verified_complete=true`, verifier verdict `pass`, zero proof gaps, 72 contiguous events, 16 run artifacts, zero outstanding leases, zero worktree entries, zero managed containers, publication only after verification, an intact host sentinel, and no raw or Base64-encoded registered secret in target or state bytes.

Two independent read-only reviews returned `FREEZE: YES` with no P0/P1/P2 implementation or test finding. The final real gate used Docker client 29.8.0, server 29.5.2/API 1.54, local Unix context `colima`, Linux/arm64 daemon identity `815f9bce2b2930154aaaf49cf86667332a3b576d6b85a92ed070ff9d1a0971fb`, and immutable image `sha256:08a5a9124f184f29018f59c1abbe7015a0498a447d5aecd60b18029316465379`.

Remaining limits are explicit: this proves the tested macOS arm64/Colima configuration, not every Docker/kernel/filesystem combination; Docker is not VM-strength isolation; writable bind mounts have no portable disk quota; `network=none` retains loopback; cleanup coalescing and owner checks are process-local; and numeric PGID identity relies on the stated trusted-same-user boundary. No live provider call was made. A dependency-cold offline wheel installation was attempted but not claimed because the local uv cache lacks an installable PyYAML distribution; direct wheel import and CLI execution against the locked dependency environment passed.

See `AGENTS.md`, `docs/`, and the active plan under `.agent/plans/` for architecture and security contracts.
