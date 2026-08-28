"""Job description analysis: structured extraction and grounded fit reports."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from aptiordesk.ai.base import AIProvider, ChatMessage, Role
from aptiordesk.ai.prompts.engine import get_template
from aptiordesk.ai.prompts.guards import FABRICATION_RULES, UNTRUSTED_PREAMBLE, wrap_untrusted
from aptiordesk.database.models.job import (
    Job,
    JobAnalysis,
    JobExtraction,
    JobFit,
    JobFitComparison,
    JobFitRatio,
    JobPosting,
)
from aptiordesk.database.models.resume import ResumeVersion
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.database.repositories.tailoring_repo import TailoringRepository
from aptiordesk.documents.render import resume_to_markdown
from aptiordesk.features.jobs.fit_ratio import calculate_job_fit_ratio

log = logging.getLogger(__name__)

MIN_JD_LENGTH = 80


@dataclass(frozen=True)
class GeneratedJobAnalysis:
    """AI output prepared off-thread but not yet written to SQLite.

    SQLite connections are thread-affine.  Keeping this value entirely made
    of Pydantic models lets a worker perform the slow provider call, then hand
    the result to the UI thread for persistence through its own connection.
    """

    job: Job
    analysis: JobAnalysis
    result: JobExtraction | JobFit


class JobService:
    def __init__(self, conn: sqlite3.Connection):
        self._repo = JobRepository(conn)
        self._profiles = ProfileRepository(conn)
        self._resumes = ResumeRepository(conn)
        self._tailoring = TailoringRepository(conn)

    def create_job(self, raw_description: str, url: str = "") -> Job:
        raw_description = (raw_description or "").strip()
        if len(raw_description) < MIN_JD_LENGTH:
            raise ValueError(
                f"The job description is too short to analyze (minimum {MIN_JD_LENGTH} characters)."
            )
        return self._repo.create(Job(raw_description=raw_description, url=url))

    def import_posting(self, posting: JobPosting) -> tuple[Job, bool]:
        """Save a browser-captured posting. Returns (job, was_already_saved).

        Re-importing the same listing refreshes it in place rather than
        creating a second copy, but never discards a description that is
        already stored in favour of an emptier one — the snapshot is the point.
        """
        existing = self._repo.find_by_source(posting.source, posting.source_id)
        job = Job(
            id=existing.id if existing else None,
            title=posting.title,
            company=posting.company,
            url=posting.url,
            raw_description=posting.description or (existing.raw_description if existing else ""),
            source=posting.source,
            source_name=posting.source_name,
            source_id=posting.source_id,
            location=posting.location,
            remote_type=str(posting.remote_type),
            employment_type=str(posting.employment_type),
            experience_level=str(posting.experience_level),
            salary_min=posting.salary_min,
            salary_max=posting.salary_max,
            salary_currency=posting.salary_currency,
            salary_period=posting.salary_period,
            posted_at=posting.posted_at,
            retrieved_at=posting.retrieved_at,
            skills=list(posting.skills),
            also_on=list(posting.also_on),
        )
        if existing:
            self._repo.update(job)
            return job, True
        return self._repo.create(job), False

    def analyze(self, provider: AIProvider, job: Job) -> JobExtraction:
        """Synchronous compatibility wrapper: generate, then persist."""
        generated = self.generate_analysis(provider, job)
        return self.persist_generated_analysis(generated)

    @staticmethod
    def generate_analysis(provider: AIProvider, job: Job) -> GeneratedJobAnalysis:
        """Run job extraction without accessing SQLite; safe in a worker thread."""
        template = get_template("job_extraction")
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            jd_block=wrap_untrusted(job.raw_description, "JOB DESCRIPTION"),
        )
        extraction = provider.structured(
            [ChatMessage(Role.USER, prompt)], JobExtraction, temperature=0.2
        )
        return GeneratedJobAnalysis(
            job=job,
            result=extraction,
            analysis=JobAnalysis(
                job_id=job.id,
                kind="extraction",
                prompt_id=template.id,
                prompt_version=template.version,
                provider_snapshot=f"{provider.config.kind}:{provider.config.model}",
                result=extraction.model_dump(),
            ),
        )

    def fit_analysis(self, provider: AIProvider, job: Job, resume_version: ResumeVersion) -> JobFit:
        """Synchronous compatibility wrapper: generate, then persist."""
        ratio = self.calculate_fit_ratio(job, resume_version)
        generated = self.generate_fit_analysis(provider, job, resume_version, ratio)
        return self.persist_generated_analysis(generated)

    def calculate_fit_ratio(self, job: Job, resume_version: ResumeVersion) -> JobFitRatio:
        """Calculate and persist the local, deterministic ratio on the owner thread."""
        extraction_row = self._repo.latest_analysis(job.id, "extraction")
        extraction = (
            JobExtraction.model_validate(extraction_row.result)
            if extraction_row is not None
            else None
        )
        profile = self._profiles.get_default()
        ratio = calculate_job_fit_ratio(
            job,
            resume_version,
            extraction=extraction,
            profile=profile,
        )
        return self._repo.save_fit_ratio(ratio)

    def fit_comparison(self, job: Job, selected_version: ResumeVersion) -> JobFitComparison:
        """Resolve current/tailored versions and score both with one method."""
        base = selected_version
        tailored = None
        if selected_version.tailoring_session_id is not None:
            session = self._tailoring.get_session(selected_version.tailoring_session_id)
            if session is not None and session.job_id == job.id:
                base = self._resumes.get_version(session.base_resume_version_id) or selected_version
                tailored = selected_version
        else:
            tailored = self._resumes.latest_tailored_for(job.id, selected_version.id)

        current_ratio = self.calculate_fit_ratio(job, base)
        tailored_ratio = self.calculate_fit_ratio(job, tailored) if tailored is not None else None
        return JobFitComparison(current=current_ratio, tailored=tailored_ratio)

    @staticmethod
    def generate_fit_analysis(
        provider: AIProvider,
        job: Job,
        resume_version: ResumeVersion,
        ratio: JobFitRatio | None = None,
    ) -> GeneratedJobAnalysis:
        """Run fit comparison without accessing SQLite; safe in a worker thread."""
        template = get_template("job_fit")
        resume_md = resume_to_markdown(resume_version.content)
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            fabrication_rules=FABRICATION_RULES,
            jd_block=wrap_untrusted(job.raw_description, "JOB DESCRIPTION"),
            resume_block=wrap_untrusted(resume_md, "RESUME"),
        )
        fit = provider.structured([ChatMessage(Role.USER, prompt)], JobFit, temperature=0.3)
        fit.ratio = ratio or calculate_job_fit_ratio(job, resume_version)
        return GeneratedJobAnalysis(
            job=job,
            result=fit,
            analysis=JobAnalysis(
                job_id=job.id,
                kind="fit",
                resume_version_id=resume_version.id,
                prompt_id=template.id,
                prompt_version=template.version,
                provider_snapshot=f"{provider.config.kind}:{provider.config.model}",
                result=fit.model_dump(),
            ),
        )

    def persist_generated_analysis(self, generated: GeneratedJobAnalysis) -> JobExtraction | JobFit:
        """Persist a generated result using the caller thread's connection."""
        self._repo.add_analysis(generated.analysis)
        if generated.analysis.kind == "extraction" and isinstance(generated.result, JobExtraction):
            # Fill headline fields only when the saved job did not already
            # provide them (browser imports normally do).
            if generated.result.title and not generated.job.title:
                generated.job.title = generated.result.title
            if generated.result.company and not generated.job.company:
                generated.job.company = generated.result.company
            self._repo.update(generated.job)
        return generated.result


__all__ = ["GeneratedJobAnalysis", "JobService"]
