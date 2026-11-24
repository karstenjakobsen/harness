ALTER TABLE goals ADD COLUMN deleted_at TEXT;

PRAGMA user_version = 2;
