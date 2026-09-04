# Phase 2 BYOK PydanticAI Runtime

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

Add the first real model runtime without giving the model a second execution path around Agent Fleet. A user will be able to initialize a repository with an explicitly selected PydanticAI runtime, an opaque provider/model identifier, and a user-owned environment-variable reference; then `fleet run` will ask real CoS, Engineer, and Verifier model invocations for strict project-owned outputs while every proposed action still crosses `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`. Authorized candidate writes then use a Fleet-owned candidate-worktree primitive, while fake verification/approval fixtures use `FakeSandboxProvider`.

A representative opt-in flow is:

```bash
export OPENAI_API_KEY='<set outside Agent Fleet>'
fleet init . --runtime pydantic-ai --provider-model openai:gpt-5-mini --credential-ref env:OPENAI_API_KEY --sandbox fake --yes
fleet doctor --path .
fleet run "Update the disposable canary" --project . --runtime pydantic-ai --sandbox fake
```

The resolved key must never enter repository configuration, SQLite, artifacts, prompts, model-visible tool context, sandbox configuration, events, exceptions, or CLI output. Phase 2 still uses `FakeSandboxProvider`; therefore even a real model PASS cannot become `verified_complete=true`, and command evidence remains explicitly simulated. The ordinary test suite remains deterministic and network-denied.

## Scope

### In scope

- Add a `PydanticAIRuntimeAdapter` that implements the project-owned `RuntimeAdapter` port and contains all PydanticAI-specific translation.
- Declare typed runtime capabilities and fail closed before Run creation or provider access when required capabilities are absent.
- Treat provider/model identifiers as bounded opaque strings in the domain; support only the explicitly wired initial OpenAI provider families in the composition root.
- Add strict `env:NAME` credential references, an environment-backed secret store, an opaque/non-serializable secret value, and dynamic redactor registration immediately before provider construction.
- Add strict `ScopeDecision`, `ImplementationReport`, `VerifierVerdict`, and `UsageRecord` runtime outputs without allowing provider SDK objects into domain or persistence.
- Add package-owned CoS, Engineer, and Verifier system prompts, while treating repository `.fleet/agents/*.md` content as bounded untrusted project guidance.
- Evolve the runtime port to accept a control-plane-bound tool catalog. The adapter may expose only those schemas; execution must call the catalog wrapper and therefore the existing gateway and permission broker.
- Map missing credentials, unsupported providers, capability mismatch, transport failure, timeout, invalid structured output, and retry exhaustion into stable redacted Fleet errors.
- Persist bounded usage facts when the provider reports them, without estimating price or storing raw responses/headers.
- Extend `fleet init`, `fleet run`, and `fleet doctor` for explicit runtime/provider/credential selection and preflight. Preview must neither resolve credentials nor contact a provider.
- Test both fake and PydanticAI adapters against common runtime semantics using PydanticAI `TestModel`/`FunctionModel` facilities with live model requests disabled.
- Add an opt-in manual live smoke path and document exact results. It is never part of normal CI and is skipped honestly when no explicit credential is available.

### Out of scope

- Docker, Modal, hosted, or local-unsafe execution; real project commands; and OS isolation. Those begin in Phase 3.
- A general filesystem/shell tool surface. Phase 2 exposes only the already-authorized narrow Phase 1 action vocabulary through the gateway.
- Allow-for-run, persistent exact trust, revoke/explain CLI, or a full protected-action registry. Those remain Phase 4.
- Chat, parallel Engineers, Researcher/Architect execution, multi-node scheduling, or merge/join behavior. Those remain Phase 5.
- Operational FleetPatch propose/diff/apply/rollback. Those remain Phase 6.
- Keyring support, a second real harness adapter, MCP, provider-native shell/filesystem tools, provider-hosted tools, arbitrary network tools, external writes, push/deploy, or price estimation.
- Silently reading a credential reference chosen by repository-controlled files. The binding must originate in an explicit user CLI option and be stored only in Fleet-owned state as a reference.

## Current repository state

Phase 1.5 is merged at `13d5d5c63ee13a8af6b43d0981e05f1817f4778b`; its implementation tree matches reviewed commit `68f2d0abd49ac3a02b8c6500263fd51b4898af5c`. The current Phase 2 branch started clean from that merge and now contains the complete local Phase 2 candidate described below. No Phase 3 Docker execution has begun.

Relevant components are:

- `src/agent_fleet/ports/runtime.py::RuntimeAdapter` exposes typed capabilities, explicit preflight modes, and `invoke(request, services)` with a trusted provider-neutral tool catalog.
- `src/agent_fleet/adapters/runtime/fake.py::FakeRuntimeAdapter` and `src/agent_fleet/adapters/runtime/pydantic_ai.py::PydanticAIRuntimeAdapter` implement that same contract. The latter contains the only PydanticAI/provider imports.
- `src/agent_fleet/application/workflow.py::WorkflowEngine` owns CoS -> Engineer -> Verifier sequencing, creates logical agent identities, asks `ToolGateway` to execute runtime-proposed actions, and assembles authoritative evidence.
- `src/agent_fleet/application/gateway.py::ToolGateway` canonicalizes model intent, asks `PermissionBroker`, persists audit state, and is the only authorized application route to candidate writes or sandbox commands.
- `src/agent_fleet/adapters/secrets/environment.py::EnvironmentSecretStore` implements inspect/resolve for strict `env:NAME`; the shared `Redactor` dynamically registers raw and common encoded forms before a provider can raise.
- `Project`, `Run`, `RuntimeConfiguration`, and `FleetSpec` carry backward-compatible runtime/model/reference fields. Old aggregate rows reopen as fake. SQLite migration `0002` preserves all v1 rows and permits a null `agent_instances.task_id` only for the pre-TaskSpec CoS lifecycle.
- `src/agent_fleet/bootstrap.py::build_container` registers both runtimes by exact name, shares one secret/redaction boundary, and wires role-bound `GatewayRuntimeToolCatalog` instances into the existing gateway/broker/sandbox path.
- `ProjectService` binds interactive confirmation to an exact proposal identity, rejects differing existing `.fleet/` trees before state/artifact mutation, stages content-addressably, publishes through no-follow directory FDs without overwrite, and verifies target snapshot bytes before Project persistence.
- `DoctorService` inspects provider readiness without resolution or network. Preview is state-free and performs only shape/capability validation.
- `src/agent_fleet/schemas/generate.py` includes the new strict public outputs/usage schema; all three package-owned prompts and schemas are present in wheel and sdist.

