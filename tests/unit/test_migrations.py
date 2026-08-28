from aptiordesk.database import db
from aptiordesk.database.retired_features import RETIRED_TABLES


def test_fresh_database_reaches_latest_version(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 1


def test_expected_tables_exist(conn):
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "settings",
        "ai_providers",
        "profiles",
        "profile_items",
        "resumes",
        "jobs",
        "job_fit_ratios",
        "tailoring_sessions",
        "cover_letters",
        "interview_sessions",
    } <= tables
    assert not set(RETIRED_TABLES) & tables


def test_migrate_is_idempotent(conn):
    before = conn.execute("PRAGMA user_version").fetchone()[0]
    db.migrate(conn)  # second run applies nothing
    after = conn.execute("PRAGMA user_version").fetchone()[0]
    assert before == after


def test_cli_provider_schema_preserves_existing_provider(tmp_path):
    database = tmp_path / "provider-v9.db"
    connection = db.connect(database)
    connection.executescript(
        """
        CREATE TABLE ai_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            base_url TEXT,
            model TEXT NOT NULL DEFAULT '',
            temperature REAL NOT NULL DEFAULT 0.7,
            max_tokens INTEGER NOT NULL DEFAULT 2048,
            timeout_s INTEGER NOT NULL DEFAULT 60,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO ai_providers VALUES (
            7, 'Existing Ollama', 'ollama', NULL, 'gemma3', 0.4, 4096, 90, 1, 'a', 'b'
        );
        PRAGMA user_version = 9;
        """
    )

    assert db.migrate(connection, database_path=database) == 12
    row = connection.execute("SELECT * FROM ai_providers WHERE id=7").fetchone()
    assert row["name"] == "Existing Ollama"
    assert row["model"] == "gemma3"
    assert row["cli_adapter"] == "codex"
    assert row["cli_executable"] is None
    connection.close()


def test_skill_addition_schema_preserves_existing_suggestions(tmp_path):
    database = tmp_path / "suggestions-v10.db"
    connection = db.connect(database)
    connection.executescript(
        """
        CREATE TABLE suggestions (
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
        INSERT INTO suggestions VALUES (
            4, 2, '/summary', 'Old', 'New', 'Why', 'JD', 'Resume', '',
            'accepted', '', 'now'
        );
        PRAGMA user_version = 10;
        """
    )

    assert db.migrate(connection, database_path=database) == 12
    row = connection.execute("SELECT * FROM suggestions WHERE id=4").fetchone()
    assert row["suggested_text"] == "New"
    assert row["status"] == "accepted"
    assert row["operation"] == "replace"
    assert row["skill_category"] == ""
    connection.close()


def test_foreign_keys_enforced(conn):
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO profile_items(profile_id, kind, sort_order, data_json, "
            "created_at, updated_at) VALUES (999, 'skill', 0, '{}', 't', 't')"
        )


def test_v8_data_is_archived_before_retired_tables_are_dropped(tmp_path):
    database = tmp_path / "legacy.db"
    connection = db.connect(database)
    connection.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
        CREATE TABLE applications (id INTEGER PRIMARY KEY, notes TEXT);
        CREATE TABLE application_events (id INTEGER PRIMARY KEY, application_id INTEGER);
        CREATE TABLE career_campaigns (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE contacts (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE contact_interactions (id INTEGER PRIMARY KEY, contact_id INTEGER);
        CREATE TABLE opportunity_reviews (id INTEGER PRIMARY KEY, notes TEXT);
        CREATE TABLE action_items (id INTEGER PRIMARY KEY, title TEXT);
        INSERT INTO applications VALUES (1, 'Submitted');
        INSERT INTO application_events VALUES (1, 1);
        INSERT INTO career_campaigns VALUES (1, 'Focused search');
        INSERT INTO contacts VALUES (1, 'Recruiter');
        INSERT INTO contact_interactions VALUES (1, 1);
        INSERT INTO opportunity_reviews VALUES (1, 'Strong role');
        INSERT INTO action_items VALUES (1, 'Follow up');
        PRAGMA user_version = 8;
        """
    )

    assert db.migrate(connection, database_path=database) == 12
    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert not set(RETIRED_TABLES) & tables
    archives = list((tmp_path / "migration-archives").glob("*.json"))
    assert len(archives) == 1
    import json

    archive = json.loads(archives[0].read_text(encoding="utf-8"))
    assert archive["tables"]["applications"] == 1
    assert archive["tables"]["career_campaigns"] == 1
    assert archive["sha256"]
    connection.close()
