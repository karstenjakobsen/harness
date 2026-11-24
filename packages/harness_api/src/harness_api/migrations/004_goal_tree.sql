ALTER TABLE goals ADD COLUMN parent_goal_id INTEGER REFERENCES goals(id);
CREATE INDEX goals_by_parent ON goals(parent_goal_id);

ALTER TABLE goal_revisions ADD COLUMN duration_days INTEGER
    CHECK (duration_days IS NULL OR
           (typeof(duration_days) = 'integer' AND duration_days > 0));

CREATE UNIQUE INDEX one_completion_per_revision ON goal_events(goal_id, revision)
    WHERE kind = 'completion';

PRAGMA user_version = 4;
