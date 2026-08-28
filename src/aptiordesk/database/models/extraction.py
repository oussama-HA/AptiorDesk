"""Provenance for AI-extracted data.

Every value the AI produces is classified against the source document rather
than against the model's own confidence claim. Models are unreliable narrators
about their own certainty, but "does this string actually occur in the source
text?" is a question with a deterministic answer.

- ``EXTRACTED`` — found in the source document, so it is the candidate's own
  information.
- ``INFERRED``  — the model produced it but it is not in the source. It may be
  a reasonable normalisation ("Jan 2021" -> "2021-01") or a fabrication. Either
  way the user must confirm it; it is never saved silently.
- ``MISSING``   — absent, for the user to fill in if they want to.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Provenance(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    MISSING = "missing"


class FieldNote(BaseModel):
    """Provenance for one field, addressed by a dotted path.

    Paths mirror the ``ResumeContent`` structure, e.g. ``full_name``,
    ``experiences.0.title``, ``experiences.0.highlights.1``.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    provenance: Provenance
    value_preview: str = ""
    reason: str = ""

    @property
    def needs_review(self) -> bool:
        return self.provenance is Provenance.INFERRED


class SectionOutcome(BaseModel):
    """What happened to one section of the extraction.

    Sections are extracted independently, so one failure does not lose the
    rest — which is the whole reason extraction is split up.
    """

    name: str
    ok: bool = True
    item_count: int = 0
    error: str = ""
    raw_output: str = ""

    def summary(self) -> str:
        if self.ok:
            return f"{self.name}: {self.item_count} found"
        return f"{self.name}: failed — {self.error}"


class ExtractionReport(BaseModel):
    """The full account of one resume extraction, shown on the review screen."""

    model_config = ConfigDict(extra="ignore")

    source_filename: str = ""
    source_chars: int = 0
    diagnosis: str = "ok"
    diagnosis_message: str = ""
    document_warnings: list[str] = Field(default_factory=list)
    sections: list[SectionOutcome] = Field(default_factory=list)
    notes: list[FieldNote] = Field(default_factory=list)
    model: str = ""
    prompt_version: int = 0

    # -- queries used by the review UI ---------------------------------------

    def inferred(self) -> list[FieldNote]:
        """Fields the user must confirm — not found verbatim in the document."""
        return [n for n in self.notes if n.provenance is Provenance.INFERRED]

    def missing(self) -> list[FieldNote]:
        return [n for n in self.notes if n.provenance is Provenance.MISSING]

    def failed_sections(self) -> list[SectionOutcome]:
        return [s for s in self.sections if not s.ok]

    def provenance_for(self, path: str) -> Provenance:
        for note in self.notes:
            if note.path == path:
                return note.provenance
        return Provenance.MISSING

    @property
    def any_content(self) -> bool:
        return any(s.ok and s.item_count for s in self.sections)

    def headline(self) -> str:
        """One line summarising the extraction for the review screen."""
        if not self.any_content:
            return "Nothing could be extracted from this document."
        found = sum(s.item_count for s in self.sections if s.ok)
        parts = [f"{found} item(s) extracted"]
        if self.inferred():
            parts.append(f"{len(self.inferred())} need checking")
        if self.failed_sections():
            parts.append(f"{len(self.failed_sections())} section(s) failed")
        return ", ".join(parts) + "."