`pydantic-ai-slim[openai]>=2.39,<3` and the directly audited `openai>=3.8,<4` transport dependency are locked at 2.39.0 and 3.8.0 in the local candidate. Ordinary tests set PydanticAI's global model-request guard to false and deny external DNS/TCP/UDP sockets. The explicitly gated live-provider canary is skipped unless all opt-in variables are deliberately supplied.

## Security impact

Phase 2 adds one intentional trusted-control-plane network boundary: a model-provider HTTPS request. It does not expand sandbox authority.

- A raw provider credential is resolved only in trusted control-plane memory immediately before constructing the provider client. It is passed explicitly to the provider object; Agent Fleet must not modify global environment variables or ask PydanticAI to infer credentials from ambient environment state.
- Only strict references matching `env:[A-Za-z_][A-Za-z0-9_]*` are accepted. The resolved value is wrapped in an opaque `SecretValue` whose string/repr/serialization behavior cannot reveal the value. Empty values fail as missing.
- The shared `Redactor` dynamically registers the resolved raw value and bounded common encodings before any provider object can raise. Start/resume register the active project binding before configuration parsing; patch apply registers both the current Project binding and the historical Run binding, covering credential-only rotation. State, artifacts, gateway, runtime errors, CLI presentation, and inspection use that same registry.
- Package instructions, model-visible tool definitions/output schemas, bounded user context, complete new provider messages, tool arguments/results, and the final SDK-serialized request body are scanned before their next trust-boundary transition. A secret-bearing companion response is rejected before any deferred tool side effect.
- Provider exceptions cross a cause-free Fleet error boundary. A final request guard verifies the SDK-merged endpoint/headers/body before send; a response hook rejects registered secrets and clears untrusted provider headers before OpenAI SDK handling. Raw SDK exceptions, response bodies, headers, request objects, and tracebacks are neither persisted nor returned.
- `AgentInvocation` continues to contain logical IDs, bounded text, and artifact hashes/references only. It must not contain a host path, sandbox handle, credential/reference value, approval/grant, adapter, provider client, or callable executor.
- Trusted runtime sideband objects are constructed by `WorkflowEngine`; the model cannot supply or alter run/task/agent/stage/workspace bindings. Tool arguments are validated, canonicalized into `ToolIntent`, and executed only by the existing `ToolGateway`.
- PydanticAI built-in shell, filesystem, MCP, code-execution, provider-native, and unbound function tools are prohibited. A static architecture test rejects such imports/registrations.
- The initial provider allowlist is a composition-root concern. An opaque domain model identifier does not imply that every prefix is implemented; unsupported prefixes fail before credential resolution or network.
- Retry counts, request/tool budgets, provider-reported token accounting, and total wall-clock timeout are control-plane limits. Provider SDK retries are disabled. The model cannot increase them; the complete deferred-call batch is budget- and schema-validated before its first side effect; and a whole invocation is not blindly retried after an externally observable tool action.
- Real model output remains untrusted. Strict output models, size/count bounds, registered-secret scans, and the existing evidence assembler/completion gate remain authoritative.
- FakeSandbox continues to advertise `security_level=fake`, `executes_code=false`, and `isolation_enforced=false`. No real-model result can erase the resulting proof gap.

The applicable invariants from `docs/SECURITY_MODEL.md` are secret non-disclosure, model/executor separation, deny-by-default authorization, control-plane identity binding, sandbox honesty, immutable evidence linkage, bounded untrusted input, and explicit external side effects.

## Proposed design

The trusted data and action flow is:

```text
explicit CLI credential ref -> Fleet-owned runtime config -> EnvironmentSecretStore
                                                        -> SecretValue + Redactor register
                                                        -> provider client (control plane only)

TaskSpec + ProjectKnowledge + FleetPlan -> WorkflowEngine -> AgentInvocation
                                                |          + BoundRuntimeToolCatalog
                                                v
                                  PydanticAIRuntimeAdapter -> model provider
                                                |
                               typed output / deferred tool call
                                                |
                         BoundRuntimeToolCatalog -> ToolGateway -> PermissionBroker
                                                               -> candidate-worktree write
                                                               -> FakeSandbox command/fixture
                                                |
                                      bounded usage + checkpoint ref
                                                v
                                  authoritative artifacts/evidence
```

### Runtime configuration and selection

The implementation adds strict runtime configuration fields for `runtime`, `provider_model`, and `credential_ref`. The repository-generated FleetSpec may request `pydantic-ai` and carry an opaque model identifier, but the credential reference used at runtime comes from the explicit init user command and lives in Fleet-owned state rather than repository-controlled `.fleet/` content. Only the reference is persisted; never the resolved value.

`build_container` accepts a validated runtime selection/config object and returns a runtime registry or selector containing `fake` and `pydantic-ai`. `WorkflowEngine.start` selects by exact adapter name and checks that its typed capabilities contain the stage requirements before persisting a Run. Unknown adapters or unsupported provider prefixes fail closed without fallback.

Phase 2 initially supports explicit `openai:<model>` and `openai-chat:<model>` construction using PydanticAI's OpenAI integration and a provider client supplied with the resolved key. Domain and persisted models merely validate identifier length/shape; they do not import provider enums or SDK types.

