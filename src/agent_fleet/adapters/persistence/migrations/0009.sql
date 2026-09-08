CREATE TABLE model_configuration_audit (
    sequence INTEGER PRIMARY KEY CHECK(sequence > 0),
    audit_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE model_profile_versions (
    name TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    removed INTEGER NOT NULL CHECK(removed IN (0,1)),
    record_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    audit_sequence INTEGER NOT NULL REFERENCES model_configuration_audit(sequence),
    PRIMARY KEY(name,revision)
);
CREATE TABLE model_profile_heads (
    name TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    FOREIGN KEY(name,revision) REFERENCES model_profile_versions(name,revision)
);
CREATE TABLE project_model_selection_versions (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    record_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    audit_sequence INTEGER NOT NULL REFERENCES model_configuration_audit(sequence),
    PRIMARY KEY(project_id,revision)
);
CREATE TABLE project_model_selection_heads (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    revision INTEGER NOT NULL,
    FOREIGN KEY(project_id,revision) REFERENCES project_model_selection_versions(project_id,revision)
);
CREATE TABLE run_model_bindings (
    root_run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    bindings_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    audit_sequence INTEGER NOT NULL REFERENCES model_configuration_audit(sequence)
);
