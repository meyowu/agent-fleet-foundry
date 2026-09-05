CREATE TABLE runtime_budget_owners (
    owner_run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    limits_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE runtime_budget_runs (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    owner_run_id TEXT NOT NULL REFERENCES runtime_budget_owners(owner_run_id)
);

CREATE TABLE runtime_attempts (
    attempt_id TEXT PRIMARY KEY,
    owner_run_id TEXT NOT NULL REFERENCES runtime_budget_owners(owner_run_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_instance_id TEXT NOT NULL REFERENCES agent_instances(agent_instance_id),
    status TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX runtime_attempts_owner ON runtime_attempts(owner_run_id);
CREATE UNIQUE INDEX runtime_attempts_active_agent ON runtime_attempts(agent_instance_id)
WHERE status = 'running';

CREATE TABLE runtime_model_requests (
    attempt_id TEXT NOT NULL REFERENCES runtime_attempts(attempt_id),
    request_sequence INTEGER NOT NULL CHECK(request_sequence > 0),
    data_json TEXT NOT NULL,
    PRIMARY KEY(attempt_id, request_sequence)
);

CREATE TABLE runtime_tool_batches (
    attempt_id TEXT NOT NULL REFERENCES runtime_attempts(attempt_id),
    batch_sequence INTEGER NOT NULL CHECK(batch_sequence > 0),
    calls_sha256 TEXT NOT NULL,
    tool_calls INTEGER NOT NULL CHECK(tool_calls > 0),
    PRIMARY KEY(attempt_id, batch_sequence)
);

CREATE TABLE runtime_simulated_steps (
    attempt_id TEXT PRIMARY KEY REFERENCES runtime_attempts(attempt_id)
);