### Secrets and redaction

`SecretRef`, `SecretValue`, and `EnvironmentSecretStore` provide a side-effect-free `inspect`/`is_configured` path for doctor and a `resolve` path for the invocation boundary. Resolution reads exactly the named variable once and rejects malformed/missing/empty values through stable diagnostics.

Before constructing any provider object, register the raw value and explicit bounded encodings in the existing shared `Redactor`. Do not retain the raw value after provider construction beyond unavoidable SDK ownership. Tests scan SQLite and WAL bytes, artifact files, events, JSON/human CLI output, exceptions, tool arguments, runtime checkpoint data, and fake sandbox inspection for raw and encoded sentinels.

### Runtime contract and typed output

The shared contract uses a typed `RuntimeCapability`, bounded provider-neutral `AgentInvocation`, strict CoS `ScopeDecision`, Engineer `ImplementationReport`, Verifier `VerifierVerdict`, and `AgentInvocationResult` containing only their union, a provider-neutral `UsageRecord`, metadata, and an optional opaque checkpoint reference.

The PydanticAI adapter chooses the exact output type from the trusted role. It loads one package-owned base prompt and appends bounded repository role guidance as untrusted context, never as an authority grant. Unknown roles fail closed. Model/provider objects remain inside the adapter.

### Tool mediation

The project-owned `RuntimeToolCatalog` carries only model-visible JSON schemas plus pure `validate` and async `execute` entry points bound to trusted run/task/agent/stage/workspace identity. The application constructs a role-specific catalog with the smallest existing actions: CoS has no side-effect tools; Engineer may request candidate writes and simulated verification commands; Verifier receives simulated verification only and cannot write.

The PydanticAI implementation uses its external/deferred tool mechanism so the model can emit tool calls without receiving the executor. Agent Fleet maps each call into the bound catalog, which invokes `ToolGateway`; results are bounded/redacted before resuming the model. PydanticAI's own approval or tool-execution feature is never treated as a security boundary. Tool names must exactly match the application catalog, and any provider/tool argument identity field is ignored or rejected.

The control plane separately tracks remaining request/tool budgets across deferred resumes. It validates all call IDs, catalog membership, generic argument shape, catalog-specific schemas, and the whole batch budget before executing the first item. If a side-effecting call is executed, a transport/timeout/invalid-output failure is terminal for that invocation rather than replaying the side effect. Retry is allowed only before any gateway execution and is bounded by a small application constant.

### Usage, checkpoints, and errors

Map only documented provider-neutral usage counts into `UsageRecord`: requests, input tokens, output tokens, total tokens, tool calls, and provider-reported cost/currency only if explicitly available. Unknown fields and raw response metadata are discarded. If no value is reported, store `None`; never infer price. The total-token ceiling is checked from provider-reported usage after a response and before any continuation/tool, while `max_tokens` bounds requested output; it is not a guaranteed pre-spend ceiling for unknown input usage.

Phase 2 keeps deferred history only inside one bounded invocation and does not persist a PydanticAI checkpoint. A supplied checkpoint reference fails closed; durable provider-conversation resume remains a later recovery feature. Client-supplied history is never accepted for authorization or resumption.

Stable Fleet error codes distinguish runtime unavailable, capability missing, credential invalid/missing, provider unsupported, provider failure, timeout, structured-output invalid, retry exhausted, and tool-budget exhausted. `WorkflowEngine` marks a running agent and Run failed, persists a bounded `run.failed` event, and returns the logical `run_id` in safe CLI error details; no failed invocation remains indefinitely RUNNING. Phase 2 does not claim a dedicated `ERROR_REPORT` artifact.

### Persistence compatibility

Optional/defaulted aggregate JSON fields on `Project` and `Run` carry provider/model/reference and usage artifact IDs, so existing rows reopen as `fake` with no provider configuration. Migration `0002` changes only the relational `agent_instances.task_id` constraint: it becomes nullable when and only when `role='cos'`, allowing the CoS AgentInstance to be persisted as RUNNING before its ScopeDecision creates a TaskSpec. The completed CoS row is rebound to that TaskSpec, and v1 rows are copied intact.

## Public contracts

- CLI:
  - `fleet init PATH --runtime {fake,pydantic-ai} --provider-model ID --credential-ref env:NAME --sandbox fake [--preview|--yes]`
  - `fleet run GOAL --project PATH [--runtime ...] [--provider-model ...] [--credential-ref ...] --sandbox fake`
  - `fleet doctor --path PATH` reports provider selection and `configured`, `missing`, `invalid`, or `not_selected` without displaying a raw value or full credential reference.
- Domain/config models:
  - bounded `RuntimeName`, `ProviderModelId`, `SecretRef`, `RuntimeCapability`;
  - strict `ScopeDecision`, `UsageRecord`, and role-output union;
  - optional provider-neutral runtime configuration on `Project`/`Run` with fake-compatible defaults.
- Ports:
  - `RuntimeAdapter.capabilities` is typed;
  - `RuntimeAdapter.invoke(request, services)` accepts `RuntimeInvocationServices` containing trusted configuration and tool catalog;
  - `SecretStore.inspect/is_configured/resolve` has explicit no-resolution and resolution operations;
  - `RuntimeToolCatalog` is the sole model-tool execution boundary.
- Adapters:
  - `FakeRuntimeAdapter` and `PydanticAIRuntimeAdapter` satisfy the same contract suite;
  - `EnvironmentSecretStore` resolves only strict `env:` references;
  - no provider SDK type is returned from an adapter.
- Artifacts/schemas:
  - add generated schemas for scope decision, implementation report, usage record, and existing verifier verdict;
  - `runtime_usage` artifacts persist one bounded usage record per role invocation;
  - package prompts under `src/agent_fleet/adapters/runtime/prompts/` in wheel and sdist.
