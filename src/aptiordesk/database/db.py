"""SQLite connection factory and forward-only migration runner.

Migrations are numbered SQL files in ``aptiordesk/data/migrations`` named
``NNNN_description.sql``. The applied schema version is tracked with
``PRAGMA user_version``; each file runs once, in order, inside a
transaction.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from importlib import resources
from pathlib import Path

from aptiordesk.database.retired_features import RETIRING_SCHEMA_VERSION, archive_retired_data

log = logging.getLogger(__name__)

_MIGRATION_NAME = re.compile(r"^(\d{4})_[\w-]+\.sql$")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _load_migrations() -> list[tuple[int, str, str]]:
    """Return [(number, name, sql)] sorted by number."""
    out: list[tuple[int, str, str]] = []
    package = resources.files("aptiordesk.database.migrations")
    for entry in package.iterdir():
        m = _MIGRATION_NAME.match(entry.name)
        if m:
            out.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    out.sort(key=lambda t: t[0])
    numbers = [n for n, _, _ in out]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError(f"Duplicate migration numbers: {numbers}")
    return out


def migrate(conn: sqlite3.Connection, *, database_path: str | Path | None = None) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    migrations = _load_migrations()
    for number, name, sql in migrations:
        if number <= current:
            continue
        log.info("Applying migration %s", name)
        if number == RETIRING_SCHEMA_VERSION:
            archive = archive_retired_data(conn, database_path)
            if archive is not None:
                log.info("Archived retired feature data to %s", archive)
        try:
            conn.execute("BEGIN")
            for statement in _split_statements(sql):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        current = number
    return current


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into statements.

    Constraint on migration files: plain DDL/DML only — no triggers, no
    semicolons inside string literals, comments only as `--` lines.
    """
    lines = [ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def open_database(db_path: str | Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn, database_path=db_path)
    return conn
