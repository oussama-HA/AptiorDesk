"""Persistence for AI provider configurations (keys live in the keyring)."""

from __future__ import annotations

import sqlite3

from aptiordesk.database.models.provider import CLIAdapterKind, ProviderConfig, ProviderKind
from aptiordesk.database.repositories._util import now_iso


class ProviderRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def list(self) -> list[ProviderConfig]:
        rows = self._conn.execute("SELECT * FROM ai_providers ORDER BY id").fetchall()
        return [self._row_to_config(r) for r in rows]

    def get(self, provider_id: int) -> ProviderConfig | None:
        row = self._conn.execute("SELECT * FROM ai_providers WHERE id=?", (provider_id,)).fetchone()
        return self._row_to_config(row) if row else None

    def get_active(self) -> ProviderConfig | None:
        row = self._conn.execute(
            "SELECT * FROM ai_providers WHERE is_active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        return self._row_to_config(row) if row else None

    def create(self, config: ProviderConfig) -> ProviderConfig:
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO ai_providers(name, kind, base_url, model, temperature, "
                "max_tokens, timeout_s, is_active, cli_adapter, cli_executable, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    config.name,
                    config.kind.value,
                    config.base_url or None,
                    config.model,
                    config.temperature,
                    config.max_tokens,
                    config.timeout_s,
                    int(config.is_active),
                    config.cli_adapter.value,
                    config.cli_executable or None,
                    ts,
                    ts,
                ),
            )
        config.id = cur.lastrowid
        if config.is_active:
            self.set_active(config.id)
        return config

    def update(self, config: ProviderConfig) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE ai_providers SET name=?, kind=?, base_url=?, model=?, "
                "temperature=?, max_tokens=?, timeout_s=?, cli_adapter=?, "
                "cli_executable=?, updated_at=? WHERE id=?",
                (
                    config.name,
                    config.kind.value,
                    config.base_url or None,
                    config.model,
                    config.temperature,
                    config.max_tokens,
                    config.timeout_s,
                    config.cli_adapter.value,
                    config.cli_executable or None,
                    now_iso(),
                    config.id,
                ),
            )

    def delete(self, provider_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM ai_providers WHERE id=?", (provider_id,))

    def set_active(self, provider_id: int) -> None:
        """Exactly one provider may be active."""
        with self._conn:
            self._conn.execute("UPDATE ai_providers SET is_active=0 WHERE is_active=1")
            self._conn.execute(
                "UPDATE ai_providers SET is_active=1, updated_at=? WHERE id=?",
                (now_iso(), provider_id),
            )

    @staticmethod
    def _row_to_config(row: sqlite3.Row) -> ProviderConfig:
        return ProviderConfig(
            id=row["id"],
            name=row["name"],
            kind=ProviderKind(row["kind"]),
            base_url=row["base_url"] or "",
            model=row["model"],
            temperature=row["temperature"],
            max_tokens=row["max_tokens"],
            timeout_s=row["timeout_s"],
            is_active=bool(row["is_active"]),
            cli_adapter=CLIAdapterKind(row["cli_adapter"] or CLIAdapterKind.CODEX.value),
            cli_executable=row["cli_executable"] or "",
        )
