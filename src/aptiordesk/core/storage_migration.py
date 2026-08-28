"""Safe one-time migration from the legacy product data directory."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir

from aptiordesk.core.identity import (
    DATA_DIR_NAME,
    DATABASE_NAME,
    LEGACY_DATA_DIR_NAME,
    LEGACY_DATABASE_NAME,
)

_MARKER_NAME = "identity-migration.json"
_COPY_DIRECTORIES = ("models", "assets")


@dataclass(frozen=True)
class StorageMigrationResult:
    migrated: bool
    source: str
    destination: str
    database_rows: dict[str, int]


def product_data_dir() -> Path:
    return Path(user_data_dir(DATA_DIR_NAME, False))


def legacy_data_dir() -> Path:
    return Path(user_data_dir(LEGACY_DATA_DIR_NAME, False))


def ensure_storage_identity() -> StorageMigrationResult:
    """Copy legacy persisted data into AptiorDesk without deleting the source.

    SQLite's backup API is used instead of copying the database file, so data
    still present in a WAL file is included in the verified destination.
    """
    destination = product_data_dir()
    source = legacy_data_dir()
    destination.mkdir(parents=True, exist_ok=True)
    new_db = destination / DATABASE_NAME
    old_db = source / LEGACY_DATABASE_NAME

    if new_db.exists() or not old_db.exists():
        return StorageMigrationResult(False, str(source), str(destination), {})

    temp_db = destination / f".{DATABASE_NAME}.migrating"
    if temp_db.exists():
        temp_db.unlink()

    counts: dict[str, int] = {}
    source_conn: sqlite3.Connection | None = None
    destination_conn: sqlite3.Connection | None = None
    try:
        source_conn = sqlite3.connect(f"file:{old_db.as_posix()}?mode=ro", uri=True)
        destination_conn = sqlite3.connect(str(temp_db))
        source_conn.backup(destination_conn)
        destination_conn.commit()

        integrity = destination_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Migrated database failed integrity_check: {integrity}")

        tables = [
            row[0]
            for row in destination_conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for table in tables:
            source_count = source_conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608 - schema-owned name
            ).fetchone()[0]
            copied_count = destination_conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608 - schema-owned name
            ).fetchone()[0]
            if source_count != copied_count:
                raise RuntimeError(
                    f"Migration verification failed for {table}: "
                    f"expected {source_count}, copied {copied_count}"
                )
            counts[table] = copied_count
    except Exception:
        if destination_conn is not None:
            destination_conn.close()
            destination_conn = None
        if source_conn is not None:
            source_conn.close()
            source_conn = None
        temp_db.unlink(missing_ok=True)
        raise
    finally:
        if destination_conn is not None:
            destination_conn.close()
        if source_conn is not None:
            source_conn.close()

    os.replace(temp_db, new_db)
    for name in _COPY_DIRECTORIES:
        old_child = source / name
        new_child = destination / name
        if old_child.is_dir() and not new_child.exists():
            shutil.copytree(old_child, new_child)

    result = StorageMigrationResult(True, str(source), str(destination), counts)
    marker = {
        **asdict(result),
        "completed_at": datetime.now(UTC).isoformat(),
        "source_preserved": True,
    }
    marker_path = destination / _MARKER_NAME
    temp_marker = destination / f".{_MARKER_NAME}.tmp"
    temp_marker.write_text(json.dumps(marker, indent=2, sort_keys=True), encoding="utf-8")
    json.loads(temp_marker.read_text(encoding="utf-8"))
    os.replace(temp_marker, marker_path)
    return result


__all__ = [
    "StorageMigrationResult",
    "ensure_storage_identity",
    "legacy_data_dir",
    "product_data_dir",
]
