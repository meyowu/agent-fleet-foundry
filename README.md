# Agent Fleet Foundry

**Give a coding task to a local team of AI agents. Review the patch and test evidence before applying it.**

Agent Fleet Foundry is a command-line tool for working on Git repositories with your own
model API key. A **Chief of Staff (CoS)** scopes the task, an **Engineer** makes
changes in an isolated Git worktree, and an independent **Verifier** checks the
result. You stay in control of permissions and changes to your checkout.

- **Local workflow:** project state, approvals and artifacts live on your machine.
- **Bring your own key:** explicitly choose a provider/model and a local credential reference.
- **Isolated execution:** run project commands in local Docker containers with networking disabled.
- **Reviewable results:** inspect the diff, command results and verification gaps before applying.
- **Persistent sessions:** return to a project conversation and inspect previous tasks.
- **Model-free baseline observations:** explicitly approve an existing check and inspect its retained output without asking an agent to repair the project.

This is an early-stage developer tool. Start with the small learning project below.
Live models can fail or exhaust their budget; an agent saying “done” is not proof
that a change passed verification. [Development history](docs/DEVELOPMENT_HISTORY.md)
and [roadmap](docs/IMPLEMENTATION_ROADMAP.md) are maintained separately.

[中文用户指南](docs/USER_GUIDE.md) · [Security](SECURITY.md) · [Data handling](docs/DATA_HANDLING.md) · [Contributing](CONTRIBUTING.md)

## Quickstart: fork → install → configure → run

Use one terminal for these steps. The example uses the OpenAI/PydanticAI adapter;
you supply a model ID available to your account. Installation and image building
may download dependencies. Actual model tasks use your provider account and may
incur charges.

### 1. Check prerequisites

You need:

- **macOS or Linux** with a local filesystem. Native Windows is not supported for the full workflow.
- **Python 3.12–3.14**, **Git 2.45+**, and **uv**.
- **Docker** with a running local Linux daemon, using a Unix socket.
- An API key for the real-model route, or the **no-key practice route** in step 5.

```bash
uv --version
git --version
docker info
```

