# Agent Fleet

Agent Fleet is a **local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization**. A user gives goals to one Chief of Staff (CoS); the control plane assembles the smallest valid team, constrains its authority and execution boundary, and delivers reviewable changes with evidence.

It is deliberately not a generic multi-agent chat framework or a permanent roster of named bots. Models propose scope, plans, actions, and organizational changes. Deterministic application code validates those proposals, owns permissions and sandbox selection, computes the canonical patch, and decides what the available evidence can prove.

This repository implements **Phase 0 through Phase 6**: deterministic repository profiling, all five bounded adaptive strategies, independent exact permissions and user-owned persistent trust, content-addressed evidence, real Git worktrees, guarded patch application, explicit BYOK PydanticAI, a hardened local Docker execution boundary, durable cumulative budgets, persistent CoS chat and reviewed versioned organization evolution. The deterministic fake runtime remains available for offline development and tests; no live model-provider call is required for the bootstrap canary.

Phase7 adds packaged runner/learning assets, fresh-install/upgrade/scale verification, security tooling and platform CI. The [current verification table](#release-candidate-verification-2026-09-05) reports the repaired candidate and distinguishes actual results from pending gates. The CLI's highest fully accepted whole-phase marker remains6: the Phase7 public-release gate still requires an explicitly authorized live-provider canary and an owner-selected license. Neither has been supplied, and neither is inferred from automated tests.

The [detailed user guide (简体中文)](docs/USER_GUIDE.md), also bundled in the distribution, covers installation, initialization, BYOK, chat, adaptive teams, exact permissions, evidence/code review, organization evolution and both recovery procedures. [PR #5](https://github.com/meyowu/agent-fleet-codex-kit/pull/5), the [completion plan](.agent/plans/2026-09-05-mvp-completion.md) and the [acceptance ledger](docs/MVP_ACCEPTANCE.md) track GitHub delivery separately from public release.

Three sandbox providers are registered. `DockerSandboxProvider` is the isolated path and creates one inspected, resource-bounded, network-disabled container per reviewed command from an already-local immutable image. `FakeSandboxProvider` records commands without executing them. `LocalUnsafeSandboxProvider` executes directly on the host only after a separate `--allow-unsafe-local` confirmation and can never count as isolated evidence. Provider selection is exact and immutable for a project/run; Docker failure never falls back to host execution.

## Product north star

Six capabilities determine whether Agent Fleet provides differentiated value:

| Capability | Current implementation boundary | Remaining target |
|---|---|---|
| Repository-aware bootstrap | **Enforced:** bounded static inspection finds supported ecosystems, build systems, boundaries, exact candidate commands, provenance, confidence, and ambiguities; preview is read-only; init stages the proposal, runs a disposable canary through the normal Docker workflow, validates a hash-linked `BootstrapReport`, proves cleanup, and only then publishes `.fleet/`. | The canary is a deterministic Fleet-owned fixture; executing arbitrary target-repository setup or networked commands remains out of scope. |
| Adaptive Fleet | **Enforced:** persistent project-bound CoS chat; every run has a validated `FleetPlan`; direct/single/pair create only planned roles. Parallel Engineers use scoped child runs and stable joins; read-only Researcher/Architect reports follow declared dependencies. | Unconstrained scheduling, background/multi-machine fleets and general provider-history restoration remain outside this MVP. |
| Independent permission control plane | **Phase 4 accepted:** ToolGateway re-evaluates current role/workflow/task/user/sandbox ceilings; exact once/run/project rules, explain/revoke/reset, private user-owned trust and durable single-winner dispatch are verified. Phase 5 Milestone 1 preserves cumulative budgets across approval pauses. | Arbitrary shell and approved isolated-worker networking remain unavailable; general provider-history restoration is not implemented. |
| Independent sandbox abstraction | **Enforced local slice:** strict `SandboxRequirements` matching dispatches exact fake, Docker, or separately confirmed local-unsafe providers. Docker pins a local Unix daemon and image ID, inspects effective configuration before start, bounds execution, and recovers exact labeled resources. | Modal and hosted providers, approved network modes, and a multi-user/remote-daemon trust model remain unimplemented. |
| Evidence-first delivery | **Enforced:** exact ConfigSnapshot, TaskSpec, FleetPlan, patch, command inspection/transcript, verdict, cleanup, BootstrapReport, risk, and proof-gap links form content-addressed evidence. Typed criterion references bind joined-candidate and descendant-cleanup provenance through chat and organization versions. Only fresh non-mutating Docker evidence can verify; fake/local-unsafe cannot. | Broader project command/tool coverage and actual model reliability need separate evidence. |
| Versioned Fleet evolution | **Enforced:** CoS delivers immutable proposals and semantic/text diffs; explicit CLI application publishes a whole organization version; current-head rollback creates a new audited inverse. Typed path-conditioned verification skills change required command evidence; actual Linux/macOS native publication tests passed. | No model self-application, permission expansion or protected FleetSpec mutation. Unsupported metadata/filesystems fail closed. |

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

Historical Phase6 acceptance proved organization proposals, native publication and abrupt-process recovery, with1973 default passes and14 separately enabled real-Docker passes before checkpoint `b42cdf9`. The rule-enforcement journey required Engineer and independent Verifier to each run five baseline plus two integration tests, then restored the exact prior rule through an audited inverse. Full commands, failures, hashes and metadata/package refreshes remain in the [evolution plan](.agent/plans/2026-09-05-versioned-fleet-evolution.md). Current release-candidate results are reported below; these historical counts are not additional current gates.

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

On macOS with Colima, pytest's temporary root must be under a host path shared into the VM. Create a **new** directory under an existing shared cache parent; never use an existing project, home or cache root as `--basetemp`, because pytest manages and may remove its contents:

```bash
fleet_test_root=$(mktemp -d "${HOME}/.cache/agent-fleet-docker.XXXXXX")
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:0.1.0-py314-v1 \
uv run --offline pytest -q -m docker_integration tests/docker \
  --basetemp="$fleet_test_root/fixtures"
```

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
- SQLite migrations `0001`–`0008`, durable exact once/run/always approval grants, per-action persistent-rule capability receipts, provider/image/daemon-bound Projects and Runs, cumulative budget accounting, graph/conversation ownership and recoverable worktree/sandbox/execution leases;
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
- strict PydanticAI `ScopeDecision`, `FleetPatch`, `ImplementationReport`, `SpecialistReport`, and `VerifierVerdict` outputs plus provider-neutral usage records and bounded provider metadata;
- role- and stage-bound PydanticAI resource tools whose execution crosses `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`; whole deferred batches receive side-effect-free catalog schema validation first, then authorized candidate writes use the Fleet-owned candidate-worktree primitive while fake command/approval fixtures use `FakeSandboxProvider`. The CoS-only `fleet_content_sha256` helper is pure, has no I/O and grants no authority; it does not use the resource gateway;
- provider errors, timeouts, invalid output, and budget/retry exhaustion mapped to stable Fleet errors without persisting raw provider responses or SDK objects;
- ordinary adapter, integration, CLI, and E2E coverage with live model requests and sockets denied.

## Honest security limitations

`FakeSandboxProvider` is a recorder with `security_level=fake`, `isolation_enforced=false`, and `executes_code=false`; it is not a security boundary. `LocalUnsafeSandboxProvider` executes with the Fleet process's host authority and is also not isolation. Neither can publish a verified bootstrap or turn a model Verifier PASS into `verified_complete=true`.

Docker isolation assumes the local OS account, Docker CLI/configuration, daemon, kernel/VM, and preloaded runner image are trusted. Docker daemon access is itself highly privileged. Fleet accepts only a pinned local Unix endpoint and Linux daemon, but it does not isolate against another process running as the same host user. Workspace identity and the private empty `.git` shadow are rechecked immediately before dispatch. A non-inheritable read-only descriptor pins the shadow inode to prevent reuse after unlink; timestamp checks additionally detect same-inode drift. The descriptor closes on failed preparation or successful logical cleanup. Docker still resolves mount pathnames after the final check; this is not an atomic path handoff or a guarantee for every Docker/kernel/filesystem combination.

On POSIX, the bounded Docker CLI runner starts a private process group, sends at most one immediate destructive group signal, reuses one child waiter, and requires bounded leader reap plus a non-destructive group-absence probe before cancellation can succeed. The proof still identifies the group by a numeric PGID; it is not a cryptographic identity and cannot defend against a hostile same-user process deliberately racing PGID reuse. Removing that residual boundary requires a supervisor, cgroup, or pidfd-class design. In-process cleanup calls with the same terminal target coalesce and survive repeated caller cancellation; conflicting `RELEASED`/`RECOVERED` requests fail closed, but this is not a cross-process ownership lock. Cleanup or termination failure takes precedence over an ordinary cancellation result.

Only `network=none` is accepted by the isolated Phase 3 path. Images must already exist locally and may expose only the allowlisted environment defaults; Fleet does not build, pull, patch, or attest their supply chain. Cgroup-v2 daemons may report `MemorySwappiness=null`; Fleet accepts that only while the inspected memory and memory-swap hard limits are equal, which proves no container swap allocation. A crash after the durable create-dispatch checkpoint but before an exact Docker ID is persisted is intentionally conservative: zero label matches remain `FAILED`, parent resources stay intact, and no command is replayed. If the resource appears later, the operator reruns exact-run recovery after confirming the old owner stopped; a permanent zero remains outstanding for diagnosis rather than becoming an unsafe absence claim. Phase 3 has no cross-process owner-liveness lock, so it intentionally does not run destructive recovery automatically on every CLI startup.

One overall model verdict cannot independently establish multiple acceptance criteria. Milestone 1 adds `structured_criterion_results` with exact current independent-verifier command/artifact references; missing mappings remain inconclusive with `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`, and invalid mappings cannot establish PASS. The normal two-criterion/new-module Docker journey proves this boundary; the same fake-sandbox mapping remains inconclusive. The policy surface covers bounded candidate operations, exact reviewed verification commands, and one explicit fake approval fixture. Phase 4 adds a separately reviewed user path ceiling, not an inference of path intent from natural language; target-checkout mutation still requires explicit patch review/apply. There is no approved isolated-worker networking, remote/hosted sandbox, arbitrary shell surface, external write, or keyring/second-provider integration. Persistent CoS chat is accepted; the working-tree FleetPatch lifecycle and its remaining gates are described above.

The Phase 5 candidate delivery path is intentionally text-only: changed or deleted binary files, unsafe file types, protected paths and changed Git indexes fail closed. New regular UTF-8 files are included in canonical patches; unchanged binary assets may remain in a repository. This avoids concealing registered secrets inside Git's encoded binary-patch format. Ignored paths retain Git ignore semantics; there is no global cache-name exclusion. Generated test fixtures explicitly ignore their Python test caches. New-file snapshots are bounded to 1,024 files, 2 MB per file and 8 MB total; emitted patches are limited to 16 MB, while model patch context retains its smaller 120 KB bound.

The BYOK external boundary is provider HTTPS from the trusted control-plane process. Model prompts and selected project/task context are therefore disclosed to that provider according to its terms. `max_total_tokens` is enforced from provider-reported usage after each response and before continuations/tools; it is not a pre-spend billing ceiling, so a first or final request can report more total tokens than remained. `max_tokens` still bounds requested output. The response hook runs before OpenAI SDK response handling, but Fleet does not install global logging filters: a caller that programmatically enables low-level transport (`httpx2`/`httpcore2`) DEBUG logging may log transport metadata before that hook. Normal Fleet CLI operation and `OPENAI_LOG` do not enable those low-level loggers. Provider-native shell, filesystem, MCP, hosted tools, and arbitrary model-selected network tools are disabled. Installed adapter code shares the control-plane process's OS authority; isolation from arbitrary third-party adapter code is not claimed.

Local SQLite/events are append-only through the application API but are not tamper-proof against the local OS user. Git worktree cleanup force-removes only Fleet-owned paths beneath `AGENT_FLEET_HOME`; it never resets, cleans, stashes, or discards the target checkout.

Git subprocesses resolve an absolute executable outside repository/Fleet-state-controlled `PATH` entries using lexical, canonical, and filesystem-identity containment; require stable top-level/git-dir/common-dir identity; ignore global/system config; disable hooks, fsmonitor, replacements, lazy fetching, credentials, signing, and external diffs; reject any repository-local executable filter/diff/hook/include surface without copying its name into a later argv; and use only an explicit subcommand allow-list. Invalid repository errors omit unresolved canonical paths and underlying untrusted exception chains. This is not a multi-user isolation boundary: a same-OS-user process can still race repository-local config between the non-executing config probe and a later Git command. Ordinary Git command paths are not generally byte-capped; the organization-boundary reader separately bounds/drains output and hashes index bytes. A parent-process timeout alone does not prove malicious descendants were reaped. A future shadow Git metadata/index boundary plus general process-group/output enforcement is required before hostile multi-user repositories are in scope.

Patch application updates the original working tree only. It does not stage, commit, merge, push, or create a pull request.

## Roadmap boundary

- Phase 1.5: completed offline foundation—repository profiling, validated adaptive FleetPlan, independent PermissionBroker, sandbox capabilities, EvidenceBundle/CompletionGate, and FleetPatch schema validation.
- Phase 2: implemented explicit BYOK `env:NAME` references and the PydanticAI runtime behind the project-owned runtime/tool contracts.
- Phase 3: completed local Docker sandbox, bounded file/command tools, deterministic recovery, and evidence-gated bootstrap.
- Phase 4: accepted three-state policy, exact once/run/project trust, audited revocation and safe approval resume.
- Phase 5: accepted cumulative budgets, all five adaptive strategies and persistent bounded CoS chat.
- Phase 6: accepted reviewed FleetPatch publication, required verification rules and audited rollback/recovery.
- Phase 7: implemented local release candidate with full offline, Docker, installed-user and platform verification; final GitHub delivery is recorded in the release plan and PR. Owner license and live-provider proof remain separate public-release gates.

Phase0–6 establishes local execution, exact permissions, evidence, durable budgets, adaptive execution, persistent chat and reviewed FleetPatch evolution. Phase7 release hardening/platform proof and live-provider/license gates remain distinct. See [release procedure](docs/RELEASE.md), [data disclosure](docs/DATA_HANDLING.md), [dependency policy](docs/DEPENDENCIES.md) and [security checklist](SECURITY.md).

## Quality gates

```bash
uv run --offline ruff format --check .
uv run --offline ruff check .
uv run --offline mypy src tests
uv run --offline pytest -q -ra
uv run --offline python -m agent_fleet.schemas.generate --check
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:0.1.0-py314-v1 \
uv run --offline pytest -q -m docker_integration tests/docker
```

## Release-candidate verification (2026-09-05)

Runtime behavioral freeze: `c03fa3d455b073958ade3c4d365a0231319e1b59eb715af3b79bb278bff5d3c3`, checkpoint `329324430e4b712062f045fb613173cf4a8adea7`. The final help-text/CI-assertion refresh has source/test/script hash `c400cdb40fa16bb13d2c1a8732893560ccc91db5fdbf916bdcf6868857378cf6`; its only production delta is corrected resume help wording. Exact final-head checks, documentation/archive refreshes and GitHub delivery are recorded separately in the [release ExecPlan](.agent/plans/2026-09-05-release-candidate.md). Test selections overlap; do not sum these rows.

| Gate | Exact observed result and scope |
| --- | --- |
| Formatting, lint, strict types, schemas, dependency lock | Ruff267 files; mypy219 files on Darwin and Linux;82 schemas; lock55/sync53; whitespace checks passed. |
| Complete default suite | Runtime freeze: macOS `2004 passed,18 skipped in1515.89s`; Linux `1997 passed,25 skipped in994.03s`. macOS partitions:unit1027,contract578,integration372,offline E2E22,four offline Docker cases andone readiness case. |
| Standalone offline adversarial replay | `734 passed in199.76s`; zero skips/errors/failures, structured verdict0. This named subset includes Docker contracts and native publication/recovery. |
| Real Docker boundary | `14 passed,4 deselected in148.37s`; zero skips/errors/failures. macOS arm64/Colima with runner v1 image `sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241`. |
| Docker residue read-back |26 distinct databases:97 released/nine historical recovered leases, no outstanding lease, pending organization operation/head or active chat claim; no managed containers before starting the separate installed journey. |
| Independent shadow/native/proposal review | PASS: `277 passed in20.01s`; extra probes prove no dispatch after replacement/drift, read-only/non-inheritable pin, cancellation retention, cleanup/finalization and valid workspace writes. Not a daemon or Linux run. |
| Fresh installed wheel/sdist/public journey | Documentation-final checks: **3 passed, no skips**;36 locked distributions,82 schemas/eight migrations and the655-line guide in isolated environments. Exact archive identities, commands and durations are recorded in the release plan. |
| Linux/macOS × Python3.12–3.14 | All nine jobs passed in [workflow33986257215](https://github.com/meyowu/agent-fleet-codex-kit/actions/runs/33986257215). Each macOS selection1664 passed; each Linux selection1659 passed/five Darwin skips. Linux standalone security729 passed/five Darwin skips; opt-in jobs passed. Final-head and post-merge runs are linked through [PR #5](https://github.com/meyowu/agent-fleet-codex-kit/pull/5) and the plan. |

Default skips are14 separately tested real-Docker cases,three separately tested installed cases andone unperformed live-provider case. Linux additionally skips five Darwin metadata andtwo case-insensitive-filesystem-only cases, exercised on macOS. CI covers all units/contracts/offline E2E plus selected integrations on six combinations; the complete integration suite additionally runs on Linux3.14 and locally on macOS3.14, not every integration on all combinations.

The public installed Docker journey exercises doctor, Safe/src init, chat with cross-process exact approvals and duplicate-submission read-back, independent real five-test receipts, explicit code apply, persistent-rule revocation and confirmed no-op recovery. A separate installed registration substitutes only offline FunctionModel responses to exercise CoS proposal/diff/apply/rollback. That fixture is neither stock fake behavior nor live-provider inference. Source fresh-process crash and real Docker interruption-recovery tests supply the separate interruption evidence.

Live inference remains **unperformed**. Default opt-in skips are not passes, and automated local/CI acceptance does not establish arbitrary-model reliability, a public release, or a license. The repository remains private; no PyPI publication or public runner registry is assumed. GitHub delivery is complete only after actual merge and remote-main read-back, recorded in the plan.

## Historical acceptance

Earlier checkpoints, exact commands, failed attempts and successful repeats are retained in the [acceptance ledger](docs/MVP_ACCEPTANCE.md) and living plans: [Phase4/completion](.agent/plans/2026-09-05-mvp-completion.md), [budgets/evidence](.agent/plans/2026-09-05-adaptive-workflow-chat.md), [adaptive graph](.agent/plans/2026-09-05-adaptive-graph.md), [persistent chat](.agent/plans/2026-09-05-persistent-chat.md) and [organization evolution](.agent/plans/2026-09-05-versioned-fleet-evolution.md). Historical skips, package limitations and old main-branch identities describe those snapshots, not current acceptance. See the [Chinese user guide](docs/USER_GUIDE.md) for the maintained user journey.
