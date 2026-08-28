-- AptiorDesk schema v3: cover letters with versions.

CREATE TABLE cover_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_version_id INTEGER REFERENCES resume_versions(id) ON DELETE SET NULL,
    tone TEXT NOT NULL DEFAULT 'professional',
    length TEXT NOT NULL DEFAULT 'standard',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE cover_letter_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cover_letter_id INTEGER NOT NULL REFERENCES cover_letters(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    content_md TEXT NOT NULL,
    rationale_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (cover_letter_id, version_no)
);