Install missing tools using their official instructions: [uv](https://docs.astral.sh/uv/getting-started/installation/),
[Git](https://git-scm.com/downloads), and [Docker](https://docs.docker.com/get-started/get-docker/).
On macOS, Docker Desktop or a local Colima VM can provide the Linux daemon. With
Colima, the project and Fleet state directories must be shared with the VM.
Remote/TCP Docker daemons are not supported.

### 2. Fork and install

Click **Fork** on [this repository](https://github.com/meyowu/agent-fleet-foundry),
then clone **your fork**. Replace `YOUR_GITHUB_USERNAME` below:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/agent-fleet-foundry.git
cd agent-fleet-foundry
uv sync --frozen --all-extras --python 3.14
source .venv/bin/activate
fleet version
fleet --help
```

The activated environment makes `fleet` available even after changing directories.
Install from your reviewed checkout; these instructions do not assume a published
PyPI package or prebuilt public runner image.

### 3. Build the local runner

From the fork's root directory:

```bash
docker build --pull \
  -t agent-fleet-runner:local \
  src/agent_fleet/assets/runner
```

This runner includes Python and pytest for the learning project. Fleet only uses
images already present locally. It does not build images, download dependencies
or install missing project tools during a task.

### 4. Create a small project to try it on

Copy the bundled exercise into a **new, nonexistent directory**. It has five tests
and one deliberate division-by-zero bug. Keep Fleet state outside both repositories.
The paths below are examples; choose unused locations if they already exist.

```bash
export FLEET_DEMO="$HOME/fleet-learning"
export AGENT_FLEET_HOME="$HOME/.local/share/fleet-learning-state"

python - "$FLEET_DEMO" <<'PY'
from importlib.resources import files
import shutil
import sys

shutil.copytree(
    str(files("agent_fleet").joinpath("assets/canary")),
    sys.argv[1],
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
)
PY

git -C "$FLEET_DEMO" init --initial-branch=main
git -C "$FLEET_DEMO" add .
git -C "$FLEET_DEMO" commit -m "Add learning project"
cd "$FLEET_DEMO"
```

If Git asks for an identity, configure your own name and email for this exercise.
Keep `AGENT_FLEET_HOME` consistent when reopening a terminal; it selects your local
state and conversation history. Do not commit or upload that directory.

### 5. Choose a model and supply your API key

For the real-model route, the following Bash/Zsh prompt hides the key while you
paste it. The key value does not appear in the command itself or shell history.
Do this in your own terminal, not in an issue or an agent conversation.

```bash
printf 'OpenAI API key (hidden): '
read -r -s OPENAI_API_KEY
export OPENAI_API_KEY
printf '\n'

export FLEET_RUNTIME=pydantic-ai
printf 'Provider/model ID (for example openai:gpt-5-nano): '
read -r FLEET_MODEL_ID
export FLEET_MODEL_ID
```

Use the full `openai:MODEL_ID` value for the Responses adapter. The model must
support tool calling and structured output. The example is not a guarantee of
access or success with your account. Fleet uses the official provider endpoint;
custom OpenAI-compatible URLs are not supported.

**Prefer a no-key practice run?** Skip the block above and run this instead:

```bash
export FLEET_RUNTIME=fake
```

This route uses scripted agents for the bundled exercise and real Docker tests.
It cannot solve arbitrary tasks. You can later [configure a real model profile](docs/USER_GUIDE.md#3-给不同角色绑定不同模型)
for future tasks, or repeat the exercise with new project/state directories.

### 6. Preview and initialize

First check Docker readiness:

```bash
fleet doctor --path . --sandbox docker --docker-image agent-fleet-runner:local --json
```

Check `data.healthy` and the required checks. `ok: true` only means the diagnostic
command ran successfully; it does not prove model access.

Prepare the initialization arguments. These contain a credential **reference**,
never the key value. Bash and Zsh both support this array:

```bash
fleet_init_args=(
  --runtime "$FLEET_RUNTIME"
  --sandbox docker
  --docker-image agent-fleet-runner:local
  --trust-mode safe
  --allow-path src
)
if [ "$FLEET_RUNTIME" = pydantic-ai ]; then
  fleet_init_args+=(
    --provider-model "$FLEET_MODEL_ID"
    --credential-ref env:OPENAI_API_KEY
  )
fi

fleet init . "${fleet_init_args[@]}" --preview --json
```

Review the proposed `.fleet/` files, allowed paths and test command. Then initialize:

```bash
fleet init . "${fleet_init_args[@]}" --yes
fleet doctor --path . --json
```

Initialization first runs a disposable bootstrap check with scripted agents and
real Docker. It publishes `.fleet/` only after verification and cleanup succeed.
This step makes **no model request**, even with a real runtime selected. `--yes`
confirms initialization, not future permissions. The generated `.fleet/` files
may be versioned; they contain neither the key value nor its environment reference.

### 7. Run your first task

Run the following command in the learning project:

```bash
fleet run 'Fix the canary behavior: in src/canary_calc/core.py, make divide(a, 0) raise ValueError("division by zero is not allowed"). Preserve normal division and independently verify the existing tests. Only change src/canary_calc/core.py.' \
  --project . --json
```

With the real runtime, this is where provider requests and charges begin. Read the
JSON result and copy `data.run_id`. In Safe mode, expect `paused_for_approval` and
a `data.pending_approval_id` identifying the exact command that needs consent.
Set the actual returned IDs below; these are identifiers, not credentials:

```bash
export FLEET_RUN_ID='run_REPLACE_WITH_RETURNED_ID'
export FLEET_REQUEST_ID='perm_REPLACE_WITH_RETURNED_ID'
fleet permissions explain "$FLEET_REQUEST_ID" --json
```

Review the command, role, project and sandbox. If you approve that exact request:

```bash
fleet approve "$FLEET_REQUEST_ID" --once --json
fleet resume "$FLEET_RUN_ID" --json
```

Engineer and Verifier approvals are separate. If the resumed run pauses again,
replace `FLEET_REQUEST_ID` with the **new** `pending_approval_id`, inspect it, then
repeat approve/resume for the same `FLEET_RUN_ID`. Do not rerun the original task to
resolve an approval; that would start another task and may incur more model charges.

Each command above exits before the next command runs. This is the validated
quickstart route. Same-process Session restoration is also supported, with exact
checkpoint and permission checks preserved. See the [Session guide](docs/USER_GUIDE.md)
and its [historical F acceptance](docs/MVP_ACCEPTANCE.md#p1-f--exact-docker-session-restoration-2026-09-12).

### 8. Review and apply the result

Inspect the candidate and its verification evidence:

```bash
fleet status "$FLEET_RUN_ID" --json
fleet artifacts "$FLEET_RUN_ID" --json
fleet patch show "$FLEET_RUN_ID" --json
```

For the successful exercise, expect `ready_for_review`, `verified_complete=true`,
passing Engineer and independent Verifier test evidence, and no proof gaps. If the
run fails or is inconclusive, inspect its reason and artifacts before starting more
paid work. Your original source remains unchanged until you explicitly apply.

When satisfied:

```bash
fleet patch apply "$FLEET_RUN_ID" --json
git diff -- src/canary_calc/core.py
```

Fleet applies the reviewed patch to your working tree. You decide whether to commit
or push it. To continue later, activate the same CLI environment, restore the same
state path and selected key, and enter the project. Use the saved run ID for
inspection, or `fleet run` for a new task.

## Use Fleet on your own repository

After the exercise, choose a committed, clean Git checkout and a runner containing
its required tools. Repeat steps 5–8 there. Inspect the preview's detected commands;
the included Python/pytest image will not run every project's dependencies or Node
toolchain. Adjust `--allow-path` to real paths in that repository, repeating it for
multiple scopes. Keep Fleet state outside your repositories.

For scripts, use `fleet run "Your bounded task" --project /path/to/repo --json`,
then the `permissions`, `approve`, `resume`, `status`, and `patch` commands.
`fleet run --help` lists cumulative request, token, tool and time limits. Token
limits are usage accounting, not a guaranteed billing cap.

## Observe an existing check without a model

For a registered, clean committed project with a prepared local Docker image,
`fleet baseline` can run one already configured verification command after exact
one-time consent. Review the command and boundary, then substitute the returned
review ID and hash:

```bash
fleet baseline plan . --command COMMAND_ID --json
fleet baseline run REVIEW_ID --allow-once --review-sha256 REVIEW_SHA256 --json
fleet baseline show REVIEW_ID --json
```

The retained `observation` exposes bounded, redacted stdout/stderr, exit code,
hashes and truncation flags. Viewing it does not rerun the command. A missing
dependency or failing assertion remains a nonzero business result; this produces
no repair patch or model-completion claim. It does not install dependencies or
prepare an image for you. See the [baseline and Session instructions](docs/USER_GUIDE.md#不调用模型的项目基线检查standalone-cli)
for scope, consent and recovery, and the [six generated repository examples](docs/BASELINE_COHORT.md).

## Data and safety

A real model receives selected source excerpts, task context and tool results.
**Local-first does not mean offline inference.** API keys stay in the trusted
control-plane process; workers do not receive them. State and artifacts can contain
private code and command output, so keep them private. Do not paste unrelated
secrets into source or prompts: redaction cannot discover every unknown credential.

Docker workers run with restricted permissions and networking disabled. The local
OS, Docker daemon and control-plane dependencies remain trusted. This is not a
hostile-host or multi-user security boundary. Read [data handling](docs/DATA_HANDLING.md)
and the [security model](docs/SECURITY_MODEL.md) before using sensitive code.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `fleet: command not found` | Activate the fork's `.venv` using its full path in a new terminal. |
| Docker/image check fails | Start the local daemon and build the exact image tag used in step 6. On Colima, check shared host paths. |
| Credential is missing | Export the selected variable in the same terminal; pass `env:OPENAI_API_KEY`, not its value. Fleet does not automatically load `.env`. |
| Repository is dirty | Review and commit or manually stash your own changes. Fleet does not discard them for you. |
| Initialization refuses an existing project | Do not delete `.fleet/` to reset it. Use model profiles for future model changes; see the user guide for recovery. |
| A task is paused or not verified | Inspect `fleet status`, pending permissions and proof gaps. A successful model response alone is insufficient. |

## Documentation

- [Explicit live Canary selections](docs/LIVE_CANARY_SELECTION.md): bounded per-role
  test configuration and its qualification limits.
- [Known issues](docs/KNOWN_ISSUES.md): current operational limitations.
- [Full user guide (简体中文)](docs/USER_GUIDE.md): model profiles, sessions, permissions and recovery.
- [Baseline cohort](docs/BASELINE_COHORT.md): six generated Python/Node observations and their explicit Docker selection.
- [Architecture](docs/ARCHITECTURE.md) and [configuration](docs/CONFIG_AND_SCHEMAS.md).
- [Contributing](CONTRIBUTING.md): local quality checks and contribution workflow.
- [Development history](docs/DEVELOPMENT_HISTORY.md), [acceptance ledger](docs/MVP_ACCEPTANCE.md) and [roadmap](docs/IMPLEMENTATION_ROADMAP.md).
- [Publication privacy review](docs/PUBLICATION_PRIVACY_REVIEW.md) and [release procedure](docs/RELEASE.md).

## Current verification snapshot

The Engineer terminal contract delivered in [PR #16](https://github.com/meyowu/agent-fleet-foundry/pull/16) sends its unchanged, closed
ImplementationReport schema in strict wire mode. Other terminal compatibility
modes and all local semantic validation remain unchanged. A fixed local
terminal-schema error message distinguishes that stage from malformed call
envelopes without exposing raw provider error data. Focused actual-SDK offline
tests passed **129 cases**, with independent retained-fixture verification.
Offline tests alone do not establish successful live task completion.

The current full local offline suite passed **4,296 tests, with 32 skipped**;
all 4,328 test identities reconcile and all 554 source inputs stayed unchanged.
Independent full/source/static readback passed. The skips are 28 opt-in Docker cases
(including the six baseline cohort cases), three fresh-install and one live-provider
case; they are not passes. Formatting (483 files), lint, type checking (396 source files),
generated schemas, offline lock validation (99 packages) and whitespace checks
also passed. The focused and full counts overlap and must not be added.
The original two timing-sensitive cases ran serially after all heavy
groups stopped; their passes are included in 4,296, not added to it.
Exact separate Docker, adversarial, package/installation and Git delivery results
are maintained in the [living plan](.agent/plans/2026-09-12-engineer-terminal-contract.md)
and [acceptance ledger](docs/MVP_ACCEPTANCE.md#p1-h--engineer-terminal-contract-2026-09-12).
These offline results do not qualify a live Provider/Harness combination.

A historical PR #13 baseline-source real-Docker cohort passed **six cases in 437.84 seconds**,
with independent evidence and exact-scope cleanup readback. The generated Python
and Node repositories produced actual business exit codes **0/2/1/0/1/1**. All six
observations were verified, but only two business checks passed. These are six
generated fixtures with scripted bootstrap agents, not six external projects,
live-model reliability or the 24-task evaluation campaign. Exact independent,
standard-Docker, adversarial, package/installation and Git delivery records are
maintained separately in the [baseline delivery plan](.agent/plans/2026-09-12-baseline-delivery.md)
and [acceptance ledger](docs/MVP_ACCEPTANCE.md#p1-d-and-p1-e--baseline-observations-2026-09-12).

PR #12's delivered Session-restoration slice had its own **4,246-pass/26-skip**
offline result and separately qualified 22-case Docker gate; those historical
F results do not qualify newer baseline artifacts or replace their gates.
PR #11's earlier 4,211-pass/23-skip baseline is preserved in the
[diagnostics plan](.agent/plans/2026-09-12-sdk-response-diagnostics.md), not added to
the current count. OpenAI Agents SDK and LangGraph provide fixed response-failure
messages without changing validation, error codes, permissions, retries or
unknown-usage accounting.

[PR #15](https://github.com/meyowu/agent-fleet-foundry/pull/15) separately delivered
six pinned **real public-repository static observations**: five incomplete
inspections and one complete inspection, all environments still unverified and
all business baselines unchecked. A distinct 61-case readiness regression and
independent evidence readback passed; no target code or model ran. See the
[real-repository report](docs/PUBLIC_REPOSITORY_READINESS.md) for exact discovery
limitations. These are not six passing business projects or cold starts.

The latest completed real OpenAI mixed-Harness attempt (live06, delivered-source
PR #16) **did not pass**: CoS/PydanticAI used `openai:gpt-5-nano`, with Engineer/
OpenAI Agents SDK and the uninvoked Verifier/LangGraph explicitly assigned
`openai:gpt-4.1-nano-2025-04-14`. Three requests reported **12,961 tokens** with
zero unknown requests. The Engineer's final report passed structural validation,
but claimed an edit and passing tests that the evidence did not support: the actual
patch was empty and its sole real Docker pytest command exited **1**. The control
plane rejected delivery with `COMMAND_DENIED` before invoking the Verifier.
This is an evidence-backed rejection, not successful task completion. The original
bundle remains inconclusive and the target unapplied; later cleanup cannot promote
it. Actual charge is unconfirmed. See the [post-H canary plan](.agent/plans/2026-09-12-engineer-terminal-live-canary.md)
for exact observations and independent readback. Failed live05 (five reported
requests/17,487 tokens, terminal validation failure) and earlier failed/unknown
attempts remain in the [prior canary plan](.agent/plans/2026-09-12-low-cost-harness-canary.md).
This does not invalidate the earlier bounded PydanticAI-only qualification, but
does not qualify mixed Harnesses or other providers. Native P0 finalization remains
`NOT_GO`; actual external-repository, cold-start and provider/Harness campaigns
remain unqualified. Existing campaign machinery is not proof that those runs occurred;
see [known issues](docs/KNOWN_ISSUES.md).
No GitHub Actions success is claimed for these locally verified changes.

## License

Copyright 2026 Agent Fleet contributors. Licensed under [Apache-2.0](LICENSE).
