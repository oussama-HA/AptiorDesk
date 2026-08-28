"""Filesystem locations for all locally stored AptiorDesk data."""

from __future__ import annotations

from pathlib import Path

from aptiordesk.core import storage_migration
from aptiordesk.core.identity import DATABASE_NAME

_identity_checked = False


def data_dir() -> Path:
    global _identity_checked
    if not _identity_checked:
        storage_migration.ensure_storage_identity()
        _identity_checked = True
    d = storage_migration.product_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / DATABASE_NAME


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scratch_dir() -> Path:
    """Short-lived working files (e.g. voice recordings awaiting transcription)."""
    d = data_dir() / "scratch"
    d.mkdir(parents=True, exist_ok=True)
    return d
