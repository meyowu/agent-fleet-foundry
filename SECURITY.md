# Security

Agent Fleet Foundry separates proposals, authorization, execution and completion evidence.
Read [the threat model](docs/SECURITY_MODEL.md), [data disclosure](docs/DATA_HANDLING.md)
and [acceptance ledger](docs/MVP_ACCEPTANCE.md) before using it on sensitive code.
Docker is not a VM boundary against a malicious host/kernel/daemon. FakeSandbox
does not execute; local-unsafe is explicitly non-isolating. There is no implicit
isolated-to-host fallback. Models cannot self-approve or change protected authority.

## Reporting

Do not publish credentials, private source, executable exploit payloads against
unrelated systems or raw state dumps in public issues. Use GitHub private
vulnerability reporting **if enabled**, or an existing verified private maintainer
channel. No monitored email address, disclosure SLA or bug-bounty program is
claimed. A sanitized report should identify the exact commit, platform, smallest
reproduction, expected/observed permission boundary and affected artifact IDs.

## Release checklist

- [ ] Exact frozen source/test identity, default/static/schema checks and package bytes recorded.
- [ ] Path/link/index escape, protected mutation, command injection and deferred-batch negatives pass.
- [ ] Broker ceilings, approval ownership, exact persistent trust, revocation and single dispatch pass.
- [ ] Real Docker effective user/mount/network/capability/environment/resource inspection passes.
- [ ] Registered raw/encoded secret and outside-workspace sentinel checks pass without leakage.
- [ ] Crash/cancellation recovery retains uncertain ownership and removes only exact owned resources.
- [ ] Independent Verifier mutation cannot enter the accepted patch; evidence gaps remain visible.
- [ ] FleetPatch full-tree atomicity, old-generation refusal, rollback and recovery cut points pass.
- [ ] Fresh wheel/sdist and installed public quickstart, upgrade and platform checks are recorded.
- [ ] Actual manually authorized live-provider canary is recorded, or public release stays blocked.
- [ ] Owner license authorization is recorded before public OSS publication.

These are release-run checkboxes, not a claim that every item has passed. The
ledger maps all53 specified negative cases and S01–S11 to concrete tests/results.
Each release must copy/record its own verdict and limitations.

## Reproducible adversarial replay

After explicit contributor dependency setup, from the checkout:

```bash
uv run --offline python scripts/verify_adversarial.py --output /absolute/path/to/new-offline-audit
uv run --offline python scripts/verify_adversarial.py --docker \
  --image agent-fleet-runner:0.1.0-py314-v1 --output /absolute/path/to/new-docker-audit
```

The script refuses existing/relative output destinations, uses only disposable
fixtures and writes JUnit plus structured selection/count/hash evidence. Docker
needs both explicit arguments and an already-local runner; it never builds/pulls,
uses provider keys or globally prunes resources. On Colima choose a new directory
under a VM-shared parent. It replays named automated malicious-input, sentinel,
authority and recovery cases; it is not a human penetration audit or hostile-host
proof. A nonzero exit or unexpected skip is not a release pass. On Linux, five
exact Darwin-only metadata cases are reported as expected platform skips, never
as executed coverage; macOS must exercise them separately. Preserve failed fixtures for
diagnosis; reconcile exact owned Run resources instead of broad deletion.
