"""Archive data from removed product areas before their tables are dropped."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from aptiordesk.core.identity import PRODUCT_NAME

RETIRING_SCHEMA_VERSION = 9
RETIRED_TABLES = (
    "career_campaigns",
    "contacts",
    "contact_interactions",
    "opportunity_reviews",
    "action_items",
    "applications",
    "application_events",
)


def archive_retired_data(conn: sqlite3.Connection, database_path: str | Path | None) -> Path | None:
    """Create and verify a readable archive when legacy tables contain rows."""
    existing = _existing_tables(conn)
    tables = [name for name in RETIRED_TABLES if name in existing]
    if not tables:
        return None

    payload = {
        name: [dict(row) for row in conn.execute(f'SELECT * FROM "{name}"').fetchall()]
        for name in tables
    }
    if not any(payload.values()):
        return None
    if database_path is None or str(database_path) == ":memory:":
        raise RuntimeError("Retired feature data exists but no durable archive path was provided.")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    document = {
        "product": PRODUCT_NAME,
        "reason": "Retired planning and application-status features",
        "schema_version_before": conn.execute("PRAGMA user_version").fetchone()[0],
        "created_at": datetime.now(UTC).isoformat(),
        "tables": {name: len(rows) for name, rows in payload.items()},
        "sha256": checksum,
        "data": payload,
    }

    root = Path(database_path).resolve().parent / "migration-archives"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = root / f"retired-features-v{RETIRING_SCHEMA_VERSION}-{stamp}.json"
    candidate = target
    suffix = 1
    while candidate.exists():
        candidate = target.with_stem(f"{target.stem}-{suffix}")
        suffix += 1
    temp = candidate.with_suffix(".tmp")
    temp.write_text(json.dumps(document, indent=2, sort_keys=True, default=str), encoding="utf-8")

    verified = json.loads(temp.read_text(encoding="utf-8"))
    verified_payload = verified.get("data", {})
    verified_canonical = json.dumps(
        verified_payload, sort_keys=True, separators=(",", ":"), default=str
    )
    if hashlib.sha256(verified_canonical.encode("utf-8")).hexdigest() != checksum:
        temp.unlink(missing_ok=True)
        raise RuntimeError("Retired feature archive checksum verification failed.")
    if verified.get("tables") != {name: len(rows) for name, rows in payload.items()}:
        temp.unlink(missing_ok=True)
        raise RuntimeError("Retired feature archive row-count verification failed.")

    os.replace(temp, candidate)
    return candidate


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


__all__ = ["RETIRED_TABLES", "RETIRING_SCHEMA_VERSION", "archive_retired_data"]