- Compatibility:
  - existing fake CLI invocations and stored Phase 0/1 databases continue to work;
  - omitted runtime remains `fake` for backward compatibility;
  - PydanticAI options with fake runtime or missing PydanticAI options fail with actionable configuration diagnostics, never implicit inference.

## Milestones

### Milestone 1: Provider-neutral contracts and secret boundary

Add strict runtime/secret/output/usage contracts, dynamic redaction, environment secret resolution, stable errors, compatibility fields, schemas, and focused security tests. Migrate FakeRuntime to the new port without changing its observable offline behavior.

Acceptance:

- Existing aggregate rows and fake CLI flows remain valid.
- Strict malformed references, missing/empty variables, accidental stringification, and dynamic redaction tests pass.
- Runtime capability mismatch is rejected before Run creation and before any provider call.
- Scope, implementation, verifier, and usage models round-trip through generated schemas without SDK objects.

### Milestone 2: PydanticAI adapter and gateway-bound tools

Add the dependency, package-owned prompts, provider factory, PydanticAI adapter, exact external-tool translation, bounded deferred loop, usage mapping, timeout/retry mapping, and common runtime contracts.

Acceptance:

- TestModel/FunctionModel obtains strict outputs for CoS, Engineer, and Verifier.
- The exact model-visible tool set is role/stage-specific and every execution reaches a bound `ToolGateway` test double; no native shell/filesystem/provider tool exists.
- Provider failure, timeout, invalid output, retry exhaustion, and post-side-effect failure produce the expected stable redacted Fleet error.
- `pydantic_ai.models.ALLOW_MODEL_REQUESTS` is false in ordinary tests, and a socket/network-deny fixture confirms no network.

### Milestone 3: CLI/composition vertical slice

Wire runtime selection, Fleet-owned runtime configuration, doctor/preflight, workflow typed outputs, usage/checkpoint artifacts, and real-provider opt-in through the current CoS -> Engineer -> Verifier journey while retaining FakeSandbox evidence honesty.

Acceptance:

- Preview performs no credential read, state write, or network call.
- Explicit PydanticAI init/run with missing/invalid credentials returns actionable stable JSON and human diagnostics without creating a Run or leaking the reference/value.
- Offline integration tests drive all three roles through a PydanticAI fake model and the existing gateway/evidence pipeline.
- A model PASS with FakeSandbox ends reviewable but `verified_complete=false`, with the simulated execution proof gap intact.
- Existing fake success/fail/repair/approval/inconclusive/direct/single-engineer E2E behavior remains green.

### Milestone 4: Independent acceptance, documentation, and delivery

Update README, architecture/security/config documentation, this plan, schemas, package contents, and an opt-in live-smoke guide. Run every required gate, freeze a candidate identity, obtain fresh independent read-only verification, then create one Phase 2 commit, push its feature branch, merge its PR, and repeat critical verification on merged `main`.

Acceptance:

- Formatting, lint, strict type checking, unit, contract, integration, offline E2E, schema drift, build, archive inspection, diff hygiene, network-deny, and secret-leak scans all pass with exact recorded results.
- Manual live smoke is either PASS with three typed role outputs and no leakage, or explicitly `NOT RUN` because no credential was supplied; absence is never reported as success.
- A fresh verifier confirms acceptance against a frozen Git/diff identity.
- GitHub records one Phase 2 commit/PR merge, remote `main` matches the reviewed tree, and the post-merge working tree is clean.

## Detailed implementation steps

1. Add this ExecPlan before changing dependencies or implementation, then keep it current after every milestone, security discovery, or deviation.
2. Add provider-neutral runtime identifiers, capability/output/usage models, error codes, schema generation entries, and backward-compatible persisted fields under `src/agent_fleet/domain/`.
3. Extend `Redactor` with thread-safe/idempotent dynamic registration; implement strict `SecretRef`/opaque `SecretValue` and `EnvironmentSecretStore`; add exhaustive leak and malformed-reference tests.
4. Define `RuntimeToolCatalog` and update `RuntimeAdapter`; migrate `FakeRuntimeAdapter` plus WorkflowEngine call sites and common contract tests before adding the real adapter.
5. Add `pydantic-ai-slim[openai]` with a v2-compatible bound and refresh `uv.lock`. Verify exact installed API imports before writing adapter code.
6. Add package-owned prompt resources and archive tests. Keep security rules in code and phrase repository guidance as untrusted input.
7. Implement the explicit OpenAI provider factory and `PydanticAIRuntimeAdapter`, including strict output selection, external/deferred tools, budgets, total timeout, provider retry disablement, usage mapping, and stable redacted failures.
8. Extend application runtime selection and preflight, ensuring unsupported runtime/provider/capabilities/credential states fail before Run persistence or network.
9. Extend init/run/doctor flags and presentation. Persist only Fleet-owned references and bounded opaque identifiers; keep preview read-only and offline.
10. Integrate typed outputs into planning/implementation/verification, persist bounded usage/checkpoint evidence if required, and retain completion-gate proof gaps under FakeSandbox.
11. Add offline adapter unit/contract tests, integration/E2E tests, architecture boundaries, network-deny, provider-object isolation, retry/side-effect idempotency, and adversarial secret scans.
12. Update README and normative docs with exact user journey, trust boundary, limitations, live-smoke instructions, and results. Update `Progress`, `Discoveries`, `Decision Log`, and `Outcomes`.
13. Run the full quality matrix, freeze the candidate identity, commission a fresh independent verifier, repair any findings, and rerun affected/full gates.
14. Commit Phase 2 once, push `codex/phase-2-pydantic-ai-runtime`, open and merge a GitHub PR, verify remote merge/tree identity, rerun post-merge checks, then begin Phase 3 only after Phase 2 acceptance passes.

## Validation plan

