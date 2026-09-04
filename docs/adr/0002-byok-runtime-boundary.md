# ADR 0002: Keep BYOK provider access inside the trusted control plane

- Status: Accepted for Phase 2
- Date: 2026-09-04

## Context

Agent Fleet needs a real model runtime without allowing a model harness to become an executor, permission authority, or secret manager. Repository configuration is untrusted and may request roles, models, tools, and permissions, but it cannot grant authority or select an unrelated ambient secret for the control plane to read. Provider SDKs also commonly infer credentials from global environment variables and retry requests internally, which conflicts with explicit per-project BYOK binding, concurrent runs, and Fleet-owned retry accounting.

## Decision

Phase 2 adds one `PydanticAIRuntimeAdapter` behind the project-owned `RuntimeAdapter` port. Provider/model IDs remain opaque bounded strings in domain and persistence. The adapter implementation initially recognizes only the explicitly wired `openai:` and `openai-chat:` prefixes; unsupported prefixes fail closed without fallback.

The credential reference must originate in an explicit user CLI option and is persisted only in Fleet-owned state. Repository `.fleet/` configuration may record the runtime and opaque provider/model ID, but not the credential reference used for resolution. Phase 2 accepts only strict `env:NAME` references and 8–16384-byte visible-ASCII resolved values, rejecting control characters and invalid HTTP-header encodings before provider construction. Preview validates the reference shape with no environment read, state/repository write, provider construction, or network. Doctor inspects configured/missing/invalid status without returning the value or contacting a provider. Init and run preflight resolve the value in trusted control-plane memory and register it plus bounded common encodings with the shared redactor before mutation; the live invocation resolves it at the provider-construction boundary and passes it to an explicitly constructed provider client. That client pins the official OpenAI HTTPS base and host, disables redirects and ambient proxy/CA discovery, clears unrelated ambient OpenAI identity fields, and disables SDK retries. Agent Fleet never writes the raw value, modifies the process environment, honors `OPENAI_BASE_URL` for this adapter, or asks the SDK to infer a key.

Every model-visible tool is derived from a role- and stage-bound project tool catalog. Tool execution constructs a canonical intent and crosses `ToolGateway -> PermissionBroker` before any candidate-workspace or sandbox operation. Provider-native shell, filesystem, MCP, code-execution, and arbitrary network tools are not enabled. The model cannot supply run/task/agent/workspace identity, an approval grant, a sandbox handle, or an executor.

The trusted control plane owns request/tool/provider-reported-token/time limits and retry decisions. Provider SDK retries are disabled. The complete deferred tool batch is schema-validated before its first execution, and a whole invocation is not retried after a gateway action with an observable side effect. Fleet-supplied prompt/schema/context material, complete new provider messages, and the final serialized provider body are registered-secret scanned at their boundaries. Provider exceptions are mapped to cause-free stable Fleet errors; raw response bodies, headers, SDK objects, and exception representations are discarded. The provider HTTPS request is an intentional control-plane network boundary: selected prompts and bounded project/task context leave the machine and are subject to provider data handling. It does not enable worker-sandbox networking.

The Phase 2 worker remains `FakeSandboxProvider`. A real model response can improve orchestration realism, but it cannot upgrade simulated command evidence or set `verified_complete=true`.

Phase 2 init is not an in-place configuration merge. If a runtime/provider change would alter an existing generated `.fleet/` tree, initialization fails before Project/artifact state or repository mutation. The user reviews the preview, moves the complete conflicting tree aside, and explicitly initializes again. A credential-reference-only update may proceed because that reference is Fleet-owned state and is absent from `.fleet/`.

## Consequences

- Users get explicit local-first BYOK behavior without committing a key or giving it to a worker.
- A malicious repository cannot redirect Fleet to read an arbitrary environment variable.
- Domain/application code does not depend on PydanticAI or provider SDK response types.
- Adding another provider requires an explicit adapter-level factory and tests, even though persisted identifiers are provider-agnostic.
- Init/run preflight diagnose malformed or missing references without contacting a provider; preview never reads or resolves a value, and doctor uses inspect-only status.
- Provider reconfiguration cannot leave Fleet state and repository `.fleet/` with different runtime selections; conflicting generated trees fail before mutation.
- Approval, audit, evidence, and sandbox semantics remain harness-independent.
- Keyring, multiple harnesses, Docker execution, full persistent trust, and operational FleetPatch remain later phases.

## Rejected alternatives

- **Repository-owned `credentialRef` as the active binding.** Rejected because an untrusted checkout could select an unrelated ambient secret and make the trusted control plane act as a confused deputy.
- **Raw key flags or repository files.** Rejected because command history, process listings, artifacts, and Git make disclosure likely.
- **Temporarily modifying `os.environ`.** Rejected because concurrent invocations can cross-use credentials and SDK failures may observe global state.
- **Generic PydanticAI string model construction.** Rejected on the live path because it can infer ambient credentials outside Fleet's explicit secret lifecycle.
- **Harness-native execution or approval.** Rejected because no harness may bypass Fleet's independent permission and sandbox control planes.
- **Beginning Docker execution in Phase 2.** Rejected because runtime acceptance must pass before the Phase 3 execution boundary is introduced.
