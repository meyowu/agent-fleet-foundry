CREATE TABLE organization_events (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    record_kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    previous_event_sha256 TEXT,
    event_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_json TEXT NOT NULL,
    UNIQUE(project_id, sequence)
);
CREATE INDEX organization_events_record ON organization_events(record_kind,record_id,sequence);
CREATE TABLE organization_trees (
    tree_sha256 TEXT PRIMARY KEY,
    audit_event_id TEXT NOT NULL REFERENCES organization_events(event_id),
    data_json TEXT NOT NULL
);
CREATE TABLE organization_versions (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    version INTEGER NOT NULL CHECK(version >= 0),
    predecessor_version INTEGER,
    tree_sha256 TEXT NOT NULL REFERENCES organization_trees(tree_sha256),
    config_snapshot_sha256 TEXT NOT NULL,
    operation_id TEXT,
    audit_event_id TEXT NOT NULL REFERENCES organization_events(event_id),
    data_json TEXT NOT NULL,
    PRIMARY KEY(project_id,version),
    UNIQUE(operation_id)
);
CREATE TABLE organization_heads (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    revision INTEGER NOT NULL CHECK(revision >= 0),
    tree_sha256 TEXT NOT NULL REFERENCES organization_trees(tree_sha256),
    config_snapshot_sha256 TEXT NOT NULL,
    project_sha256 TEXT NOT NULL,
    pending_operation_id TEXT,
    audit_event_id TEXT NOT NULL REFERENCES organization_events(event_id),
    data_json TEXT NOT NULL,
    FOREIGN KEY(project_id,revision) REFERENCES organization_versions(project_id,version)
);
CREATE TABLE organization_proposals (
    proposal_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    source_run_id TEXT NOT NULL REFERENCES runs(run_id),
    base_revision INTEGER NOT NULL,
    proposal_sha256 TEXT NOT NULL,
    before_tree_sha256 TEXT NOT NULL REFERENCES organization_trees(tree_sha256),
    after_tree_sha256 TEXT NOT NULL REFERENCES organization_trees(tree_sha256),
    created_at TEXT NOT NULL,
    audit_event_id TEXT NOT NULL REFERENCES organization_events(event_id),
    data_json TEXT NOT NULL,
    FOREIGN KEY(project_id,base_revision) REFERENCES organization_versions(project_id,version)
);
CREATE TABLE organization_operations (
    operation_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES organization_proposals(proposal_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    base_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('prepared','committed','aborted','recovery_required')),
    audit_event_id TEXT NOT NULL REFERENCES organization_events(event_id),
    data_json TEXT NOT NULL
);
CREATE UNIQUE INDEX organization_one_pending ON organization_operations(project_id) WHERE status IN ('prepared','recovery_required');
CREATE UNIQUE INDEX organization_one_applied_proposal ON organization_operations(proposal_id) WHERE status='committed';
CREATE TABLE organization_run_admissions (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision INTEGER NOT NULL,
    parent_run_id TEXT REFERENCES runs(run_id),
    run_binding_sha256 TEXT NOT NULL,
    audit_event_id TEXT NOT NULL REFERENCES organization_events(event_id),
    data_json TEXT NOT NULL,
    FOREIGN KEY(project_id,revision) REFERENCES organization_versions(project_id,version)
);
