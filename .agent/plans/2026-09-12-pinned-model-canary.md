# One explicitly pinned-model mixed-Harness diagnostic canary

This ExecPlan is living. Maintain Progress, Discoveries, Decision Log and Outcomes.
This tracked record was created after the live04 dispatch from the earlier private
`mixed-live04-protocol.md`; it does not claim that this file existed before dispatch.
The pre-dispatch protocol and separate manual decision remain the original authority.

## Purpose and user-visible result

Measure one unchanged CLI canary under an explicitly reviewed dated-model selection
at the two strict SDK boundaries. A user should see the actual typed outcome and
cleanup evidence, including a failed or inconclusive result, rather than a guessed
explanation for a prior response-model mismatch. This is a configuration experiment,
not a production repair, automatic retry or permanent model recommendation.

The existing operator entry point remains:

```sh
.venv/bin/python scripts/run_live_canary.py --run \
  --selection reviewed-roles.json \
  --image agent-fleet-runner:0.1.0-py314-v1 \
  --output /absolute/private/new-canary-evidence
```

This is a command-shape example, not authorization to rerun live04. Root already
dispatched the one approved attempt through the private hidden-input launcher04.

## Scope

### In scope

- One finite original live canary from clean delivered PR13, with only the two
  explicitly selected model strings changed from live03.
- Retained safe selection/accounting/CLI/evidence records and stopped-owner
  independent readback; later documentation of the actual result.
- Un-packaged plan/ledger bookkeeping. All556 accepted source/build/README/guide
  inputs remain unchanged.

### Out of scope

Production, tests, schemas, SDK/dependency changes; widened response identity,
endpoint/header/body admission; permission or budget increases; new providers;
model fallback, automatic further attempt, accepted-patch apply, image pull/build,
worker networking, package publication, actual campaign or native P0 qualification.

## Current repository state

Execution is from delivered PR13 merge
`606a255580c9ee76f75e899de533431d5ca58c5d`, identical to accepted head
`1577eb0914f6b4757d7fd706634bac076ff05a63` at tree
`83868cd4efebb2b8607f73adcf6e5f112aa24546`. D/E delivered normally at13:55:02Z;
postmerge original54-case smoke passed4.38s with556 accepted inputs unchanged.
The new `codex/p1-pinned-canary-results` branch contains only later documentation.
See `2026-09-12-baseline-delivery.md` for non-additive full/optional/delivery evidence.

`scripts/run_live_canary.py` invokes the original
`tests/live/test_provider_smoke.py::test_live_provider_cli_cos_engineer_verifier_canary`.
Its `assert_live_canary_verification` oracle and prepared fixture remain unchanged.
The runtime registry selects exact adapters; `RunModelBindings` freezes the
effective roles and `CompletionGate` derives assurance from authoritative evidence.
The model cannot grant permissions or bypass `ToolGateway`/`PermissionBroker`.

## Security impact

No trust boundary changes. One dedicated user-authorized credential reference
serves the selected OpenAI roles. Root supplies its value only through hidden stdin
to a transient trusted parent: no key in files, argv, logs, model context, worker
mounts or subagents. No ambient/additional-provider credential discovery is allowed.
Credentials remain outside Docker. Exact response-model equality and all existing
request/response checks continue to fail closed; raw returned models/provider
responses are not collected to explain failure. Unknown accounting stays unknown.

Only the already-prepared local standard image and matching local daemon are used.
Their pre-dispatch identity check is recorded in the private protocol; this document
does not issue another Docker command. Tool requests still require the original
scope-bound approvals; no success verdict grants source-apply authority.

## Proposed design and public contracts

There is no new public contract or implementation. The explicit selection is:

| Role | Harness | Exact provider model |
| --- | --- | --- |
| CoS | PydanticAI | `openai:gpt-5-nano` |
| Engineer | OpenAI Agents SDK | `openai:gpt-5-nano-2025-08-07` |
| Verifier | restricted LangGraph | `openai:gpt-5-nano-2025-08-07` |

Original role closure/defaults, exact task/criterion, permissions and oracle remain.
The private selection's raw-file SHA256 is
`14450b558787f42f05c7181b72125da4819a2911fce4f5716fff461746a07430`;
parsed canonical SHA256 is
`63e7e8be26d778abe4bf7920db0556726ae88b0ee81ad0fc073e6c65ef9020d1`.
These identities are distinct and must not be interchanged.

