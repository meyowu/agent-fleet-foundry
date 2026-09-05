CREATE TABLE fleet_graphs (
    parent_run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    plan_sha256 TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    status TEXT NOT NULL,
    driver_generation INTEGER NOT NULL CHECK(driver_generation >= 0),
    driver_claim_id TEXT,
    immutable_manifest_json TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE fleet_graph_nodes (
    parent_run_id TEXT NOT NULL REFERENCES fleet_graphs(parent_run_id),
    node_id TEXT NOT NULL,
    iteration INTEGER NOT NULL CHECK(iteration = 0),
    child_run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    child_task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
    revision INTEGER NOT NULL CHECK(revision >= 0),
    status TEXT NOT NULL,
    binding_json TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY(parent_run_id, node_id, iteration)
);

CREATE TABLE fleet_graph_driver_claims (
    claim_id TEXT PRIMARY KEY,
    parent_run_id TEXT NOT NULL REFERENCES fleet_graphs(parent_run_id),
    generation INTEGER NOT NULL CHECK(generation > 0),
    plan_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    released_at TEXT,
    data_json TEXT NOT NULL,
    UNIQUE(parent_run_id, generation)
);
