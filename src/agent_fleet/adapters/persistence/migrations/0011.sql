CREATE TABLE evaluation_campaigns (
    campaign_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    manifest_sha256 TEXT NOT NULL UNIQUE,
    registered_at TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    UNIQUE (manifest_id, revision)
);

CREATE TABLE evaluation_slots (
    campaign_id TEXT NOT NULL REFERENCES evaluation_campaigns(campaign_id),
    case_id TEXT NOT NULL,
    repetition INTEGER NOT NULL CHECK (repetition BETWEEN 0 AND 2),
    PRIMARY KEY (campaign_id, case_id, repetition)
);

CREATE TABLE evaluation_reservations (
    attempt_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    repetition INTEGER NOT NULL,
    idempotency_sha256 TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY (campaign_id, case_id, repetition)
        REFERENCES evaluation_slots(campaign_id, case_id, repetition),
    UNIQUE (campaign_id, case_id, repetition),
    UNIQUE (campaign_id, idempotency_sha256),
    UNIQUE (campaign_id, attempt_id)
);

CREATE TABLE evaluation_outcomes (
    outcome_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    campaign_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY (campaign_id, attempt_id)
        REFERENCES evaluation_reservations(campaign_id, attempt_id)
);
