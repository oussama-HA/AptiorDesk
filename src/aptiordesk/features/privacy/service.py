"""Backup, restore, and permanent deletion of local data.

Your data is yours: everything AptiorDesk stores can be exported to a single
readable zip, restored on another machine, or destroyed completely. API keys
are deliberately excluded from backups — they live in the OS keyring and must
never travel in a file.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import zipfile
from pathlib import Path

from aptiordesk.ai import keystore
from aptiordesk.core import paths
from aptiordesk.core.errors import DataError
from aptiordesk.core.identity import BACKUP_MANIFEST, LEGACY_BACKUP_MANIFEST, PRODUCT_NAME
from aptiordesk.database import db
from aptiordesk.database.repositories.provider_repo import ProviderRepository

log = logging.getLogger(__name__)

BACKUP_FORMAT = 2
MANIFEST_NAME = BACKUP_MANIFEST
LEGACY_MANIFEST_NAME = LEGACY_BACKUP_MANIFEST
_PRIVATE_SETTING_KEYS = {"browser_extension.token"}
_LEGACY_JOB_SOURCE_SECRETS = (
    "jobsource-adzuna-app_id",
    "jobsource-adzuna-app_key",
)

# Every table we own. Order matters on restore: parents before children.
_TABLES = [
    "settings",
    "ai_providers",
    "profiles",
    "profile_items",
    "resumes",
    "resume_versions",
    "jobs",
    "job_analyses",
    "tailoring_sessions",
    "suggestions",
    "cover_letters",
    "cover_letter_versions",
    "interview_sessions",
    "questions",
    "answers",
    "feedback",
]


def export_backup(conn: sqlite3.Connection, path: str | Path) -> Path:
    """Write every table to a zip containing readable JSON."""
    path = Path(path)
    schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    payload: dict[str, list[dict]] = {}
    for table in _TABLES:
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        except sqlite3.OperationalError:
            continue  # table from a newer/older schema
        table_rows = [dict(row) for row in rows]
        if table == "settings":
            # Local authentication material is machine-specific, just like an
            # API key. It must not travel in a portable backup.
            table_rows = [row for row in table_rows if row.get("key") not in _PRIVATE_SETTING_KEYS]
        payload[table] = table_rows

    manifest = {
        "format": BACKUP_FORMAT,
        "product": PRODUCT_NAME,
        "schema_version": schema_version,
        "tables": {name: len(rows) for name, rows in payload.items()},
        "note": (
            "API keys are NOT included in this backup — they are stored in your "
            "operating system's credential manager and must be re-entered after "
            "a restore."
        ),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for table, rows in payload.items():
            archive.writestr(f"data/{table}.json", json.dumps(rows, indent=2, default=str))
    log.info("Backup written to %s (%d tables)", path.name, len(payload))
    return path


def read_manifest(path: str | Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            manifest_name = next(
                (name for name in (MANIFEST_NAME, LEGACY_MANIFEST_NAME) if name in names),
                None,
            )
            if manifest_name is None:
                raise KeyError(MANIFEST_NAME)
            manifest = json.loads(archive.read(manifest_name))
            manifest["_manifest_name"] = manifest_name
            return manifest
    except (KeyError, zipfile.BadZipFile) as exc:
        raise DataError(f"This file is not an {PRODUCT_NAME} backup.", detail=str(exc)) from exc


def restore_backup(conn: sqlite3.Connection, path: str | Path) -> dict[str, int]:
    """Replace all local data with the backup's contents.

    Destructive by design — the caller must confirm with the user first.
    """
    manifest = read_manifest(path)
    if manifest.get("format") not in {1, BACKUP_FORMAT}:
        raise DataError(
            f"This backup uses format {manifest.get('format')}, which this version "
            f"of {PRODUCT_NAME} cannot read (it expects {BACKUP_FORMAT})."
        )
    backup_schema = manifest.get("schema_version", 0)
    current_schema = conn.execute("PRAGMA user_version").fetchone()[0]
    if backup_schema > current_schema:
        raise DataError(
            f"This backup was made by a newer version of {PRODUCT_NAME}. Update the app, "
            "then restore again."
        )

    restored: dict[str, int] = {}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        try:
            conn.execute("BEGIN")
            conn.execute("PRAGMA defer_foreign_keys = ON")
            for table in reversed(_TABLES):
                conn.execute(f"DELETE FROM {table}")  # noqa: S608
            for table in _TABLES:
                entry = f"data/{table}.json"
                if entry not in names:
                    continue
                rows = json.loads(archive.read(entry))
                if not rows:
                    continue
                columns = list(rows[0].keys())
                placeholders = ",".join("?" for _ in columns)
                statement = f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})"  # noqa: S608
                conn.executemany(statement, [[row[c] for c in columns] for row in rows])
                restored[table] = len(rows)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise DataError(
                "The backup could not be restored; your existing data was left unchanged.",
                detail=str(exc),
            ) from exc
    log.info("Restored %d tables from %s", len(restored), Path(path).name)
    return restored


def delete_all_data(conn: sqlite3.Connection, *, delete_models: bool = False) -> list[str]:
    """Permanently destroy local data. Returns a list of what was removed."""
    removed: list[str] = []

    provider_ids = [p.id for p in ProviderRepository(conn).list() if p.id is not None]
    for provider_id in provider_ids:
        keystore.delete_key(provider_id)
    if provider_ids:
        removed.append(f"{len(provider_ids)} stored API key(s) from the OS keyring")

    # Remove credentials left by the retired in-app search adapters.
    for secret_name in _LEGACY_JOB_SOURCE_SECRETS:
        keystore.delete_secret(secret_name)
    removed.append("legacy job-source credentials from the OS keyring")

    with conn:
        conn.execute("PRAGMA defer_foreign_keys = ON")
        for table in reversed(_TABLES):
            try:
                conn.execute(f"DELETE FROM {table}")  # noqa: S608
            except sqlite3.OperationalError:
                continue
    conn.execute("VACUUM")
    removed.append("all profile, resume, job, letter, tailoring, and interview data")

    scratch = paths.scratch_dir()
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
        removed.append("temporary voice recordings")

    if delete_models:
        models = paths.models_dir()
        if models.exists():
            shutil.rmtree(models, ignore_errors=True)
            removed.append("downloaded speech models")

    log.info("Deleted all local data (%d categories)", len(removed))
    return removed


def data_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts per table, for showing the user what is actually stored."""
    summary: dict[str, int] = {}
    for table in _TABLES:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        except sqlite3.OperationalError:
            continue
        if count:
            summary[table] = count
    return summary


def reopen_database() -> sqlite3.Connection:
    """Fresh connection with migrations applied — used after a restore."""
    return db.open_database(paths.db_path())
