CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT CHECK (id != 'admin' OR deleted_at IS NULL)
);

CREATE TABLE IF NOT EXISTS operators (
    id INTEGER PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    mission TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS operators_by_registered_owner ON operators(owner_user_id)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'paused', 'completed', 'revoked')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    parent_goal_id INTEGER REFERENCES goals(id)
);

CREATE INDEX IF NOT EXISTS goals_by_parent ON goals(parent_goal_id);

CREATE TABLE IF NOT EXISTS goal_revisions (
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    title TEXT NOT NULL,
    desired_outcome TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration TEXT CHECK (duration IN ('one_time', 'standing')),
    assessment_type TEXT CHECK (assessment_type IN ('objective', 'judgment', 'mixed')),
    success_criteria TEXT,
    measurement_plan TEXT,
    duration_days INTEGER CHECK (
        duration_days IS NULL OR (typeof(duration_days) = 'integer' AND duration_days > 0)
    ),
    target_distinct_dates INTEGER CHECK (
        target_distinct_dates IS NULL OR (typeof(target_distinct_dates) = 'integer' AND target_distinct_dates > 0)
    ),
    window_start TEXT,
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

CREATE TABLE IF NOT EXISTS goal_events (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    retry_key TEXT,
    statement_evidence_id INTEGER REFERENCES goal_events(id),
    FOREIGN KEY (goal_id, revision) REFERENCES goal_revisions (goal_id, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_completion_per_revision ON goal_events(goal_id, revision)
    WHERE kind = 'completion';

CREATE UNIQUE INDEX IF NOT EXISTS observation_retry ON goal_events(goal_id, actor, retry_key)
    WHERE kind = 'observation';

CREATE INDEX IF NOT EXISTS observations_by_goal ON goal_events(goal_id, id)
    WHERE kind = 'observation';

CREATE TABLE IF NOT EXISTS completion_citations (
    decision_id INTEGER NOT NULL REFERENCES goal_events(id),
    evidence_id INTEGER NOT NULL REFERENCES goal_events(id),
    PRIMARY KEY (decision_id, evidence_id)
);

INSERT INTO users (id, display_name) VALUES ('admin', 'admin')
    ON CONFLICT (id) DO NOTHING;

CREATE TRIGGER IF NOT EXISTS keep_system_admin BEFORE DELETE ON users WHEN OLD.id = 'admin'
BEGIN
    SELECT RAISE(ABORT, 'The system user admin cannot be deleted.');
END;
PRAGMA user_version = 6;
