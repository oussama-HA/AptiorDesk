from __future__ import annotations

import json
import sqlite3

from aptiordesk.core import storage_migration
from aptiordesk.core.identity import DATABASE_NAME, LEGACY_DATABASE_NAME


def test_legacy_database_is_copied_verified_and_preserved(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    legacy.mkdir()
    old_database = legacy / LEGACY_DATABASE_NAME
    connection = sqlite3.connect(old_database)
    connection.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO evidence(value) VALUES ('preserve me')")
    connection.commit()
    connection.close()

    monkeypatch.setattr(storage_migration, "legacy_data_dir", lambda: legacy)
    monkeypatch.setattr(storage_migration, "product_data_dir", lambda: current)
    result = storage_migration.ensure_storage_identity()

    assert result.migrated
    assert old_database.exists()
    migrated = sqlite3.connect(current / DATABASE_NAME)
    assert migrated.execute("SELECT value FROM evidence").fetchone()[0] == "preserve me"
    assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    migrated.close()
    marker = json.loads((current / "identity-migration.json").read_text(encoding="utf-8"))
    assert marker["source_preserved"] is True
    assert marker["database_rows"]["evidence"] == 1


def test_existing_aptiordesk_database_is_never_overwritten(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    legacy.mkdir()
    current.mkdir()
    for path, value in (
        (legacy / LEGACY_DATABASE_NAME, "legacy"),
        (current / DATABASE_NAME, "current"),
    ):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE evidence (value TEXT)")
        connection.execute("INSERT INTO evidence VALUES (?)", (value,))
        connection.commit()
        connection.close()

    monkeypatch.setattr(storage_migration, "legacy_data_dir", lambda: legacy)
    monkeypatch.setattr(storage_migration, "product_data_dir", lambda: current)
    result = storage_migration.ensure_storage_identity()

    assert not result.migrated
    database = sqlite3.connect(current / DATABASE_NAME)
    assert database.execute("SELECT value FROM evidence").fetchone()[0] == "current"
    database.close()
