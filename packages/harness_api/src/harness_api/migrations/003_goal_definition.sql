ALTER TABLE goal_revisions ADD COLUMN duration TEXT
    CHECK (duration IN ('one_time', 'standing'));
ALTER TABLE goal_revisions ADD COLUMN assessment_type TEXT
    CHECK (assessment_type IN ('objective', 'judgment', 'mixed'));
ALTER TABLE goal_revisions ADD COLUMN success_criteria TEXT;
ALTER TABLE goal_revisions ADD COLUMN measurement_plan TEXT;

CREATE TABLE goal_events (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    FOREIGN KEY (goal_id, revision) REFERENCES goal_revisions (goal_id, revision)
);

PRAGMA user_version = 3;