The private protocol records an official model-page check on2026-09-12 at
<https://developers.openai.com/api/docs/models/gpt-5-nano>, listing the dated model
as Deprecated. This is a historical operator check, not a new availability claim,
permanent recommendation or authorization to substitute a newer/pricier model.

## Milestones

1. Complete live03 stopped independent readback and D/E exact Git delivery before
   a separate informed manual decision; preserve all earlier failures.
2. Dispatch exactly one pinned live04 with immutable selection/source identities.
3. After owners stop, reconcile terminal CLI/test, role/request/usage and typed
   patch/command/verifier artifacts, original source and exact cleanup.
4. Obtain independent bounded verdict and document the result without upgrading
   failed attempts, unmeasured costs or wider campaign status.

## Detailed implementation steps

1. Retain `mixed-live04-protocol.md`, the credential-free parsed selection and
   private launcher04's exact-head/raw-file guards. No source file changes.
2. Use the existing original task: only `src/canary_calc/core.py`, an explicit
   zero-divisor ValueError guard, Engineer write/test and independent Verifier test,
   canonical patch/command/independent-verdict requirements. Do not edit the oracle.
3. Root's one private dispatch records `openai-mixed-live-04`; do not read active
   fixture/DB/credential contents or send a second invocation from this docs slice.
4. Once stopped, the separately assigned verifier reads only admitted safe evidence
   and exact immutable state/cleanup metadata. Record actual results here and in
   the P0/P1 plan and acceptance ledger; do not rewrite original evidence bundles.

## Validation plan

Keep the original one-attempt/900-second launcher limit and12 approval-loop iterations.
The root envelope is12 invocations,24 requests,32 tools,65536 reported tokens and
600 active seconds. Each role remains8 requests,12 tools,32768 tokens,120 seconds
and1 configured retry. These are existing runtime bounds, not authority for a
second whole attempt or guaranteed pre-spend dollar ceilings.

Expected passing evidence must bind the canonical selection and frozen role profiles
to actual CoS, Engineer and independent Verifier execution, real Docker receipts,
canonical patch, original-source preservation, `CompletionGate` decision and exact
complete cleanup. Test exit0, bootstrap fake-agent receipts, configured roles or
an empty namespace alone are insufficient. Preserve failed requests and null usage;
do not estimate account billing or silently normalize an unexpected model identity.

This docs task runs no tests, Git operations, Docker/provider requests or DB probes.
Its checks are bounded text/whitespace, evidence-hash and556-input comparisons.

## Rollback and recovery

No migration or production rollback is needed. Preserve the selection and all raw
failed/ambiguous evidence. Wait for stopped owners before exact resource readback;
never prune globally or remove fixtures to pass. A timeout or uncertain descendant
state is not proof of cleanup and does not permit automatic recovery/replay.
Any subsequent attempt or model change needs a new informed manual decision.

## Progress

- [x] Private pre-dispatch protocol and credential-free selection parser checks
  preceded the attempt; raw/canonical digests above were recorded separately.
- [x] Live03 stopped NOT_PASSED; its independent failed-attempt audit passed/read
  release13:44:44.347799Z. Report `mixed-live03-readback.tm0PwoSS/VERDICT.md`
  SHA256 `bb8ef5f08f37d739ee05627ae15690f424b93bdadb97b0925a70b18c2dc2b47a`.
- [x] D/E PR13 delivery/postmerge smoke completed; all heavy tests stopped and
  both execution/bookkeeping checkouts were clean at the delivered merge.
- [x] (2026-09-12T13:57Z) Root separately decided and dispatched exactly one pinned
  live04 through hidden-input launcher04 from the accepted clean primary checkout.
- [x] Later tracked plan created from the private protocol. No claim that this
  tracked file existed before dispatch or that documentation initiated another run.
- [x] Live04 stopped NOT_PASSED:2026-09-12T13:57:54.978425Z–13:58:49.445718Z,
  54.467s wall; pytest1 failed/52.66s,13 warnings. Target
  `run_b2ce5fa98bd54c0b81f6f3c1515a9d7f` completed one CoS request with4684 input,
  4633 output and9317 total tokens. Engineer's first reserved request remains
  UNKNOWN: two invocations/two requests total, zero target tools/commands/patch/
  Verifier. Exact CLI and `run.failed` message is
  `The Agents SDK rejected response processing.` with `provider_sdk/response_policy`.
  Cleanup reports complete/no outstanding leases; these are runner records, not
  independent physical acceptance.
