PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT CHECK (id != 1 OR deleted_at IS NULL),
    CHECK ((id = 1) = (username = 'admin'))
) STRICT;

CREATE TABLE operators (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    mission TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
) STRICT;

CREATE INDEX operators_by_registered_owner ON operators(owner_user_id)
    WHERE deleted_at IS NULL;

CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'paused', 'completed', 'revoked')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    parent_goal_id INTEGER REFERENCES goals(id)
) STRICT;

CREATE INDEX goals_by_parent ON goals(parent_goal_id);

CREATE TABLE goal_revisions (
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    title TEXT NOT NULL,
    desired_outcome TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration TEXT CHECK (duration IN ('one_time', 'standing')),
    assessment_type TEXT CHECK (assessment_type IN ('objective', 'judgment', 'mixed')),
    success_criteria TEXT,
    measurement_plan TEXT,
    duration_days INTEGER CHECK (duration_days > 0),
    target_distinct_dates INTEGER CHECK (target_distinct_dates > 0),
    window_start TEXT,
    PRIMARY KEY (goal_id, revision)
) STRICT, WITHOUT ROWID;

CREATE TABLE goal_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TEXT,
    completion_granted_at TEXT,
    completion_grant_id INTEGER AS (CASE WHEN completion_granted_at IS NOT NULL THEN id END)
) STRICT;

CREATE UNIQUE INDEX one_active_operator_per_goal
    ON goal_assignments (goal_id)
    WHERE released_at IS NULL;

CREATE INDEX open_assignments_by_operator ON goal_assignments(operator_id)
    WHERE released_at IS NULL;

CREATE UNIQUE INDEX assignment_completion_grant ON goal_assignments(goal_id, completion_grant_id);

-- Begin goal event schema
CREATE TABLE goal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('message', 'observation', 'completion')),
    actor_user_id INTEGER REFERENCES users(id),
    message_role TEXT CHECK (message_role IN ('user', 'operator')),
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    retry_key TEXT,
    statement_evidence_id INTEGER,
    completion_grant_id INTEGER,
    -- Only observations can serve as evidence, and only completions can own citations.
    evidence_id INTEGER AS (CASE WHEN kind = 'observation' THEN id END),
    decision_id INTEGER AS (CASE WHEN kind = 'completion' THEN id END),
    UNIQUE (goal_id, evidence_id),
    UNIQUE (goal_id, decision_id),
    UNIQUE (revision, evidence_id),
    CHECK ((kind = 'message') = (message_role IS NOT NULL)),
    CHECK (kind != 'message' OR actor_user_id IS NULL),
    CHECK ((statement_evidence_id IS NOT NULL) + (completion_grant_id IS NOT NULL) = (kind = 'completion')),
    CHECK (completion_grant_id IS NULL OR
        (actor_user_id IS NULL AND json_type(payload, '$.rationale') IS 'text')),
    FOREIGN KEY (goal_id, completion_grant_id) REFERENCES goal_assignments(goal_id, completion_grant_id),
    FOREIGN KEY (goal_id, statement_evidence_id) REFERENCES goal_events(goal_id, evidence_id),
    FOREIGN KEY (revision, statement_evidence_id) REFERENCES goal_events(revision, evidence_id),
    FOREIGN KEY (goal_id, revision) REFERENCES goal_revisions (goal_id, revision)
) STRICT;

CREATE UNIQUE INDEX one_completion_per_revision ON goal_events(goal_id, revision)
    WHERE kind = 'completion';

CREATE UNIQUE INDEX observation_retry ON goal_events(goal_id, retry_key, coalesce(actor_user_id, 0))
    WHERE kind = 'observation';

CREATE INDEX observations_by_goal ON goal_events(goal_id, id)
    WHERE kind = 'observation';

CREATE TABLE completion_citations (
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    decision_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL,
    FOREIGN KEY (goal_id, decision_id) REFERENCES goal_events(goal_id, decision_id),
    FOREIGN KEY (goal_id, evidence_id) REFERENCES goal_events(goal_id, evidence_id),
    PRIMARY KEY (decision_id, evidence_id)
) STRICT, WITHOUT ROWID;
-- End goal event schema

INSERT INTO users (username, display_name) VALUES ('admin', 'admin');

CREATE TRIGGER keep_system_admin BEFORE DELETE ON users WHEN OLD.id = 1
BEGIN
    SELECT RAISE(ABORT, 'The system user admin cannot be deleted.');
END;
PRAGMA user_version = 8;
