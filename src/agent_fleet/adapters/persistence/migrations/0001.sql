CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    canonical_root TEXT NOT NULL UNIQUE,
    data_json TEXT NOT NULL
);

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    status TEXT NOT NULL,
    stage TEXT,
    data_json TEXT NOT NULL
);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    data_json TEXT NOT NULL
);

CREATE TABLE agent_instances (
    agent_instance_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    role TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE run_events (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    run_id TEXT REFERENCES runs(run_id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE UNIQUE INDEX run_events_run_sequence
ON run_events(run_id, sequence)
WHERE run_id IS NOT NULL;

CREATE UNIQUE INDEX run_events_project_sequence
ON run_events(project_id, sequence)
WHERE run_id IS NULL;

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    run_id TEXT REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE tool_intents (
    intent_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    idempotency_key TEXT NOT NULL,
    intent_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_request_id TEXT,
    data_json TEXT NOT NULL,
    UNIQUE(run_id, idempotency_key)
);

CREATE TABLE approvals (
    request_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL UNIQUE REFERENCES tool_intents(intent_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    status TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE capability_grants (
    grant_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE REFERENCES approvals(request_id),
    intent_id TEXT NOT NULL UNIQUE REFERENCES tool_intents(intent_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    remaining_uses INTEGER NOT NULL CHECK (remaining_uses >= 0),
    data_json TEXT NOT NULL
);

CREATE TABLE resource_leases (
    lease_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    status TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE INDEX resource_leases_active ON resource_leases(status, run_id);
