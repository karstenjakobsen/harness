-- Historical layouts used to test supported workspace upgrades.
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operators (
    id INTEGER PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    mission TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'paused', 'completed', 'revoked')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goal_revisions (
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    title TEXT NOT NULL,
    desired_outcome TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (goal_id, revision)
);

CREATE TABLE IF NOT EXISTS goal_assignments (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_operator_per_goal
    ON goal_assignments (goal_id)
    WHERE released_at IS NULL;

INSERT INTO users (id, display_name) VALUES ('local', 'Local user')
    ON CONFLICT (id) DO NOTHING;

PRAGMA user_version = 1;

ALTER TABLE goals ADD COLUMN deleted_at TEXT;

PRAGMA user_version = 2;

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

ALTER TABLE goals ADD COLUMN parent_goal_id INTEGER REFERENCES goals(id);
CREATE INDEX goals_by_parent ON goals(parent_goal_id);

ALTER TABLE goal_revisions ADD COLUMN duration_days INTEGER
    CHECK (duration_days IS NULL OR
           (typeof(duration_days) = 'integer' AND duration_days > 0));

CREATE UNIQUE INDEX one_completion_per_revision ON goal_events(goal_id, revision)
    WHERE kind = 'completion';

PRAGMA user_version = 4;
