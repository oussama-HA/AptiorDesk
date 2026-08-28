-- AptiorDesk schema v4: interview sessions, questions, answers, feedback.

CREATE TABLE interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    resume_version_id INTEGER REFERENCES resume_versions(id) ON DELETE SET NULL,
    mode TEXT NOT NULL DEFAULT 'mock' CHECK (mode IN ('prep', 'mock')),
    persona TEXT NOT NULL DEFAULT 'friendly_recruiter',
    stage TEXT NOT NULL DEFAULT 'recruiter_screen',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'abandoned')),
    report_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES interview_sessions(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'behavioral',
    stage TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    text TEXT NOT NULL,
    key_points_json TEXT NOT NULL DEFAULT '[]',
    why_asked TEXT NOT NULL DEFAULT '',
    is_followup INTEGER NOT NULL DEFAULT 0,
    parent_question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_questions_session ON questions(session_id, sort_order);
CREATE INDEX idx_questions_job ON questions(job_id);

CREATE TABLE answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES interview_sessions(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    text TEXT NOT NULL DEFAULT '',
    input_mode TEXT NOT NULL DEFAULT 'typed' CHECK (input_mode IN ('typed', 'voice')),
    duration_s REAL,
    words_per_minute REAL,
    filler_json TEXT NOT NULL DEFAULT '{}',
    in_library INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_answers_question ON answers(question_id, attempt_no);

CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    result_json TEXT NOT NULL,
    prompt_id TEXT NOT NULL DEFAULT '',
    prompt_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
