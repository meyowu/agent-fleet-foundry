# Agent Fleet

Agent Fleet is a **local-first, BYOK Chief-of-Staff CLI that bootstraps, operates, secures, and evolves a project-specific agent organization**. A user gives goals to one Chief of Staff (CoS); the control plane assembles the smallest valid team, constrains its authority and execution boundary, and delivers reviewable changes with evidence.

It is deliberately not a generic multi-agent chat framework or a permanent roster of named bots. Models propose scope, plans, actions, and organizational changes. Deterministic application code validates those proposals, owns permissions and sandbox selection, computes the canonical patch, and decides what the available evidence can prove.

This repository implements **Phase 0 through Phase 6**: deterministic repository profiling, all five bounded adaptive strategies, independent exact permissions and user-owned persistent trust, content-addressed evidence, real Git worktrees, guarded patch application, explicit BYOK PydanticAI, a hardened local Docker execution boundary, durable cumulative budgets, persistent CoS chat and reviewed versioned organization evolution. The deterministic fake runtime remains available for offline development and tests; no live model-provider call is required for the bootstrap canary.

Phase7 adds packaged runner/learning assets, fresh-install/upgrade/scale verification, security tooling and platform CI. The [historical verification table](#release-candidate-verification-2026-09-05) reports that earlier candidate. The CLI's highest fully accepted whole-phase marker remains6: the Phase7 public-release gate still requires passing live-provider evidence and an owner-selected license. The bounded live canary passed on September9 as recorded below; it does not infer a license or complete the broader release gates.

The Session-first release adds a foreground session entry, exact in-session review, opt-in pre-execution planning approval, immutable per-role model bindings, operational custom role templates and an authenticated local read-only dashboard. Follow the [living release plan](.agent/plans/2026-09-07-session-first-release.md) for current verification; the September5 CI results below do not accept these additions.

## P0/P1 continuation — 2026-09-11

The owner resumed only the unfinished evaluation, Provider/Harness and Session
work, with a separate verified GitHub delivery for each completed slice. Dashboard
expansion, connectors, Memory/evolution and hosted sandbox productization remain
deferred. The [continuation ExecPlan](.agent/plans/2026-09-11-p0-p1-completion.md)
records current contracts, checks and delivery status; the September10 results
below remain their own historical candidate, not automatic acceptance of new code.

The first slice adds five illegal-plan regressions through the actual Session,
Workflow and SQLite paths: direct code-change assurance, single-Engineer
independent-verification claims, ineligible Verifier selection, overlapping parallel
write scopes and undeclared specialist roles. Each must persist a failed Run/turn
with no specialist dispatch, command, child Run, lease or grant, then permit a
legal new task in the same Session without altering the old failure. Production
validators and permissions are unchanged. These are offline security/continuation
checks, not five live tasks or full S2/cold-start acceptance.

Slice A local acceptance: **4098 passed,23 optional skips** across4121 unique
collected/JUnit identities, with zero gaps, duplicates, failures or errors and
all547 source/test inputs unchanged. Three disjoint integration groups passed
249/264/251 cases; the remaining default group passed3333 with23 skips; the final
cancellation/recovery case passed alone after those groups. Ruff format/lint,
mypy, schema freshness, offline lock and whitespace checks passed. Fresh
independent verification additionally passed22 focused cases and five full
SQLite/event/source-preservation replays. The post-documentation distribution
check passed1/8.69s. GitHub delivery is pending; no new remote CI or live-model
success is claimed.

Remaining P0/P1 work is explicit: original-DB evaluation write containment and
the24-task campaign are not accepted; Provider/Harness selections have passed
independent offline review but await full integration/qualification; the six
Python/Node baseline cohort and public retained-output visibility are in progress.
No new paid model requests were made for these results.

## S1–S3 development status — 2026-09-10 UTC

**Merged to main:** [PR7](https://github.com/meyowu/agent-fleet-codex-kit/pull/7)
merged at2026-09-10 04:03:03UTC as `cea291098780f39e9d985cea0b77a5687f7fda3f`.
GitHub's merge tree exactly equals the accepted PR head `ccf1f28`; local main
fast-forwarded to that merge. Session `ecb668b`, read-scope `e522c93` and evidence
documentation `ccf1f28` are included. This delivers the verified foundation, not
all S1–S3 OKRs. All new commits use `[skip ci]`; exact head/merge Actions readback
returned zero runs, so no fresh remote CI success is claimed. The stop remains in
force for feature work and paid calls. Final documentation/package and remote
readbacks are recorded in the [delivery ExecPlan](.agent/plans/2026-09-10-verified-foundations-merge.md).

Current tested working source is `61e79cba` (546 source/dependency inputs),
including the eleven-file Session-baseline slice and ten-file read-scope slice.
The combined local gates have passed and their original evidence was independently
reconciled; this is **not completion of all S1–S3 OKRs**.

| Current gate | Exact result | Verification boundary |
| --- | --- | --- |
| Full default matrix | 4093 passed, 23 skipped; 4116 unique collected identities, zero gaps/duplicates/failures/errors; finished02:45:47UTC | All unit, contract, integration and offline E2E tests; cancellation regression executed alone after other groups.39 warnings retained. |
| Static checks | Six passed: Ruff format462 files, lint, mypy390 files,115 schemas, offline99-package lock and diff check | Existing pinned environment; no dependency update. |
| Optional Docker | 29 passed/212.23s; independent readback passed | Ten overlap default helpers;19 are actual optional Docker cases.681 Artifacts,199 terminal leases,66 paths and52 known native IDs checked. |
| Fresh installation | 3 passed/253.29s; independent readback passed | Three installations, six original archives,95 prepared wheels,332 package/guide files,115 schemas,13 migrations;54 released leases and18 absent paths. |
| Model-free physical Session | One complete six-phase journey independently passed | Three actual business tests, two read-only filesystem probes, actual `/baseline show` and exact container/worktree cleanup; warm Python baseline observation only. |
| Final pre-live archives | 1 passed/2.60s; independent archive readback passed | Current source and all 60 final input documents held; wheel/sdist contents, import origins and 9837 runtime files checked. These archives precede this post-live result wording. |
| Real-model CLI E2E | 1 passed/77.00s; independent original-evidence audit passed | One `openai:gpt-5-nano` / PydanticAI / Docker CoS → Engineer → Verifier canary; no automatic repeat or target patch application. |
| GitHub delivery refresh | Six static checks passed; pre-merge distribution1 passed/2.53s | Ruff format463 files, lint, mypy390 files,115 schemas, offline99-package lock and whitespace; wheel/sdist plus installed-wheel smoke using existing dependencies, not another fresh dependency install. |

Each gate binds its own frozen inputs. The default, Docker and installation
gates held the source and29 pre-result public documents unchanged.
The installation result binds the pre-result README/guide; refreshed pre-live
documentation and archive verification subsequently passed. After the live audit
released the document hold, result wording changed. The later owner-authorized
GitHub delivery refreshed static and offline package checks; final post-merge
documentation/package results are recorded in the delivery plan. No source or
dependency changed, and no new provider or Docker execution was performed for delivery.
Exact commands, original timings, hashes and failure history are in the
[S1–S3 ExecPlan](.agent/plans/2026-09-09-s1-s3-system-development.md) and
[Session-baseline plan](.agent/plans/2026-09-09-session-business-baseline.md).

A read-tool schema successor is independently accepted and now integrated:
896 distinct offline cases and six static gates pass, including the
unchanged synthetic LangGraph credential-encoding counterexample. Its predecessor's
499 passes and privacy failure remain retained. The repair qualifies selected-key
construction, not arbitrary later key registration or universal provider pattern
enforcement. No actual credential or provider call was used in these checks.
Earlier private physical-Session scripts remain explicitly failed: the first was
rejected before setup for fixture/transport defects; the next actual journey
passed its commands and cleanup but stopped before show because its oracle
incorrectly required a null recovery digest after ownership. The current snapshot
digest was correct. An oracle-only successor now passes the full journey above;
no product validator was relaxed and neither old attempt was replayed.

Latest full-suite checkpoint:
`61e79cba174cd05a8ba019c53ec815b6c39800fea394041e89e066e4132d4a10`.
The latest bounded paid model attempt passed at03:37:39UTC and its independent
audit passed at03:43:42UTC, as detailed below. S1 original-database terminal writes remain disabled/NOT_GO;
external campaign, other-provider live, coldstart and broader Session/Harness
acceptance remain incomplete. Local passes did not authorize an automatic paid
retry or merge. The subsequent explicit owner request authorized only GitHub
delivery; its actual merged status is recorded above. Feature work remains stopped.

The preceding fully tested checkpoint is `30b8f476` (543 source/dependency inputs).
Its full default matrix passed22:32:07UTC:3966 passed,23 optional skips and3989
exact unique identities, with no failures/errors/gaps/duplicates or code drift.
All six static gates passed21:57:47UTC and the post-result refresh at23:50:47UTC.
It adds the standalone, model-free `fleet baseline` commands described below.
Independent baseline acceptance passed542 fresh cases plus six earlier exact-byte
controls (548 unique total); this is not physical Docker, whole-candidate or
Session acceptance. The main transplant preserved all498 previous inputs outside
the45 accepted baseline files. Database migrations now reach13 and public schemas
total115. That historical checkpoint's Docker29, fresh-install3 and pre-key
archive1 gates and independent readbacks passed. That checkpoint's live regression
failed; those older archives do not qualify current result documentation.

The preceding Verifier guidance candidate `9cd328d8` explains that task scopes
constrain reads and directs patch inspection to the existing diff tool. Six
focused cases passed in19.51s and the overlapping387-case runtime/permission
cohort passed in81.77s. All six whole-checkout static gates passed at21:24:44UTC
(format434 files,mypy365,108 schemas,offline99-package lock). Independent review
passed406 unique cases at21:31:51UTC:387 fresh regressions plus19 additional
controls,98 artifact bindings,30 released leases and ten absent worktree paths.
A fresh combined full-suite gate is now recorded above; final packaging remains
separate. Within that guidance slice only prompt text and
two tool descriptions change; permissions, executable tool logic, schemas and
budgets remain unchanged. The current30b8 paid regression tested this guidance
and still failed on an out-of-scope read; prompt guidance is not reliable scope
selection by itself. Guidance commit `fd958db` and baseline commit `8fdf7eb`
were pushed with documentation commit `2eb44d8` to draft PR7. Readback confirmed
its exact head, no branch Actions runs and unchanged main `3fb0971`; it was not
merged at that checkpoint. The then-uncommitted Session/read-scope slices have
since been committed, pushed and merged as recorded above.
The diagnostic and configuration-warning corrections are commits `8afffe7`
and `864ad43`. Those and strict-output commit `a4952dd` are pushed to the development
branch and were still in an open draft PR7 at that checkpoint. The target-bound CoS hash correction
is commit `584c551`, with a fresh passing whole offline suite and independent
component/pre-key package acceptance; its latest live regression failed. Exact
result-document packaging and GitHub readback are recorded in the living plan.

**Latest live E2E passed (2026-09-10 03:37:39 UTC).** On current `61e79cba`,
one bounded `openai:gpt-5-nano` / PydanticAI / Docker CLI attempt completed CoS,
Engineer and independent Verifier. Both live roles ran `python -m pytest` with
exit0 against the same minimal two-line guard patch in `src/canary_calc/core.py`.
The strict VerifierVerdict and structured criterion were accepted; CompletionGate
is true, status is `ready_for_review`, and proof gaps are empty. The original
target remains unchanged and the patch is not applied. This is the real CLI
workflow, not a live interactive-Session or multi-provider campaign qualification.

Eight requests reported32870 input+9093 output=41963 tokens: CoS2/15287,
Engineer4/17236,Verifier2/9440; four tools,66.682625 active seconds and zero
unknown/outstanding/reserved requests or tokens. Monetary cost was not reported.
Original pytest passed1/77.00s; launcher78.662s, normal stop and cleanup complete.
Independent audit `a9681755` passed at03:43:42UTC:46 physical Artifact bindings,
118 live+91 separate Fake-bootstrap events,12 released leases,four absent
worktree paths/four native containers and the empty exact installation scope.
Source546,all60 input documents and9837 dependency files did not drift.
Only the zero-divisor behavior was tested; the ordinary nonzero branch was not
separately tested, despite the model's broader narrative. Docker's documented
isolation limits remain. Earlier failures below are retained, not relabeled.
No additional paid attempt,model upgrade or permission relaxation followed.
The one-test stop was honored; subsequent commit/push/merge occurred only after
the owner's separate delivery request.

**Previous live regression did not pass (23:35:50 UTC).** On predecessor `30b8f476`,
one bounded `openai:gpt-5-nano` / PydanticAI / Docker CLI attempt completed CoS
and Engineer. Engineer and independent Verifier each executed `python-test`
successfully against the same candidate patch. Verifier then requested
`repo.read_file` on `README.md`, outside the sole allowed path
`src/canary_calc/core.py`. The Broker returned `PHASE1_DEFAULT_DENY`, with zero
dispatch claims for that read. README is not globally secret or prohibited;
this rejection belongs to this immutable task scope. No final VerifierVerdict
was accepted and CompletionGate remains false. This is neither an API-key/
connection failure nor a strict-output-validation failure.

Six requests reported21293 input+10857 output=32150 tokens: CoS1/8463,
Engineer3/12492,Verifier2/11195; four charged tools,75.752308 active seconds and
zero unknown/outstanding/reserved requests. Monetary cost was not reported.
Pytest failed/86.72s; launcher88.552s, normal stop and cleanup complete.
Independent original-evidence audit94126dc4 at23:42:32UTC verifies42 artifact
bindings,104 live+91 separate Fake-bootstrap events,12 released leases,four
absent worktree paths/four native containers and an empty exact installation
scope. The original target remains broken and unapplied; source543,documents59
and9837 dependency files did not drift. The patch adds the requested guard but
also changes docstrings and removes type annotations; it is not claimed minimal.
The actual pytest case tests the zero-divisor guard, not separately the ordinary
nonzero branch. The failed pre-cleanup evidence bundle is preserved unchanged.
No automatic retry,model upgrade,permission relaxation or target application.
Full result and archive receipts are in the living S1–S3 plan.

**Previous live regression did not pass (20:44:18 UTC).** On predecessor `3fe0cafe`,
one bounded `openai:gpt-5-nano` / PydanticAI / Docker CLI attempt completed CoS
and Engineer and reached Verifier. Both roles executed `python-test`; afterward
Verifier requested `repo.read_file` on `.fleet`, outside the immutable task's
allowed path. The Broker correctly returned protected `PHASE1_DEFAULT_DENY`;
that intent had zero dispatch claims. The run failed with `COMMAND_DENIED`, with
no accepted VerifierVerdict or verified completion. This is not an API-key or
connection failure. Eight requests reported38976 input+11584 output=50560 tokens,
five charged tools and zero unknown/outstanding/reserved requests. Monetary cost
was not reported. Pytest failed/102.36s, launcher104.009s, outer105.663s. Source
bytes remained unchanged; no automatic retry, budget increase, permission
relaxation or patch application occurred. Independent readback sealed21:00:24UTC:
42 physical Artifact bindings,113 live and91 bootstrap events,12 released leases,
four absent worktree paths/four exact containers and an empty installation scope.
The target remains unchanged and unapplied. The failed bundle predates cleanup;
it is not rewritten as passing. Passing commands alone are not accepted task
delivery, and this attempt does not qualify S1–S3.

**Previous CoS regression did not pass (19:29:48 UTC).** On predecessor `092b8228`,
one real `openai:gpt-5-nano` / PydanticAI / Docker CLI attempt stopped in CoS
SCOPING with `RUNTIME_BUDGET_EXCEEDED` / `usage_limit`. It produced no accepted
TaskSpec,patch,Engineer or Verifier result,so it did not exercise the strict
Verifier correction. Four responses reported33403 input+6174 output=39577 tokens,
exceeding the32768-token invocation profile while the65536-token root remained
unexhausted. Token reservations are not pre-spend invoice caps. Three model tool
batches were charged; authorized provider-log inspection shows repeated pure
`fleet_content_sha256` calls on invented source text,not source writes or command
execution. The last response requested the same helper again; budget rejection
prevented that fourth helper dispatch. Monetary cost was not reported.
Pytest failed/62.86s,launcher64.649s,outer66.390s. Independent physical readback
confirms complete cleanup: six bootstrap leases released,two worktree paths and
two exact native containers absent,and the installation scope empty. All28 checked
Artifacts,the two Docker command receipts and the accepted CompletionGate belong
to Fake bootstrap or project context—not this failed live run. The live run has
zero Gateway intents/dispatches,resource leases or command receipts; target
HEAD/status/source remains unchanged. No automatic paid retry,model
upgrade,budget increase or target patch application occurred. This failure remains
separate from both offline strict-wire acceptance and the historical passing canary.
Strict-output code/tests/security guidance are pushed commit `a4952dd`; no GitHub
Actions run was created. A target-bound proposal-hash correction now passes local
checks under its [ExecPlan](.agent/plans/2026-09-09-organization-hash-targets.md),
but the later current canary also failed as recorded above. It requires `operation`, an allowed `.fleet/`
path and content; ordinary business-source paths are rejected. This is not a
guarantee of correct model intent or elimination of all repeated calls.

**Previous live regression also failed (17:41:48 UTC).** On predecessor `21700932`,
one real `openai:gpt-5-nano` / PydanticAI / Docker CLI attempt reached Verifier but
failed strict structured-output validation after its independent command execution.
No VerifierVerdict was accepted. The safe diagnostic is
`structured_output_after_side_effect` / `schema_validation`. The local record does
not retain raw model output. Subsequent authorized read-only inspection of the
[exact provider response](https://platform.openai.com/logs/resp_0fe1fc2b3e5c6371006aa19a4c84e887d091c42d0023f0dd53)
showed a criterion object placed in `criterion_results` (which accepts narrative
strings), with `structured_criterion_results` omitted. The verdict was lowercase
`pass` and rationale was present; those fields were not the observed fault. This
private dashboard link requires the project's access and is not public evidence.
Ten requests reported
37173 input +12514 output =49687 tokens, seven tools and zero unknown/outstanding
reservations. Monetary cost was not reported. Pytest failed in107.98s; the launcher
finished in109.681s and reported cleanup complete. No automatic retry or target
patch application occurred. The earlier passing canary below remains historical
evidence, not a passing result for this prior attempt.

| Gate | Exact result and boundary |
| --- | --- |
| Default unit/contract/integration/offline E2E collection | **3966 passed,23 optional skips**,3989 exact unique identities,all freshly executed on30b8f476. Five disjoint groups completed at22:32:07UTC with zero failures/errors/missing/duplicate/extra cases or code/dependency drift. Integration groups:247/1752.17s,245/1142.93s,245/947.15s; other3228 passed+23 skipped/1148.29s; unchanged cancellation oracle1/9.20s alone after the heavy groups. Independent terminal identity/static readback passed22:36:17UTC (sealda654c0c). All39 compatibility/deprecation warnings are retained. Historical3fe was3811 passed/23 skips, not the current total. |
| Final result-document archives for3fe | **1 passed/2.51s**, launcher4.668s, finished21:03:49UTC; independent readback passed21:07:25UTC. Both archives and installed resources match316 immutable584 runtime/guide files plus held README04844 overlay. The earlier pre-key archive check passed1/2.54s. Neither covers later guidance/doc changes or claims a fresh dependency installation. |
| Target-bound CoS hash independent checks | **524 unique passes**:324 focused/40.57s,168 legacy/.69s,26 independent/.31s and6 additional installed SDK/LangGraph controls. Exact path/type/budget/replay/secret boundaries,ordinary scoping and real persisted organization proposals were checked.103 databases,78 Artifact bindings,zero leases and18 original-only Git registries were read back. Retain94 inert running Run records and10 direct-adapter running attempts with settled requests/closed clients; these are not completed product Runs. Component coverage overlaps the default suite and is not live proof. |
| Prior strict Verifier independent checks | **507 unique passes**:294 related/20.09s,197 provider/86.69s and16 independent controls/2.35s. Both real SDK MockTransport wire formats,unsupported-profile zero dispatch,physical client cleanup,no effect replay and unchanged local validation were checked on092.89 databases and251 Artifact hashes were read back;49 leases released and19 paths absent. Three intentional paused-approval fixtures retain three private worktrees and three nonexecuting Fake leases. Strict Verifier bytes remain unchanged; this prior component coverage is not new live-provider proof. |
| Diagnostic and warning independent checks | **280 unique diagnostic checks** (253/16.66s plus27 malicious controls/1.21s), and36 warning cases/0.05s. These component counts overlap full default coverage. |
| Format/lint/types/schema/lock | Latest30b8 refresh: Ruff format458 files and lint passed; mypy387 files passed;115 exact schemas;99-package offline lock check and whitespace check passed. All six commands exited0 at23:50:47UTC with no code drift. The earlier21:57:47UTC receipt recorded457 formatting files. Neither is a new938589 combined-source gate. |
| Post-live-result30b8 archives | **1 passed/4.30s**,7.619s wrapper,finished23:50:52UTC. Independent read-only sealb5b10f70 at23:55:44UTC checks wheel/sdist336 members each,332 runtime/guide resources,115 schemas,13 migrations and exact README0967/guide92a bytes. Original source543 and9837 previously inventoried runtime bytes remained unchanged. This used the held main environment, not a fresh installation or the earlier snapshot-origin run; it predates current Session/doc changes. |
| Historical named adversarial replay | **737 passed/218.40s** on the earlier checkpoint, no skips; not a new execution of the diagnostic/warning successor. |
| Current real Docker selection | **29 passed/239.06s**,241.36s wrapper,finished22:37:04UTC on30b8f476:19 actual Docker cases and10 helper cases. Independent physical readback passed22:55:26UTC (seal60497364):45 DBs,681 artifacts,199 terminal leases (190 released/9 recovered),66 absent worktree paths,52 absent known native IDs and19 empty exact installation scopes. Two historical no-handle records remain explicit; current absence does not prove they never executed. Code and pinned daemon/image/endpoint unchanged. This selection does not test the new model-free baseline command. |
| Current fresh installation journeys | **3 passed/276.18s**,278.518s wrapper,finished22:49:38UTC on30b8f476, using only the95 prepared locked wheels and pinned local Docker. Source and READMEed1323b7/USER_GUIDE92a10891 held throughout. Independent readback98088803 passed23:02:32UTC:three environments/six archives each matched332 runtime/guide resources,115 schemas and13 migrations;54 released leases,18 absent paths,six absent native IDs. This is separate from later result-document archive refreshes. |
| Current pre-key archive checkpoint | **1 passed/2.85s**,6.314s wrapper,finished22:57:22UTC. Independent84a0d527 passed23:06:01UTC:exact source543/README70af/guide92a snapshot,332 packaged runtime/guide resources,115 schemas,13 migrations,159 snapshot-only module origins and9837 unchanged dependency files. This predates the latest live-result documentation; subsequent archive receipts are recorded in the living plan and do not imply another live success. |
| Historical real Docker selection | **29 passed/462.21s**:19 actual Docker cases and10 helper cases.199 terminal leases,66 absent paths and19 empty installation scopes independently checked. |
| Historical fresh installation journeys | **3 passed/484.59s**, using95 prepared locked wheels. Three environments/six archives matched316 runtime/guide files;54 leases released and18 paths absent. The optional entry's later strict-origin correction separately passed three full-entry positives,three symlink negatives andthree distinguishing old-entry controls. |

The historical Docker and installation executions belong to predecessor `afb64027`; they were
accepted at `21700932`, which changed only five test files and preserved every
production/dependency byte. The current hash-target successor has fresh offline
tests and the failed real-provider attempt above. The subsequent30b8 combined
baseline has fresh full offline acceptance and a passing ordinary29-case Docker
gate and its independent resource audit, plus three passing fresh installation
journeys. Installation and pre-key archive independent audits now pass; the
latest paid attempt has an independently verified FAIL. Final result-document
archive execution and GitHub delivery are separately recorded in the living plan.
The failed CoS-only live attempt belongs
to092. The earlier
eight fixture failures and the later warning-wrap failure remain retained, with
independent successful replacement replays rather than rewritten results. Prior
c0c36e24 acceptance was3702 passed/23 skips via34 fresh CLI cases plus3691
byte-identical carried identities; the092 matrix was3743 passed/23 skips and the
3fe0cafe matrix was3811 passed/23 skips; current30b8 is3966 passed/23 skips,
each fully fresh. The SDK receiver
fixture failure and two independent-auditor expectation failures are retained,
with corrected complete replays and no candidate validator relaxation.
All23 default skips remain explicit (19 Docker,3 installation,1 live); optional
successes do not turn the skipped live test into a new provider run. Known Google
Python3.14 deprecation and test-property/JUnit warnings remain recorded. Final
documentation/archive readback and GitHub delivery are separate entries in the
[living plan](.agent/plans/2026-09-09-s1-s3-system-development.md).

Production PydanticAI requests strict OpenAI output-tool arguments for the exact
Verifier contract on Responses and Chat Completions. Unsupported strict profiles
fail before a request; other providers,roles and offline overrides remain unchanged.
Strict generation does not replace local validators or CompletionGate,and nullable
structured mapping retains its existing compatibility semantics. The separately
model-free business baseline is now integrated into the working source; its
combined full-suite,optional and pre-key package gates pass. The separate first
physical generated Python baseline is also independently accepted below.

### Model-free business baseline (standalone CLI)

For an already registered, clean, committed Git project with an existing local
Docker runner and reviewed verification command, `fleet baseline plan . --command
COMMAND_ID --json` records a five-minute review without executing that command.
Inspect its source/configuration/trust/command/image bindings, then use
`fleet baseline run REVIEW_ID --allow-once --review-sha256 SHA --json` for one
explicitly approved observation. `show`, `revoke` and exact stopped-owner `recover`
are separate commands. See the [Chinese walkthrough](docs/USER_GUIDE.md#不调用模型的项目基线检查standalone-cli).

The source is mounted read-only; only bounded scratch is writable. No model,
dependency installation, image pull, target patch, Agent verdict or CompletionGate
is involved. Existing deny rules still win, even against persistent allow rules.
Permanent owner/dispatch claims prevent automatic command replay after a crash.
Reports distinguish observed command exits from incomplete output or cleanup;
recovery can clean only the reviewed resources and cannot turn an unknown command
result into a pass. The CLI composition can migrate its separate state database
to13; it is not a globally side-effect-free inspector. The Session entry below
reuses this controller; neither entry is six-project/cold-start qualification.

The first current-source physical Python fixture completed at22:54:07UTC:
one public CLI command exited0/10.904s, with three actual Docker unittest checks
passing (reported.001s), nonroot/read-only mount observation and two EROFS30
write refusals. Missing consent was refused before effects; approved/materialized/
post-command source hashes match. Root observed complete cleanup and unchanged
original target. Independent readbackcd66a97d passed23:06:20UTC:14 canonical
baseline rows,one consumed authorization/owner/dispatch/observation/report,three
released leases and exact native/worktree absence;102 original fixture files and
543 source files unchanged. Root accepted this narrow result at23:10UTC. This is one generated,
registration-only baseline fixture—not public bootstrap, Session, a multi-project
cohort, a model task or an independent business-correctness verdict.

### Model-free baseline inside a Session

In an already selected, registered project with the same prepared runner and
reviewed command prerequisites, stay in one foreground session:

```text
fleet chat .
/baseline plan COMMAND_ID
/confirm <the displayed review code>
/baseline run
/baseline show
```

`/confirm` records only the exact once authorization: it does not execute the
command. `/baseline run` separately consumes it once. Conversation identity,
repository, metadata revision and local selection generation are checked together
at authorization and claim. Baseline operations after ordinary Session selection
perform no additional secret lookup, history read or runtime/model construction;
normal Session startup/history redaction duties remain unchanged.

`/cancel`, EOF and interrupts retain and drain baseline-owned cleanup, without
retargeting an ordinary Run. Overlapping work is refused. Uncertain executions do
not replay. Review codes/focus are process-local and are not restored after restart;
use the standalone `show`/reviewed `recover` lifecycle for retained state. The
result remains a baseline observation, not a Run/Turn, accepted patch or verdict.
Offline acceptance used real Session processes with synthetic Docker transport;
physical Session qualification and combined-source gates are still pending.

The first S1 evaluation slice is implemented: immutable preregistered manifests,
outcome records and deterministic reports preserve first-round denominators,
failures, unknown usage, missing attempts and separate repeat results. A real CoS
failure can retain its Run before any TaskSpec exists. Independent review passed
123 focused tests in0.42s plus16 additional checks on source/test/script freeze
`334c089e01b380b167d0950af8e6d11a564275f0ff33ad3e9f85d5853bc13092`;
all92 existing schemas remained byte-identical and three evaluation schemas were
added. A prior candidate failed the CoS-before-Task case and remains recorded.

The next S1 slice adds an atomic, reopenable evaluation ledger: preregister a
campaign, reserve its finite attempt budget and retain preflight failures without
inventing a Run. Independent review passed143 tests/6.90s and38 additional checks
on its19-file `39b9548c` inventory. It is a non-executing Python service; no campaign
runner or external-oracle authority is granted. Reports remain `structural_only`
and `not_evaluated`, and ledger `execution_authorized` is exactly false.

The later reserved-execution service passed independent offline acceptance on
32-file `851b996` /532-file `bc1021a5`:424 unique regression cases plus8 probes.
It binds one permanently budgeted campaign attempt to the actual Workflow Run;
the earlier non-executing ledger is not its dispatch authority. No public campaign
CLI or external oracle is admitted. Its successor evidence observer **failed**
independent security review: read inspection created WAL/SHM sidecars, and temporary
Artifact/DB path replacements bypassed identity checks. The323 ordinary passes do
not override those three adverse cases. Both terminal-recording entry points now
reject before reading state; the original atomic-write criterion remains unmet.
The separate-process read repair passed independent acceptance on seven-path
`f346092d` plus security registry `524ecd19`, using frozen snapshot `8ec710a1`:
79 unique tests,108 exact schemas and40 checked child/process-stage absences.
Actual database/Artifact replacement, sidecar, cancellation and cleanup-failure
cases were checked. Deliberate cleanup faults require test-owned recovery and
are not reported as product-drained. The reader is still not exposed through
public composition or CLI. It refuses an already or concurrently populated secret
registry instead of copying secret forms into its child, so inspection requires
a fresh credential-free process. Read acceptance is not terminal-write acceptance,
successful campaign finalization or permission to replay an attempt.

`fleet readiness . --json` now provides a read-only static repository report:
detected commands, declared dependencies, repository boundaries, lockfile presence
and explicit unsupported/omitted details. It does not install dependencies, open a
model connection, run tests or declare the environment ready. Independent review
passed76 tests/6.99s on corrected14-file inventory `7ab4f93e`, including actual
Unicode output bounded to1MiB; legacy profiling and existing state stayed unchanged.
Exit0 means static inspection finished, exit1 means incomplete inspection, and
exit2 means admission failed safely—not task success or failure.

Shared Fake/PydanticAI runtime admission now rejects mismatched roles, unsupported
tools and checkpoint requests before dispatch (159 focused tests plus26 independent
checks on `8ad3fdea`). Session management passed independent acceptance on11-file
inventory `efda1d9c`:65 focused tests/51.72s plus144 compatibility tests/391.41s
(209 unique cases). `/models`, reviewed future-only `/models use`, `/roles`,
`/readiness` and bounded `/tasks` history are now available. Historical inspection
does not retarget active cancellation or authorize mutations. Six read-only views
preserved43 state tables; the Unicode readiness view stayed within1MiB. This
acceptance does not cover the subsequent provider/SDK registration changes.
The direct PydanticAI/Anthropic API-key path passed independent offline acceptance
on14-file inventory `ff390b94`:233 tests/8.14s plus5 actual-SDK cleanup fault checks,
with exact dependency hashes and persisted failure diagnostics. A repeated-cancel
cleanup failure and a diagnostic-projection gap were fixed; prior failed evidence
is retained. Its normal workflow uses FakeSandbox and keeps
`SIMULATED_EVIDENCE_ONLY`. Anthropic live is not yet accepted. OpenAI Agents
SDK0.22.1 and shared per-role provider routing passed independent offline acceptance
on immutable521-file snapshot `7ea80a0d`:105 SDK tests/13.67s plus375 shared
tests/9.07s, **480 unique cases**, and7 additional boundary probes. Exact raw usage,
all three permission decisions and retained cancellation cleanup were checked.
Ruff/format31 files, mypy15 modules and106 schema comparisons passed. This snapshot
does not accept concurrent campaign/template drafts, live SDK qualification, Docker,
packaging or the current whole checkout. The2MiB response bound is post-read;
SDK tracing policy is process-global and version-specific. Terminal wire tools use
`strict=false` while original strict local output validation remains mandatory.

Google Developer API (`google:<model>`, PydanticAI) and the then-current shared
provider/Harness paths passed independent offline acceptance on12-file `b16750cf`
/544-file `bf83e3d7`:593 unique cases/34.49s plus9 probes/.58s,108 schemas,
53 physical artifact hashes and34 released leases. All flows remain simulated;
DENY's retained pre-cleanup bundle conservatively lacks a cleanup proof even when
physical cleanup is observed. No Google credential or live request was used.
LangGraph and its shared integration passed independent offline acceptance on
19-file `17303dd0` /555-file `c0d9a5f0`:732 unique cases/84.43s, six direct
config controls,108 schemas,53 artifact hashes,48 released leases and17 absent
worktree paths. An earlier candidate passed718 tests but failed five edited-YAML/
distributed-schema provider checks; that failure is retained and corrected in
both validation paths. Dependency resolution adds15 exact pins without changing
existing versions. This is **not live qualification**, current Session acceptance,
or acceptance of the mutable whole checkout.

The separate mixed-Harness overlay passed independent9-case acceptance in37.26s
on556-file `71fedc`:three cyclic per-role assignments under ALLOW, explicit separate
approvals/reopen and DENY. The original profile revision stayed pinned after future
profiles changed.159 artifacts,42 reported requests/630 synthetic tokens,42 released
leases and15 absent paths were checked. This is actual offline SDK routing through
Fleet, with simulated HTTP/sandbox results—not three independently successful live
mixed-Harness tasks.

Four packaged role/verification bundles now have a read-only `fleet role-bundles`
preview path. Independent acceptance on15-file `a9d2d609` passed55 focused/87.59s,
43 compatibility/91.74s and20 additional/16.55s. All four new-CoS proposal,
explicit review/apply, custom-role execution and rollback journeys were checked:
165 artifacts,38 terminal leases and11 absent workspaces. Preview does not
initialize state or publish configuration. This snapshot excludes later shared
Session wiring and does not prove real-model/Docker completion.

Session `/recover` now offers a one-use, five-minute stopped-owner review for the
current task; `/recover --confirm-owner-stopped <code>` cleans that exact old task
without model replay. `/deny` can select a sole pending request without its ID;
multiple requests remain explicit choices. Independent replay passed275 cases,
but an additional concurrency probe found that cleanup could include a resource
created after review. That candidate **failed acceptance**. Its replacement binds
reviewed ownership and exact resource payloads in one transaction. Its8-file
`3a7fcc33` successor passed independent acceptance on557-file `f65a5eab`:
353 regression cases/755.69s plus23 original/additional/resource probes,376 unique
passes. The original late-resource failure now passes without expanding review
scope.29 new CAS fixtures have64 terminal leases,46 absent worktree paths and
zero active claims; all61 observed child processes are absent. Intentional legacy
paused/failure fixtures retain six private worktrees and are not a global cleanup
claim. Earlier275/344 results remain historical, not new execution. This acceptance
excludes later observer/security/packaging edits and whole S1–S3 completion.
Ten logical journeys and the five-strategy positive/negative gate
are frozen in `tests/fixtures/session-journeys.json`, not counted as ten independent
test executions or three real cold starts.

Remaining S1–S3 acceptance includes the original-DB terminal-write boundary and
external oracle,24 tasks across6 actual Python/Node repositories (including12 sealed
first rounds), approved business baselines and3 cold starts, additional Provider/
Harness six-task live qualifications, and three live mixed combinations. Static
readiness is not an executed business baseline. No Anthropic/Google credentials
were available, and neither their live support nor new Harness live reliability
is inferred from offline SDK tests. No real24-task campaign or live qualification
of an additional Provider/Harness is accepted yet. The historical canary below is
one bounded real task, not new full-suite or full-roadmap proof. See the
[contracts](docs/CONFIG_AND_SCHEMAS.md#evaluation-contracts-s1-foundation-no-execution-authority)
and [living S1–S3 plan](.agent/plans/2026-09-09-s1-s3-system-development.md).

## CoS, transport and evidence corrections — 2026-09-09 UTC (bounded live canary passed)

**Attempt6 passed the real OpenAI nano / Docker / public-CLI canary**, independently accepted at10:37:04UTC against candidate7af below. One test passed/132.52s; launcher133.644s. Real CoS, Engineer and independent Verifier completed; both command stages ran genuine pytest against the same minimal single-file zero-division guard patch. All18 artifact hashes and116 events validated, and independent CompletionGate replay returned `verified_complete=true` with no proof gaps. Seven requests reported23498 input+12867 output=36365 tokens; four tools,zero unknown/outstanding/reserved usage. CoS1 request/9091 tokens,Engineer4/17023,Verifier2/10251. Monetary cost was not reported. Original target source/HEAD and its11 initialized Fleet files stayed unchanged; no target patch application. All12 leases released and the exact installation scope containedzero containers.

This accepts one bounded, unapplied guard-change canary, not broader S1-S3 completion, general provider reliability, package-build readiness or GitHub delivery. CoS still emitted one procedural criterion alongside the behavioral guard criterion: its command receipt alone does not prove verdict content; the retained actual independent verdict establishes that procedural outcome here. Guidance does not guarantee behavior-only criteria. All five earlier paid failures remain retained, including unknown usage where recorded. The secret-safe launcher completed its registered-credential-form scan and export checks; no credential is stored in this repository.

Current fixture-corrected candidate: `7af364db0934f12f46e35304e2feee07d7ebfb5a2e59ce5a54b693bca25d1577`. **Enabled Docker29 passed/220.27s.** Default coverage is **2462 passed,23 optional skips across2485 unique cases**:2452 passes/4 skips are explicitly carried forward from byte-identical53e5 dependency closures, replacing the entire old Docker subset with fresh10 passes/19 skips in39.46s. Independent comparison verified exactly2 changed test files,399 unchanged source/test/script files, unchanged config/conftest/lock, all four helper consumers replayed and no missing/extra/duplicate identities. This is not a claim that unchanged tests re-executed under7af. Formatting340 files, lint, mypy278, schemas, whitespace and offline lock55/31ms passed again. Product/runtime/asset bytes are unchanged from53e5; its audited offline installation3/285.06s remains applicable. Independent physical review passed:199 terminal leases (190 released,9 recovered),zero outstanding or remaining lease paths,zero containers across19 exact installation scopes. The repaired evolution journey proved all four real commands:Engineer and independent Verifier each ran5 baseline and2 integration tests against the same patch. Archive-content check1/1.86s passed; final archive hashes/read-back are recorded in the living plan and private manifest. The subsequent bounded live result is recorded above; these local results alone do not establish it.

Criterion-guidance freeze `53e5cb815f2d8da1b92ed622ccef57b7b8a98119c75aa03f22837f7e8950c4f1` completed **2458 default passes,23 optional skips**, with an independently exact2481-case collection/JUnit union. Disjoint groups:135/862.67s,185/820.82s,230/810.21s,1907 passed plus23 skipped/776.49s, then the unchanged serial cancellation case1/7.73s after all heavy workloads. Formatting340 files, lint, mypy278, schemas, whitespace and offline lock55/21ms passed. Writer-focused205/57.55s and independent205/115.47s overlap that total. Installation3/285.06s passed;54 leases released,zero outstanding or exact-scope containers, with257 package/guide files matching fresh installs and archives.

Historical53e5 enabled Docker gate: **24 passed,1 failed/366.12s**. All three new actual-Docker criterion-mapping cases passed, including unchanged rejection of empty and transcript-mixed proof. The existing organization-evolution journey exposed a shared test-helper assumption of exactly one required command, while its valid TaskSpec requires two. The subsequent7af correction changed only that helper and its evolution consumer, preserving the product and its two-command evidence checks. The failed gate remains retained. The fresh enabled/disabled Docker gates, affected consumers and exact dependency/identity reconciliation subsequently passed at7af as recorded above. Carried-forward results are explicitly labeled, not claimed as re-executed; current resource and archive receipts are recorded separately.

Historical strict-action freeze: `85fe6944e76189da9707539ae25ad769f22579f9115d47e2a0194989bf68a652`. Fresh default regression completed **2447 passed,21 optional skips**, covering2468 collected cases. Disjoint selections: integration133/853.99s,185/820.05s,230/808.52s; other1898 passed plus21 skipped/763.73s; then the unchanged cancellation/recovery case1/8.29s after all heavy test workloads stopped. Independent exact2468-identity collection/JUnit review passed before attempt5. No production timeout, permission or completion validator was weakened.

Formatting339 files, lint, mypy277 including launcher, generated schemas, whitespace and offline lock55/11ms passed. Writer-focused265/36.59s and fresh independent235/18.30s passed and overlap the default total. Separately enabled real Docker21/354.33s and fresh offline installation3/291.75s passed;175 Docker leases are166 released/9 recovered,54 installation leases released,zero outstanding andzero containers in every exact installation scope. All257 runtime/assets/guide files matched3 fresh installs,4 wheels and3 sdists. Refreshed archive1/1.92s and independent exact2468-identity/package/resource review passed before attempt5. Later result-only prose changes require their own archive read-back; earlier archive hashes remain bound to their original prose. These local gates do not prove live E2E success.

An offline actual-SDK reproduction exposed response-cookie storage causing a later request to be rejected by the exact header policy. The stateless-cookie client correction keeps Cookie prohibited and passed its frozen local gates below. This is a plausible cause of attempt3, not a proven observation of its unretained response headers. The live fixture now reuses the shipped standalone-module metadata instead of the shared synthetic fixture's invalid `builtins` package-build backend. Engineer and independent Verifier must still execute genuine pytest commands; this canary does not establish package-build readiness. Attempt4 executed this corrected transport/fixture candidate but still failed at Verifier arguments. The subsequent strict action-tool correction passed fresh local gates above, live acceptance at that checkpoint was still pending and was subsequently achieved by attempt6. Earlier results are historical acceptance of their named freezes only.

Transport/fixture freeze: `e0a3d908330c50c4ef35a3eab84dbdf7b3380c98b8145bb375974431a9a9480f`. Complete default regression: **2400 passed,21 optional skips** across2421 collected cases. Disjoint selections: integration133/861.30s,184/824.25s,206/814.58s; unit/contract/offline E2E/default optional directories1876 passed plus21 skipped/767.88s; the unchanged timing-sensitive cancellation case ran separately after other workloads and passed1/8.22s. Independent identity review passed with2421 exact identities andzero omissions/duplicates. Formatting336 files, lint, mypy274 including launcher, generated schemas, whitespace and offline lock55 passed. Targeted independent transport/diagnostic checks105/3.95s and fixture preflight2/28.74s overlap these totals.

Separately enabled Docker:21 passed/315.21s, with175 terminal leases (166 released,9 recovered),zero outstanding across37 databases andzero containers across17 exact installation scopes. Fresh offline wheel/sdist and installed-Docker journeys:3 passed/288.98s;54 released leases,zero outstanding andzero exact-installation containers. These opt-in results overlap the default skips; no provider request or dependency/image download occurred. Final archive read-back after documentation updates is recorded in the living plan.

Preflight limitation: the standalone success journey verifies in real Docker. In the fake repair-history scenario, actual command results are failure/failure/pass/pass, but existing unstructured evidence assembly retains the earlier failed/old-verifier receipts and does not grant verified completion. Initial preflight1 passed/1 failed in28.69s exposed an overstrong new test expectation; the corrected negative test asserts that conservative nonacceptance without weakening production completion rules. The original report remains. A later passing command is not being reported as accepted repair-history delivery.

The [living canary plan](.agent/plans/2026-09-08-low-budget-live-e2e.md) now includes the user-authorized corrective slice. CoS receives reviewed workflow choices, and its packaged prompt/JSON Schema descriptions distinguish workflow, team strategy and parallel writer assignments. Existing validators remain unchanged. Runtime errors add fixed, secret-safe diagnostic categories to JSON details and durable `agent.failed` events; no raw exception text, provider bodies/headers, validation records or credentials are retained. Model choice, budgets, SDK retries and the post-side-effect retry prohibition are unchanged.

Corrective source/tests/scripts freeze: `25aa6ec20b2577ce5a87412c774002afa64507f5cadbac02e3252edd61036515`. The complete2392-case default matrix now has **2373 passed,19 deliberately skipped**: integration133/842.73s,183/495.31s,206/791.07s; other1851 passed plus19 skipped/741.37s. Focused checks:122 passed/6.70s. Static checks passed: Ruff332 files, lint, mypy270 files and generated schemas. Independent targeted safety review:39 passed/5.85s plus eleven cause-free mapping probes. Fresh Docker:19 passed/267.80s, with zero outstanding leases in35 state databases and zero containers across15 exact installation scopes. Optional Docker results overlap the default selection and are not additional unique cases.

The first parallel default replay had2372 passes,1 failure and19 skips. The sole failure hit a15-second test-fixture wait before cancellation assertions; the same case passed alone/16.05s, then its entire183-case partition passed with other workloads stopped. No timeout or safety check was weakened; all original evidence remains. Fresh wheel/sdist/installed-Docker validation passed3 cases/147.34s; archive-content check1/2.15s. Independent installation audit matched all255 runtime files and the guide, with54 released leases/zero outstanding andzero exact-installation containers.

Historical real attempt5 **failed the final evidence-mapping gate**, not the model/tool loop. CoS, Engineer and independent Verifier all completed; both roles ran real isolated Docker `python-test` with exit0 against the same single-file patch. Verifier reported pass, but one criterion had no evidence references and two cited command-transcript IDs alongside CommandEvidence IDs. The strict current-verifier mapping rules rejected all three: `STRUCTURED_CRITERION_MAPPING_INVALID`, `CRITERION_NOT_PASSING`, `PROOF_GAPS_PRESENT`. Status is `ready_for_review` with `verified_complete=false`, not accepted delivery. Result:1 failed/163.89s, launcher165.036s;9 requests/responses,42781 input +15760 output =58541 reported tokens,zero unknown/outstanding,5 tools. Fresh independent audit verified all18 artifact hashes, the exact failed gate replay, unchanged original target,12 released leases andzero remaining paths/containers. The subsequent guidance and fixture corrections passed the bounded attempt6 above; this fifth attempt remains a failure and no gate was weakened.

Historical real attempt4 **failed during Verifier tool-argument validation**, after CoS and Engineer completed. Engineer produced the exact single-file guard patch and ran real Docker `python-test` with exit0. Verifier inspected the diff, then requested `run_verification` without its required `command_id`; trusted validation refused it before any Verifier command. This exact shape was observed in the user-authorized Dashboard and is not an invalid final verdict claim. Result:1 failed/90.87s, launcher92.014s;8 responses,31993 input +8428 output =40421 reported tokens,zero unknown requests,4 tools. All11 leases released;zero exact-installation containers; target baseline unchanged. Its subsequent strict-tool correction ran in attempt5 above; this historical attempt remains a failure.

The subsequent correction explicitly requests strict arguments for shipped external action tools, while original local validators and PermissionBroker remain authoritative. `run_verification` requires an exact `command_id` plus `reason`; unavailable real commands are not invented, and malformed batches receive fixed `tool_arguments` diagnostics before tool reservation or effects. Strict-incompatible schemas fail closed without fallback. The fresh local results above accept this frozen correction; attempt5 completed real independent verification but did not pass the final evidence gate.

Corrected real attempt3 **failed** after CoS successfully produced an accepted `code-change`/`engineer_verifier` plan and Engineer executed `repo.list_files`. The next model-request boundary returned `PROVIDER_FAILED` with `provider_sdk`/`unknown`; the exact cause is under offline investigation, not attributed to billing or model availability. Result:1 failed/46.75s, launcher47.861s;3 request reservations,6325 input +4623 output =10948 reported tokens, plus1 unknown request/30248 conservative token debit. That debit is not measured usage or proof of dispatch. Cleanup completed withzero outstanding leases. No live Verifier, accepted patch or live verification command evidence exists. This was the third real attempt; no automatic whole-run retry occurred. Earlier attempts remain recorded below. Final archive/install receipts must be refreshed after these README changes.

## Initial low-budget canary attempts — 2026-09-09 UTC (live acceptance failed)

The [living canary plan](.agent/plans/2026-09-08-low-budget-live-e2e.md) tracks this slice. Thin one-shot CLI budget flags, real profile binding, safe retained evidence and a one-attempt `openai:gpt-5-nano` launcher are implemented. No model upgrade or whole-run retry is automatic. Both manually launched live attempts **failed during CoS**, before live Engineer/Verifier dispatch. The first returned invalid structured output; the second permitted one existing pre-effect correction under unchanged model/budgets, but the subsequent request failed at the provider boundary. Neither initial attempt establishes live E2E or general nano reliability.

User-authorized read-only inspection of OpenAI Dashboard logs established that both responses actually called `submit_scope_decision`. Both selected `fleet_strategy="engineer_verifier"` with nonempty `writer_assignments`. Offline reproduction against the real `ScopeDecision` validator rejects both with `only the parallel strategy accepts writer assignments`. For this strategy, the control plane creates the Engineer and independent Verifier; assignments must be empty. Attempt 2 additionally proposed undeclared `workflow="engineer_verifier"` instead of `code-change`, a separate check it would fail after fixing the assignments. The later `PROVIDER_FAILED` cause remains unknown. These are observed output-contract failures, not evidence of a missing API key or a proven end-to-end fix. Paid attempts were stopped for diagnosis; the subsequently authorized corrective implementation later passed only the bounded attempt6 described above.

Attempt-2 source/test/scripts identity is `3846df53077a2db00df688542e9ad542aabbd9956da01265042f11603e74ac52`. Its exhaustive disjoint local partitions cover all **2358 collected cases: 2339 passed, 19 deliberately skipped**, with no failures. Independent review matched every JUnit case identity to fresh collection. Skips are 15 Docker cases, 3 fresh-install cases and 1 live-provider case; enabled optional results below overlap that selection. The earlier zero-correction candidate (`fadda04b73f16a828bc61f3d122c4012416a0be011b90bc4a3117953018514db`) separately passed 2338 tests with the same 19 skips; both are historical, not an additional total or acceptance of the corrective candidate.

| Attempt-2 historical local gate | Exact result |
| --- | --- |
| Unit/contract/offline E2E and default optional directories | 1820 passed, 19 skipped in 781.07s: 1164 unit, 623 contract, 28 offline E2E and 5 offline helper checks passed. |
| Complete integration, three disjoint groups | 133 passed in 879.02s; 182 passed in 847.67s; 204 passed in 826.13s — 519 total. |
| Separately enabled Docker | 19 passed in 171.44s (15 Docker and 4 helper cases), carried forward from the first freeze: calibration changed only three live test/helper files, not runtime or Docker code/tests. Independent audit: 15 exact installation scopes with zero containers; 35 state databases with zero outstanding leases. |
| Focused launcher regressions (overlap) | 22 passed in 0.45s. |
| Formatting / lint / types / schemas / lock | Ruff 327 files; lint passed; mypy 265 files; generated-schema check passed; offline lock validation resolved 55 packages. |
| Real nano attempt 1, zero corrections | FAIL: 1 failed in 70.92s (launcher 71.991s). CoS `RUNTIME_OUTPUT_INVALID`; 1 request, 3907 input + 6929 output = 10836 reported tokens, 0 tools. Cleanup complete, no outstanding leases. |
| Real nano attempt 2, one permitted pre-effect correction | FAIL: 1 failed in 82.61s (launcher 84.217s). CoS `PROVIDER_FAILED`; 2 requests reserved, 3904 input + 7999 output = 11903 reported tokens, plus 1 request with unknown usage; 0 tools. Cleanup complete, no outstanding leases. |

Calibration changed only three test/helper files to permit one correction and assert the exact frozen profile. Focused calibration checks passed **23 tests, with 1 live case skipped in 10.73s**. The 32768-token unknown ledger charge in attempt 2 is conservative budget accounting, not measured billing or proof that its reserved request reached OpenAI. Across both attempts, 22739 tokens were reported, but total consumption/cost is unknown; no invoice is inferred. Neither attempt produced a live Engineer/Verifier result, patch or completion verdict. Final archive-input verification is recorded in the living plan after this README freeze; it is not a fresh dependency-install gate.

Initial Docker preflight used an unshared macOS temporary directory and failed **14 cases, with 5 passing in 71.20s**; its failed-state leases/worktrees are retained for diagnosis. Exact installation-scoped checks found no surviving containers, but unknown dispatched execution leases are intentionally not marked recovered from absence alone. The first combined focused run had 1 failure and 46 passes; the macOS orphan-cleanup race was fixed and the final full suite replayed. See the living plan for the failed approaches, exact selections and evidence boundaries.

No GitHub Actions, dependency/image downloads, commits, pushes, merges or target patch application are part of this slice. Host proof remains macOS arm64/Python3.14.6 with local Colima. See the launcher instructions below for the credential-owning terminal boundary.

## Session-first local verification — 2026-09-07

The final source/test/scripts freeze is `de7ab84636c185e543dfd76b84cc9e97af64aa9ee9ef7ec63f12d3348f4b3135`. All default tests were replayed as exhaustive disjoint partitions: **2283 passed, 19 deliberately skipped**, covering all2302 collected cases. The skipped cases are15 real-Docker,3 fresh-install and1 live-provider cases; optional gates are separate, never inferred from skips. Results below overlap and must not be added as independent test totals.

| Final local gate | Exact result |
| --- | --- |
| Unit + contract | 1749 passed in228.82s. |
| Complete integration, three disjoint file groups | 133 passed in1111.34s;182 passed in1072.79s;186 passed in997.53s —501 total. |
| Offline E2E + default Docker/release/live directories | 33 passed,19 skipped in742.64s. |
| Separately enabled real Docker | 15 passed,4 deselected in370.03s. |
| Standalone offline adversarial replay | 736 passed in459.08s; script elapsed461.966s, no unexpected skips/errors. |
| Formatting / lint / types / generated contracts | Ruff312 files; mypy260 files;92 schemas and migrations1–10; JavaScript syntax and whitespace passed. Offline lock55/sync53 passed. |
| Actual local browser | 17 assertions passed twice; desktop/mobile/200-percent text, empty state, real CLI update, disconnect/reconnect and token denial observed. |

The [Session-first acceptance ledger](docs/SESSION_FIRST_ACCEPTANCE.md) records exact commands/reports, retained failed attempts, final wheel/sdist installation and installed Docker/browser results, cleanup and GitHub delivery separately. README and the bundled guide are frozen before that final installation gate; its resulting receipts update the ledger, not these archive inputs. Tests use prepared dependencies and no live provider key/request. Current host proof is macOS arm64/Python3.14.6 with local Colima workers, not new Linux or multi-Python CI. Hosted CI is intentionally not rerun under the owner's Actions-minute constraint; no workflow or protection is weakened. Public license/live-provider gates and future integrations remain open as described below.

## Session-first workflow

In an initialized repository, enter `fleet` once (an actual interactive terminal is required). Bare noninteractive input prints help without initializing state. For an explicit execution-plan gate, use:

```bash
fleet chat . --review-plan
```

```text
> Fix the regression and add a test.
> /plan
> /plan approve
> /confirm <displayed-review-code>
> /resume
> /diff
> /apply
> /confirm <displayed-review-code>
```

Plan approval, permission approval, execution resume and code application are separate actions. `/approve` can select an exact pending permission request without copying its ID. Review tickets expire after five minutes, are consumed once and are invalidated by selection or authority changes. An interrupted process cannot silently reclaim or replay an already consumed planning decision. An unregistered interactive session offers public bootstrap preview/confirmation; genuine Docker canary evidence is still required before publishing the configuration.

Named model profiles live in user-owned state. For an offline routing exercise on a registered project with new profile names and no existing model selection:

```bash
fleet models set planning --runtime fake
fleet models set coding --runtime fake
fleet models bind planning --path . --default --revision 0
fleet models bind coding --path . --role engineer --revision 1
fleet models selection .
fleet dashboard .
```

For existing profiles/selections, inspect their current revisions before updating; the example's revision numbers are not reusable defaults. Real profiles use the existing explicit `--runtime pydantic-ai --provider-model <provider:model> --credential-ref env:NAME` boundary; never put a key value in a command. Each task pins exact profile revisions before CoS dispatch, so editing a profile affects future tasks, not a paused one. Open the dashboard's printed loopback address and paste the current server process's terminal token. It displays persisted root/child agents, selected models, usage, approvals, events and evidence; it cannot start tasks, approve requests or apply patches. Closing the server revokes the token. No cloud account, external asset, browser storage or mandatory hosted service is involved.

Custom `.fleet/agents/roles.yaml` templates inherit only an Engineer, Verifier, Researcher or Architect execution kind. Reviewed FleetPatch changes version the catalog and guidance. Tools, paths and steps can be narrowed, not expanded beyond the base role; names remain exact permission principals. Custom parallel plans must explicitly select a compatible full-parent repair Engineer. See the [Chinese guide](docs/USER_GUIDE.md) and [configuration contract](docs/CONFIG_AND_SCHEMAS.md#12-session-first-model-and-role-contracts).

The [detailed user guide (简体中文)](docs/USER_GUIDE.md), also bundled in the distribution, covers installation, initialization, BYOK, chat, adaptive teams, exact permissions, evidence/code review, organization evolution and both recovery procedures. [PR #5](https://github.com/meyowu/agent-fleet-codex-kit/pull/5), the [completion plan](.agent/plans/2026-09-05-mvp-completion.md) and the [acceptance ledger](docs/MVP_ACCEPTANCE.md) record the accepted local candidate and GitHub delivery separately from public release.

Three sandbox providers are registered. `DockerSandboxProvider` is the isolated path and creates one inspected, resource-bounded, network-disabled container per reviewed command from an already-local immutable image. `FakeSandboxProvider` records commands without executing them. `LocalUnsafeSandboxProvider` executes directly on the host only after a separate `--allow-unsafe-local` confirmation and can never count as isolated evidence. Provider selection is exact and immutable for a project/run; Docker failure never falls back to host execution.

## Product north star

Six capabilities determine whether Agent Fleet provides differentiated value:

| Capability | Current implementation boundary | Remaining target |
|---|---|---|
| Repository-aware bootstrap | **Enforced:** bounded static inspection finds supported ecosystems, build systems, boundaries, exact candidate commands, provenance, confidence, and ambiguities; preview is read-only; init stages the proposal, runs a disposable canary through the normal Docker workflow, validates a hash-linked `BootstrapReport`, proves cleanup, and only then publishes `.fleet/`. | The canary is a deterministic Fleet-owned fixture; executing arbitrary target-repository setup or networked commands remains out of scope. |
| Adaptive Fleet | **Enforced:** persistent project-bound CoS chat; every run has a validated `FleetPlan`; direct/single/pair create only planned roles. Parallel Engineers use scoped child runs and stable joins; read-only Researcher/Architect reports follow declared dependencies. | Unconstrained scheduling, background/multi-machine fleets and general provider-history restoration remain outside this MVP. |
| Independent permission control plane | **Phase 4 accepted:** ToolGateway re-evaluates current role/workflow/task/user/sandbox ceilings; exact once/run/project rules, explain/revoke/reset, private user-owned trust and durable single-winner dispatch are verified. Phase 5 Milestone 1 preserves cumulative budgets across approval pauses. | Arbitrary shell and approved isolated-worker networking remain unavailable; general provider-history restoration is not implemented. |
| Independent sandbox abstraction | **Enforced local slice:** strict `SandboxRequirements` matching dispatches exact fake, Docker, or separately confirmed local-unsafe providers. Docker pins a local Unix daemon and image ID, inspects effective configuration before start, bounds execution, and recovers exact labeled resources. | Modal and hosted providers, approved network modes, and a multi-user/remote-daemon trust model remain unimplemented. |
| Evidence-first delivery | **Enforced:** exact ConfigSnapshot, TaskSpec, FleetPlan, patch, command inspection/transcript, verdict, cleanup, BootstrapReport, risk, and proof-gap links form content-addressed evidence. Typed criterion references bind joined-candidate and descendant-cleanup provenance through chat and organization versions. Only fresh non-mutating Docker evidence can verify; fake/local-unsafe cannot. | Broader project command/tool coverage and actual model reliability need separate evidence. |
| Versioned Fleet evolution | **Enforced:** CoS delivers immutable proposals and semantic/text diffs; explicit CLI application publishes a whole organization version; current-head rollback creates a new audited inverse. Typed path-conditioned verification skills change required command evidence; actual Linux/macOS native publication tests passed. | No model self-application, permission expansion or protected FleetSpec mutation. Unsupported metadata/filesystems fail closed. |

“Enforced” means a property is checked by code and tests at the named boundary. “Partial” means a real subset exists but does not yet satisfy the complete product claim. “Roadmap” means documentation or schema direction only; it must not be presented as executable behavior. See [ADR 0001](docs/adr/0001-product-north-star.md) for the decision and tradeoffs.

## Reviewable organization evolution

Phase 6 has passed local behavioral acceptance, not public-release acceptance. In a registered project, ask CoS for an organization change such as “For backend changes, always run integration tests.” The response contains a proposal ID; it does not apply the change. Inspect the complete proposal and both derived diffs before authorizing it:

```text
fleet fleet-patch list --path .
fleet fleet-patch show <proposal-id>
fleet fleet-patch diff <proposal-id>
fleet fleet-patch apply <proposal-id>
fleet fleet-patch rollback <current-applied-proposal-id>
```

Every command supports `--json`. Code delivery remains separate: `fleet patch show <run-id>` and `fleet patch apply <run-id>` operate on code, not organization proposals. Fleet never stages or commits user source as part of organization publication.

A workflow may reference a declarative `.fleet/skills/backend-integration.yaml` that requires named verification commands when a code-change task's allowed paths overlap the backend. Requirements are recomputed from the immutable configuration during both TaskSpec creation and final evidence assembly. They are **requirements, not grants**: the exact command still passes through the PermissionBroker and the selected sandbox. A broad scope such as `src` cannot evade a narrower backend requirement. Skills cannot contain executable scripts, change the fixed stage order, grant network access, or add unregistered agents.

Publication binds both the logical ConfigSnapshot and the complete bounded `.fleet/` tree, including safe unreferenced files, modes and empty directories. The generation increases on apply and rollback, even if previous bytes return. An older ready-for-review code candidate therefore becomes stale; request a new run after changing organization rules. Once a project has an admitted Run/history, `fleet init` cannot replace or rebind that organization, including its credential reference. Moving `.fleet/` aside does not erase the version fence. Protected runtime/sandbox/credential configuration is outside FleetPatch. Explicit user-owned model profiles can change runtime/model/reference choices for future tasks; changing the registered sandbox still requires a separate registration with the old project/state preserved.

Supported native publication requires a local macOS or Linux filesystem with same-filesystem atomic directory exchange, writable private staging beside the repository and supported exact metadata. Unsupported ownership, links, ACLs, special flags or extended attributes fail closed. This is local process-crash recovery, not a hardware power-loss or hostile-host guarantee. See [ADR 0006](docs/adr/0006-atomic-organization-publication.md).

An interrupted publisher retains its exact operation and fence. After confirming that the original process has stopped:

```text
fleet fleet-patch operation <operation-id>
fleet fleet-patch recover <operation-id> --owner-stopped
```

Recovery inspects the known original/new orientation; it never exchanges directories again or overwrites unexplained user edits. Publication status and cleanup are separate: `cleanup_complete=true` means inspected complete, `false` records a cleanup gap, and `null` means not inspected by that invocation. Repeating a committed apply returns its original version without applying again or claiming historical cleanup. Failure before a staging receipt exists retains unrecorded private scratch for manual inspection; it cannot be recovered automatically using an invented journal entry. Preserve state and scratch on uncertainty.

Historical Phase6 acceptance proved organization proposals, native publication and abrupt-process recovery, with1973 default passes and14 separately enabled real-Docker passes before checkpoint `b42cdf9`. The rule-enforcement journey required Engineer and independent Verifier to each run five baseline plus two integration tests, then restored the exact prior rule through an audited inverse. Full commands, failures, hashes and metadata/package refreshes remain in the [evolution plan](.agent/plans/2026-09-05-versioned-fleet-evolution.md). Current release-candidate results are reported below; these historical counts are not additional current gates.

## Installed quickstart

No PyPI publication or public runner registry is assumed. Build the reviewed checkout with `uv build`, or obtain the exact reviewed local wheel. Install it into a new environment outside your target project:

```bash
uv venv /absolute/path/to/fleet-cli --python 3.14
source /absolute/path/to/fleet-cli/bin/activate
uv pip install /absolute/path/to/agent_fleet-0.1.0-py3-none-any.whl
fleet version --json
python -c "from importlib.resources import files; print(files('agent_fleet').joinpath('assets/runner'))"
```

The last command prints the installed build context. Build explicitly with `docker build --pull -t agent-fleet-runner:0.1.0-py314-v1 /printed/runner/directory`; dependency/image preparation may use the network, but Fleet never performs it automatically. The runner pins the Python base by OCI digest and five pytest wheels by version/hash. [Runner policy](src/agent_fleet/assets/runner/README.md) states the actual reproducibility limits.

For a first exercise, use the [packaged learning project and step-by-step guide](docs/USER_GUIDE.md#公开学习项目无需模型-key). Copy into a new directory, create its initial Git commit, select a disjoint state directory, and use fake runtime plus real Docker. Review exact approvals, inspect `verified_complete` and command evidence, then apply the code explicitly. This is genuine isolated testing with a deterministic model, not live model reasoning.

## Development setup

Python 3.12–3.14 and Git 2.45 or newer are required. The Git floor is needed for the hardened `--no-lazy-fetch` execution ceiling. `uv` is the preferred contributor tool.

```bash
uv sync --all-extras
uv run fleet version
uv run fleet doctor --json
```

Use `AGENT_FLEET_HOME` to place local state somewhere explicit. Tests always point it at a temporary directory.

## Docker sandbox and verified bootstrap

Docker mode requires a local Linux Docker daemon reachable through a local Unix socket and an image that already exists locally. Fleet never pulls or builds an image, accepts a remote/TCP daemon, or falls back to another provider. The supplied test runner image can be built explicitly by the operator:

```bash
docker build --pull \
  -t agent-fleet-runner:0.1.0-py314-v1 \
  src/agent_fleet/assets/runner

export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet doctor \
  --path /path/to/repo \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --json

uv run fleet init /path/to/repo \
  --runtime fake \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --preview --json

uv run fleet init /path/to/repo \
  --runtime fake \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --yes
```

The final init command first runs a disposable fake-runtime/real-Docker canary through the ordinary workflow. It publishes `.fleet/` only after the final patch, independent verifier command, terminal container inspection, cleanup receipt, completion decision, and `BootstrapReport` hashes all validate. A fake or local-unsafe sandbox can preview the proposal but cannot satisfy this publication gate.

The opt-in real-Docker suite never runs implicitly:

```bash
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE='<preloaded-local-runner-with-python-and-pytest>' \
uv run pytest -q -m docker_integration tests/docker
```

The full Docker suite includes public profiler-detected pytest execution. Runner v1 now includes the genuine required pytest dependencies. The historical Phase5/6 acceptance image `agent-fleet-runner:phase5-chat` and the new runner v1 are local builds, not published images. An unrelated project may require additional reviewed tools; Fleet never installs them during a run.

On macOS with Colima, pytest's temporary root must be under a host path shared into the VM. Create a **new** directory under an existing shared cache parent; never use an existing project, home or cache root as `--basetemp`, because pytest manages and may remove its contents:

```bash
fleet_test_root=$(mktemp -d "${HOME}/.cache/agent-fleet-docker.XXXXXX")
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:0.1.0-py314-v1 \
uv run --offline pytest -q -m docker_integration tests/docker \
  --basetemp="$fleet_test_root/fixtures"
```

## Runtime selection and BYOK

The two registered runtimes are `fake` and `pydantic-ai`. The real adapter accepts only explicit `openai:<model>` and `openai-chat:<model>` identifiers. There is no provider inference or fallback: every other prefix fails closed before credential resolution or network access.

BYOK configuration uses a strict `env:NAME` reference. The reference comes from the user's explicit `fleet init` or `fleet models set` selection and is persisted only in Fleet-owned local state; `.fleet/fleet.yaml` records the original runtime and opaque provider/model ID, never the credential reference or value. Resolved values must be 8–16384 bytes of visible ASCII, which rejects control characters before HTTP-header construction. The raw value remains in trusted control-plane memory, is registered with the shared redactor, and is passed explicitly to the provider client. It is not put in repository configuration, prompts, artifacts, events, worker input, or the process environment by Agent Fleet.

Preview validates the runtime/model/reference shape and the complete proposed `.fleet/` patch, but does not read the referenced environment variable, migrate or write Fleet state, write the repository, construct a provider client, or use the network. Initialization resolves the environment reference before any project state or `.fleet/` write; it does not make a model request. `fleet run` preflights and pins effective user-approved per-role bindings before CoS dispatch, or uses the original registration when no model selection exists; it resolves only the selected credential references before any provider request.

Initialization is fail-closed rather than an in-place `.fleet/` reconfiguration command. Before any Run has established an organization head, an identical generated tree can be reused and a credential-reference-only update does not alter repository files. Once a head exists, **all reinitialization is rejected**, including identical bytes and reference-only changes; moving `.fleet/` aside cannot bypass the recorded head. Rotate a key's value through the same recorded environment reference when needed. Supported organization edits use reviewed FleetPatch. Explicit user-owned model profiles can change runtime/model/reference choices for future tasks; changing the registered sandbox still requires a separate registration with the old project/state preserved. Fleet never overwrites a mixed or partially changed tree.

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
# Set OPENAI_API_KEY through your normal secure environment mechanism.

uv run fleet init /path/to/repo \
  --runtime pydantic-ai \
  --provider-model openai:gpt-5-mini \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --preview --json

uv run fleet init /path/to/repo \
  --runtime pydantic-ai \
  --provider-model openai:gpt-5-mini \
  --credential-ref env:OPENAI_API_KEY \
  --sandbox docker \
  --docker-image agent-fleet-runner:0.1.0-py314-v1 \
  --yes

uv run fleet doctor --path /path/to/repo --json
uv run fleet run "Fix the canary behavior" --project /path/to/repo --sandbox docker
```

Use `openai-chat:<model>` only when the OpenAI Chat Completions model path is intended; `openai:<model>` uses the Responses model path. Run-time provider flags are optional when they match the reviewed project registration; if supplied, they must match exactly. `--fake-scenario` is rejected for `pydantic-ai`.

One-shot `fleet run` accepts optional cumulative ceilings: `--max-agent-invocations`, `--max-model-requests`, `--max-tool-calls`, `--max-total-tokens`, and `--max-active-seconds`. Omitted options preserve existing defaults. Invalid values fail before creating a Run; accepted limits are persisted and do not reset on approval/resume. ModelProfile limits additionally constrain each role invocation. Reported-token limits are post-response accounting, not a guaranteed dollar or pre-spend ceiling.

`fleet doctor` reports the original project registration, not readiness of every per-role model profile. Effective profile preflight occurs when starting a task. Users selecting profiles should omit legacy runtime override flags.

`fleet doctor` inspects whether the selected environment reference is configured and valid without resolving/returning its value and without contacting a provider. The Phase 2 OpenAI client pins `https://api.openai.com/v1`, disables SDK redirects, retries, and ambient proxy/CA discovery, clears ambient OpenAI organization/project/admin/webhook selections, and supplies the explicitly resolved authorization value. A final request hook validates the SDK-merged method, endpoint, headers, content length, and serialized body before send; a response hook rejects registered-secret material and removes provider-controlled headers before OpenAI SDK parsing/logging. `OPENAI_BASE_URL`, proxy variables, and unrelated OpenAI identity variables cannot redirect the selected BYOK credential. A generated doctor report exits zero even when `data.healthy` is false: exit zero means diagnostics completed, while readiness is expressed by `data.healthy` and the individual required checks. A missing PydanticAI credential is a failed required check; the fake runtime reports `not_selected` and does not require a provider credential. A command-level Fleet error still returns its documented nonzero category.

The live smoke test is deliberately opt-in and modifies only its generated disposable fixture. For the bounded low-cost source-checkout test, export `FLEET_OPENAI_TEST_KEY` securely in your own terminal, then launch from that **same terminal** using the prepared `.venv`. Do not print the key, paste it into a command argument, or copy it into a repository file.

```bash
# macOS/Colima: this existing parent must be shared with the VM.
fleet_evidence_parent=$(mktemp -d "$HOME/.cache/agent-fleet-live.XXXXXX")
.venv/bin/python scripts/run_live_canary.py --run \
  --output "$fleet_evidence_parent/attempt-01"
```

The local Docker image `agent-fleet-runner:0.1.0-py314-v1` must already exist; `--image` may select another prepared compatible local image. The launcher pins `openai:gpt-5-nano`, strips unrelated provider/debug/pytest environment settings, never pulls or installs, and refuses a reused output directory. It sets explicit live/Docker opt-ins for its child only. A missing key fails before launching; ordinary pytest continues to skip the live case.

The root task allows at most 12 agent invocations, 24 model requests, 32 tool calls, 65,536 reported tokens and 600 active seconds. Each role profile allows 8 requests, 12 tools, 32,768 reported tokens and a 120-second timeout. Attempt 1 used zero structured-output corrections; the current configuration permits one correction through the existing runtime, before any side-effecting tool attempt, under the same cumulative ceilings. SDK retries remain zero and provider reasoning defaults are unchanged. The launcher has a separate 900-second wall timeout. These limits are not guaranteed dollar caps, and a failed or interrupted response may have incurred charges. Do not repeat a failed attempt without inspecting its evidence.

PASS requires actual CoS → Engineer → Verifier usage, exact model/profile revisions, real isolated command receipts, an independently verified single-file patch with no proof gaps, unchanged source checkout, complete accounting and cleanup. `canary-evidence.json` retains structured artifacts/commands/usage, `cleanup.json` records finalizer cleanup, and `summary.json` plus `pytest.log` record the original outcome. Diagnostic files are private and scanned for registered-secret forms before persistence. The synchronous test finalizer handles normal failures; the launcher never infers safe recovery after missing/incomplete finalization. Hard interruption can leave detached Docker/Git processes or leases requiring explicit reconciliation; it reports NOT_PASSED and withholds recovery. Offline FunctionModel/bootstrap tests and source-safety review do not substitute for the real-provider gate.

## Offline preview and fake test mode

Start from a Git repository with at least one commit. Preview performs repository-aware discovery without executing repository code or writing Fleet state:

```bash
export AGENT_FLEET_HOME=/path/to/a/disposable/state-directory
uv run fleet init /path/to/canary-repo --preview --json
```

`fleet init --preview --json` returns RepositoryProfile, ProjectKnowledge, every proposed `.fleet/` file, and a unified diff without creating `.fleet/` or `AGENT_FLEET_HOME`. Semantic profile hashes and serialized artifact hashes use explicitly different fields. Registered secrets in repository-derived profile/configuration data are rejected before parsing, output, or any Fleet write; malformed YAML errors do not retain registered values in their exception chain.

Fake mode remains deterministic test infrastructure and supports legacy Phase 0–2 project registrations, but it cannot prove an isolated bootstrap. A public `fleet init --runtime fake --sandbox fake --yes` therefore runs the canary, returns `BOOTSTRAP_CANARY_FAILED`, and leaves the target `.fleet/` unpublished. Use the Docker quickstart above for a new verified registration.

The init/run path safely tolerates only the exact unchanged `.fleet/` status and referenced configuration contents produced by initialization. Configuration loading accepts only bounded regular non-symlink files. A changed referenced file is rejected before run creation even when Git's untracked-file status is textually unchanged, and explicit patch apply rechecks the run-bound ConfigSnapshot as well as repository/base/status identity. Differing `.fleet/` reinitialization also fails before Fleet state changes rather than overwriting the existing tree. Repository and Fleet-state roots must be disjoint in both directions. Real and fake runtimes use the same workflow, artifacts, gateway, permission broker, and completion gate.

The code-change scripted workflow expects `src/canary_calc/core.py` in the target repository. It changes `divide(a, b)` so division by zero raises `ValueError("division by zero is not allowed")`. `--fake-scenario direct` creates no specialist workspace, `single_engineer` creates one Engineer, and the default creates Engineer plus fresh Verifier. `parallel_engineers` additionally creates a separately scoped `metadata.py`; `specialist` runs the declared read-only research/architecture chain before one Engineer. `repair`, `fail`, `approval`, `inconclusive`, and `verifier_mutation` exercise bounded negative paths. The mutation scenario is denied by PermissionBroker before a write. These are test/demonstration scripts, not model judgments; arbitrary repositories require the real runtime and reviewed command profile.

For an existing fake registration or the test harness, the approval scenario is:

```bash
uv run fleet run "Fix the canary behavior" --project /path/to/canary-repo --fake-scenario approval
uv run fleet approve <request-id> --once
uv run fleet resume <run-id>
```

`fleet deny <request-id>` followed by `fleet resume <run-id>` rejects the run. Repeated resume does not repeat the recorded logical side effect.

## Exact permissions (Phase 4 accepted)

Use Safe mode to require an explicit approval for each new exact command scope. A run grant covers the same action only within its owning run; an always rule covers the same project, role, workflow stage, command arguments, workspace and sandbox conditions in later runs. Engineer approval never grants Verifier approval, and changing a command does not inherit its earlier permission. A durable per-intent dispatch claim permits only one execution owner, even across concurrent CLI processes. An incomplete claim is not replayable.

```bash
uv run fleet permissions configure --project /path/to/repo --mode safe --allow-path src
uv run fleet permissions list --project /path/to/repo --json
uv run fleet permissions explain <request-id> --json
uv run fleet approve <request-id> --once
# Alternatives to --once, not additional flags:
uv run fleet approve <request-id> --run
uv run fleet approve <request-id> --always --scope project
uv run fleet resume <run-id>
uv run fleet permissions explain <rule-id> --json
uv run fleet permissions revoke <rule-id> --json
uv run fleet permissions reset --project /path/to/repo --json
```

Choose exactly one approval lifetime per request. `--allow-path` is repeatable and sets the upper candidate-path ceiling; CoS can narrow it but cannot widen it. Omitted paths preserve existing settings. New init previews show the proposed user policy; repeat init preserves omitted trust mode and paths. Trust lives at `<Fleet state root>/trust/trust.yaml`, using `AGENT_FLEET_HOME` when set or the platform's user-data directory otherwise. Repository `requestedPermissions` cannot grant it. Do not manually edit grant records or the SQLite database.

Approval pauses retain the current Engineer or Verifier identity and exact workspace/sandbox. A fresh CLI process revalidates those bindings before continuing. Verification also checks the canonical patch hash so changed code cannot reuse earlier evidence. Model-call IDs and display prose may change on reconstruction; the original reviewed intent explanation is retained, while execution-bearing fields must remain identical. Milestone 1 durably retains usage and immutable budgets across paused, failed and cancelled invocations; a new physical attempt does not reset its logical agent's step ceiling. General provider-history restoration remains unimplemented.

Historical once-only checkpoint compatibility can restore only the exact persisted original agent after validated state lookup; it does not grant run-wide or persistent authority or override accounting checks. Runs without a reliable budget ledger report `legacy_unknown` and fail closed rather than resume with invented zero usage. Claims remain permanent across restart: grant consumption alone is not permission to dispatch a second time.

Safe mode still permits bounded candidate file operations inside the reviewed scope, while commands prompt. Balanced permits the supported exact reviewed verification commands. `autonomous-sandbox` currently has the same supported-command ceiling as Balanced; it does not enable arbitrary shell, networking or host execution. Local-unsafe commands continue to require exact approval. Revocation removes a grant/rule, not the underlying trust-mode defaults; in Balanced a command may still be allowed by the reviewed baseline. `reset` revokes project grants/rules while preserving its reviewed mode and path ceiling.

After a control-plane crash, recovery is deliberately scoped to one known Run and is not
performed as a blanket startup sweep. First confirm that no other Fleet process still owns the
Run, then invoke:

```bash
uv run fleet recover <run-id> --confirm-owner-stopped --json
```

The command marks an interrupted `RUNNING`/`APPLYING` Run failed and reconciles only its
persisted leases. It is idempotent for an already terminal, fully cleaned Run and refuses durable
ordinary states such as `PAUSED_FOR_APPROVAL`, which must use `resume` or `cancel` instead. An adaptive parent with a retained uncertain driver/continuation claim is an exception: after confirming its owner stopped, recovery may abandon the claimed pause and clean its exact descendants. It never takes over the old execution.

## Adaptive graph execution (Phase 5 Milestone 2 accepted)

CoS proposes a strategy; trusted code checks the reviewed role, scope, delegation, step and concurrency ceilings. Parallel assignments must have explicit subgoals, non-overlapping paths and complete acceptance-criterion coverage. The reviewed workflow `maxParallelAgents` (default 2, maximum 8) limits active children, not total queued tasks. Legacy advanced plans without operational subgoals/criteria remain readable but cannot execute.

Each worker has its own durable Run, TaskSpec, approval principal, workspace and artifact ownership. All workers share the parent's cumulative budget, but not once/run grants. Researcher and Architect may list/read/search/diff their candidate view; they cannot write files, execute commands or request an approval through their tool catalog. Their bounded reports are explicitly untrusted reasoning, not test evidence.

Inspect the parent with `fleet status <parent-id> --json`. The graph includes node/dependency state, child IDs, ordered join receipts and the exact `pending_child_approval_ids`. Approve each displayed child request, then `fleet resume <parent-id>`. `WAITING_FOR_CHILDREN` does not invent a parent approval. Public child resume/apply/cancel/recover are refused; lifecycle operations use the parent. Approved requests preserve original child agent/workspace/sandbox identities across reconstruction.

Independent writers finish in any order; patches join in stable node-ID order into a fresh parent candidate. The parent Verifier checks the complete original task in another clean workspace. A child's full test suite may fail because another child's file is absent; only the joined parent verification can establish completion. Bounded sequential parent repair is explicitly audited and never replays successful children. Explicit `fleet patch apply <parent-id>` still changes only the target working tree.

Driver and parent-continuation claims are durable and have no automatic expiry. Duplicate resume cannot acquire the same work or clean the winning owner's resources. If an owner crashes after dispatch or resume preparation, use exact operator-confirmed recovery, not an automatic retry. Cancellation fences the graph and retains dependency-ordered cleanup; cleanup failures remain recoverable leases. EvidenceBundle includes typed graph/join/child-cleanup provenance, while its verification commands remain parent-owned.

## Persistent CoS chat (Phase 5 accepted)

After successful initialization, use the registered runtime and sandbox:

```bash
uv run fleet chat /path/to/repo
# At the chat prompt:
/help
/status
/permissions <request-id>
/approve <request-id> --once
/resume
/artifacts
/exit
```

Natural-language lines submit a goal; slash commands are deterministic local controls. Approval does not resume automatically. `/deny <request-id>`, `/cancel`, and `/approve <request-id> --run` or `--always --scope project` use the same exact permission service as ordinary CLI commands. `/permissions` without an ID lists the selected project's rules. Inspect/apply using session `/diff`, `/apply`, `/confirm`, or the compatible `fleet patch show <run-id>` and `fleet patch apply <run-id>` commands. A delivered turn does not mean the patch was applied or independently verified: inspect its Run evidence and warnings.

Reopening `fleet chat /path/to/repo` selects the latest project-bound conversation. Use `--conversation <conversation-id>` to select an exact conversation or `--new` for a new one. Automation can submit one goal:

```bash
uv run fleet chat /path/to/repo --conversation <conversation-id> \
  --message "Explain the validation path" --submission-id review-validation-1 --json
```

The submission key is scoped to the conversation. Retrying identical content returns the original turn/Run, even after later turns, without another execution or budget reset; different content under the same key fails. Only one active turn is allowed. New goals are not queued while running or awaiting approval. Public `fleet resume <run-id>` enforces the same conversation ownership as `/resume`.

History contains bounded summaries and authoritative artifact references, not raw provider histories: at most eight recent settled turns and 32 KiB of serialized context. Omitted/truncated context is explicit. Lines are bounded to 16 KiB UTF-8; a conversation holds at most 1,000 turns. Interactive input supports POSIX terminals and pipes with bounded buffering; unsupported descriptors/platforms fail clearly. `--json` and `--submission-id` require `--message`.

While a role is working, `/status` remains responsive. EOF, `/exit`, and repeated Ctrl-C retain and await cancellation/cleanup of locally active work; an already paused approval turn remains available for restart. Use `/cancel` explicitly to cancel a waiting turn. A delayed cancellation stays bound to its original Run and cannot cancel a newer turn. Unknown ownership after a crash never expires into a right to replay; stop its original process, inspect the Run, and use `fleet recover <run-id> --confirm-owner-stopped`. Recovery can fence a conversation-owned interrupted CREATED or PAUSED state, preserves budgets, and releases the turn only after exact root/descendant cleanup. Each new chat invocation must explicitly select `--allow-unsafe-local` before host execution; `/resume` uses that session's choice.

## What is enforced now

- strict Pydantic v2 persistent/external models and safe YAML loading;
- type-specific stable ID prefixes for persistent and public identity fields, including project, run, task, agent, event, approval, grant, artifact, intent, lease, workspace, sandbox, plan, and FleetPatch IDs;
- explicit workflow transitions with transactional per-run events;
- SQLite migrations `0001`–`0010`, durable exact once/run/always approval grants, per-action persistent-rule capability receipts, provider/image/daemon-bound Projects and Runs, immutable per-role model bindings, planning-decision journals, cumulative budget accounting, graph/conversation ownership and recoverable worktree/sandbox/execution leases;
- repository-aware no-execution profiling with provenance, ambiguity, read/entry/depth limits, and symlink defenses;
- repository-specific FleetSpec/verification proposals plus immutable profile/knowledge artifacts;
- exact content-addressed ConfigSnapshot and TaskSpec bindings for each run, status inspection, and patch apply;
- validated per-run FleetPlans, dynamic direct/single/pair roles, accepted bounded parallel/specialist child graphs and deterministic parent joins;
- model-style writes routed through ToolGateway and an independently injected PermissionBroker;
- permission-decision events and exact role/stage/action/resource/sandbox matching;
- intrinsically coherent sandbox capability reporting and exact requirement matching across fake, Docker, and separately confirmed local-unsafe providers, with no fallback;
- fixed-path Docker CLI resolution; local-Unix/Linux-daemon, API/capability, immutable-image, and image-environment preflight; one container per command with non-root identity, dropped capabilities, no-new-privileges/seccomp, read-only root, network none, private namespaces, exact mounts/tmpfs/environment, and CPU/memory/no-swap/PID/shm/file-descriptor bounds;
- effective Docker inspection before start, direct argv only, bounded output and single-task process-group timeout/cancellation handling, retained dependency-ordered execution/sandbox/worktree cleanup, exact full-ID/11-label recovery, and a durable pre-dispatch checkpoint that prevents command replay after crashes;
- descriptor-relative, no-follow workspace reads/searches/writes/deletes with inode/type/size/path ceilings; `.git` is shadowed from containers and remains control-plane-only;
- canonical repository-relative path checks with traversal, symlink, filesystem-identity, case-folded protected-path, and bidirectional state/repository containment defenses;
- structured Git subprocess argv with no shell, reset, clean, stash, push, or implicit commit;
- separate candidate and verification worktrees; verifier mutation intents are denied;
- control-plane-computed patch/hash and explicit apply with repository/base/status guards;
- content-addressed artifacts with read-time integrity checks;
- canary-before-publication bootstrap staging with a hash-linked `BootstrapReport`; target `.fleet/` publication requires independently verified Docker evidence plus complete cleanup and never accepts fake/local-unsafe claims;
- structured command evidence and EvidenceBundle/CompletionGate assurance, expanded in `fleet run/status` as changed paths, command results, verdicts, risks, proof gaps, and reason codes;
- recursive registered-secret rejection across mapping keys and values before bootstrap preview/configuration, package prompt/tool/output-schema model input, provider response/tool execution, final serialized provider request, ToolIntent, task, event, approval, or artifact persistence, plus redaction for trusted user-authored diagnostics;
- exact runtime selection with typed capability preflight and no implicit fallback;
- strict `env:NAME` BYOK references, environment-backed inspection/resolution, opaque secret values, and dynamic redaction of raw and common encoded forms;
- strict PydanticAI `ScopeDecision`, `FleetPatch`, `ImplementationReport`, `SpecialistReport`, and `VerifierVerdict` outputs plus provider-neutral usage records and bounded provider metadata;
- role- and stage-bound PydanticAI resource tools whose execution crosses `GatewayRuntimeToolCatalog -> ToolGateway -> PermissionBroker`; whole deferred batches receive side-effect-free catalog schema validation first, then authorized candidate writes use the Fleet-owned candidate-worktree primitive while fake command/approval fixtures use `FakeSandboxProvider`. The CoS-only `fleet_content_sha256` helper is pure, has no I/O and grants no authority; it does not use the resource gateway;
- provider errors, timeouts, invalid output, and budget/retry exhaustion mapped to stable Fleet errors without persisting raw provider responses or SDK objects;
- ordinary adapter, integration, CLI, and E2E coverage with live model requests and sockets denied.

## Honest security limitations

`FakeSandboxProvider` is a recorder with `security_level=fake`, `isolation_enforced=false`, and `executes_code=false`; it is not a security boundary. `LocalUnsafeSandboxProvider` executes with the Fleet process's host authority and is also not isolation. Neither can publish a verified bootstrap or turn a model Verifier PASS into `verified_complete=true`.

Docker isolation assumes the local OS account, Docker CLI/configuration, daemon, kernel/VM, and preloaded runner image are trusted. Docker daemon access is itself highly privileged. Fleet accepts only a pinned local Unix endpoint and Linux daemon, but it does not isolate against another process running as the same host user. Workspace identity and the private empty `.git` shadow are rechecked immediately before dispatch. A non-inheritable read-only descriptor pins the shadow inode to prevent reuse after unlink; timestamp checks additionally detect same-inode drift. The descriptor closes on failed preparation or successful logical cleanup. Docker still resolves mount pathnames after the final check; this is not an atomic path handoff or a guarantee for every Docker/kernel/filesystem combination.

On POSIX, the bounded Docker CLI runner starts a private process group, sends at most one immediate destructive group signal, reuses one child waiter, and requires bounded leader reap plus a non-destructive group-absence probe before cancellation can succeed. The proof still identifies the group by a numeric PGID; it is not a cryptographic identity and cannot defend against a hostile same-user process deliberately racing PGID reuse. Removing that residual boundary requires a supervisor, cgroup, or pidfd-class design. In-process cleanup calls with the same terminal target coalesce and survive repeated caller cancellation; conflicting `RELEASED`/`RECOVERED` requests fail closed, but this is not a cross-process ownership lock. Cleanup or termination failure takes precedence over an ordinary cancellation result.

Only `network=none` is accepted by the isolated Phase 3 path. Images must already exist locally and may expose only the allowlisted environment defaults; Fleet does not build, pull, patch, or attest their supply chain. Cgroup-v2 daemons may report `MemorySwappiness=null`; Fleet accepts that only while the inspected memory and memory-swap hard limits are equal, which proves no container swap allocation. A crash after the durable create-dispatch checkpoint but before an exact Docker ID is persisted is intentionally conservative: zero label matches remain `FAILED`, parent resources stay intact, and no command is replayed. If the resource appears later, the operator reruns exact-run recovery after confirming the old owner stopped; a permanent zero remains outstanding for diagnosis rather than becoming an unsafe absence claim. Phase 3 has no cross-process owner-liveness lock, so it intentionally does not run destructive recovery automatically on every CLI startup.

One overall model verdict cannot independently establish multiple acceptance criteria. Milestone 1 adds `structured_criterion_results` with exact current independent-verifier command/artifact references; missing mappings remain inconclusive with `STRUCTURED_CRITERION_MAPPING_UNAVAILABLE`, and invalid mappings cannot establish PASS. The normal two-criterion/new-module Docker journey proves this boundary; the same fake-sandbox mapping remains inconclusive. The policy surface covers bounded candidate operations, exact reviewed verification commands, and one explicit fake approval fixture. Phase 4 adds a separately reviewed user path ceiling, not an inference of path intent from natural language; target-checkout mutation still requires explicit patch review/apply. There is no approved isolated-worker networking, remote/hosted sandbox, arbitrary shell surface, external write, or keyring/second-provider integration. Persistent CoS chat is accepted; the working-tree FleetPatch lifecycle and its remaining gates are described above.

The Phase 5 candidate delivery path is intentionally text-only: changed or deleted binary files, unsafe file types, protected paths and changed Git indexes fail closed. New regular UTF-8 files are included in canonical patches; unchanged binary assets may remain in a repository. This avoids concealing registered secrets inside Git's encoded binary-patch format. Ignored paths retain Git ignore semantics; there is no global cache-name exclusion. Generated test fixtures explicitly ignore their Python test caches. New-file snapshots are bounded to 1,024 files, 2 MB per file and 8 MB total; emitted patches are limited to 16 MB, while model patch context retains its smaller 120 KB bound.

The BYOK external boundary is provider HTTPS from the trusted control-plane process. Model prompts and selected project/task context are therefore disclosed to that provider according to its terms. `max_total_tokens` is enforced from provider-reported usage after each response and before continuations/tools; it is not a pre-spend billing ceiling, so a first or final request can report more total tokens than remained. `max_tokens` still bounds requested output. The response hook runs before OpenAI SDK response handling, but Fleet does not install global logging filters: a caller that programmatically enables low-level transport (`httpx2`/`httpcore2`) DEBUG logging may log transport metadata before that hook. Normal Fleet CLI operation and `OPENAI_LOG` do not enable those low-level loggers. Provider-native shell, filesystem, MCP, hosted tools, and arbitrary model-selected network tools are disabled. Installed adapter code shares the control-plane process's OS authority; isolation from arbitrary third-party adapter code is not claimed.

Local SQLite/events are append-only through the application API but are not tamper-proof against the local OS user. Git worktree cleanup force-removes only Fleet-owned paths beneath `AGENT_FLEET_HOME`; it never resets, cleans, stashes, or discards the target checkout.

Git subprocesses resolve an absolute executable outside repository/Fleet-state-controlled `PATH` entries using lexical, canonical, and filesystem-identity containment; require stable top-level/git-dir/common-dir identity; ignore global/system config; disable hooks, fsmonitor, replacements, lazy fetching, credentials, signing, and external diffs; reject any repository-local executable filter/diff/hook/include surface without copying its name into a later argv; and use only an explicit subcommand allow-list. Invalid repository errors omit unresolved canonical paths and underlying untrusted exception chains. This is not a multi-user isolation boundary: a same-OS-user process can still race repository-local config between the non-executing config probe and a later Git command. Ordinary Git command paths are not generally byte-capped; the organization-boundary reader separately bounds/drains output and hashes index bytes. A parent-process timeout alone does not prove malicious descendants were reaped. A future shadow Git metadata/index boundary plus general process-group/output enforcement is required before hostile multi-user repositories are in scope.

Patch application updates the original working tree only. It does not stage, commit, merge, push, or create a pull request.

## Roadmap boundary

- Phase 1.5: completed offline foundation—repository profiling, validated adaptive FleetPlan, independent PermissionBroker, sandbox capabilities, EvidenceBundle/CompletionGate, and FleetPatch schema validation.
- Phase 2: implemented explicit BYOK `env:NAME` references and the PydanticAI runtime behind the project-owned runtime/tool contracts.
- Phase 3: completed local Docker sandbox, bounded file/command tools, deterministic recovery, and evidence-gated bootstrap.
- Phase 4: accepted three-state policy, exact once/run/project trust, audited revocation and safe approval resume.
- Phase 5: accepted cumulative budgets, all five adaptive strategies and persistent bounded CoS chat.
- Phase 6: accepted reviewed FleetPatch publication, required verification rules and audited rollback/recovery.
- Phase 7: implemented local release candidate with full offline, Docker, installed-user and platform verification; final GitHub delivery is recorded in the release plan and PR. Owner license and live-provider proof remain separate public-release gates.

Phase0–6 establishes local execution, exact permissions, evidence, durable budgets, adaptive execution, persistent chat and reviewed FleetPatch evolution. Phase7 release hardening/platform proof and live-provider/license gates remain distinct. See [release procedure](docs/RELEASE.md), [data disclosure](docs/DATA_HANDLING.md), [dependency policy](docs/DEPENDENCIES.md) and [security checklist](SECURITY.md).

## Quality gates

```bash
uv run --offline ruff format --check .
uv run --offline ruff check .
uv run --offline mypy src tests
uv run --offline pytest -q -ra
uv run --offline python -m agent_fleet.schemas.generate --check
AGENT_FLEET_ENABLE_DOCKER_TESTS=1 \
AGENT_FLEET_DOCKER_TEST_IMAGE=agent-fleet-runner:0.1.0-py314-v1 \
uv run --offline pytest -q -m docker_integration tests/docker
```

## Release-candidate verification (2026-09-05)

Runtime behavioral freeze: `c03fa3d455b073958ade3c4d365a0231319e1b59eb715af3b79bb278bff5d3c3`, checkpoint `329324430e4b712062f045fb613173cf4a8adea7`. The final help-text/CI-assertion refresh has source/test/script hash `c400cdb40fa16bb13d2c1a8732893560ccc91db5fdbf916bdcf6868857378cf6`; its only production delta is corrected resume help wording. Exact final-head checks, documentation/archive refreshes and GitHub delivery are recorded separately in the [release ExecPlan](.agent/plans/2026-09-05-release-candidate.md). Test selections overlap; do not sum these rows.

| Gate | Exact observed result and scope |
| --- | --- |
| Formatting, lint, strict types, schemas, dependency lock | Ruff267 files; mypy219 files on Darwin and Linux;82 schemas; lock55/sync53; whitespace checks passed. |
| Complete default suite | Runtime freeze: macOS `2004 passed,18 skipped in1515.89s`; Linux `1997 passed,25 skipped in994.03s`. macOS partitions:unit1027,contract578,integration372,offline E2E22,four offline Docker cases andone readiness case. |
| Standalone offline adversarial replay | `734 passed in199.76s`; zero skips/errors/failures, structured verdict0. This named subset includes Docker contracts and native publication/recovery. |
| Real Docker boundary | `14 passed,4 deselected in148.37s`; zero skips/errors/failures. macOS arm64/Colima with runner v1 image `sha256:2afebd51ae66f07096063b53fc14b6a45b18dd63b01d7f31ed0cb640c51da241`. |
| Docker residue read-back |26 distinct databases:97 released/nine historical recovered leases, no outstanding lease, pending organization operation/head or active chat claim; no managed containers before starting the separate installed journey. |
| Independent shadow/native/proposal review | PASS: `277 passed in20.01s`; extra probes prove no dispatch after replacement/drift, read-only/non-inheritable pin, cancellation retention, cleanup/finalization and valid workspace writes. Not a daemon or Linux run. |
| Fresh installed wheel/sdist/public journey | Documentation-final checks: **3 passed, no skips**;36 locked distributions,82 schemas/eight migrations and the655-line guide in isolated environments. Exact archive identities, commands and durations are recorded in the release plan. |
| Linux/macOS × Python3.12–3.14 | Final PR head `e413192` passed **all nine jobs** in [workflow33987810067](https://github.com/meyowu/agent-fleet-codex-kit/actions/runs/33987810067): each macOS selection1664 passed; each Linux selection1659 passed/five Darwin skips. Complete Linux default1997 passed/25 skips1031.53s; standalone security729 passed/five Darwin skips142.20s; installed2 passed/one deselected56.55s; Docker plus installed public journey15 passed/six deselected181.22s. |

Default skips are14 separately tested real-Docker cases,three separately tested installed cases andone unperformed live-provider case. Linux additionally skips five Darwin metadata andtwo case-insensitive-filesystem-only cases, exercised on macOS. CI covers all units/contracts/offline E2E plus selected integrations on six combinations; the complete integration suite additionally runs on Linux3.14 and locally on macOS3.14, not every integration on all combinations.

The public installed Docker journey exercises doctor, Safe/src init, chat with cross-process exact approvals and duplicate-submission read-back, independent real five-test receipts, explicit code apply, persistent-rule revocation and confirmed no-op recovery. A separate installed registration substitutes only offline FunctionModel responses to exercise CoS proposal/diff/apply/rollback. That fixture is neither stock fake behavior nor live-provider inference. Source fresh-process crash and real Docker interruption-recovery tests supply the separate interruption evidence.

Live inference was **unperformed in this September 5 snapshot**; the later unsuccessful nano attempts are recorded in the current canary section above. Default opt-in skips are not passes, and automated local/CI acceptance does not establish arbitrary-model reliability, a public release, or a license. The repository remains private; no PyPI publication or public runner registry is assumed. [PR #5](https://github.com/meyowu/agent-fleet-codex-kit/pull/5) was merged on2026-09-05 at20:02:01 UTC as `0cead7dcafcace07d64892c0ff41ed72939d706a`. Local/remote main initially matched that merge, whose tree `7b052436feb7c537391d4f421a8ee35468a93380` exactly equals the accepted PR head. The documentation-only delivery record and proportionate post-merge/package checks are recorded in the [release plan](.agent/plans/2026-09-05-release-candidate.md); [main-branch checks](https://github.com/meyowu/agent-fleet-codex-kit/actions/workflows/ci.yml?query=branch%3Amain) expose the exact record revision's CI separately.

## Historical acceptance

Earlier checkpoints, exact commands, failed attempts and successful repeats are retained in the [acceptance ledger](docs/MVP_ACCEPTANCE.md) and living plans: [Phase4/completion](.agent/plans/2026-09-05-mvp-completion.md), [budgets/evidence](.agent/plans/2026-09-05-adaptive-workflow-chat.md), [adaptive graph](.agent/plans/2026-09-05-adaptive-graph.md), [persistent chat](.agent/plans/2026-09-05-persistent-chat.md) and [organization evolution](.agent/plans/2026-09-05-versioned-fleet-evolution.md). Historical skips, package limitations and old main-branch identities describe those snapshots, not current acceptance. See the [Chinese user guide](docs/USER_GUIDE.md) for the maintained user journey.
