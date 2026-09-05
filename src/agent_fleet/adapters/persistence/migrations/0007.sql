CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    repository_identity TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    next_turn_sequence INTEGER NOT NULL CHECK (next_turn_sequence BETWEEN 1 AND 1001),
    active_turn_id TEXT REFERENCES conversation_turns(turn_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_event_id TEXT NOT NULL REFERENCES run_events(event_id),
    data_json TEXT NOT NULL
);

CREATE INDEX conversations_project_recent
ON conversations(project_id, repository_identity, updated_at, conversation_id);

CREATE TABLE conversation_turns (
    turn_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 1000),
    submission_key TEXT NOT NULL,
    submission_sha256 TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    status TEXT NOT NULL CHECK (status IN (
        'running', 'waiting', 'delivered', 'failed', 'cancelled', 'recovery_required'
    )),
    owner_generation INTEGER NOT NULL CHECK (owner_generation >= 1),
    active_claim_id TEXT REFERENCES conversation_turn_claims(claim_id),
    binding_json TEXT NOT NULL,
    record_event_id TEXT NOT NULL REFERENCES run_events(event_id),
    data_json TEXT NOT NULL,
    UNIQUE(conversation_id, sequence),
    UNIQUE(conversation_id, submission_key)
);

CREATE UNIQUE INDEX conversation_one_active_turn
ON conversation_turns(conversation_id)
WHERE status IN ('running', 'waiting', 'recovery_required');

CREATE TABLE conversation_turn_claims (
    claim_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    turn_id TEXT NOT NULL REFERENCES conversation_turns(turn_id) DEFERRABLE INITIALLY DEFERRED,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'released', 'fenced')),
    claimed_at TEXT NOT NULL,
    released_at TEXT,
    record_event_id TEXT NOT NULL REFERENCES run_events(event_id),
    data_json TEXT NOT NULL,
    UNIQUE(turn_id, generation)
);

CREATE UNIQUE INDEX conversation_one_active_claim
ON conversation_turn_claims(turn_id) WHERE status = 'active';
