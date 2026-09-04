# ADR 0001: Product north star and control-plane primitives

- Status: Accepted
- Date: 2026-09-04

## Context

Agent Fleet was inspired by the operating methodology behind Lauren Tan's use of Grok bot and refined through a product-design discussion about applying that style of delegation to software repositories. The useful product is not another generic multi-agent chat framework. Existing frameworks already make it easy to name several agents and let them exchange messages; that alone does not provide repository understanding, least-authority execution, independent verification, or durable organizational learning.

The Phase 0/1 implementation proved a narrow offline CoS -> Engineer -> Verifier control-plane path. It also exposed abstractions that would freeze the wrong product if real model and Docker adapters were added immediately: static repository templates, a closed three-role roster, authorization embedded in ToolGateway, a sandbox contract without capability semantics, and completion that was not gated by authoritative evidence.

## Decision

The normative product position is:

> A local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization.

The user normally interacts with one persistent Chief of Staff. The deterministic control plane, not the model harness, creates the smallest valid team for each task, owns permission and sandbox decisions, assembles authoritative evidence, and applies versioned organizational changes only after review.

Six capabilities define whether the product has differentiated value:

1. **Repository-aware bootstrap.** `fleet init .` derives an evidence-backed `RepositoryProfile`, proposed `FleetSpec`, and factual `ProjectKnowledge`; it establishes the requested execution boundary and demonstrates the complete flow on a disposable canary. Detection never executes repository code and is not authorization.
2. **Adaptive Fleet.** CoS proposes a typed `FleetPlan` for the smallest sufficient topology. Roles are ephemeral responsibility instances selected from validated project configuration, not a permanent council. The control plane validates the plan and owns scheduling.
3. **Independent permission control plane.** Every runtime-requested side effect becomes a canonical `ToolIntent` evaluated by an injected `PermissionBroker` as `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`. A harness cannot grant itself authority or acquire an alternate execution path.
4. **Independent sandbox abstraction.** Execution requirements are matched against explicit provider capabilities. Docker, future remote providers, and an explicitly unsafe local provider remain interchangeable only at this controlled boundary; the harness never selects its own boundary.
5. **Evidence-first delivery.** A structured `EvidenceBundle` binds the task, plan, canonical patch, commands, test/build results, verifier verdict, risks, and proof gaps. `CompletionGate` distinguishes lifecycle completion from verified completion and rejects simulated output as executed proof.
6. **Versioned Fleet evolution.** Organizational changes are typed `FleetPatch` proposals with protected-path validation, semantic/textual diffs, before/after hashes, explicit application, audit history, and rollback. Agents never silently rewrite their own permissions or instructions.

Phase 1.5 establishes these contracts and exercises an honest offline subset before Phase 2 provider integration or Phase 3 Docker execution. It does not pull Phase 4 persistent trust or Phase 6 operational FleetPatch commands forward.

## Alternatives considered

- **Position the project as a general multi-agent framework.** Rejected because the category is too broad and does not explain a defensible user outcome.
- **Keep a fixed CoS/Engineer/Verifier roster.** Rejected because even simple tasks would pay unnecessary coordination cost, while complex tasks could not add the required specialties or parallelism.
- **Let each model harness own tools, permissions, or execution.** Rejected because policy semantics would vary by adapter and framework-native tools could bypass the product's audit boundary.
- **Treat successful workflow execution as proof of task completion.** Rejected because model assertions and simulated command results are not evidence that code was built or tested.
- **Allow the organization to update its own configuration directly.** Rejected because silent self-modification is neither reviewable nor safely reversible.

## Consequences

- Provider and sandbox integrations are blocked until Phase 1.5 contracts and acceptance tests pass.
- Extensible role and workflow identifiers are separated from authority; permissions continue to depend on trusted project, run, task, stage, action, resource, and sandbox context.
- Adaptive plans remain proposals constrained by deterministic validation, budgets, declared roles, and completion policy. This is not an unrestricted agent swarm.
- Repository intelligence and evidence carry provenance, confidence, hashes, and explicit unknowns. Generated prose is not promoted to fact merely because an agent wrote it.
- The architecture contains more explicit domain objects and gates than a simple agent loop, but those objects are the product's differentiating control plane.
- Documentation and CLI output must always distinguish what is enforced now, what is partially demonstrated with fake adapters, and what remains roadmap work.
