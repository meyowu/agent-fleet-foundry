# One low-cost non-reasoning Harness compatibility experiment

This living ExecPlan is written before dispatch. Maintain Progress, Discoveries,
Decision Log and Outcomes. It permits a configuration-only test, not new runtime
implementation or an automatic retry of the prior failed model selections.

## Purpose and user-visible result

Determine whether the original real CoS → Engineer → independent Verifier
Canary can complete with a low-cost non-reasoning model at the two strict SDK
boundaries. Preserve the exact task, approvals, original-source non-application,
structured artifacts and CompletionGate. A failing attempt remains failing.

## Scope and current repository state

The test executes clean delivered PR13 commit
`606a255580c9ee76f75e899de533431d5ca58c5d`, not this documentation worktree.
All556 source/README/guide inputs match its accepted full/static/optional gates;
postmerge54-case smoke passed4.38s. No implementation, schema, dependency,
permission, budget, prompt, fixture or test assertion changes are in scope.
No future productization, native P0 bypass, broader campaign or new provider.

Live03 rejected a response-model comparison. Live04's explicit dated GPT-5 nano
selection failed inside SDK response processing. Its independent failed-attempt
audit passed; the model outcome did not. Static inspection of pinned Agents
0.22.1/OpenAI3.8.0 narrows the explicit nonstreaming ModelBehaviorError factory
to the shared failed/incomplete guard before Fleet's identity check, but cannot
recover the actual status/reason or justify a source fix. Preserve both attempts.

## Security impact and public contracts

Only reviewed role bindings change through the existing schema-version1 selection:
CoS stays PydanticAI/openai:gpt-5-nano; Engineer/OpenAI Agents SDK and
Verifier/restricted LangGraph explicitly select
`openai:gpt-4.1-nano-2025-04-14`. All use the same dedicated credential reference
`env:FLEET_OPENAI_TEST_KEY`, supplied through hidden stdin into a trusted transient
parent. No credential files, arguments, model context, worker mounts or subagents.
No fallback, relaxed model/status/usage validation, raw exception inspection or
automatic patch application. Existing PermissionBroker and Sandbox boundaries stay.

