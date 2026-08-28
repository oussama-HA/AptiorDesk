-- Tailoring suggestions may now add an evidence-backed skill, in addition to
-- replacing an existing resume string. Existing suggestions remain replaces.

-- Defensive bootstrap for partial development databases stamped past the
-- original tailoring migration.
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    target_path TEXT NOT NULL,
    original_text TEXT NOT NULL DEFAULT '',
    suggested_text TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    jd_evidence TEXT NOT NULL DEFAULT '',
    profile_evidence TEXT NOT NULL DEFAULT '',
    warnings TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    edited_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

ALTER TABLE suggestions ADD COLUMN operation TEXT NOT NULL DEFAULT 'replace';
ALTER TABLE suggestions ADD COLUMN skill_category TEXT NOT NULL DEFAULT '';
