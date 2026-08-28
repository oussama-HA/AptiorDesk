"""Job posting models and AI analysis schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RemoteType(StrEnum):
    UNKNOWN = "unknown"
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


class EmploymentType(StrEnum):
    UNKNOWN = "unknown"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"


class ExperienceLevel(StrEnum):
    UNKNOWN = "unknown"
    INTERNSHIP = "internship"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    EXECUTIVE = "executive"


class JobPosting(BaseModel):
    """A browser-captured job normalized before local persistence."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source: str = ""
    source_name: str = ""
    source_id: str = ""
    url: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    remote_type: RemoteType = RemoteType.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    experience_level: ExperienceLevel = ExperienceLevel.UNKNOWN
    description: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""
    posted_at: str = ""
    retrieved_at: str = ""
    also_on: list[str] = Field(default_factory=list)


class Job(BaseModel):
    """A saved job. ``raw_description`` is a snapshot taken at import time —
    listings get edited and taken down, and everything built from a job
    (tailoring, interview prep) must keep the text it was grounded in."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: int | None = None
    title: str = ""
    company: str = ""
    url: str = ""
    raw_description: str = ""

    #: "manual" for a pasted posting, otherwise the job source's id.
    source: str = "manual"
    source_name: str = ""
    source_id: str = ""
    location: str = ""
    remote_type: str = "unknown"
    employment_type: str = "unknown"
    experience_level: str = "unknown"
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""
    posted_at: str = ""
    retrieved_at: str = ""
    skills: list[str] = Field(default_factory=list)
    also_on: list[str] = Field(default_factory=list)
    hidden: bool = False

    @property
    def is_imported(self) -> bool:
        return self.source != "manual"


class JobExtraction(BaseModel):
    """Structured facts extracted from a job description. Every field must
    come from the posting itself — absent information stays empty."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    company: str = ""
    location: str = ""
    seniority: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    required_qualifications: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    tools_and_platforms: list[str] = Field(default_factory=list)
    education_requirements: list[str] = Field(default_factory=list)
    experience_requirements: str = ""
    work_authorization: str = ""
    salary_info: str = ""
    keywords: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    missing_or_ambiguous: list[str] = Field(default_factory=list)


class FitItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requirement: str = ""
    candidate_evidence: str = ""
    comment: str = ""


class FitFactor(BaseModel):
    """One measurable part of the deterministic Job Fit Ratio."""

    model_config = ConfigDict(extra="ignore")

    key: str
    label: str
    weight: int = Field(ge=0, le=100)
    score: int = Field(ge=0, le=100)
    matched_count: int = Field(default=0, ge=0)
    total_count: int = Field(default=0, ge=0)
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    explanation: str = ""


class JobFitRatio(BaseModel):
    """Transparent deterministic score for one job/resume-version pair."""

    model_config = ConfigDict(extra="ignore")

    job_id: int | None = None
    resume_version_id: int | None = None
    score: int = Field(default=0, ge=0, le=100)
    base_score: int = Field(default=0, ge=0, le=100)
    critical_penalty: int = Field(default=0, ge=0, le=100)
    scoring_version: str = "1.0"
    factors: list[FitFactor] = Field(default_factory=list)
    missing_critical: list[str] = Field(default_factory=list)
    methodology: str = ""
    created_at: str = ""


class JobFitComparison(BaseModel):
    """Current resume versus a tailored version for the same saved job."""

    current: JobFitRatio
    tailored: JobFitRatio | None = None

    @property
    def improvement(self) -> int | None:
        if self.tailored is None:
            return None
        return self.tailored.score - self.current.score


class JobFit(BaseModel):
    """Job-fit analysis grounded in the candidate's actual materials.
    The AI writes the evidence narrative but never chooses the numeric ratio;
    ``ratio`` is produced by AptiorDesk's deterministic local scorer."""

    model_config = ConfigDict(extra="ignore")

    strong_matches: list[FitItem] = Field(default_factory=list)
    partial_matches: list[FitItem] = Field(default_factory=list)
    missing_qualifications: list[FitItem] = Field(default_factory=list)
    transferable_experience: list[FitItem] = Field(default_factory=list)
    gaps_or_risks: list[str] = Field(default_factory=list)
    clarifications_needed: list[str] = Field(default_factory=list)
    keywords_to_include: list[str] = Field(default_factory=list)
    summary: str = ""
    methodology: str = ""
    ratio: JobFitRatio | None = None


class JobAnalysis(BaseModel):
    """A stored analysis run (extraction or fit) with provenance."""

    id: int | None = None
    job_id: int
    kind: str  # extraction | fit
    resume_version_id: int | None = None
    prompt_id: str = ""
    prompt_version: int = 0
    provider_snapshot: str = ""
    result: dict = Field(default_factory=dict)
    created_at: str = ""
