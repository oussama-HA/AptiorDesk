"""Persistence for job postings and their stored analyses."""

from __future__ import annotations

import json
import sqlite3

from aptiordesk.database.models.job import Job, JobAnalysis, JobFitRatio
from aptiordesk.database.repositories._util import now_iso


class JobRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def list(self, *, include_hidden: bool = False) -> list[Job]:
        sql = "SELECT * FROM jobs {} ORDER BY updated_at DESC".format(
            "" if include_hidden else "WHERE hidden = 0"
        )
        return [self._row_to_job(r) for r in self._conn.execute(sql).fetchall()]

    def find_by_source(self, source: str, source_id: str) -> Job | None:
        """Look up a listing already imported from a search result."""
        if not source_id:
            return None
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE source=? AND source_id=?", (source, source_id)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def set_hidden(self, job_id: int, hidden: bool) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE jobs SET hidden=?, updated_at=? WHERE id=?",
                (int(hidden), now_iso(), job_id),
            )

    def get(self, job_id: int) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    _COLUMNS = (
        "title",
        "company",
        "url",
        "raw_description",
        "source",
        "source_name",
        "source_id",
        "location",
        "remote_type",
        "employment_type",
        "experience_level",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        "posted_at",
        "retrieved_at",
        "skills_json",
        "also_on_json",
    )

    def _values(self, job: Job) -> tuple:
        return (
            job.title,
            job.company,
            job.url,
            job.raw_description,
            job.source,
            job.source_name,
            job.source_id,
            job.location,
            job.remote_type,
            job.employment_type,
            job.experience_level,
            job.salary_min,
            job.salary_max,
            job.salary_currency,
            job.salary_period,
            job.posted_at,
            job.retrieved_at,
            json.dumps(job.skills),
            json.dumps(job.also_on),
        )

    def create(self, job: Job) -> Job:
        ts = now_iso()
        placeholders = ",".join("?" for _ in self._COLUMNS)
        with self._conn:
            cur = self._conn.execute(
                f"INSERT INTO jobs({','.join(self._COLUMNS)}, created_at, updated_at) "  # noqa: S608
                f"VALUES({placeholders},?,?)",
                (*self._values(job), ts, ts),
            )
        job.id = cur.lastrowid
        return job

    def update(self, job: Job) -> None:
        assignments = ",".join(f"{c}=?" for c in self._COLUMNS)
        with self._conn:
            self._conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at=? WHERE id=?",  # noqa: S608
                (*self._values(job), now_iso(), job.id),
            )

    def delete(self, job_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    # -- analyses ------------------------------------------------------------

    def add_analysis(self, analysis: JobAnalysis) -> JobAnalysis:
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO job_analyses(job_id, kind, resume_version_id, prompt_id, "
                "prompt_version, provider_snapshot, result_json, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    analysis.job_id,
                    analysis.kind,
                    analysis.resume_version_id,
                    analysis.prompt_id,
                    analysis.prompt_version,
                    analysis.provider_snapshot,
                    json.dumps(analysis.result),
                    ts,
                ),
            )
        analysis.id = cur.lastrowid
        analysis.created_at = ts
        return analysis

    def latest_analysis(self, job_id: int, kind: str) -> JobAnalysis | None:
        row = self._conn.execute(
            "SELECT * FROM job_analyses WHERE job_id=? AND kind=? ORDER BY id DESC LIMIT 1",
            (job_id, kind),
        ).fetchone()
        return self._row_to_analysis(row) if row else None

    def latest_fit_analysis(self, job_id: int, resume_version_id: int) -> JobAnalysis | None:
        """Latest fit result for this exact resume version.

        Keyword recommendations are evidence-dependent. Reusing a fit run from
        a different resume could turn an unsupported term into a tailoring
        instruction, so callers must match both sides of the comparison.
        """
        row = self._conn.execute(
            "SELECT * FROM job_analyses WHERE job_id=? AND kind='fit' "
            "AND resume_version_id=? ORDER BY id DESC LIMIT 1",
            (job_id, resume_version_id),
        ).fetchone()
        return self._row_to_analysis(row) if row else None

    # -- deterministic Job Fit Ratio ----------------------------------------

    def save_fit_ratio(self, ratio: JobFitRatio) -> JobFitRatio:
        """Upsert one reproducible score for a job/resume/scoring version."""
        if ratio.job_id is None or ratio.resume_version_id is None:
            raise ValueError("A Job Fit Ratio requires saved job and resume version ids")
        ts = now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO job_fit_ratios(job_id, resume_version_id, scoring_version, "
                "score, result_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id, resume_version_id, scoring_version) DO UPDATE SET "
                "score=excluded.score, result_json=excluded.result_json, "
                "updated_at=excluded.updated_at",
                (
                    ratio.job_id,
                    ratio.resume_version_id,
                    ratio.scoring_version,
                    ratio.score,
                    ratio.model_dump_json(exclude={"created_at"}),
                    ts,
                    ts,
                ),
            )
        ratio.created_at = ts
        return ratio

    def get_fit_ratio(
        self, job_id: int, resume_version_id: int, scoring_version: str = "1.0"
    ) -> JobFitRatio | None:
        row = self._conn.execute(
            "SELECT result_json, created_at FROM job_fit_ratios "
            "WHERE job_id=? AND resume_version_id=? AND scoring_version=?",
            (job_id, resume_version_id, scoring_version),
        ).fetchone()
        if row is None:
            return None
        ratio = JobFitRatio.model_validate_json(row["result_json"])
        ratio.created_at = row["created_at"]
        return ratio

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            title=row["title"],
            company=row["company"],
            url=row["url"],
            raw_description=row["raw_description"],
            source=row["source"],
            source_name=row["source_name"],
            source_id=row["source_id"],
            location=row["location"],
            remote_type=row["remote_type"],
            employment_type=row["employment_type"],
            experience_level=row["experience_level"],
            salary_min=row["salary_min"],
            salary_max=row["salary_max"],
            salary_currency=row["salary_currency"],
            salary_period=row["salary_period"],
            posted_at=row["posted_at"],
            retrieved_at=row["retrieved_at"],
            skills=json.loads(row["skills_json"] or "[]"),
            also_on=json.loads(row["also_on_json"] or "[]"),
            hidden=bool(row["hidden"]),
        )

    @staticmethod
    def _row_to_analysis(row: sqlite3.Row) -> JobAnalysis:
        return JobAnalysis(
            id=row["id"],
            job_id=row["job_id"],
            kind=row["kind"],
            resume_version_id=row["resume_version_id"],
            prompt_id=row["prompt_id"],
            prompt_version=row["prompt_version"],
            provider_snapshot=row["provider_snapshot"],
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
        )
