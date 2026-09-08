# ADR 0008: Local read-only dashboard

Status: accepted; release evidence is in the Session-first ExecPlan.

## Context

A foreground CoS session can own an adaptive group while another terminal needs
to observe it. A second executor or a dashboard that interprets model messages as
successful work would undermine the control plane and evidence boundary.

## Decision

Ship packaged semantic HTML/CSS/JavaScript from the existing Python CLI, using
only an IPv4 loopback listener. The browser reads the same persisted project,
Run, child, agent, model-selection, budget, approval and evidence records. It has
no action routes and never launches a worker or provider call. No new hosted
service, account system, frontend dependency chain or remote asset is required.

A fresh random bearer token is displayed once in the trusted terminal. The user
pastes it into a password input; only page memory retains it. Every API request
requires it. Exact Host/Origin and fetch-site checks, no CORS, no cookies, a
restrictive local-only CSP, no framing, no HTTP logs and no caching reduce browser
cross-origin exposure. Repository text is rendered with textContent, never HTML.
Stopping the foreground server revokes the token and closes only its owned sockets.

SQLite observation uses query-only bounded snapshot reads, not automatic state
initialization or migration. Existing evidence/model services independently
check content identities. Their observations are not falsely labeled a globally
atomic snapshot. Each root/child event source retains its own sequence cursor;
bounded fetch-SSE reconnects, deduplicates IDs and explicitly resets invalid
cursors. The browser distinguishes disconnected/stale state from live updates.

Request lines, headers, bodies, concurrent connections, query work, frames,
artifacts, stream bytes and lifetime are bounded. A per-read socket timeout alone
is insufficient against slow headers, so header parsing has an absolute timer
and pre-parser byte limits. A successful stream handshake alone is insufficient
to establish liveness, so a separate seven-second receive watchdog controls the
live indicator. Independent probes reproduced both former failure modes and
verify the enforced boundaries.

## Alternatives

Native EventSource with a token in its URL would leak a capability through URL
history/logs; fetch-SSE supplies an Authorization header instead. A dashboard
backend that starts work or grants approvals would duplicate security-critical
ownership paths; those controls remain in the trusted terminal. A hosted UI with
user accounts would create a materially different disclosure and threat model.

## Consequences

The dashboard provides observation, not unattended execution or remote-team
administration. It cannot protect a token from a hostile same-user process or
browser extension. A stopped dashboard leaves separately owned task execution
alone. Fake evidence remains simulated. Bounded history/artifact views explicitly
omit earlier/larger data; the CLI remains the complete inspection surface.
