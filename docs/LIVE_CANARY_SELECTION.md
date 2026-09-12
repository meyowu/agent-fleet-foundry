# Explicit live Canary role selections

The optional launcher can exercise the existing Provider/Harness adapters with
an explicitly reviewed model binding for each of CoS, Engineer and Verifier.
This is bounded test infrastructure, not a claim that every admitted combination
has passed live qualification or the separate six-task/mixed-role campaigns.

Without `--selection`, the existing path remains PydanticAI with
`openai:gpt-5-nano` and `env:FLEET_OPENAI_TEST_KEY` for all three roles. It does
not obtain credentials from a ChatGPT subscription or create an API key.

## Review the selection

Create a JSON document containing exactly these fields. This example selects
three Harnesses using the same OpenAI credential; it is an explicit test
configuration, not a pre-qualified mixed-Harness claim.

```json
{
  "schema_version": 1,
  "cos": {
    "runtime_name": "pydantic-ai",
    "provider_model": "openai:gpt-5-nano",
    "credential_ref": "env:FLEET_OPENAI_TEST_KEY"
  },
  "engineer": {
    "runtime_name": "openai-agents",
    "provider_model": "openai:gpt-5-nano",
    "credential_ref": "env:FLEET_OPENAI_TEST_KEY"
  },
  "verifier": {
    "runtime_name": "langgraph",
    "provider_model": "openai:gpt-5-nano",
    "credential_ref": "env:FLEET_OPENAI_TEST_KEY"
  }
}
```

Admission follows the production runtime configuration contract:

| Runtime | Admitted provider prefixes |
| --- | --- |
| `pydantic-ai` | `openai`, `openai-chat`, `anthropic`, `google` |
| `openai-agents` | `openai` |
| `langgraph` | `openai` |

Model identifiers must be explicitly chosen and available to the configured
account. Admission does not establish availability or successful inference.
There is no model/provider/credential fallback.

The initialized catalog also contains Architect and Researcher. For a non-default
canonical selection, the fixture deliberately binds the reviewed CoS profile as the default
for these two unused ancillary roles, then sets the three exact primary-role
overrides. The final selection revision is4 and admission freezes all five
bindings. This deterministic configuration policy is not automatic fallback,
permission to execute extra roles, or evidence that ancillary agents ran. The
Canary still requires only CoS, Engineer and independent Verifier execution.
The legacy canonical selection keeps its existing single default profile and
revision1, whether selected implicitly or through an equivalent JSON file.

Credential references must use the dedicated uppercase namespace
`env:FLEET_[A-Z][A-Z0-9_]*`. For example, `env:FLEET_ANTHROPIC_TEST_KEY` is valid;
`env:ANTHROPIC_API_KEY`, `env:SSLKEYLOGFILE`, loader variables and Fleet control
variables are not accepted as credential destinations. This prevents a selected
key from changing TLS, loader, shell, Docker, telemetry or provider routing.
Distinct provider families must use different variable names **and key values**.

Never put a key in this JSON, a command argument, a repository file or model
prompt. Export the selected values only in the trusted launching shell, using
your normal non-echoing credential input. The launcher passes only selected
credentials in a cleared child environment. Worker sandboxes receive no keys.

Unknown fields, duplicate JSON fields, alternate schema versions, fake runtimes,
unsupported pairings, endpoint or budget overrides and unsafe variable names
are rejected before credential lookup, evidence-directory creation or dispatch.
Selection files must be regular, non-symlink files of at most16 KiB; FIFOs are
rejected promptly. Parsed canonical JSON, not a mutable file pointer, reaches
the test process. Its digest binds attempt, role bindings, usage and result.

## Run one attempt

Use the pinned contributor environment and an already prepared local Docker
runner. Choose a **new absolute** private evidence directory outside the checkout.

```sh
.venv/bin/python scripts/run_live_canary.py --run \
  --selection reviewed-roles.json \
  --image agent-fleet-runner:0.1.0-py314-v1 \
  --output /absolute/private/new-canary-evidence
```

Omit `--selection reviewed-roles.json` to use the unchanged default configuration.
The launcher does not retry automatically, apply the patch to the target, publish
anything or widen approval scopes. It retains the original failed attempt.

The existing finite limits remain: one whole attempt,900-second launcher wall,
12 approval-loop iterations, and a root envelope of12 agent invocations,
24 model requests,32 tool calls,65,536 tokens and600 active seconds. Each role
profile is additionally bounded. Reported-token ceilings are post-response
accounting, not guaranteed pre-spend ceilings. These limits are **not a dollar
spending cap**. Pricing/unknown costs and separate campaign budgets must not be
invented from a successful exit code.

A passing result requires the actual CoS → Engineer → independent Verifier
workflow, frozen selected runtime/model/profile identities, real Docker command
evidence, reviewable patch, completion decision and complete resource cleanup.
Skipped tests, pytest exit0 alone, a mismatched selection digest or an unsupported
combination are not passing qualification. All selected credential forms are
checked before output/evidence persistence. Failed or ambiguous cleanup remains
visible; do not erase evidence or automatically replay the task.

## Validation boundary

Ordinary selection, public profile-binding, environment isolation, admission,
redaction and no-false-pass tests run without keys, Internet or Docker. Live
qualification results are separately recorded in the [acceptance ledger](MVP_ACCEPTANCE.md#p1-b--explicit-canary-selection-infrastructure-2026-09-12)
and the [living ExecPlan](../.agent/plans/2026-09-11-p0-p1-completion.md).
Infrastructure acceptance does not satisfy the new-provider six-task qualification
sets, three cross-provider tasks or three mixed-Harness tasks by itself.

The example's mixed-Harness selection was attempted once after the complete
offline gate on 2026-09-12. CoS/PydanticAI completed, then Engineer/OpenAI Agents
SDK failed its response-policy check; Verifier/LangGraph did not execute. The
target executed no tools and produced no patch. One request has unknown usage,
so the total charge cannot be established from the local report. The launcher
retained this failure and complete cleanup evidence without automatic retry.
The specific rejected response field is unresolved; do not remove identity,
terminal-status or usage validation to make this example pass.
