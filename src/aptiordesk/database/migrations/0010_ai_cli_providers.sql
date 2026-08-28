-- Add device CLI providers while preserving every existing provider row.
-- The original provider-kind CHECK constraint requires a table rebuild.

-- Defensive bootstrap for partial development databases that were stamped
-- with a later version without containing the original provider table.
CREATE TABLE IF NOT EXISTS ai_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ollama', 'openai_compat', 'anthropic', 'gemini')),
    base_url TEXT,
    model TEXT NOT NULL DEFAULT '',
    temperature REAL NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 2048,
    timeout_s INTEGER NOT NULL DEFAULT 60,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE ai_providers RENAME TO ai_providers_v9;

CREATE TABLE ai_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ollama', 'openai_compat', 'anthropic', 'gemini', 'cli')),
    base_url TEXT,
    model TEXT NOT NULL DEFAULT '',
    temperature REAL NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 2048,
    timeout_s INTEGER NOT NULL DEFAULT 60,
    is_active INTEGER NOT NULL DEFAULT 0,
    cli_adapter TEXT NOT NULL DEFAULT 'codex' CHECK (cli_adapter IN ('codex', 'claude', 'gemini')),
    cli_executable TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO ai_providers(
    id, name, kind, base_url, model, temperature, max_tokens, timeout_s,
    is_active, created_at, updated_at
)
SELECT
    id, name, kind, base_url, model, temperature, max_tokens, timeout_s,
    is_active, created_at, updated_at
FROM ai_providers_v9;

DROP TABLE ai_providers_v9;