The [official model page](https://developers.openai.com/api/docs/models/gpt-4.1-nano)
checked2026-09-12 documents non-reasoning tool/structured-output support and the
dated selection. Input0.10/cached0.025/output0.40 USD per1M tokens is a reference,
not an invoice or dollar cap. Input is more expensive than GPT-5 nano's0.05;
this is a low-cost alternative after its failed trials, not a globally-cheapest
or permanent model recommendation. The page includes a Deprecated label; account
availability and actual successful inference must be demonstrated, not assumed.

## Proposed design and milestones

1. Parse the explicit selection offline and bind its raw/canonical digests.
2. Confirm prior stopped cleanup, clean accepted code and prepared local Docker.
3. Root records a separate manual decision and launches exactly one original
   Canary using a new private evidence directory. No additional paid attempt in
   this experiment follows its terminal result.
4. Independently read actual CLI/durable artifacts and exact cleanup after owners
   stop; document success or failure, then commit/push/normal exact-head merge
   the documentation with [skip ci]. Do not claim that delivery before readback.

## Validation plan and finite envelope

Use the unchanged `scripts/run_live_canary.py --run --selection ... --image
agent-fleet-runner:0.1.0-py314-v1 --output <new-private-evidence>` and original
live test. Root12 invocations/24 requests/32 tools/65536 reported tokens/600 active
seconds; role8 requests/12 tools/32768 tokens/120 seconds/1 retry; launcher900
seconds. Post-response/unknown accounting is not a guaranteed pre-spend ceiling.
No image pull/build or worker network. All heavy test processes must be stopped.
Reuse accepted unchanged-source offline evidence, checking hashes and docs/diff
consistency; no retrospective promotion of skipped tests or prior failed bundles.

## Rollback and recovery

Do not replay a failed or ambiguous owner. Preserve every output directory and
unknown charge. Native metadata checks are exact-scope and read-only; no broad
cleanup or fixture deletion. Original project patch application remains separate.
Revert documentation through normal review if necessary, not state deletion.

## Progress

- [x] Pre-dispatch selection parsed by the production helper. Raw SHA256
  `8398f5f361d437abdb34c6891eb91f79a5c71d42b4bafe8d9a5729ea77fa205f`;
  canonical SHA256
  `9de1b68b151c58a3752b9aa6a9705b05903be8933d59c500618c2bef6248d4bc`.
- [x] Prior04 failed-attempt audit PASS/read release14:04:35.683988Z; report
  mixed-live04-readback.xy2UP1bs/VERDICT.md SHA256
  ad2b1c7ff10f354378c6c3a0947122936f33e82290b4659f7521a5b7ccdfffea.
  Static assessment released14:06:57.222639Z; report
  sdk-live04-branch-map.l8PBxAXi/VERDICT.md SHA256
  bfd691fbd7bc637e0d528d1ebd821cf795353d058ecb18c784ce2da9b088da4c.
- [x] Final preflight2026-09-12T14:16:49Z: clean primary606a255; both556
  accepted maps unchanged; new output absent; launcher AST valid; no owned heavy
  test processes. Prepared image SHA256
  2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241
  linux/arm64 and daemon e470601e-5d84-43d4-8c9d-2038812fa634 linux/aarch64
  freshly match. Disk has14GiB available; no deletion or pull/build.
- [x] Independent bounded pre-dispatch review PASS12 checks, read release
  14:18:20.155306Z; live05-predispatch-verifier.iNjcw9rZ/VERDICT.md SHA256
  0d08d2465de8435d8f55a237cd81a780a3ce3df82c0581f5d7fc3ca7730768b3.
  Only model selections and their launcher filename/digest/output differ from04;
  no changed security/budget/single-child/no-fallback control flow.
- [x] Root separate manual decision2026-09-12T14:19Z: dispatch exactly one
  configuration-only05 Canary from clean606a255 using the guarded hidden-input
  launcher05. The unchanged envelope above and existing user authorization apply.
  Preserve prior failures; no automatic second attempt or source repair.
- [x] Exactly one live05 dispatch stopped normally NOT_PASSED, exit1,
  2026-09-12T14:19:49.008936Z–14:20:26.503411Z,37.495s wall;
  pytest1 failed/35.69s/13 warnings. Runner assertions false; cleanup complete,
  recovery not withheld, diagnostic_errors empty. Target
  run_8f55c18e3547410bb929945ddc0bc13c returned RUNTIME_OUTPUT_INVALID with
  output_schema/schema_validation and the finite message
  "The bounded Agents SDK invocation did not satisfy its trusted contract."
  This is not an exact explanation of the returned content, a justified source
  repair or qualification of the configured Verifier. No further paid attempt.
- [x] Independent stopped-owner audit PASS, read release14:27:18.204341Z;
  mixed-live05-readback.pamnbbdY/result.json SHA256
  33c54cbc07c289fea9a5cd2b09f513b2c60f9ff097acbdcbe722f1fe9c3d1b74.
  Human VERDICT.md SHA256
  952cd3a8efe4e0f81e898dbd0050ad71ea1381ab59a12c8906a2ed8f3d1273d7
  confirms the same read release and machine evidence.
  Actual model outcome remains NOT_PASSED. CoS1 request4678 input+2304 output
  =6982 tokens; Engineer4 requests10201 input+304 output=10505; total17487
  reported tokens across5 requests, zero unknown/outstanding requests. Dollar
  billing is not reported; complete token accounting is not an invoice.
  Engineer executed workspace.get_diff, workspace.write_file and command.run.
  One standalone real-Docker python -m pytest exit0 receipt exists, but no accepted
  structured Engineer completion, Run-attached command receipt, accepted patch or
  Verifier invocation exists. Do not describe this attempt as zero tools/commands.
  All36 artifact hashes/sizes validate (24 Run exports +12 project records).
  Nine leases released;3 workspaces and3 native IDs absent; exact namespace
  5fbbf50e61a8105ebc63d1a6280eceea empty. Original project/head/status, all143
  fixture files, raw/canonical selections and both556 accepted maps unchanged.
  Original bundle remains inconclusive/cleanup_unproven; the standalone receipt
  and later cleanup supplement it without rewriting or promoting assurance.
- [x] Final six-document/PR-body independent review PASS12 checks, read release
  14:37:48.260528Z; canary-final-docs-verifier.G6dePeM3/VERDICT.md SHA256
  e49819b6226412cff3579d30a2452c9b92c779d255869cfced21b4780fa16bcf.
  Source556 unchanged;22 relative links valid; scope/sensitive-pattern/evidence
  checks passed. Postrelease changes only record actual report identities and
  this verdict; they do not expand qualification or dispatch authority.
- [ ] Documentation commit/push/exact-head normal merge.

## Discoveries

The SDK-processing message is lossy: neither a token-limit explanation nor a
successful pinned identity check is established. A new configuration experiment
must not turn that uncertainty into a claimed application bug or guard bypass.

Live05 reaches actual Engineer tools and a passing command, then fails the bounded
structured-output contract. The raw schema-validation cause is not retained and
is not inferred. A standalone receipt is not the accepted Run evidence list or
an independent Verifier verdict; its existence cannot make the incomplete bundle
verified. Earlier03/04 unknown usage remains unknown despite05's complete counts.

## Decision Log

- September12: examine one explicitly different low-cost non-reasoning model
  configuration, preserving the functioning CoS selection and all guards. This
  is a compatibility experiment, not an inferred remedy or automatic fallback.

## Outcomes

NOT_RUN at plan creation; actual05 subsequently stopped NOT_PASSED as recorded
above. Prior03/04 remain failed and mixed-Harness
qualification remains open. Independent failed-attempt audit subsequently passed
at14:27:18.204341Z with the bounded results above, not model success. No further
paid attempt follows this experiment. Final documentation review passed as above;
Git delivery is pending at this record.
Even a one-task pass would not complete three mixed-Harness tasks, six-task
provider/Harness sets, cold starts, external repositories or native P0.
