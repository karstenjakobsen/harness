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

CREATE TABLE goal_definition_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    goal_id INTEGER REFERENCES goals(id),
    action TEXT NOT NULL CHECK (action IN ('create_goal', 'create_subgoal', 'revise_goal')),
    granted_at TEXT NOT NULL,
    withdrawn_at TEXT,
    CHECK ((action = 'create_goal') = (goal_id IS NULL))
) STRICT;

CREATE TABLE goal_creation_retries (
    grant_id INTEGER NOT NULL REFERENCES goal_definition_grants(id),
    retry_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    goal_id INTEGER NOT NULL UNIQUE REFERENCES goals(id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'active')),
    PRIMARY KEY (grant_id, retry_key)
) STRICT, WITHOUT ROWID;

CREATE TABLE work_delegation_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    granted_at TEXT NOT NULL,
    withdrawn_at TEXT
) STRICT;

CREATE TABLE operator_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    completion_grant_id INTEGER REFERENCES goal_assignments(id),
    definition_grant_id INTEGER REFERENCES goal_definition_grants(id)
        CHECK (definition_grant_id IS NULL OR completion_grant_id IS NULL),
    delegation_grant_id INTEGER REFERENCES work_delegation_grants(id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL DEFAULT 'unfinished'
        CHECK (outcome IN ('unfinished', 'succeeded', 'failed')),
    CHECK ((outcome = 'unfinished') = (finished_at IS NULL)),
    CHECK ((completion_grant_id IS NOT NULL) + (definition_grant_id IS NOT NULL)
        + (delegation_grant_id IS NOT NULL) <= 1)
) STRICT;

