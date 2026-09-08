CREATE TABLE plan_review_versions (
    root_run_id TEXT NOT NULL REFERENCES runs(run_id),
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'consumed')),
    checkpoint_sha256 TEXT NOT NULL,
    binding_sha256 TEXT NOT NULL,
    audit_event_id TEXT NOT NULL UNIQUE REFERENCES run_events(event_id),
    data_json TEXT NOT NULL,
    PRIMARY KEY(root_run_id, revision)
);
CREATE TABLE plan_review_heads (
    root_run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    revision INTEGER NOT NULL,
    FOREIGN KEY(root_run_id, revision) REFERENCES plan_review_versions(root_run_id, revision)
);
