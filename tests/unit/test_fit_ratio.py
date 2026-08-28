from aptiordesk.database.models.job import Job, JobExtraction
from aptiordesk.database.models.profile import (
    Profile,
    Skill,
    WorkAuthorization,
    WorkExperience,
    WorkPreferences,
)
from aptiordesk.database.models.resume import Resume, ResumeContent, ResumeVersion
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.features.jobs.fit_ratio import calculate_job_fit_ratio


def _job() -> Job:
    return Job(
        id=7,
        title="Senior Product Designer",
        company="Example",
        location="London",
        remote_type="hybrid",
        experience_level="senior",
        skills=["Figma", "User research", "Design systems"],
        raw_description=(
            "We require Figma, user research, and design systems experience. "
            "Lead product discovery and maintain a shared design system. "
            "Candidates must be authorized to work without visa sponsorship."
        ),
    )


def _version(*skills: str, title: str = "Product Designer") -> ResumeVersion:
    return ResumeVersion(
        id=11,
        resume_id=3,
        content=ResumeContent(
            professional_title=title,
            location="London",
            skills=[Skill(name=value) for value in skills],
            experiences=[
                WorkExperience(
                    title=title,
                    organization="Studio",
                    description="Led product discovery and user research.",
                    highlights=["Built reusable interface patterns for a product team."],
                )
            ],
        ),
    )


def test_ratio_is_deterministic_and_exposes_factor_evidence():
    extraction = JobExtraction(
        seniority="senior",
        responsibilities=[
            "Lead product discovery",
            "Maintain a shared design system",
        ],
        technical_skills=["Figma", "User research", "Design systems"],
        work_authorization="Must be authorized without visa sponsorship",
        keywords=["product discovery", "prototyping"],
    )
    profile = Profile(
        preferences=WorkPreferences(
            preferred_locations=["London"],
            work_mode="hybrid",
        ),
        work_auth=WorkAuthorization(needs_sponsorship=False),
    )
    version = _version("Figma", "User research", "Design systems", title="Senior Product Designer")

    first = calculate_job_fit_ratio(_job(), version, extraction=extraction, profile=profile)
    second = calculate_job_fit_ratio(_job(), version, extraction=extraction, profile=profile)

    assert first.score == second.score
    assert first.score >= 70
    assert sum(factor.weight for factor in first.factors) == 100
    required = next(factor for factor in first.factors if factor.key == "required_skills")
    assert required.total_count >= 3
    assert "Figma" in required.matched
    assert "not an ATS score" in first.methodology


def test_supported_tailoring_improves_score_without_ai_generated_number():
    extraction = JobExtraction(
        seniority="senior",
        responsibilities=["Lead product discovery", "Maintain a shared design system"],
        technical_skills=["Figma", "User research", "Design systems"],
        keywords=["product discovery", "design systems"],
    )
    current = _version("Figma")
    tailored = _version(
        "Figma",
        "User research",
        "Design systems",
        title="Senior Product Designer",
    )
    tailored.id = 12

    before = calculate_job_fit_ratio(_job(), current, extraction=extraction)
    after = calculate_job_fit_ratio(_job(), tailored, extraction=extraction)

    assert after.score > before.score
    assert after.score - before.score >= 10
    assert before.missing_critical


def test_ratio_persistence_round_trip(conn):
    jobs = JobRepository(conn)
    resumes = ResumeRepository(conn)
    job = jobs.create(_job().model_copy(update={"id": None}))
    resume = resumes.create(Resume(name="Main resume"))
    version = resumes.add_version(
        resume.id,
        _version("Figma", "User research").content,
        label="Current",
    )
    ratio = calculate_job_fit_ratio(job, version)

    saved = jobs.save_fit_ratio(ratio)
    loaded = jobs.get_fit_ratio(job.id, version.id)

    assert loaded is not None
    assert loaded.score == saved.score
    assert loaded.factors == saved.factors
