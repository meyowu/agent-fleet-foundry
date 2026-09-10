# Bounded read-scope tool-schema guidance

This living ExecPlan records Progress, Discoveries, Decision Log and Outcomes.
It is a bounded offline successor to the current live scope-denial failure, not
permission to replay a spent paid attempt or to relax any acceptance gate.

## Purpose and current state

Current main source30b8f476 has passing local gates but its nano canary failed
after Verifier requested README.md outside its sole allowed core.py scope.
Both test commands passed; final verification did not. Prompt guidance already
explained the scope and did not prevent the request. Make the read tool's schema
carry a conservative scope hint without granting authority or reading files.

The existing GatewayRuntimeToolCatalog advertises one broad path string. TaskSpec
paths denote exact paths or descendants, not necessarily regular files. A closed
file enum would require additional trusted metadata and is not this design.
The existing path predicate casefolds Unicode; ASCII case classes alone are not
equivalent even when the configured scope is ASCII.

## Scope and ownership

One isolated-clone Writer may change only:

- src/agent_fleet/application/runtime_tools.py
- tests/unit/test_runtime_tools.py
- tests/contract/test_action_tool_schemas.py
- tests/contract/test_pydantic_ai_runtime.py
- tests/contract/test_openai_agents_runtime.py
- tests/contract/test_langgraph_runtime.py
- tests/contract/test_anthropic_provider.py
- tests/contract/test_google_provider.py
- tests/integration/test_pydantic_ai_workflow.py

Successor03 additionally owns exactly
`src/agent_fleet/adapters/runtime/langgraph.py`, released only under the
post-registration repair contract below. The original nine-file candidates and
their evidence stay immutable. No other adapter implementation is released.

Root owns this plan and later result documentation. No main edit, provider/Harness
implementation change outside that exact successor seam, workflow/Gateway/Broker/path-predicate change, dependency,
public schema/migration, model setting, instruction prompt or paid call is in scope.
The Session baseline Writer owns a separate clone and disjoint paths; neither
Writer may overwrite the other's files or root-owned documentation. No commits,
pushes or installation by the Writer without root release. Clone origin is local,
never a GitHub or main-worktree publication target.

## Proposed design and security

Capture a bounded immutable tuple of the trusted allowed-path strings at catalog
construction. For at most32 scopes, at most4096 total input ASCII characters and
at most8192 rendered pattern characters, build a conservative JSON Schema pattern
for repo_read_file.path only. Unsupported, empty, root, noncanonical, control-
containing, non-ASCII, wildcard-looking (asterisk/question/bracket), over-depth or
oversized scope sets retain the original broad
schema. Do not add a public configuration toggle or invent file/directory types.

For supported scopes, use only portable literal regex escaping, explicit ASCII
case classes, ordinary groups/alternation, a start anchor and an exact-end or slash
component boundary. A conceptual shape is:

```text
(?:^(?:ESCAPED_ASCII_SCOPE_ALTERNATIVES)(?:/|$)|NON_ASCII_CHARACTER)
```

The non-ASCII alternative is mandatory: admit every non-ASCII input to the existing
Broker rather than accidentally reject legitimate Unicode casefold aliases such
as Kelvin sign/long-s. This is intentionally an overapproximation, not the full
path predicate. No lookaround, inline flags, Python-only anchors, custom regex
engine, filesystem discovery, regex-encoded forbidden-path policy or prompt text.

Canonicality, forbidden/protected scope, symlinks, file bounds, permissions and all
effects remain independently checked by existing catalog/Gateway/Broker/filesystem
code. The schema may admit invalid or nonexistent descendants; it never proves a
file exists or that a read is allowed. No finite-file-enum or regular-file claim.

Return a fresh read-tool definition and nested schema on every definitions access;
do not mutate the shared _READ_FILE or other catalogs. Freeze the original scope
capture so a later mutable TaskSpec list cannot silently change this hint. Preserve
all existing read-tool metadata, required fields and length limits. Other tools'
definitions and executable translation/validation/dispatch logic remain unchanged.

Do not transform a registered secret into regex fragments and expose it through a
schema. Check the original bounded captured scope strings against the shared
Redactor before exposing a narrowed schema, including after late secret
registration. Fall back to the broad schema without publishing the original scope
or a diagnostic containing it. Existing credential handling stays unchanged; test
with synthetic sentinels only. The pattern is a model hint, not a secret boundary.

