"""Tailoring session models and the AI suggestion schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STRATEGIES: dict[str, str] = {
    "balanced": "General-purpose: clear, achievement-oriented, honest.",
    "ats": "ATS-focused: mirror the posting's terminology precisely where truthful; "
    "plain phrasing; no tables or graphics implied.",
    "recruiter": "Recruiter-friendly: lead with impact and scope; scannable bullets.",
    "technical": "Technical: emphasize concrete technologies, architecture and depth.",
    "executive": "Executive: emphasize leadership scope, strategy, and business outcomes.",
    "career_change": "Career change: foreground transferable skills and bridge language.",
    "entry_level": "Entry-level: emphasize education, projects, internships, potential.",
}


class TailoringSession(BaseModel):
    id: int | None = None
    job_id: int
    base_resume_version_id: int
    strategy: str = "balanced"
    status: str = "draft"  # draft | applied | discarded


class SuggestionModel(BaseModel):
    """One proposed change from the AI, targeting a single string field in the
    resume content via a JSON-pointer path (e.g. "/experiences/0/highlights/1")."""

    model_config = ConfigDict(extra="ignore")

    operation: Literal["replace", "add_skill"] = "replace"
    target_path: str = ""
    original_text: str = ""
    suggested_text: str = ""
    skill_category: str = ""
    rationale: str = ""
    jd_evidence: str = ""
    profile_evidence: str = ""


class SuggestionList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    suggestions: list[SuggestionModel] = Field(default_factory=list)


class Suggestion(SuggestionModel):
    """A persisted suggestion with review state."""

    id: int | None = None
    session_id: int = 0
    warnings: str = ""
    status: str = "pending"  # pending | accepted | rejected | edited
    edited_text: str = ""

    def final_text(self) -> str:
        return self.edited_text if self.status == "edited" else self.suggested_text
