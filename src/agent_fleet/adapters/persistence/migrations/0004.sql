CREATE TABLE capability_grants_v4 (
    grant_id TEXT PRIMARY KEY,
    request_id TEXT UNIQUE REFERENCES approvals(request_id),
    intent_id TEXT NOT NULL UNIQUE REFERENCES tool_intents(intent_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    remaining_uses INTEGER CHECK (remaining_uses IS NULL OR remaining_uses BETWEEN 0 AND 10000),
    data_json TEXT NOT NULL
);

INSERT INTO capability_grants_v4
    (grant_id, request_id, intent_id, run_id, remaining_uses, data_json)
SELECT grant_id, request_id, intent_id, run_id, remaining_uses, data_json
FROM capability_grants;

DROP TABLE capability_grants;

ALTER TABLE capability_grants_v4 RENAME TO capability_grants;

CREATE INDEX capability_grants_run ON capability_grants(run_id);

CREATE TABLE tool_dispatch_claims (
    intent_id TEXT PRIMARY KEY REFERENCES tool_intents(intent_id),
    intent_hash TEXT NOT NULL CHECK (
        length(intent_hash) = 64 AND intent_hash NOT GLOB '*[^0-9a-f]*'
    ),
    claimed_at TEXT NOT NULL
);
