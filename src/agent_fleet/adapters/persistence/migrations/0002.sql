CREATE TABLE agent_instances_v2 (
    agent_instance_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    task_id TEXT REFERENCES tasks(task_id),
    role TEXT NOT NULL,
    data_json TEXT NOT NULL,
    CHECK (task_id IS NOT NULL OR role = 'cos')
);

INSERT INTO agent_instances_v2(agent_instance_id, run_id, task_id, role, data_json)
SELECT agent_instance_id, run_id, task_id, role, data_json
FROM agent_instances;

DROP TABLE agent_instances;

ALTER TABLE agent_instances_v2 RENAME TO agent_instances;
