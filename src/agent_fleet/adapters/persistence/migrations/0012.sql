CREATE TABLE evaluation_executions (
    attempt_id TEXT PRIMARY KEY REFERENCES evaluation_reservations(attempt_id),
    campaign_id TEXT NOT NULL,
    root_run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    record_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY (campaign_id, attempt_id) REFERENCES evaluation_reservations(campaign_id, attempt_id)
);

CREATE INDEX evaluation_executions_campaign ON evaluation_executions(campaign_id);
