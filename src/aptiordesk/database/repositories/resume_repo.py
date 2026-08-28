"""Persistence for resumes and their immutable versions."""

from __future__ import annotations

import json
import sqlite3

from aptiordesk.database.models.extraction import ExtractionReport
from aptiordesk.database.models.resume import Resume, ResumeContent, ResumeVersion
from aptiordesk.database.repositories._util import now_iso


class ResumeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- resumes -------------------------------------------------------------

    def list(self) -> list[Resume]:
        rows = self._conn.execute("SELECT * FROM resumes ORDER BY updated_at DESC").fetchall()
        return [self._row_to_resume(r) for r in rows]

    def get(self, resume_id: int) -> Resume | None:
        row = self._conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
        return self._row_to_resume(row) if row else None

    def create(self, resume: Resume) -> Resume:
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO resumes(profile_id, name, source, source_filename, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (resume.profile_id, resume.name, resume.source, resume.source_filename, ts, ts),
            )
        resume.id = cur.lastrowid
        return resume

    def rename(self, resume_id: int, name: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE resumes SET name=?, updated_at=? WHERE id=?",
                (name, now_iso(), resume_id),
            )

    def delete(self, resume_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM resumes WHERE id=?", (resume_id,))

    # -- versions ------------------------------------------------------------

    def add_version(
        self,
        resume_id: int,
        content: ResumeContent,
        *,
        label: str = "",
        raw_text: str = "",
        created_from_version_id: int | None = None,
        tailoring_session_id: int | None = None,
        extraction_report: ExtractionReport | None = None,
        source_diagnosis: str = "",
    ) -> ResumeVersion:
        next_no = self._conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM resume_versions WHERE resume_id=?",
            (resume_id,),
        ).fetchone()[0]
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO resume_versions(resume_id, version_no, label, content_json, "
                "raw_text, created_from_version_id, tailoring_session_id, "
                "extraction_report_json, source_diagnosis, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    resume_id,
                    next_no,
                    label,
                    content.model_dump_json(),
                    raw_text,
                    created_from_version_id,
                    tailoring_session_id,
                    extraction_report.model_dump_json() if extraction_report else "{}",
                    source_diagnosis,
                    ts,
                ),
            )
            self._conn.execute("UPDATE resumes SET updated_at=? WHERE id=?", (ts, resume_id))
        return ResumeVersion(
            id=cur.lastrowid,
            resume_id=resume_id,
            version_no=next_no,
            label=label,
            content=content,
            raw_text=raw_text,
            created_from_version_id=created_from_version_id,
            tailoring_session_id=tailoring_session_id,
            created_at=ts,
        )

    def list_versions(self, resume_id: int) -> list[ResumeVersion]:
        rows = self._conn.execute(
            "SELECT * FROM resume_versions WHERE resume_id=? ORDER BY version_no DESC",
            (resume_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def get_version(self, version_id: int) -> ResumeVersion | None:
        row = self._conn.execute(
            "SELECT * FROM resume_versions WHERE id=?", (version_id,)
        ).fetchone()
        return self._row_to_version(row) if row else None

    def count_versions(self, resume_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM resume_versions WHERE resume_id=?", (resume_id,)
        ).fetchone()
        return int(row[0])

    def version_has_tailoring_dependents(self, version_id: int) -> bool:
        row = self._conn.execute(
            "SELECT EXISTS(SELECT 1 FROM tailoring_sessions WHERE base_resume_version_id=?)",
            (version_id,),
        ).fetchone()
        return bool(row[0])

    def delete_version(self, version_id: int) -> None:
        with self._conn:
            row = self._conn.execute(
                "SELECT tailoring_session_id FROM resume_versions WHERE id=?",
                (version_id,),
            ).fetchone()
            tailoring_session_id = row["tailoring_session_id"] if row else None
            self._conn.execute("DELETE FROM resume_versions WHERE id=?", (version_id,))
            if tailoring_session_id is not None:
                remaining = self._conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM resume_versions WHERE tailoring_session_id=?)",
                    (tailoring_session_id,),
                ).fetchone()[0]
                if not remaining:
                    self._conn.execute(
                        "DELETE FROM tailoring_sessions WHERE id=?",
                        (tailoring_session_id,),
                    )

    def list_tailored_versions(self) -> list[tuple[Resume, ResumeVersion]]:
        rows = self._conn.execute(
            "SELECT id, resume_id FROM resume_versions "
            "WHERE tailoring_session_id IS NOT NULL ORDER BY created_at DESC, id DESC"
        ).fetchall()
        tailored: list[tuple[Resume, ResumeVersion]] = []
        for row in rows:
            resume = self.get(row["resume_id"])
            version = self.get_version(row["id"])
            if resume is not None and version is not None:
                tailored.append((resume, version))
        return tailored

    def latest_version(self, resume_id: int) -> ResumeVersion | None:
        row = self._conn.execute(
            "SELECT * FROM resume_versions WHERE resume_id=? ORDER BY version_no DESC LIMIT 1",
            (resume_id,),
        ).fetchone()
        return self._row_to_version(row) if row else None

    def latest_tailored_for(self, job_id: int, base_resume_version_id: int) -> ResumeVersion | None:
        """Latest applied version created from this job/base pair."""
        row = self._conn.execute(
            "SELECT rv.* FROM resume_versions rv "
            "JOIN tailoring_sessions ts ON ts.id=rv.tailoring_session_id "
            "WHERE ts.job_id=? AND ts.base_resume_version_id=? "
            "ORDER BY rv.created_at DESC, rv.id DESC LIMIT 1",
            (job_id, base_resume_version_id),
        ).fetchone()
        return self._row_to_version(row) if row else None

    # -- mapping -------------------------------------------------------------

    @staticmethod
    def _row_to_resume(row: sqlite3.Row) -> Resume:
        return Resume(
            id=row["id"],
            profile_id=row["profile_id"],
            name=row["name"],
            source=row["source"],
            source_filename=row["source_filename"] or "",
        )

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> ResumeVersion:
        return ResumeVersion(
            id=row["id"],
            resume_id=row["resume_id"],
            version_no=row["version_no"],
            label=row["label"],
            content=ResumeContent.model_validate(json.loads(row["content_json"])),
            raw_text=row["raw_text"],
            created_from_version_id=row["created_from_version_id"],
            tailoring_session_id=row["tailoring_session_id"],
            extraction_report=ExtractionReport.model_validate(
                json.loads(row["extraction_report_json"] or "{}")
            ),
            source_diagnosis=row["source_diagnosis"] or "",
            created_at=row["created_at"],
        )
