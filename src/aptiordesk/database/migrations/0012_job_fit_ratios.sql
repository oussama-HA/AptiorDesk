-- Versioned, transparent Job Fit Ratio results. One row is retained per
-- job/resume/scoring-method tuple so scores can be reproduced and compared.

CREATE TABLE job_fit_ratios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_version_id INTEGER NOT NULL REFERENCES resume_versions(id) ON DELETE CASCADE,
    scoring_version TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (job_id, resume_version_id, scoring_version)
);

CREATE INDEX idx_job_fit_ratios_job_resume
    ON job_fit_ratios(job_id, resume_version_id, updated_at);
