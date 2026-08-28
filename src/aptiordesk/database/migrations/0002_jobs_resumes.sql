-- AptiorDesk schema v2: resumes with versioning, jobs with analyses,
-- tailoring sessions with per-suggestion review state.

CREATE TABLE resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'imported')),
    source_filename TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL,
    raw_text TEXT NOT NULL DEFAULT '',
    created_from_version_id INTEGER REFERENCES resume_versions(id) ON DELETE SET NULL,
    tailoring_session_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (resume_id, version_no)
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    raw_description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE job_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('extraction', 'fit')),
    resume_version_id INTEGER REFERENCES resume_versions(id) ON DELETE SET NULL,
    prompt_id TEXT NOT NULL DEFAULT '',
    prompt_version INTEGER NOT NULL DEFAULT 0,
    provider_snapshot TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_job_analyses_job ON job_analyses(job_id, kind, created_at);

CREATE TABLE tailoring_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    base_resume_version_id INTEGER NOT NULL REFERENCES resume_versions(id) ON DELETE CASCADE,
    strategy TEXT NOT NULL DEFAULT 'balanced',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'applied', 'discarded')),
    created_at TEXT NOT NULL
);

CREATE TABLE suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES tailoring_sessions(id) ON DELETE CASCADE,
    target_path TEXT NOT NULL,
    original_text TEXT NOT NULL DEFAULT '',
    suggested_text TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    jd_evidence TEXT NOT NULL DEFAULT '',
    profile_evidence TEXT NOT NULL DEFAULT '',
    warnings TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected', 'edited')),
    edited_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_suggestions_session ON suggestions(session_id);
