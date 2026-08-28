import sqlite3

import pytest

from aptiordesk.database import db


@pytest.fixture(autouse=True)
def isolated_product_storage(tmp_path, monkeypatch):
    """Tests must never read or mutate a developer's real application data."""
    from aptiordesk.core import paths, storage_migration

    current = tmp_path / "aptiordesk-data"
    legacy = tmp_path / "legacy-data"
    monkeypatch.setattr(storage_migration, "product_data_dir", lambda: current)
    monkeypatch.setattr(storage_migration, "legacy_data_dir", lambda: legacy)
    monkeypatch.setattr(paths, "_identity_checked", False)
    yield
    paths._identity_checked = False


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory database with all migrations applied."""
    connection = db.connect(":memory:")
    db.migrate(connection)
    yield connection
    connection.close()
