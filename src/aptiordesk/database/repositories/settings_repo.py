"""Key/value app settings stored as JSON in the `settings` table."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class SettingsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, payload),
            )

    def delete(self, key: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
