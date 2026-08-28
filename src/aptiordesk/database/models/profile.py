"""Candidate profile domain models (pydantic v2).

The profile is the structured source of truth for resume tailoring, cover
letters, and interview preparation. JSON columns in SQLite are validated
against these models on every read/write.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ContactInfo(_Model):
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    portfolio_url: str = ""
    github_url: str = ""


class WorkPreferences(_Model):
    target_titles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    work_mode: str = ""  # remote | hybrid | onsite | flexible
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = ""
    notes: str = ""


class WorkAuthorization(_Model):
    authorized_in: list[str] = Field(default_factory=list)
    needs_sponsorship: bool | None = None
    notes: str = ""


class Profile(_Model):
    id: int | None = None
    display_name: str = ""
    summary: str = ""
    contact: ContactInfo = Field(default_factory=ContactInfo)
    preferences: WorkPreferences = Field(default_factory=WorkPreferences)
    work_auth: WorkAuthorization = Field(default_factory=WorkAuthorization)
    #: Path -> origin ("manual", "extracted", "inferred"). A resume import must
    #: not silently overwrite a value the user set themselves, so it checks here.
    field_origin: dict[str, str] = Field(default_factory=dict)


# --- Profile items (one row per entry, discriminated by `kind`) ---------------


class WorkExperience(_Model):
    title: str = Field(default="", description="job title")
    organization: str = Field(default="", description="employer name")
    location: str = Field(default="", description="city, country")
    # Free-form ISO-ish, e.g. "2021-03" — user controlled, never reformatted.
    start_date: str = Field(default="", description="YYYY-MM or YYYY as written")
    end_date: str = Field(default="", description="YYYY-MM, or empty if this is the current role")
    description: str = Field(default="", description="role summary in the candidate's words")
    highlights: list[str] = Field(
        default_factory=list, description="one achievement bullet, copied verbatim"
    )


class Education(_Model):
    institution: str = Field(default="", description="school or university name")
    degree: str = Field(default="", description="e.g. BSc, MSc, PhD")
    field_of_study: str = Field(default="", description="e.g. Computer Science")
    start_date: str = Field(default="", description="YYYY if given")
    end_date: str = Field(default="", description="graduation year")
    details: str = Field(default="", description="honours, thesis, GPA if stated")


class Skill(_Model):
    name: str = Field(default="", description="a single skill, tool, or technology")
    level: str = Field(default="", description="only if the resume states one")
    category: str = Field(default="", description="e.g. Languages, Cloud")


class Project(_Model):
    name: str = Field(default="", description="project name")
    url: str = Field(default="", description="project URL if given")
    description: str = Field(default="", description="what it is")
    highlights: list[str] = Field(default_factory=list, description="a detail bullet")


class Certification(_Model):
    name: str = Field(default="", description="certification name")
    issuer: str = Field(default="", description="issuing body")
    date: str = Field(default="", description="date obtained")
    url: str = Field(default="", description="credential URL if given")


class Language(_Model):
    name: str = Field(default="", description="language name")
    proficiency: str = Field(default="", description="e.g. native, fluent, B2")


class SimpleEntry(_Model):
    """Generic entry for awards, publications, and volunteer experience."""

    title: str = Field(default="", description="title or name")
    organization: str = Field(default="", description="issuing or hosting organisation")
    date: str = Field(default="", description="date if given")
    description: str = Field(default="", description="detail if given")


ITEM_MODELS: dict[str, type[_Model]] = {
    "experience": WorkExperience,
    "education": Education,
    "skill": Skill,
    "project": Project,
    "certification": Certification,
    "language": Language,
    "award": SimpleEntry,
    "publication": SimpleEntry,
    "volunteer": SimpleEntry,
}


class ProfileItem(_Model):
    id: int | None = None
    profile_id: int
    kind: str
    sort_order: int = 0
    data: dict = Field(default_factory=dict)
    #: "manual" | "extracted" | "inferred" — where this entry came from.
    provenance: str = "manual"
    source_resume_version_id: int | None = None
    #: True once the user has edited this entry by hand. Protects it from being
    #: overwritten by a later resume import without explicit approval.
    user_edited: bool = False
    #: True when the AI produced this but it could not be found in the source
    #: document, so the user should confirm it.
    needs_review: bool = False

    def parsed(self) -> _Model:
        """Validate `data` against the model for this item's kind."""
        model = ITEM_MODELS.get(self.kind, SimpleEntry)
        return model.model_validate(self.data)
