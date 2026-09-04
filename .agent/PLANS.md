# ExecPlans for Agent Fleet

An ExecPlan is a living, self-contained implementation document for complex work. Its reader must be able to continue the task using only the repository and the plan, without relying on an earlier chat transcript.

Create an ExecPlan when work spans multiple modules, introduces or changes a public contract, affects persistence or migrations, changes security behavior, adds a major adapter, or cannot be safely completed as one small edit.

Store plans under `.agent/plans/<yyyy-mm-dd>-<short-name>.md`.

## Required behavior

- Write the plan before substantial implementation.
- Update it after every meaningful discovery, decision, completed milestone, or deviation.
- Keep `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` current.
- Use repository-relative paths and name important symbols.
- State observable user behavior and acceptance criteria, not only internal tasks.
- Include exact validation commands and expected evidence.
- Document safe retry and recovery behavior.
- Do not erase failed approaches; summarize why they failed when the information will prevent repetition.
- Resolve routine ambiguities using the product and security specifications. Ask the user only for decisions that are genuinely product-defining or impossible to infer safely.
- Keep the implementation runnable at each milestone.

## Required plan template

```markdown
# <Feature or phase title>

This ExecPlan is a living document. Maintain `Progress`, `Discoveries`, `Decision Log`, and `Outcomes` as implementation proceeds.

## Purpose and user-visible result

Describe the user problem and what a user will be able to do when this plan is complete. Include one concrete command-line example or interaction.

## Scope

### In scope

- ...

### Out of scope

- ...

## Current repository state

Describe the relevant architecture and existing implementation. Cite repository-relative paths and important classes/functions. Explain unfamiliar terms.

## Security impact

List affected trust boundaries, permission actions, secret flows, sandbox behavior, external side effects, and audit events. State which invariants from `docs/SECURITY_MODEL.md` apply.

## Proposed design

Explain the end-to-end behavior, domain state transitions, ports, adapters, persistence changes, and error paths. Include a small diagram where useful.

## Public contracts

List added or changed CLI commands, configuration fields, Pydantic models, protocols, event types, database schema, exit codes, and compatibility behavior.

## Milestones

### Milestone 1: <name>

Describe the smallest demonstrable increment.

Acceptance:

- ...

### Milestone 2: <name>

...

## Detailed implementation steps

Use an ordered list. Every step should name files or symbols and describe the intended code, not merely say “implement feature.”

## Validation plan

List focused tests, full tests, manual commands, fixture repositories, expected events/artifacts, and negative/security cases.

## Rollback and recovery

Explain idempotency, partial-failure cleanup, database migration rollback or forward-repair, orphaned worktree/container cleanup, and how a user resumes or abandons a paused run.

## Progress

- [ ] (timestamp) ...

## Discoveries

- Observation: ...
  Evidence: ...
  Consequence: ...

## Decision Log

- Decision: ...
  Rationale: ...
  Alternatives: ...
  Date: ...

## Outcomes

Summarize what shipped, what evidence passed, remaining gaps, and follow-up work.
```

## Plan quality bar

A good plan makes implementation and review easier. It must answer:

- Which user journey becomes possible?
- Which trusted component authorizes and executes each side effect?
- What can fail at every boundary, and what persisted state remains afterward?
- How is work resumed without duplicating a side effect?
- Which exact evidence proves the feature works?
- Which limitations are intentionally deferred?

A plan is not a task-list dump, a restatement of the product spec, or a prediction that everything will work. It is the repository-local operational record of how the feature is being built.
