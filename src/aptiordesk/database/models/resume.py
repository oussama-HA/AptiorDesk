"""Resume domain models.

A ``Resume`` is a named document with immutable ``ResumeVersion`` rows; the
structured ``ResumeContent`` reuses the profile item models so profile and
resume speak the same schema.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aptiordesk.database.models.extraction import ExtractionReport
from aptiordesk.database.models.profile import (
    Certification,
    Education,
    Language,
    Project,
    SimpleEntry,
    Skill,
    WorkExperience,
)


class ResumeContent(BaseModel):
    """The structured body of one resume version. Also used as the AI
    extraction schema when importing a resume file."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    full_name: str = Field(default="", description="the candidate's full name")
    professional_title: str = Field(
        default="", description="headline job title, e.g. Senior Data Engineer"
    )
    email: str = Field(default="", description="email address")
    phone: str = Field(default="", description="phone number")
    location: str = Field(default="", description="city and country")
    linkedin_url: str = Field(default="", description="LinkedIn URL")
    portfolio_url: str = Field(default="", description="portfolio or personal website")
    github_url: str = Field(default="", description="GitHub URL")
    summary: str = Field(default="", description="professional summary, in the candidate's words")
    experiences: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    awards: list[SimpleEntry] = Field(default_factory=list)
    publications: list[SimpleEntry] = Field(default_factory=list)
    volunteer: list[SimpleEntry] = Field(default_factory=list)
    #: Retained so resume versions written before awards/publications/volunteer
    #: existed still round-trip; new extractions use the specific lists.
    other: list[SimpleEntry] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """True when nothing of substance was captured.

        Every field is optional so that partial extraction is possible, which
        means an all-defaults instance validates cleanly. Callers must use this
        to tell "the model returned nothing usable" from a real result.
        """
        return not any(
            (
                self.full_name.strip(),
                self.email.strip(),
                self.phone.strip(),
                self.summary.strip(),
                self.experiences,
                self.education,
                self.skills,
                self.projects,
                self.certifications,
                self.languages,
                self.awards,
                self.publications,
                self.volunteer,
                self.other,
            )
        )


class Resume(BaseModel):
    id: int | None = None
    profile_id: int | None = None
    name: str = ""
    source: str = "manual"  # manual | imported
    source_filename: str = ""


class ResumeVersion(BaseModel):
    id: int | None = None
    resume_id: int
    version_no: int = 1
    label: str = ""
    content: ResumeContent = Field(default_factory=ResumeContent)
    raw_text: str = ""
    created_from_version_id: int | None = None
    tailoring_session_id: int | None = None
    #: Provenance of the AI extraction that produced this version, kept so the
    #: review screen can be reopened long after the import.
    extraction_report: ExtractionReport = Field(default_factory=ExtractionReport)
    source_diagnosis: str = ""
    created_at: str = ""
