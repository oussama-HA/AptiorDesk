"""Persistence for cover letters and their versions."""

from __future__ import annotations

import json
import sqlite3

from aptiordesk.database.models.cover_letter import CoverLetter, CoverLetterVersion
from aptiordesk.database.repositories._util import now_iso


class CoverLetterRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def list_for_job(self, job_id: int) -> list[CoverLetter]:
        rows = self._conn.execute(
            "SELECT * FROM cover_letters WHERE job_id=? ORDER BY updated_at DESC", (job_id,)
        ).fetchall()
        return [self._row_to_letter(r) for r in rows]

    def list_all(self) -> list[CoverLetter]:
        rows = self._conn.execute("SELECT * FROM cover_letters ORDER BY updated_at DESC").fetchall()
        return [self._row_to_letter(r) for r in rows]

    def get(self, letter_id: int) -> CoverLetter | None:
        row = self._conn.execute("SELECT * FROM cover_letters WHERE id=?", (letter_id,)).fetchone()
        return self._row_to_letter(row) if row else None

    def create(self, letter: CoverLetter) -> CoverLetter:
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO cover_letters(job_id, resume_version_id, tone, length, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (letter.job_id, letter.resume_version_id, letter.tone, letter.length, ts, ts),
            )
        letter.id = cur.lastrowid
        return letter

    def delete(self, letter_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM cover_letters WHERE id=?", (letter_id,))

    # -- versions ------------------------------------------------------------

    def add_version(
        self,
        cover_letter_id: int,
        content_md: str,
        *,
        label: str = "",
        rationale: dict | None = None,
    ) -> CoverLetterVersion:
        next_no = self._conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM cover_letter_versions "
            "WHERE cover_letter_id=?",
            (cover_letter_id,),
        ).fetchone()[0]
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO cover_letter_versions(cover_letter_id, version_no, label, "
                "content_md, rationale_json, created_at) VALUES(?,?,?,?,?,?)",
                (cover_letter_id, next_no, label, content_md, json.dumps(rationale or {}), ts),
            )
            self._conn.execute(
                "UPDATE cover_letters SET updated_at=? WHERE id=?", (ts, cover_letter_id)
            )
        return CoverLetterVersion(
            id=cur.lastrowid,
            cover_letter_id=cover_letter_id,
            version_no=next_no,
            label=label,
            content_md=content_md,
            rationale=rationale or {},
            created_at=ts,
        )

    def list_versions(self, cover_letter_id: int) -> list[CoverLetterVersion]:
        rows = self._conn.execute(
            "SELECT * FROM cover_letter_versions WHERE cover_letter_id=? ORDER BY version_no DESC",
            (cover_letter_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def latest_version(self, cover_letter_id: int) -> CoverLetterVersion | None:
        versions = self.list_versions(cover_letter_id)
        return versions[0] if versions else None

    @staticmethod
    def _row_to_letter(row: sqlite3.Row) -> CoverLetter:
        return CoverLetter(
            id=row["id"],
            job_id=row["job_id"],
            resume_version_id=row["resume_version_id"],
            tone=row["tone"],
            length=row["length"],
        )

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> CoverLetterVersion:
        return CoverLetterVersion(
            id=row["id"],
            cover_letter_id=row["cover_letter_id"],
            version_no=row["version_no"],
            label=row["label"],
            content_md=row["content_md"],
            rationale=json.loads(row["rationale_json"]),
            created_at=row["created_at"],
        )
