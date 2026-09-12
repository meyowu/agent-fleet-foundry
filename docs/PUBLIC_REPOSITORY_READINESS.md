# Real public-repository static readiness observations

Status: six original observations and a normally completed focused regression
passed independent readback on2026-09-12. This is **not** six runnable
environments, six successful business tests, a live campaign or cold-start proof.

The measured product source is delivered commit
`c13a3f679222b5af5a6e6ab6fdf8a2504fdda502`. Each original immutable repository
below was acquired once and inspected once with the existing public command:

```text
fleet readiness /absolute/path/to/repository --json
```

No project program, package install, lifecycle hook, model or Docker command ran.
All six reports retained `environment_status=unverified`,
`baseline_status=not_checked`, `commands_executed=0`,
`execution_authorized=false`. Exit0 means static inspection complete; exit1 means
incomplete static inspection. Neither means the project is ready to execute.

## Frozen sample and observations

| Original repository / immutable commit | Exit | Observed static result |
| --- | ---: | --- |
| [mahmoud/boltons](https://github.com/mahmoud/boltons/tree/961dcff3f42e73b245aef65e377fe82763b257bb) | 1 | Two unsupported-metadata issues and one dynamic declaration; build/test candidates were detected. |
| [dbader/schedule](https://github.com/dbader/schedule/tree/82a43db1b938d8fdf60103bd41f329e06c8d3651) | 1 | Dynamic declaration; build candidate only, no test candidate detected. |
| [pallets/itsdangerous](https://github.com/pallets/itsdangerous/tree/672971d66a2ef9f85151e53283113f33d642dabd) | 1 | Unsupported metadata; four uv build/mypy/ruff/pytest candidates were detected. |
| [tj/node-cookie-signature](https://github.com/tj/node-cookie-signature/tree/b7bd4cb9500bfa5e696143f51d61e5f24f7a625d) | 1 | `verification_commands_missing`; no candidates were produced. |
| [lukeed/clsx](https://github.com/lukeed/clsx/tree/925494cf31bcd97d3337aacd34e659e80cae7fe2) | 1 | `verification_commands_missing`; no candidates were produced. |
| [juliangruber/balanced-match](https://github.com/juliangruber/balanced-match/tree/1c781ffdd29e5c4840221e6bf1f201ce316de600) | 0 | Complete static inspection with eleven npm-script proposals, including lifecycle scripts. No proposal was authorized or executed. |

All reported omission counters were zero. An unsupported/dynamic declaration is
still a real coverage limitation, not an omitted issue to erase or an environment
failure established by execution. Detected generic commands are not a guarantee
of equivalence to upstream's complete tox/CI/test-and-build contract.

## Practical meaning and limits

The three Python projects declare additional upstream test/build tooling: boltons'
installed-package/tox/doctest lane; schedule's coverage/type/timezone tools; and
ItsDangerous' freezegun/src-layout installation. All three Node targets require
development dependencies beyond Node/npm. This run did not install, resolve or
test those dependencies, so their execution availability remains unknown.

The missing test candidate for schedule and zero command candidates for
cookie-signature/clsx demonstrate limits of current automatic discovery on real
manifests. Schedule declares pytest in requirements-dev.txt, which the current
command-discovery path does not inspect. The two Node manifests declare scripts
but neither packageManager nor a recognized lockfile; the profiler therefore
leaves the manager unresolved and does not generate runnable candidates.
A declared npm script is not itself proof of an explicitly selected
package manager, a complete dependency closure or permission to run it. Similarly,
balanced-match's eleven proposals are not eleven approved/safe execution paths:
its test lifecycle requires preparation, and publish/version hooks are outside
this task. No weakened tests, suppressed lifecycle hooks or fallback test commands
were used to manufacture passing observations.

## Evidence and acceptance

The [living pre-execution plan](../.agent/plans/2026-09-12-public-repository-readiness.md)
freezes all six commit/tree IDs, exact blob counts/bytes, acquisition limits and
the no-execution contract. Complete source trees were admitted before raw blob
materialization, without checkout filters or hooks. Before/after source equality,
working-tree identity and non-creation of Fleet state are separate evidence gates.
All original acquisitions, reports and failed validation attempts are retained.

The first private postprocessor incorrectly applied strict Python-mode validation
to decoded JSON arrays. The same retained bytes subsequently passed strict JSON
and JSON-Schema validation; no target command was repeated or output rewritten.

The first focused regression trial wrote JUnit containing61 passes/25.887s, but
its outer30-second watchdog still observed a running process and killed it
(exit-9). Passing JUnit is not normal process/cleanup completion. A separately
authorized new attempt keeps the same61 cases, assertions and inner CLI timeouts,
using a300-second total-process watchdog. That new trial passed61 cases in22.993s,
normally exited0 in27.410s, and left its owned group absent. Its exact61 identities
match the original JUnit and all556 product source/README/guide inputs stayed
unchanged. These are61 distinct regression cases, not122 cases or six project
business-test successes. Independent artifact/document readback passed at
15:42:41 UTC; verdict SHA256
`9935fac3f6082eb976e47871648795d69f0a9f5556ad1efac151bae8814a6329`.
The original1201 retained entries and new462-entry regression closure remain
unchanged. A first verifier-script assumption about the read-only Git version
event failed and is preserved; its narrowly corrected readback passed without
another target observation or test run. Git delivery is separate and pending at
this publication record.

These observations complement the six **generated** Docker observations in
[BASELINE_COHORT.md](BASELINE_COHORT.md); they do not replace or inflate that
separate evidence. Native P0 finalization remains NOT_GO; the24-task campaign,
three real cold starts and wider Provider/Harness qualification remain incomplete.
No GitHub Actions success or remote delivery is claimed before readback.
