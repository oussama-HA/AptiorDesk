"""Persistence for tailoring sessions and their suggestions."""

from __future__ import annotations

import sqlite3

from aptiordesk.database.models.tailoring import Suggestion, TailoringSession
from aptiordesk.database.repositories._util import now_iso


class TailoringRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_session(self, session: TailoringSession) -> TailoringSession:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO tailoring_sessions(job_id, base_resume_version_id, strategy, "
                "status, created_at) VALUES(?,?,?,?,?)",
                (
                    session.job_id,
                    session.base_resume_version_id,
                    session.strategy,
                    session.status,
                    now_iso(),
                ),
            )
        session.id = cur.lastrowid
        return session

    def get_session(self, session_id: int) -> TailoringSession | None:
        row = self._conn.execute(
            "SELECT * FROM tailoring_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return TailoringSession(
            id=row["id"],
            job_id=row["job_id"],
            base_resume_version_id=row["base_resume_version_id"],
            strategy=row["strategy"],
            status=row["status"],
        )

    def set_session_status(self, session_id: int, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE tailoring_sessions SET status=? WHERE id=?", (status, session_id)
            )

    # -- suggestions ---------------------------------------------------------

    def add_suggestions(self, session_id: int, suggestions: list[Suggestion]) -> None:
        ts = now_iso()
        with self._conn:
            for s in suggestions:
                cur = self._conn.execute(
                    "INSERT INTO suggestions(session_id, operation, target_path, "
                    "original_text, suggested_text, skill_category, rationale, jd_evidence, "
                    "profile_evidence, warnings, status, edited_text, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id,
                        s.operation,
                        s.target_path,
                        s.original_text,
                        s.suggested_text,
                        s.skill_category,
                        s.rationale,
                        s.jd_evidence,
                        s.profile_evidence,
                        s.warnings,
                        s.status,
                        s.edited_text,
                        ts,
                    ),
                )
                s.id = cur.lastrowid
                s.session_id = session_id

    def list_suggestions(self, session_id: int) -> list[Suggestion]:
        rows = self._conn.execute(
            "SELECT * FROM suggestions WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [self._row_to_suggestion(r) for r in rows]

    def set_suggestion_status(self, suggestion_id: int, status: str, edited_text: str = "") -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE suggestions SET status=?, edited_text=? WHERE id=?",
                (status, edited_text, suggestion_id),
            )

    @staticmethod
    def _row_to_suggestion(row: sqlite3.Row) -> Suggestion:
        return Suggestion(
            id=row["id"],
            session_id=row["session_id"],
            operation=row["operation"],
            target_path=row["target_path"],
            original_text=row["original_text"],
            suggested_text=row["suggested_text"],
            skill_category=row["skill_category"],
            rationale=row["rationale"],
            jd_evidence=row["jd_evidence"],
            profile_evidence=row["profile_evidence"],
            warnings=row["warnings"],
            status=row["status"],
            edited_text=row["edited_text"],
        )
