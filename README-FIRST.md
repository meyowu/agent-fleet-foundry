> **Historical implementation brief.** To install and use the current product,
> start with the [public README](README.md). This file describes the original
> development kit, not the current installation procedure.

# Agent Fleet — Codex implementation kit

This kit is a complete implementation brief for a greenfield, local-first, BYOK multi-agent coding fleet whose primary user interface is a Chief of Staff (CoS).

## Working product name

- Product/CLI name: `fleet`
- Python package name: `agent_fleet`
- These names are provisional. Do not spend time on branding before the MVP works.

## Files in this kit

- `AGENTS.md` — persistent repository-wide instructions for Codex.
- `.agent/PLANS.md` — rules and template for living execution plans.
- `docs/PRODUCT_SPEC.md` — product behavior and user experience.
- `docs/ARCHITECTURE.md` — components, dependency boundaries, protocols, data model, and repository structure.
- `docs/SECURITY_MODEL.md` — threat model, permissions, always-allow semantics, sandboxing, secrets, and audit requirements.
- `docs/IMPLEMENTATION_ROADMAP.md` — phased build plan with acceptance criteria.
- `docs/CONFIG_AND_SCHEMAS.md` — configuration examples and canonical domain types.
- `docs/ROLE_PROMPTS.md` — built-in CoS, Engineer, and Verifier behavior contracts.
- `CODEX_BOOTSTRAP_PROMPT.md` — the first task to paste into Codex.
- `CODEX_PHASE_PROMPTS.md` — follow-up prompts for later phases.

## How to use

1. Create or open an empty Git repository.
2. Copy this entire kit into the repository root, preserving paths.
3. Start Codex in the repository with workspace-scoped write access and approval-on-boundary-crossing behavior.
4. Paste the contents of `CODEX_BOOTSTRAP_PROMPT.md` as the first task.
5. Review the implementation and tests after each phase before sending the next phase prompt.

Do not paste the full contents of every specification file into each Codex message. `AGENTS.md` tells Codex which files to read, while the phase prompt tells it what to implement next.

## Product thesis

The user should interact primarily with one persistent Chief of Staff. The CoS scopes work and delegates bounded tasks to ephemeral specialist agents. The system, rather than the model, owns permissions, sandboxing, workflow state, audit logs, artifacts, and approval gates.

The product is not another free-form “agents chatting with agents” demo. Its unit of value is a verified, reviewable artifact such as a code patch, test evidence, a verifier verdict, or a proposed fleet configuration change.