Required local gates:

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -q tests/unit
uv run pytest -q tests/contract
uv run pytest -q tests/integration -m integration
uv run pytest -q tests/e2e -m e2e
uv run pytest -q
uv run python -m agent_fleet.schemas.generate --check
uv build
git diff --check
```

Additional required evidence:

- Run the common runtime adapter contract suite against Fake and PydanticAI TestModel/FunctionModel.
- Run ordinary tests with live model requests disabled and sockets denied; prove no environment key is required.
- Scan repository diff, SQLite database/WAL, artifact bytes, captured stdout/stderr, event JSON, exception strings/repr/traceback, tool contexts, prompt/checkpoint data, and FakeSandbox inspection for raw and encoded credential sentinels.
- Inspect wheel and sdist for all three prompt resources and generated schemas, and confirm no test fixture secret or local path is packaged.
- Exercise preview/init/run/doctor in human and JSON modes for fake, validly configured PydanticAI test path, malformed reference, missing value, unsupported provider, and missing capability.
- Assert failures before Run creation/provider access by inspecting state/events and a provider-call spy.
- Assert FakeSandbox command evidence remains simulated and `verified_complete=false` after model PASS.
- If an explicit valid credential is available without printing it, run the documented disposable live smoke with a low bounded request/tool/token budget and record three typed outputs, usage presence/absence, and leak scan. Otherwise record `NOT RUN: no explicitly supplied credential`.
- Record exact test counts, durations, candidate diff/tree hash, verifier identity/verdict, commit, PR, merge commit, and remote tree hash in this plan and README.

## Rollback and recovery

The default fake path remains backward compatible, but Fleet never silently falls back from a selected provider. A failed PydanticAI preflight creates no Run; a failure after Run creation moves the active AgentInstance and Run to FAILED with an append-only stable `run.failed` event and discoverable logical Run ID. Retry starts a new bounded invocation and may occur only if no model tool side effect crossed the gateway. Phase 2 persists no provider message-history checkpoint and rejects caller-supplied checkpoint resumption.

No raw secret is persisted, so rollback requires no credential-value migration. Removing or renaming the environment variable makes future provider preflight fail safely; historical records contain references only. Reverting Phase 2 code while retaining a schema-v2 database is intentionally rejected as a newer unsupported schema. Operational rollback therefore restores a pre-migration database backup or keeps the Phase 2 reader while reverting behavior; migration `0002` does not delete v1 data.

Initialization stages and snapshots before repository publication. A differing existing `.fleet/` tree fails before Project/artifact mutation; users must preview, move the complete conflicting tree aside, and retry. Publication uses bounded no-follow directory-FD traversal, no-replace hard links, inode-bound rollback, and a target snapshot comparison. Failure before Project persistence may leave an exact generated `.fleet/` tree but no registration; rerunning the same init is idempotent. After the first Project save, runtime and snapshot hash already agree with the target; a later artifact failure can leave missing artifact links but not a false runtime/config binding, and an idempotent retry repairs them.

Gateway actions preserve existing exact-intent reservation and idempotency. A provider failure after an executed action does not replay that action. Resource cleanup continues through existing cancellation/recovery services; FakeSandbox owns no OS process/container. Package/dependency rollback is the Phase 2 merge revert plus `uv lock` regeneration, with Fleet state backed up before any format-changing migration.

## Progress

- [x] (2026-09-04) Confirmed Phase 1.5 merge `13d5d5c...`, clean branch `codex/phase-2-pydantic-ai-runtime`, 304-test post-merge gate, and Phase 2 prerequisite satisfaction.
- [x] (2026-09-04) Audited Phase 2 roadmap, current runtime/workflow/secret/redaction/CLI/composition gaps, current PydanticAI v2 API direction, and required security/acceptance matrix.
- [x] (2026-09-04) Created this living ExecPlan before any Phase 2 dependency or implementation edit.
- [x] (2026-09-04) Completed Milestone 1: typed runtime/output/usage contracts, backward-compatible state fields, strict env references, opaque secrets, dynamic redaction, schemas, and migrated FakeRuntime contracts.
- [x] (2026-09-04) Completed Milestone 2: PydanticAI 2.39 adapter, package prompts, explicit OpenAI factories, external/deferred gateway tools, bounded usage/errors/time/retries, offline contract tests, and package-resource checks.
- [x] (2026-09-04) Completed Milestone 3: exact runtime registry/preflight, provider-aware init/run/doctor, strict role integration, usage artifacts, offline CLI journey, and FakeSandbox completion honesty.
- [x] (2026-09-04) Closed pre-release bootstrap findings: proposal-confirmation drift, repeated-init split brain, raw filesystem errors, target snapshot drift, unsafe extra paths, leaf/parent symlink races, FIFO/unbounded reads, and rollback identity.
- [x] (2026-09-04) Updated README, architecture, security, schema, product, roadmap, ADR, live-smoke instructions, and this living plan for the implemented boundary.
- [x] (2026-09-04) Re-ran the complete local validation matrix after final credential rotation, complete model-payload/request-envelope, response-header, batch-validation, provider-routing, and descriptor-read hardening: 279 unit, 68 contract, 84 marked integration, 3 subprocess E2E, and 473 combined tests passed; the one live-provider case skipped by its explicit gate.
- [x] (2026-09-04) Froze initial composite candidate `0d50d90d...`; root self-review then invalidated that freeze before independent acceptance because Fleet's constant outer user-prompt envelope was not yet covered by the offline final model-request scan. Added a PydanticAI model wrapper that scans exact messages/settings/request parameters before dispatch plus a permanent collision regression. A new full matrix and identity are required.
- [x] (2026-09-04) Re-ran every required gate after that repair and froze replacement candidate `944043374ef940fcfea7b33e1d343442f9c9af1c23888ede9b08d1fb94ffcd93` across the same 150-entry boundary.
- [x] (2026-09-04) Obtained three fresh independent read-only PASS verdicts (acceptance, security, and release/persistence); all recomputed the same 150-entry candidate identity at start and end, with zero new P0/P1/P2 findings.
- [ ] Create the Phase 2 commit, push the feature branch, merge the GitHub PR, verify remote tree identity, and rerun post-merge checks.

## Discoveries

- Observation: the roadmap requires real harness tool use, but the current `RuntimeAdapter.invoke(request)` has no trusted tool sideband.
  Evidence: `src/agent_fleet/ports/runtime.py` accepts only `AgentInvocation`; Phase 1 scripts return action proposals that WorkflowEngine later executes.
  Consequence: evolve one shared adapter contract and bind a role-specific catalog in the application; never put executors, paths, sandbox handles, or credentials into model input.
- Observation: PydanticAI string model inference normally uses provider-standard ambient credentials, while Fleet allows an explicit arbitrary `env:NAME` reference.
  Evidence: current official PydanticAI provider APIs support explicitly constructed providers/clients, and the security model prohibits global environment mutation.
  Consequence: construct the initial provider explicitly with the resolved value and disable SDK retries; do not call generic string inference on the live path.
- Observation: PydanticAI request/tool limits apply to one model run and cannot be the sole cross-resume Fleet budget.
  Evidence: deferred tool execution can create multiple model runs, and external tool accounting is not a durable Fleet authorization ledger.
  Consequence: maintain an independent control-plane budget across the deferred loop; Gateway/PermissionBroker remains authoritative.
- Observation: runtime fields fit backward-compatible aggregate JSON, but persisting a RUNNING CoS before ScopeDecision means no TaskSpec exists yet.
  Evidence: the v1 relational `agent_instances.task_id NOT NULL` constraint rejected the required pre-output CoS lifecycle even though old Project/Run JSON reopens as fake.
  Consequence: migration `0002` preserves existing rows and permits a null task only for `role='cos'`; all other AgentInstances remain task-bound.
- Observation: a real model on FakeSandbox increases semantic realism but not execution evidence strength.
  Evidence: FakeSandbox advertises no code execution or isolation and the completion gate already rejects simulated command evidence.
  Consequence: preserve proof gaps and never label Phase 2 model output as verified project completion.
- Observation: the original re-init order persisted a new provider selection before fixed-path staging/apply, so a changed provider raised raw `FileExistsError` and left Project state inconsistent with `.fleet/`.
  Evidence: a disposable fake-to-PydanticAI re-init reproduced new runtime state with the old repository FleetSpec; permanent fake-to-provider and model-A-to-model-B regressions now assert unchanged Project, artifacts, events, and files.
  Consequence: check target compatibility before state migration, use content-addressed staging, publish/verify target bytes before Project persistence, and fail closed rather than perform an in-place configuration merge.
- Observation: human confirmation originally displayed one preview and then independently recomputed initialization without binding the two.
  Evidence: a confirmation callback that changes repository profiling inputs produced a different second proposal.
  Consequence: hash proposed bytes together with the displayed baseline diff, pass that identity into `initialize`, and reject drift before credential-backed mutation.
- Observation: path-level existence checks plus `os.replace`/`read_text` were insufficient against concurrent leaf creation, parent-directory symlink swaps, FIFO blocking, oversized files, and rollback replacement.
  Evidence: adversarial tests reproduced a leaf overwrite race, an `.fleet/agents` move/symlink swap, NUL path failure, and FIFO/unbounded-read exposure.
  Consequence: validate every output key, use bounded regular-file reads, traverse/publish through `O_DIRECTORY|O_NOFOLLOW` directory FDs, publish with no-replace hard links, track inode identities for rollback, and re-read the applied target snapshot before persistence.
- Observation: an ordinary PydanticAI model-request guard alone does not prove other code avoided direct sockets.
  Evidence: the initial socket-deny test covered only one adapter call.
  Consequence: the autouse test boundary now denies external DNS/TCP/UDP for the ordinary suite and opens it only for the explicitly marked, fully gated live canary.
- Observation: an explicitly supplied API key was still unsafe if the OpenAI SDK could honor ambient `OPENAI_BASE_URL` or proxy settings.
  Evidence: an adversarial review redirected the pre-hardening client to a disposable loopback endpoint and observed the selected bearer value there.
  Consequence: the production client now pins the official HTTPS base/host, clears ambient OpenAI identity selections, disables redirects and `trust_env`, supplies the selected authorization header explicitly, and has a permanent ambient-routing regression.
- Observation: proposal rendering and ConfigSnapshot loading used path-level check-then-read sequences that could follow a concurrently swapped parent or leaf and could read a file that grew beyond its checked size.
  Evidence: fault injection swapped an already-checked `.fleet` file to an outside symlink during preview; separate regressions exercise leaf/parent swaps, FIFO inputs, and growth between metadata inspection and read.
  Consequence: preview and configuration loads now traverse pinned no-follow directory descriptors, accept only bounded regular files, read at most ceiling plus one byte, and revalidate identity/size/timestamps after the read.
- Observation: generated role/project files were not all byte-bounded before publication, so a deterministic post-publication load failure could leave an otherwise new `.fleet` tree that blocked retry.
  Evidence: a 512001-byte generated Engineer prompt was published before `apply()` returned `CONFIG_INVALID`.
  Consequence: validation now enforces the 512000-byte per-file and 4000000-byte aggregate ceilings across the complete candidate mapping before any directory or file is created.
- Observation: a credential-only re-init can leave a READY historical Run bound to an older environment reference than its current Project.
  Evidence: a fresh `patch apply` originally registered only the current Project credential before parsing configuration, allowing a malformed file containing the still-configured historical value to survive redaction.
  Consequence: patch apply resolves/registers both distinct references before configuration parsing; missing historical values remain safely unavailable, while invalid references fail closed.
- Observation: scanning only dynamic task context and structured output missed low-entropy credentials that collide with package prompts/schemas and companion provider text beside a deferred tool call.
  Evidence: `TaskSpec` was a valid eight-byte credential present in the Engineer prompt, and a response containing secret text plus a valid write call reached the catalog before hardening.
  Consequence: scan static Fleet-supplied model material before Agent construction, complete new-message JSON before any tool, and the final serialized OpenAI body before transmission.
- Observation: scanning the dynamic context object still omitted the constant Fleet-authored wrapper added around its serialized JSON, and static preflight does not by itself prove the fully prepared PydanticAI request is secret-free.
  Evidence: the valid credential `following` collided only with the outer user-prompt sentence and would have reached an offline FunctionModel.
  Consequence: scan the final constructed user prompt and wrap every test/live Model with a boundary that scans exact serialized messages, model settings, and prepared request parameters immediately before dispatch. The OpenAI serialized-body hook remains the last network defense.
- Observation: validating a deferred batch only as generic RuntimeToolCall values could discover a later known-tool schema error after an earlier side effect.
  Evidence: catalog-specific Pydantic argument validation previously occurred inside sequential `execute` calls.
  Consequence: expose a pure catalog `validate` operation and validate the entire batch before its first execution.

## Decision Log

- Decision: Phase 2 supports only explicit `env:NAME` secret references; keyring is deferred.
  Rationale: this is the smallest required BYOK path that can be tested across platforms without hidden storage behavior.
  Alternatives: OS keyring now; raw key CLI/config. The first expands platform/error scope and the second violates the security model.
  Date: 2026-09-04.
- Decision: repository-controlled FleetSpec may not choose the credential reference used for provider resolution.
  Rationale: otherwise an untrusted repository could select an unrelated ambient secret and trigger a confused-deputy provider call. The resolved value is always forbidden; the reference itself is persisted only in Fleet-owned state from explicit user input.
  Alternatives: read `credentialRef` directly from `.fleet/fleet.yaml`; infer standard provider variables. Both weaken user intent and authority binding.
  Date: 2026-09-04.
- Decision: domain provider/model identifiers stay opaque, while the Phase 2 composition root implements an explicit initial OpenAI allowlist (`openai:` and `openai-chat:`).
  Rationale: avoids provider coupling in the domain and prevents generic model inference from reading ambient secrets. It also honors the one-real-harness limit.
  Alternatives: enumerate provider/model names in domain; support every PydanticAI provider; ask the user for a provider. All add unnecessary scope or violate the instruction to resolve ordinary choices.
  Date: 2026-09-04.
- Decision: PydanticAI external/deferred tools are a transport only; `RuntimeToolCatalog -> ToolGateway -> PermissionBroker` is the authority path.
  Rationale: no harness may control the final execution boundary or bypass policy, and deferred calls permit Fleet to execute and audit outside the harness.
  Alternatives: PydanticAI native tool execution, shell/filesystem tools, or passing Gateway directly as model data. These create bypasses or leak trusted objects.
  Date: 2026-09-04.
- Decision: provider network occurs only in the trusted control plane after explicit user selection; it is not modeled as FakeSandbox network.
  Rationale: credentials must stay outside workers, and Phase 4's full network permission UX is not yet implemented. The call is still explicit, bounded, auditable, and never made by preview/tests.
  Alternatives: put provider network in worker sandbox; invent a Phase 4 approval rule now. Both violate sequencing.
  Date: 2026-09-04.
- Decision: keep FakeSandbox and evidence semantics unchanged in strength.
  Rationale: Phase 2 is a runtime milestone, not an execution/isolation milestone. Real model output is not proof of real commands.
  Alternatives: begin Docker or local host execution. Explicitly forbidden until Phase 2 acceptance passes.
  Date: 2026-09-04.
- Decision: Phase 2 does not overwrite or merge a differing existing `.fleet/` tree in place.
  Rationale: generated prompts and policy files are user-editable; safe transactional semantic evolution belongs to FleetPatch. Exact idempotent init and credential-reference-only updates remain supported.
  Alternatives: overwrite reviewed paths one by one; replace the entire tree; silently rewrite runtime only. Each risks partial state, lost user content, or policy drift.
  Date: 2026-09-04.
- Decision: initialization confirmation is bound to `canonical_json_hash({files, patch})`, and target publication precedes the runtime/hash Project write.
  Rationale: displayed bytes and baseline must remain the bytes authorized for application, while a Project must never advertise a runtime/config hash not verified in the repository.
  Alternatives: trust a second recomputation; persist state first and repair later. Both produced observable split-brain windows.
  Date: 2026-09-04.
- Decision: no PydanticAI message checkpoint is persisted in Phase 2.
  Rationale: the bounded deferred loop needs history only in memory; adding a safe durable provider-history format was unnecessary for the required vertical slice.
  Alternatives: persist provider message objects or accept client history. Both expand the untrusted/persistence boundary without a current recovery need.
  Date: 2026-09-04.
- Decision: the Phase 2 OpenAI transport is fixed to the official API endpoint and rejects environment-driven transport selection.
  Rationale: the credential reference is explicit user authority; ambient base URLs, redirects, proxies, CA variables, or unrelated OpenAI identity fields must not be able to redirect or reinterpret that authority.
  Alternatives: honor `OPENAI_BASE_URL`; rely on SDK defaults; temporarily sanitize `os.environ`. The first two permit confused-deputy credential disclosure, while global mutation is unsafe for concurrent runs.
  Date: 2026-09-04.
- Decision: Phase 2 treats every registered secret representation as forbidden model payload, even if a short valid credential collides with trusted package text or a generated JSON field.
  Rationale: credentials are authorization material, and fail-closed rejection is safer than deciding that a textual collision is harmless. The OpenAI Authorization header is the sole intentional transport exception; the serialized body is still scanned.
  Alternatives: raise the minimum entropy/length; scan only user context; redact prompts. Those approaches either change the documented credential contract or allow credentials into model-visible material.
  Date: 2026-09-04.

## Outcomes

The local Phase 2 candidate implements explicit BYOK PydanticAI execution without moving authorization or execution into the harness. Fake and PydanticAI share strict role outputs, runtime capability preflight, a Fleet-owned tool catalog, workflow/state/evidence logic, and the independent `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker` authority path. Authorized candidate writes use a control-plane-owned worktree primitive; fake commands/approval fixtures use FakeSandbox. Environment credentials are referenced explicitly, resolved only in the control plane, dynamically redacted, and excluded from repository configuration/model payloads/persistence. Provider usage is persisted in bounded project-owned artifacts; provider errors cross stable cause-free boundaries.

Local evidence on Python 3.14.6, Pydantic 2.13.5, PydanticAI 2.39.0, OpenAI SDK 3.8.0, Git 2.50.1 (Apple Git-155), uv 0.12.9, Ruff 0.16.6, mypy 1.20.2, and pytest 9.1.1:

- `uv lock --check`: PASS, 51 packages resolved in 22 ms.
- `uv sync --all-extras`: PASS, 51 packages resolved and 49 checked in 9 ms.
- `uv run ruff format --check .`: PASS, 129 files already formatted.
- `uv run ruff check .`: PASS.
- `uv run mypy src tests`: PASS, 108 source files.
- `uv run python -m agent_fleet.schemas.generate --check`: PASS.
- `uv run pytest -q tests/unit`: PASS, 279 tests in 8.70s.
- `uv run pytest -q tests/contract`: PASS, 68 tests in 2.40s.
- `uv run pytest -q tests/integration -m integration`: PASS, 84 passed and 38 deselected in 87.89s.
- `uv run pytest -q tests/e2e -m e2e`: PASS, 3 tests in 17.90s.
- `uv run pytest -q`: PASS, 473 passed and 1 explicitly gated live-provider test skipped in 133.23s.
- `uv build --offline`: PASS; wheel and sdist each contain 97 files, including migrations `0001`/`0002`, all 3 runtime prompts, and all 17 generated schemas, with 0 tests and 0 `.agent` files.
- Built-wheel smoke: PASS; the module loaded from the wheel and `fleet version --json` returned `0.1.0` against the locked dependency environment. A dependency-cold network-disabled venv install was not demonstrated because the local uv cache lacked PyYAML; archive integrity and the synced-environment wheel entry point were demonstrated.
- `git diff --check`: PASS.
- Live provider: `NOT RUN: no explicitly supplied credential`; no ambient credential was discovered or reused.

Fresh independent read-only verification against the replacement freeze also passed without candidate drift:

- Acceptance verifier: PASS; start/end identity `944043374ef940fcfea7b33e1d343442f9c9af1c23888ede9b08d1fb94ffcd93`, 150 entries, zero P0/P1/P2 findings. It independently observed 279 unit tests in 8.98s, 68 contract tests in 2.44s, 84 marked integration tests with 38 deselected in 87.70s, 3 E2E tests in 18.45s, and 473 combined tests with the one explicit live skip in 134.68s. Static, schema, offline build/archive, wheel import/version, secret/path scan, and Phase 3 absence checks passed.
- Security verifier: PASS; the same start/end identity and zero P0/P1/P2 findings. It ran 32 focused runtime/transport regressions in 4.22s and 60 permission/Gateway/CompletionGate regressions in 5.57s, plus an independent schema-collision probe that failed before model or catalog invocation. Request-envelope/body/header scans, current and historical credential registration, deferred-batch atomicity, exact budgets, authority routing, FakeSandbox proof honesty, diff hygiene, and secret/path scans passed.
- Release/persistence verifier: PASS; the same start/end identity and zero P0/P1/P2 findings. It independently observed 473 combined tests with one explicit live skip in 136.68s, verified v1-to-v2 migration and legacy JSON defaults, direct dependency/lock versions, and rebuilt 97-file wheel/sdist archives containing 3 prompts, 17 schemas, and 2 migrations with no tests, `.agent`, local paths, or scanned credential sentinels. Wheel import/version, documentation truth, branch state, and release hygiene passed.

Initial candidate identity `0d50d90d23b9299145fd528a6fda17db40ab628fc0d6e0f03a70d1c2d3cd3654` was invalidated before verifier acceptance by the final request-envelope repair and must not be used as delivery evidence. Replacement frozen identity is `944043374ef940fcfea7b33e1d343442f9c9af1c23888ede9b08d1fb94ffcd93` across 150 entries. It hashes, in sorted path order, `mode + space + repository-relative path + NUL + SHA-256(file bytes)` for `git ls-files -co --exclude-standard`, excluding only this living plan. Commit/PR/merge identities and post-merge evidence cannot be embedded in the same single Phase 2 commit without creating a self-reference; they will be verified against GitHub and reported in the delivery record rather than inferred.

Remaining intentional limitations: FakeSandbox performs no project execution or OS isolation, so every run remains `verified_complete=false`; only `openai:` and `openai-chat:` are wired; the provider-reported total-token ceiling is not a strict pre-spend ceiling; programmatically enabled low-level transport DEBUG logging precedes Fleet's response hook; CoS-proposed paths lack a separate deterministic natural-language user-scope ceiling and therefore require explicit patch review/apply before target mutation; no durable provider-history checkpoint exists; differing `.fleet/` trees require review and move-aside rather than in-place reconfiguration; dependency minor-version drift remains possible within the declared bounds; and Docker, real commands, full permission persistence, chat/parallel specialists, and operational FleetPatch remain later phases. Commit/push/PR merge, remote-tree verification, and post-merge rerun are still pending and must be reported from authoritative read-back rather than inferred.
