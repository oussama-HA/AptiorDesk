"""Cover letter models and the AI generation schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

TONES: dict[str, str] = {
    "professional": "Polished and businesslike; the safe default.",
    "warm": "Personable and human, without being informal.",
    "concise": "Direct and economical; every sentence earns its place.",
    "confident": "Assertive about demonstrated strengths, never boastful.",
    "conversational": "Natural and plain-spoken, as if writing to a colleague.",
    "executive": "Strategic register; scope, ownership, and business outcomes.",
    "technical": "Precise about technologies and engineering substance.",
    "mission_driven": "Leads with motivation and alignment to the organization's purpose.",
}

LENGTHS: dict[str, str] = {
    "short": "About 150-200 words; three tight paragraphs.",
    "standard": "About 250-350 words; opening, two body paragraphs, close.",
    "detailed": "About 400-500 words; allows a third body paragraph.",
}


class CoverLetterInputs(BaseModel):
    """User-supplied context for one generation run."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tone: str = "professional"
    length: str = "standard"
    company_notes: str = ""
    motivation: str = ""
    personal_connection: str = ""
    hiring_manager: str = ""


class CoverLetterDraft(BaseModel):
    """AI output: the letter plus an explanation of what it selected."""

    model_config = ConfigDict(extra="ignore")

    body_markdown: str = ""
    selected_experiences: list[str] = Field(default_factory=list)
    selection_rationale: str = ""
    claims_needing_confirmation: list[str] = Field(default_factory=list)


class CoverLetter(BaseModel):
    id: int | None = None
    job_id: int
    resume_version_id: int | None = None
    tone: str = "professional"
    length: str = "standard"


class CoverLetterVersion(BaseModel):
    id: int | None = None
    cover_letter_id: int
    version_no: int = 1
    label: str = ""
    content_md: str = ""
    rationale: dict = Field(default_factory=dict)
    created_at: str = ""