CREATE TABLE run_calls (
    run_id INTEGER NOT NULL REFERENCES operator_runs(id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    tool TEXT NOT NULL CHECK (tool IN (
        'list_goals', 'get_goal_tree', 'get_goal_progress', 'complete_goal', 'create_goal', 'create_subgoal', 'revise_goal',
        'get_goal_activity', 'get_run', 'list_skills', 'read_skill', 'delegate_work'
    )),
    -- Requested IDs can be invalid or belong to a different owner.
    target_goal_id INTEGER CHECK (target_goal_id > 0),
    target_skill_id TEXT CHECK (target_skill_id IS NULL OR tool = 'read_skill'),
    target_revision INTEGER CHECK (target_revision > 0),
    target_run_id INTEGER CHECK (
        target_run_id IS NULL OR (target_run_id > 0 AND tool = 'get_run')
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL DEFAULT 'unfinished'
        CHECK (outcome IN ('unfinished', 'returned', 'denied', 'failed')),
    committed_event_id INTEGER UNIQUE,
    retrieved_event_id INTEGER,
    resolved_goal_id INTEGER REFERENCES goals(id)
        CHECK (resolved_goal_id IS NULL OR resolved_goal_id IS target_goal_id),
    returned_history TEXT CHECK (json_type(returned_history) = 'object'),
    CHECK ((outcome = 'unfinished') = (finished_at IS NULL)),
    CHECK ((returned_history IS NOT NULL) =
        (outcome = 'returned' AND tool IN ('get_goal_activity', 'get_run'))),
    CHECK ((committed_event_id IS NOT NULL) + (retrieved_event_id IS NOT NULL) <= 1),
    CHECK ((committed_event_id IS NULL AND retrieved_event_id IS NULL) OR
        (tool = 'complete_goal' AND target_goal_id IS NOT NULL)),
    FOREIGN KEY (target_goal_id, committed_event_id) REFERENCES goal_events(goal_id, decision_id),
    FOREIGN KEY (target_goal_id, retrieved_event_id) REFERENCES goal_events(goal_id, decision_id),
    PRIMARY KEY (run_id, sequence)
) STRICT, WITHOUT ROWID;

CREATE INDEX run_calls_by_resolved_goal ON run_calls(resolved_goal_id)
    WHERE resolved_goal_id IS NOT NULL;

CREATE TABLE run_call_goals (
    run_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    position INTEGER NOT NULL,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    revision INTEGER,
    status TEXT CHECK (status IN ('draft', 'active', 'paused', 'completed', 'revoked')),
    observation_ids TEXT NOT NULL CHECK (json_type(observation_ids) = 'array'),
    decision_event_id INTEGER,
    cited_evidence_ids TEXT CHECK (json_type(cited_evidence_ids) = 'array'),
    statement_evidence_id INTEGER,
    CHECK ((decision_event_id IS NULL) = (cited_evidence_ids IS NULL)),
    CHECK (statement_evidence_id IS NULL OR decision_event_id IS NOT NULL),
    PRIMARY KEY (run_id, sequence, position),
    FOREIGN KEY (run_id, sequence) REFERENCES run_calls(run_id, sequence),
    FOREIGN KEY (goal_id, revision) REFERENCES goal_revisions(goal_id, revision),
    FOREIGN KEY (goal_id, decision_event_id) REFERENCES goal_events(goal_id, decision_id),
    FOREIGN KEY (goal_id, statement_evidence_id) REFERENCES goal_events(goal_id, evidence_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX run_call_goals_by_goal ON run_call_goals(goal_id);

CREATE TABLE run_call_revisions (
    run_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    goal_id INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('committed', 'retrieved', 'unchanged')),
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id, sequence) REFERENCES run_calls(run_id, sequence),
    FOREIGN KEY (goal_id, revision) REFERENCES goal_revisions(goal_id, revision)
) STRICT, WITHOUT ROWID;

CREATE UNIQUE INDEX one_committing_call_per_revision
    ON run_call_revisions(goal_id, revision) WHERE kind = 'committed';
CREATE INDEX run_call_revisions_by_goal ON run_call_revisions(goal_id);

CREATE TABLE skill_revisions (
    id INTEGER PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    skill_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    manifest TEXT NOT NULL,
    instructions TEXT NOT NULL,
    source_path TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    discoverable INTEGER NOT NULL DEFAULT 0 CHECK (discoverable IN (0, 1)),
    UNIQUE (owner_user_id, skill_key, revision)
) STRICT;

CREATE UNIQUE INDEX current_skill ON skill_revisions(owner_user_id, skill_key)
    WHERE discoverable = 1;

CREATE TABLE run_call_skills (
    run_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    position INTEGER NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES skill_revisions(id),
    PRIMARY KEY (run_id, sequence, position),
    UNIQUE (run_id, sequence, snapshot_id),
    FOREIGN KEY (run_id, sequence) REFERENCES run_calls(run_id, sequence)
) STRICT, WITHOUT ROWID;

CREATE INDEX calls_by_skill_revision ON run_call_skills(snapshot_id);

CREATE TABLE work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    goal_id INTEGER NOT NULL,
    goal_revision INTEGER NOT NULL,
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    brief TEXT NOT NULL,
    source_path TEXT,
    base_sha TEXT,
    created_at TEXT NOT NULL,
    CHECK ((source_path IS NULL) = (base_sha IS NULL)),
    FOREIGN KEY (goal_id, goal_revision) REFERENCES goal_revisions(goal_id, revision)
) STRICT;

CREATE INDEX work_items_by_goal ON work_items(goal_id, id);

CREATE TABLE work_delegations (
    work_item_id INTEGER PRIMARY KEY REFERENCES work_items(id),
    grant_id INTEGER NOT NULL REFERENCES work_delegation_grants(id),
    retry_key TEXT NOT NULL CHECK (length(trim(retry_key)) > 0),
    fingerprint TEXT NOT NULL,
    UNIQUE (grant_id, retry_key)
) STRICT;

-- One call has one immutable result, including when its reply is lost.
CREATE TABLE run_call_work_items (
    run_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    work_item_id INTEGER NOT NULL REFERENCES work_delegations(work_item_id),
    kind TEXT NOT NULL CHECK (kind IN ('committed', 'retrieved')),
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id, sequence) REFERENCES run_calls(run_id, sequence)
) STRICT, WITHOUT ROWID;

CREATE UNIQUE INDEX work_item_committing_call ON run_call_work_items(work_item_id)
    WHERE kind = 'committed';

CREATE TRIGGER immutable_work_call BEFORE UPDATE ON run_call_work_items
BEGIN SELECT RAISE(ABORT, 'Work call results are immutable'); END;

CREATE TRIGGER retain_work_call BEFORE DELETE ON run_call_work_items
BEGIN SELECT RAISE(ABORT, 'Work call results are retained'); END;

CREATE TRIGGER immutable_work_delegation BEFORE UPDATE ON work_delegations
BEGIN SELECT RAISE(ABORT, 'Work delegations are immutable'); END;