- [x] Independent failed-attempt readback PASS/read release14:04:35.683988Z,
  actual live outcome still NOT_PASSED. `mixed-live04-readback.xy2UP1bs/VERDICT.md`
  SHA256 `ad2b1c7ff10f354378c6c3a0947122936f33e82290b4659f7521a5b7ccdfffea`.
  Safe CLI and direct immutable run.failed event37 agree; typed accounting confirms
  CoS1/9317 reported tokens, Engineer1 unknown, two invocations/two reservations,
  zero target tools/commands/patch/Verifier. All33 artifacts validate:21 run-scoped
  exports and12 project records remain distinct. All8 leases released,3 workspaces
  absent, exact namespace `bac0631c525e142d2f27d2a3c9b8957d` empty and2 bootstrap
  native IDs absent on the matching e470601e-5d84-43d4-8c9d-2038812fa634 daemon.
  All140 fixtures, both556 input maps and raw/canonical selection hashes unchanged.
  No04 auditor assertion failed. The original inconclusive/cleanup_unproven bundle
  remains unchanged; later cleanup supplements it without assurance promotion.
- [x] Final six-document/PR-body independent review PASS12 checks; read release
  14:37:48.260528Z, canary-final-docs-verifier.G6dePeM3/VERDICT.md SHA256
  e49819b6226412cff3579d30a2452c9b92c779d255869cfced21b4780fa16bcf.
  All556 accepted inputs unchanged. This is documentation acceptance only.
- [ ] Documentation commit/push/exact-head normal merge.

## Discoveries

- Live03's finite message proves the model-identity guard branch, not the returned
  model value. Engineer usage/charge remain unknown; its32768 unknown-token allowance
  is not measured consumption. Two CoS requests reported21449 tokens.
- Live03's original bundle is inconclusive/cleanup_unproven. Later audit proved
  exact cleanup without rewriting that bundle or establishing provider success.
- Live02 remains FAILED with its original unresolved field/unknown charge. Neither
  live03 nor this experiment retrospectively explains its exact returned response.
- Live04 retained a different finite response-processing message from live03's
  model-mismatch message. Raw details are unavailable: this does not prove pinning
  fixed model identity, distinguish SDK rejection from incomplete-response paths,
  reveal a returned model or establish deprecation as the cause. Engineer usage/
  charge remain unknown;9317 is measured CoS usage only.
- Completed read-only static SDK assessment PASS/read release14:06:57.222639Z,
  `sdk-live04-branch-map.l8PBxAXi/VERDICT.md` SHA256
  `bfd691fbd7bc637e0d528d1ebd821cf795353d058ecb18c784ce2da9b088da4c`.
  Installed openai-agents0.22.1/openai3.8.0 maps the explicit ModelBehaviorError
  nonstreaming HTTP path to the shared failed/incomplete guard before Fleet's
  model/status/error checks. It establishes no actual live status/model/reason or
  offline-reproducible application defect, so no source repair is justified.
  The retained synthetic model-and-failed case confirms that this earlier guard
  can hide later identity validation. Static AST-wrapper correction is retained;
  this is not raw-response evidence or another provider attempt.
- The initial live03 raw/canonical preflight failure occurred before credential/
  output/request dispatch. The retained operator correction is not erased or counted
  as a second consumed provider attempt.

## Decision Log

- Decision: explicitly pin only Engineer/Verifier to the documented dated identifier
  for one separately authorized configuration experiment; preserve CoS's alias.
  Rationale: test a bounded model selection without weakening exact response admission.
  Alternative rejected: accepting model aliases/snapshots interchangeably, silent
  model fallback or automatic retry. Date:2026-09-12.
- Decision: create this tracked operational record after dispatch, acknowledging
  chronology and retaining the prior private protocol. Rationale: accurate provenance,
  not retrospective pre-registration. Date:2026-09-12.

## Outcomes

Live04 stopped NOT_PASSED with the finite response-processing message and9317
reported CoS tokens above. Engineer usage/charge and raw cause remain unknown.
Independent stopped-evidence/physical readback passed14:04:35.683988Z, confirming
the finite failed-attempt/accounting/cleanup contract, not live success. The original
bundle stays inconclusive/cleanup_unproven despite supplemental cleanup. No pinning
success or new mixed-Harness qualification is claimed; this record authorizes
neither source repair nor attempt05. Source556 and frozen packaged
README/guide remain unchanged. Even one successful task would not qualify three
mixed-Harness tasks, per-provider six-task sets, external repositories/24-task or
cold-start campaigns, native P0 or all P0/P1. Live02/live03 failures and unknown
accounting remain historical evidence, not candidates for relabeling.