## Provider and Harness boundaries

Root searched and opened official OpenAI documentation before this contract.
The [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
lists string pattern support; the [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling)
ties strict function schemas to that feature and requires closed objects/all fields
required. This supports investigating the existing strict wire path, not a claim
that the concrete pattern or a live nano call already passed. Keep gpt-5-nano and
all existing budgets/retries unchanged. No provider request is authorized here.

Pinned local PydanticAI forwards basic patterns but its ExternalToolset does not
locally enforce them. A forced well-shaped ASCII out-of-scope call must still
reach the existing Broker denial with no read dispatch. OpenAI Agents SDK must
preserve the strict wire schema and existing local boundary; do not assume its
exact error behavior without a test. LangGraph already validates advertised
schemas before catalog invocation: a pattern-invalid ASCII call can therefore
fail as tool_arguments with no Broker intent or dispatch. This is explicitly
accepted as an earlier no-effect refusal, not a normalized Broker-denial claim.
Every call that can execute still crosses Gateway/Broker. No invalid-call retry
or relaxation of local argument validation is added.

## Milestones and validation

### Successor03 frozen repair contract (2026-09-10 00:49 UTC)

Independent actual-SDK synthetic reproduction rejects candidate02. LangGraph
currently serializes definitions before resolving/registering the selected key;
later literal scans cannot recognize a regex-encoded secret. This is a production
privacy defect in the proposed feature, not permission to weaken the oracle.

Keep pre-credential runtime/capability, duplicate/terminal-name, schema and context
checks: malformed or incompatible input must still perform zero secret resolves,
zero provider-client creation and zero sends. After the one existing selected-key
resolution/registration, freshly obtain and validate definitions from the trusted
catalog's original raw-scope provenance. Atomically retain the resulting names,
validators and wire definitions together; do not reuse the pre-registration
encoded schema or patch its rendered fragments. Re-run safe context validation
before creating a provider client. No awaited work, provider action, new secret
lookup, retries, tracing, budget change or mutable shared schema is introduced by
this preparation. A narrow pure helper or second construction pass is acceptable;
do not create a general adapter framework or change catalog/port public contracts.

Preserve runtime role/capability and duplicate-name checks against the effective
post-registration definitions too. A changed malformed catalog must fail closed;
final local validators must correspond to the actual advertised schema. Retain
all whole-batch identity, accounting, cancellation, tool and permission behavior.
The catalog's raw registered-secret collision falls back to its original broad
schema; a raw credential in ordinary request context must still refuse before
client creation. This specifies selected-key construction ordering, not a claim
that arbitrary later registry mutations are universally re-encoded safely.

Add permanent synthetic late-collision and distinguishing controls in the already
owned LangGraph test module. Preserve the independent four-case failing oracle
unchanged for fresh successor replay. Exercise pre-key invalid schemas, effective
post-key invalid definitions, ordinary positive pattern and credential/context
failures; assert original secret-resolution counts, no extra clients/requests and
physical client closure. Actual pinned PydanticAI and Agents paths need analogous
selected-key collision controls without changing their production implementations.
Complete the held conformance/workflow/permission cohort, the full owned modules
and all six static gates against a distinct frozen successor. No main integration,
paid retry, installation or fresh independent PASS is authorized by this repair.

1. Pure bounded schema generation and immutable/fresh catalog definitions.
2. Actual pinned-SDK offline wire forwarding and forced-invalid-call controls.
3. Fresh independent candidate review, root integration and combined main gates.

Focused tests must cover exact path and descendant positives; parent/sibling/
prefix-lookalike/README/.fleet ASCII negatives; case variants; regex metacharacter
literals; directory scopes without file inference; Unicode configured-scope
fallback and all-non-ASCII input preservation including casefold aliases; empty,
root, control, oversized/deep and mixed unsupported fallback; exact bounds;
no source/filesystem/Gateway operation merely to advertise definitions; source-list
and nested-return mutation; cross-catalog isolation; early/late registered-secret
fallback without exposing an encoded sentinel. Check the allowed ASCII predicate
implication and Unicode preservation using bounded generated examples, without
adding dependencies or weakening the existing executable predicate.

Actual SDK MockTransport tests must inspect OpenAI/PydanticAI and Agents wire
pattern plus strict=true and original required constraints. Preserve the local
length limits and pinned SDK's existing wire transformation: PydanticAI can move
unsupported min/maxLength into descriptions; do not claim those keywords remain
on its strict wire when they do not. Force a denied
PydanticAI read and inspect the unchanged Broker/zero-dispatch result. Exercise
LangGraph actual local pattern rejection with no catalog/dispatch and a valid
positive. Test actual SDK/schema transformers, not a handwritten wire imitation.
Inspect the admitted pinned Anthropic/Google wire transformations too; retain
provider-specific limitations and do not infer universal enforcement.
Keep all original action-schema/role/Gateway/permission/tool-batch regressions.

Use the clone's exact-lock offline environment, with no user credentials and all
live/Docker/install opt-ins disabled. Record original commands, exit codes,
collection/JUnit identities, warnings, timing and before/after candidate hashes.
Run the eight scoped test modules plus applicable existing conformance/workflow/permission
cohorts, Ruff format/check, mypy src/tests/scripts, schema comparison, offline lock
and diff checks. Root will run all final default/optional/package checks after
accepted disjoint integration; component counts overlap and are not additive.
Every failed predecessor stays retained. No paid-run or goal completion inferred.

## Rollback and recovery

Revert only these exact unshipped schema/test edits if independent qualification
fails. Preserve old denied attempts and Session work. There is no migration,
permission grant, model request or resource owner to recover in this slice.
Existing current live receiver/once marker remains spent and immutable.

## Progress

- [x] (2026-09-10 03:43:42 UTC final parent acceptance) Combined main61e79cba
  now passes the default4093/23 matrix, six statics, Docker29, installed3 and
  final pre-live archive1, each independently reconciled. The one actual
  nano/PydanticAI CLI E2E passed1/77.00s; independent parent audit a9681755
  confirms strict Verifier/pass and CompletionGate true, two live commands0,
  minimal two-line patch, complete8-request41963-token accounting and exact
  cleanup. No permission was expanded. Prior30b8 paid failure and candidate02
  privacy failure remain retained. This one success does not prove all scope
  inputs or Provider enforcement; user directs stop after this bounded test.
- [ ] (2026-09-10, explicit qualification reordering before integration) The
  first actual Session attempt terminated with a private null-only recovery-scope
  oracle failure after a successful command/report; its full journey remains
  FAIL and is never replayed. After independent old-source/physical-state readback,
  root may integrate accepted03 using exact before/after guards and rebind the
  next private physical bundle to combined61e79cba. This supersedes the guard's
  initial prerequisite for already-passing physical Session evidence. Its revised
  release must instead bind the explicit reordering contract, failed attempt and
  terminal/drained Session record, with no claim of physical acceptance. Preserve
  the unexecuted earlier guard bytes before this narrow amendment and independently
  review the change. All combined full, physical, optional and live acceptance
  criteria remain mandatory and unchanged; only their preparation order changes.
- [ ] (2026-09-10, root integration preparation) Root created private zRPObe
  read-only before/after guards; syntax parse0 and independent full-source review
  READY on script89417436/PREPARATION2d88a9a3. No guard execution or integration
  release exists. It will require root's hash-bound actual physical Session
  acceptance, exact546 old/new maps, ten preimages, preserved Session11, HEAD and
  empty index. After application it requires the complete Git-listed changed
  set to be exactly those ten paths. Known9837 runtime hashes are held separately,
  without claiming fresh installed membership. Root applies the patch itself;
  this guard never edits source or invokes tests.
- [x] (2026-09-10 01:34:56 UTC) Read-only integration preflight passed in
  private PAvD1J/attempt02. All ten accepted preimages match base2eb44d8 and
  main938589; Session11 are disjoint and all other536 closure entries remain
  unchanged prospectively. Exact patch9a231dec passed git apply --check without
  application. Prospective combined546 is61e79cba174cd05a8ba019c53ec815b6c39800fea394041e89e066e4132d4a10.
  Root read/hash-checked HANDOFF82d79fa2/report0808c5f6. The initial utility
  incorrectly included archive directories as regular source entries and exited1
  before any mutation; its script/receipt are retained. Only a distinct private
  utility's directory filter changed. This is advisory, not combined behavior or
  integration authority: root repeats exact current byte guards after the physical
  Session stage, then applies only the accepted patch.
- [x] (2026-09-10 01:25 UTC) Root read the complete independent successor03
  verdict and delivery seal. Fresh independent896 distinct cases passed:
  unchanged privacy oracle4/1.07s, owned526/33.19s, regression366/463.58s;
  wrappers4.383/38.007/468.259s, all original exits0. Six statics and a separate
  explicitly pinned-interpreter offline lock check pass. Seal at01:12:12.516062
  UTC: VERDICT.md ea22b907, VERDICT.json1f1a8e5f, deliveryf9570e4f in private
  vrMku5. All605 snapshot/543 source/9886 runtime files unchanged; four persisted
  Broker denials have zero dispatch. Writer892 overlap, not additional cases.
  Retained19 generated workspaces and38 logical negative-fixture leases are
  classified as19 nonexecuting fake sandbox handles and19 Git workspaces, not
  physical zero-resource proof. Candidate01/02 failures remain retained. Root
  accepts this narrow offline slice; main integration waits for the separately
  source-bound physical Session qualification. Current main is546/93858963.
- [x] (2026-09-10 01:05 UTC) Root completely read and hash-checked the final
  Writer handoffcd332dd8,qualification00673c42 and identityae555411. Successor03
  has892 disjoint Writer passes:owned526/33.48s and other366/463.53s,one Google
  warning per cohort,all original exits0; six statics0. All533 other closure
  entries and full9886-file clone runtime identity match. Evidence-only report/
  receipt filename collision was preserved and reconciled with distinct names;
  no product/test/predecessor bytes changed. No Writer pytest remains active.
- [ ] (2026-09-10 01:06 UTC) Fresh independent original four-case oracle passed
  unchanged (1.07s pytest/4.383s wrapper),13 pinned LangSmith warnings,exit0.
  Independent owned526 also passed33.19s/38.007s,14 warnings. These are partial
  acceptance only: the fresh20-module regression and final reconciliation remain
  active. Full605-file snapshot,543 source inputs and9886 runtime bytes stayed
  unchanged. The initial offline lock command selected another supported Python;
  its receipt is retained while an explicitly pinned-interpreter readback is added.
  No main integration, model request or universal later-registration guarantee.

- [ ] (2026-09-10 01:02 UTC) Successor03/source5433aff14e6 is frozen on exactly
  ten paths,patch9a231dec. Root read the complete LangGraph preparation diff:
  synchronous pre-key and post-registration passes each take one catalog snapshot,
  coherently reused for admission/names/validators/wire, with one secret lookup.
  Writer owned526 tests passed33.48s (37.733456s wrapper),one Google warning;
  six static gates exited0 and source unchanged. Twenty-module regression remains
  active. Fresh current_receiver_verifier has the original immutable four-case
  privacy oracle and explicit one-parent replay release; no independent successor
  acceptance is claimed yet. Root has not integrated these ten paths.

- [x] (2026-09-10 00:49 UTC, before successor edits) Root read the complete
  independent FAIL verdict and verified its SHA256. Candidate02 source543
  2e853d89/patch85091799 retains499 passing focused tests and six static passes,
  but actual pinned LangGraph synthetic transport reproduces encoded selected-key
  exposure: independent3 passes/1 failure,1.28s,13 warnings,all three clients
  closed,zero Gateway effects. Seal23e929de/VERDICT2a8db095 in private U7pewx.
  Candidate01's488/11 and static failures remain retained. The private-TMPDIR
  successor resolved its six fixture-group refusals without a production exception.
  Broad conformance was never released. Root now authorizes only successor03's
  ten-file scope and the frozen repair above; no main source changes or paid calls.

- [ ] (2026-09-10 00:30 UTC) First frozen candidate01/source1a118ddc retains
  488 passes/11 failures,34.29s wrapper,one Google deprecation warning. Six existing
  integration cases rejected publication metadata before runtime under omitted
  TMPDIR (/private/tmp fixture group differed from process group); this remains
  a diagnosis pending exact private-TMPDIR rerun,not a production exception.
  Five new assertions failed: reused Agents call identity, LangGraph wire-length
  normalization expectation (two cases), and Anthropic transformation expectation.
  Actual pinned Anthropic strict transformer moves pattern/min/maxLength into
  description: descriptive-only hint there,not machine-enforced pattern. Root
  explicitly retains that limitation and existing SDK transformation; no adapter
  source or hand-authored prompt change. Preserve initial static type/Ruff failures
  too; correct test API shapes/typing/Unicode escape notation without weakening
  the promised OpenAI wire, Broker or no-effect boundaries. Source/receipt snapshots
  remain intact; use a distinct successor freeze and private owned TMPDIR.

- [x] (2026-09-10 00:14 UTC, before implementation) Root created this living
  contract after code and official-document inspection plus bounded independent
  feasibility feedback. Current main30b8 is unchanged; no source Writer released
  yet. The LangGraph earlier-refusal distinction and conservative Unicode escape
  are explicit. The final feasible shape still requires all offline acceptance.
- [x] (2026-09-10 00:17 UTC) Root released sole read_scope_writer in the new
  private jp2D5f/repository clone from2eb44d8/30b8. The nine-file ownership above
  is disjoint from Session. Root's cleared-environment exact-lock offline sync
  exited0:99 resolved/96 installed, using existingPython3.14.6; isolated import
  points to clone/src and lock4469273f/pyprojectf051004e remain unchanged, clone
  Git status clean before release. Only this clone .venv was targeted. This is
  runtime preparation, not feature acceptance; no extra install/model/Docker
  request is authorized. Writer initially uses at most one pytest parent while
  Session uses two; total concurrent pytest parents capped at three.
- [x] Implementation, tests and immutable candidate handoff.
- [x] Fresh independent narrow offline acceptance.
- [ ] Exact root integration, preserving the eleven Session files.
- [ ] Combined main verification and result documentation.

## Discoveries

- The fresh raw-scope check on catalog access was insufficient when an adapter
  cached a transformed schema before selected-key registration. Actual transport
  reproduced the leak, even though raw request context was clean and all499
  scoped Worker cases passed. Regenerate from provenance after registration.

- ASCII scope does not imply ASCII input: Unicode casefold can map non-ASCII input
  to an ASCII scope. A broad Unicode escape avoids narrowing that legal class.
- Existing pinned Harnesses validate at different layers; pre-catalog refusal and
  Broker-audited denial must not be reported as identical evidence.
- Regex transformation can conceal a raw registered secret from later literal
  scanners; guard raw captured scope with the shared Redactor before exposure.

## Decision Log

- Reject candidate02 and add only LangGraph's preparation seam to successor03,
  2026-09-10. Keep both pre-credential rejection and post-registration regeneration;
  moving all validation after secret resolution would break an existing boundary.

- Choose a conservative path-prefix hint rather than extra file discovery or a
  false finite-file enum. This reduces common ASCII scope errors with no new I/O.
- Keep all authority in the existing control plane and record Harness-specific
  refusal behavior. A model schema is not an execution or security proof.

## Outcomes

Candidate03 is independently PASS on896 distinct offline cases and six static
gates; its exact ten-file patch9a231dec was integrated at02:10:20UTC into main
546/61e79cba. Root before/after receipts in readscope-main-integration.zRPObe bind
release3ff7b891, old938589 and new61e79cba, with all536 other files (including
Session11) and9837 runtime hashes unchanged. Independent actual failed-journey
auditb94d9dc8 released the old physical source hold without claiming acceptance.
Candidate02's499
focused passes and six statics remain superseded by its retained privacy FAIL.
The repair qualifies selected-key construction, not arbitrary later registration
or universal provider enforcement. Current main is combined546/61e79cba; its
default matrix passed4093 cases with23 skips/4116 unique identities at02:45:47UTC,
plus all six statics, independently reconciled by CQfxc3/4788e9f7. Physical Session
z7zFWN separately passed its one warm model-free journey (53f97483). Docker29 and
installed3 pass with independent seals5c428a0e and8402821b; these bind pre-result
documents. Final pre-live E9 archives passed1/2.60s and independent0203fb88.
One newly released current nano/PydanticAI E2E then passed1/77.00s with independent
actual-audit a9681755; earlier spent failed releases are unchanged and were not
replayed. The accepted two-line guard is unapplied, actual zero-divisor tests pass,
and the ordinary nonzero branch remains separately untested. Final result wording
postdates those archives. No further feature, paid request or Git work follows;
the broader S1–S3 and other-provider/live-Session goals remain incomplete.