CREATE TRIGGER retain_work_delegation BEFORE DELETE ON work_delegations
BEGIN SELECT RAISE(ABORT, 'Work delegations are retained'); END;

CREATE TABLE work_item_skills (
    work_item_id INTEGER NOT NULL REFERENCES work_items(id),
    position INTEGER NOT NULL CHECK (position >= 0),
    snapshot_id INTEGER NOT NULL REFERENCES skill_revisions(id),
    PRIMARY KEY (work_item_id, position),
    UNIQUE (work_item_id, snapshot_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE work_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    attempt_key TEXT NOT NULL UNIQUE,
    work_item_id INTEGER NOT NULL REFERENCES work_items(id),
    created_at TEXT NOT NULL,
    scratch_path TEXT UNIQUE,
    scratch_cleaned_at TEXT,
    container_key TEXT UNIQUE,
    image_digest TEXT,
    launched_at TEXT,
    exit_code INTEGER,
    exited_at TEXT,
    artifact_id INTEGER UNIQUE REFERENCES work_artifacts(id),
    CHECK ((container_key IS NULL) = (image_digest IS NULL)),
    CHECK ((container_key IS NULL) = (launched_at IS NULL)),
    CHECK ((exit_code IS NULL) = (exited_at IS NULL)),
    CHECK (exited_at IS NULL OR launched_at IS NOT NULL),
    CHECK (scratch_cleaned_at IS NULL OR scratch_path IS NOT NULL),
    UNIQUE (id, work_item_id)
) STRICT;

CREATE INDEX attempts_by_work_item ON work_attempts(work_item_id, created_at, id);

CREATE TABLE work_attempt_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    attempt_id INTEGER NOT NULL REFERENCES work_attempts(id),
    credential_hash TEXT NOT NULL UNIQUE,
    granted_at TEXT NOT NULL,
    revoked_at TEXT,
    UNIQUE (id, attempt_id)
) STRICT;

CREATE UNIQUE INDEX active_attempt_grant ON work_attempt_grants(attempt_id)
    WHERE revoked_at IS NULL;

CREATE TABLE work_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    attempt_id INTEGER NOT NULL UNIQUE,
    work_item_id INTEGER NOT NULL,
    grant_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    content BLOB NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (length(content) = size_bytes),
    FOREIGN KEY (attempt_id, work_item_id) REFERENCES work_attempts(id, work_item_id),
    FOREIGN KEY (grant_id, attempt_id) REFERENCES work_attempt_grants(id, attempt_id)
) STRICT;

CREATE TABLE worker_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    attempt_id INTEGER NOT NULL REFERENCES work_attempts(id),
    grant_id INTEGER REFERENCES work_attempt_grants(id),
    tool TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('returned', 'denied', 'failed')),
    arguments TEXT NOT NULL CHECK (json_type(arguments) = 'object'),
    artifact_id INTEGER REFERENCES work_artifacts(id),
    error TEXT,
    CHECK ((outcome = 'returned') = (error IS NULL))
) STRICT;

CREATE INDEX worker_calls_by_attempt ON worker_calls(attempt_id, id);

CREATE TRIGGER immutable_work_item BEFORE UPDATE ON work_items
BEGIN SELECT RAISE(ABORT, 'Work items are immutable.'); END;

CREATE TRIGGER retain_work_item BEFORE DELETE ON work_items
BEGIN SELECT RAISE(ABORT, 'Work items are retained.'); END;

CREATE TRIGGER immutable_work_item_skill BEFORE UPDATE ON work_item_skills
BEGIN SELECT RAISE(ABORT, 'Assigned skill revisions are immutable.'); END;

CREATE TRIGGER retain_work_item_skill BEFORE DELETE ON work_item_skills
BEGIN SELECT RAISE(ABORT, 'Assigned skill revisions are retained.'); END;

CREATE TRIGGER immutable_work_artifact BEFORE UPDATE ON work_artifacts
BEGIN SELECT RAISE(ABORT, 'Saved work artifacts are immutable.'); END;

CREATE TRIGGER retain_work_artifact BEFORE DELETE ON work_artifacts
BEGIN SELECT RAISE(ABORT, 'Saved work artifacts are retained.'); END;

INSERT INTO users (username, display_name) VALUES ('admin', 'admin');

CREATE TRIGGER keep_system_admin BEFORE DELETE ON users WHEN OLD.id = 1
BEGIN
    SELECT RAISE(ABORT, 'The system user admin cannot be deleted.');
END;
