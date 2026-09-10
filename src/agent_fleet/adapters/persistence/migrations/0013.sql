CREATE TABLE baseline_executions (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'baseline_*'),
    baseline_id TEXT NOT NULL UNIQUE CHECK (baseline_id = record_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 262144)
);
CREATE TABLE baseline_reviews (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'breview_*'),
    baseline_id TEXT NOT NULL UNIQUE REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision = 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 131072)
);
CREATE TABLE baseline_authorizations (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'bauth_*'),
    baseline_id TEXT NOT NULL UNIQUE REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 16384)
);
CREATE TABLE baseline_owner_claims (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'bclaim_*'),
    baseline_id TEXT NOT NULL UNIQUE REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision = 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 16384)
);
CREATE TABLE baseline_dispatch_claims (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'bexec_*'),
    baseline_id TEXT NOT NULL UNIQUE REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision = 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 262144)
);
CREATE TABLE baseline_resource_leases (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'blease_*'),
    baseline_id TEXT NOT NULL REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    kind TEXT NOT NULL CHECK (kind IN ('workspace', 'sandbox', 'execution')),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 262144),
    UNIQUE (baseline_id, kind)
);
CREATE TABLE baseline_command_observations (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'bobs_*'),
    baseline_id TEXT NOT NULL UNIQUE REFERENCES baseline_executions(baseline_id),
    execution_id TEXT NOT NULL UNIQUE CHECK (execution_id GLOB 'bexec_*'),
    revision INTEGER NOT NULL CHECK (revision = 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 131072),
    UNIQUE (baseline_id, execution_id)
);
CREATE TABLE baseline_reports (
    record_id TEXT PRIMARY KEY CHECK (record_id GLOB 'brpt_*'),
    baseline_id TEXT NOT NULL REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision = 0),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 262144)
);
CREATE TABLE baseline_cleanup_receipts (
    record_id TEXT PRIMARY KEY CHECK (length(record_id) = 64),
    baseline_id TEXT NOT NULL REFERENCES baseline_executions(baseline_id),
    revision INTEGER NOT NULL CHECK (revision = 0),
    record_sha256 TEXT NOT NULL CHECK (record_sha256 = record_id),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 262144)
);
CREATE TABLE baseline_events (
    baseline_id TEXT NOT NULL REFERENCES baseline_executions(baseline_id),
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    kind TEXT NOT NULL CHECK (kind IN ('cleanup_claimed')),
    scope_sha256 TEXT NOT NULL CHECK (length(scope_sha256) = 64),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256) = 64),
    payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) <= 262144),
    PRIMARY KEY (baseline_id, sequence)
);
CREATE INDEX baseline_reports_owner ON baseline_reports(baseline_id);
CREATE INDEX baseline_cleanup_receipts_owner ON baseline_cleanup_receipts(baseline_id);
CREATE UNIQUE INDEX baseline_events_scope ON baseline_events(baseline_id, scope_sha256);
