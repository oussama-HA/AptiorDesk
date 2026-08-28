-- AptiorDesk schema v7: attributed job snapshots captured from the browser.

ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE jobs ADD COLUMN source_name TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN source_id TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN location TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN remote_type TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE jobs ADD COLUMN employment_type TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE jobs ADD COLUMN experience_level TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE jobs ADD COLUMN salary_min REAL;
ALTER TABLE jobs ADD COLUMN salary_max REAL;
ALTER TABLE jobs ADD COLUMN salary_currency TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN salary_period TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN posted_at TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN retrieved_at TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN skills_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE jobs ADD COLUMN also_on_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;

-- Re-importing the same listing refreshes its snapshot instead of duplicating it.
CREATE UNIQUE INDEX idx_jobs_source_identity
    ON jobs(source, source_id) WHERE source_id != '';

CREATE INDEX idx_jobs_hidden ON jobs(hidden, updated_at);
