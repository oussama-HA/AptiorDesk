"""Read-only workspace summary built from active AptiorDesk domains."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from aptiordesk.database.repositories.profile_repo import ProfileRepository


@dataclass(frozen=True)
class DashboardSnapshot:
    profile_items: int
    resumes: int
    jobs: int
    analyzed_jobs: int
    tailoring_sessions: int
    cover_letters: int
    interview_sessions: int
    next_title: str
    next_detail: str
    next_destination: str


class DashboardService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def snapshot(self) -> DashboardSnapshot:
        profile = ProfileRepository(self._conn).get_default()
        profile_items = self._count("profile_items")
        counts = {
            "resumes": self._count("resumes"),
            "jobs": self._count("jobs", "hidden = 0"),
            "analyzed_jobs": self._distinct_count("job_analyses", "job_id"),
            "tailoring_sessions": self._count("tailoring_sessions"),
            "cover_letters": self._count("cover_letters"),
            "interview_sessions": self._count("interview_sessions"),
        }

        if not (profile.display_name or profile.summary or profile_items):
            recommendation = (
                "Build your candidate profile",
                "Add verified experience, education, and skills so every AI workflow has reliable evidence.",
                "Profile",
            )
        elif counts["resumes"] == 0:
            recommendation = (
                "Import your strongest resume",
                "A reviewed base resume unlocks job-fit analysis, tailoring, and grounded cover letters.",
                "Resumes",
            )
        elif counts["jobs"] == 0:
            recommendation = (
                "Capture a job from your browser",
                "Open a posting, use the AptiorDesk extension sidebar, and save the visible job details.",
                "Jobs",
            )
        elif counts["analyzed_jobs"] < counts["jobs"]:
            recommendation = (
                "Analyze a captured job",
                "Turn the posting into structured requirements before deciding how to tailor your materials.",
                "Jobs",
            )
        elif counts["tailoring_sessions"] == 0:
            recommendation = (
                "Tailor your resume to a role",
                "Start from a captured job and review every evidence-backed suggestion before applying it.",
                "Jobs",
            )
        elif counts["interview_sessions"] == 0:
            recommendation = (
                "Practice for the interview",
                "Generate role-specific questions and rehearse answers grounded in your real experience.",
                "Interview",
            )
        else:
            recommendation = (
                "Review your latest captured role",
                "Keep the job snapshot, analysis, tailored resume, and interview preparation aligned.",
                "Jobs",
            )

        return DashboardSnapshot(
            profile_items=profile_items,
            next_title=recommendation[0],
            next_detail=recommendation[1],
            next_destination=recommendation[2],
            **counts,
        )

    def _count(self, table: str, where: str = "") -> int:
        suffix = f" WHERE {where}" if where else ""
        return int(
            self._conn.execute(
                f'SELECT COUNT(*) FROM "{table}"{suffix}'  # noqa: S608 - schema-owned names
            ).fetchone()[0]
        )

    def _distinct_count(self, table: str, column: str) -> int:
        return int(
            self._conn.execute(
                f'SELECT COUNT(DISTINCT "{column}") FROM "{table}"'  # noqa: S608
            ).fetchone()[0]
        )


__all__ = ["DashboardService", "DashboardSnapshot"]
