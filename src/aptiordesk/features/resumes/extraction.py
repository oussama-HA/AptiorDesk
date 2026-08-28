"""Section-wise resume extraction with provenance.

Why not one call? The previous implementation asked for the entire resume in a
single structured response. Three things went wrong with that:

* The output routinely exceeded the 2048-token default budget and was cut off.
  A truncated JSON object is worse than an error, because the balanced-scan
  recovery in ``prompts.parsing`` can salvage a shorter valid object from it,
  which then validates as a mostly-empty result and looks like "nothing found".
* One malformed section lost the whole extraction.
* The combined schema was large enough that small local models lost track of
  it and invented their own key names.

Extracting section by section fixes all three: each response is small, a
failure is contained to its own section, and each schema is a handful of
fields. The cost is more round-trips, which for a local model is cheap and for
a cloud model is a few cents.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aptiordesk.ai.base import AIProvider, ChatMessage, Role
from aptiordesk.ai.prompts.engine import get_template
from aptiordesk.ai.prompts.grounding import classify
from aptiordesk.ai.prompts.guards import UNTRUSTED_PREAMBLE, wrap_untrusted
from aptiordesk.database.models.extraction import ExtractionReport, SectionOutcome
from aptiordesk.database.models.provider import ProviderKind
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.documents.pipeline import ExtractionResult
from aptiordesk.features.resumes.extraction_contract import (
    ExtractedCertification,
    ExtractedEducation,
    ExtractedLanguage,
    ExtractedProject,
    ExtractedSimpleEntry,
    ExtractedSkill,
    ExtractedWorkExperience,
    normalise_contact,
    normalise_section,
)

log = logging.getLogger(__name__)


# --- per-section schemas ------------------------------------------------------
# Small and flat on purpose: each is what one AI call must return.


class _Section(BaseModel):
    # Unknown keys at the AI boundary are a validation error, not disposable
    # metadata.  AIProvider.structured will repair the response and expose a
    # section failure if it still cannot satisfy the contract.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContactSection(_Section):
    full_name: str = Field(default="", description="the candidate's full name")
    professional_title: str = Field(
        default="", description="headline title, e.g. Senior Data Engineer"
    )
    email: str = Field(default="", description="email address")
    phone: str = Field(default="", description="phone number")
    location: str = Field(default="", description="city and country")
    linkedin_url: str = Field(default="", description="LinkedIn URL")
    github_url: str = Field(default="", description="GitHub URL")
    portfolio_url: str = Field(default="", description="portfolio or personal site")
    summary: str = Field(default="", description="the summary/profile paragraph, copied verbatim")

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return normalise_contact(value)


class ExperienceSection(_Section):
    experiences: list[ExtractedWorkExperience] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return normalise_section(
            value,
            primary_field="experiences",
            aliases={
                "experience": "experiences",
                "work_experience": "experiences",
                "work_experiences": "experiences",
                "work_history": "experiences",
                "employment": "experiences",
                "employment_history": "experiences",
                "jobs": "experiences",
                "roles": "experiences",
            },
            list_fields={"experiences": (ExtractedWorkExperience, False)},
        )


class EducationSection(_Section):
    education: list[ExtractedEducation] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return normalise_section(
            value,
            primary_field="education",
            aliases={
                "educations": "education",
                "academic_background": "education",
                "academic_history": "education",
                "degrees": "education",
                "qualifications": "education",
            },
            list_fields={"education": (ExtractedEducation, False)},
        )


class SkillsSection(_Section):
    skills: list[ExtractedSkill] = Field(default_factory=list)
    certifications: list[ExtractedCertification] = Field(default_factory=list)
    languages: list[ExtractedLanguage] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return normalise_section(
            value,
            primary_field="skills",
            aliases={
                "technical_skills": "skills",
                "core_skills": "skills",
                "competencies": "skills",
                "technologies": "skills",
                "tools": "skills",
                "certificates": "certifications",
                "credentials": "certifications",
                "spoken_languages": "languages",
                "human_languages": "languages",
            },
            list_fields={
                "skills": (ExtractedSkill, True),
                "certifications": (ExtractedCertification, True),
                "languages": (ExtractedLanguage, True),
            },
        )


class ExtrasSection(_Section):
    projects: list[ExtractedProject] = Field(default_factory=list)
    awards: list[ExtractedSimpleEntry] = Field(default_factory=list)
    publications: list[ExtractedSimpleEntry] = Field(default_factory=list)
    volunteer: list[ExtractedSimpleEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return normalise_section(
            value,
            primary_field="projects",
            aliases={
                "personal_projects": "projects",
                "honors": "awards",
                "honours": "awards",
                "volunteering": "volunteer",
                "volunteer_experience": "volunteer",
            },
            list_fields={
                "projects": (ExtractedProject, False),
                "awards": (ExtractedSimpleEntry, False),
                "publications": (ExtractedSimpleEntry, False),
                "volunteer": (ExtractedSimpleEntry, False),
            },
        )


@dataclass(frozen=True)
class SectionSpec:
    key: str
    label: str
    schema: type[_Section]
    instructions: str
    #: Output budget floor. Experience is by far the longest section, so it
    #: gets the largest; the point is that the configured default (2048) can
    #: never silently truncate a section.
    min_tokens: int


SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec(
        key="contact",
        label="contact details, headline title, and professional summary",
        schema=ContactSection,
        instructions=(
            "Take the summary text verbatim from the resume's summary, profile, "
            "or objective section. If there is no such section, leave summary "
            "empty rather than writing one."
        ),
        min_tokens=800,
    ),
    SectionSpec(
        key="experience",
        label="work experience",
        schema=ExperienceSection,
        instructions=(
            "List every role in the order it appears. Include internships and "
            "contract roles.\n"
            "- Each role is one entry, even when several roles share an employer: "
            "a promotion is two entries with the same organization.\n"
            "- Copy each achievement bullet verbatim into highlights, one bullet "
            "per list element. Do not merge, split, summarise, or reword them.\n"
            "- If a role has prose rather than bullets, put it in description and "
            "leave highlights empty."
        ),
        min_tokens=3000,
    ),
    SectionSpec(
        key="education",
        label="education",
        schema=EducationSection,
        instructions=(
            "Include degrees, diplomas, and formal programmes. Professional "
            "certifications belong to the certifications section, not here."
        ),
        min_tokens=800,
    ),
    SectionSpec(
        key="skills",
        label="skills, tools, technologies, certifications, and languages",
        schema=SkillsSection,
        instructions=(
            "- Split skill lists into one entry per skill. 'Python, SQL, Spark' "
            "is three entries, not one.\n"
            "- Use the resume's own grouping heading as the category when it has "
            "one; otherwise leave category empty.\n"
            "- Only set level when the resume states one explicitly.\n"
            "- languages means human languages (English, Arabic), not "
            "programming languages — those are skills."
        ),
        min_tokens=1500,
    ),
    SectionSpec(
        key="extras",
        label="projects, awards, publications, and volunteer experience",
        schema=ExtrasSection,
        instructions=(
            "These sections are often absent. Returning empty lists is the "
            "correct answer when the resume has none of them — do not "
            "redistribute work experience into projects to fill them."
        ),
        min_tokens=1500,
    ),
)


class ExtractionError(Exception):
    """Raised when no section could be extracted at all."""

    def __init__(self, message: str, report: ExtractionReport):
        super().__init__(message)
        self.user_message = message
        self.report = report


@dataclass(frozen=True)
class SectionProgress:
    """One progress event. Sections run concurrently, so events arrive as
    things happen, not in a fixed order — consumers key on ``key``."""

    key: str
    label: str
    status: str  # "running" | "done" | "failed"
    completed: int
    total: int


#: Remote providers can process independent section calls concurrently.  Most
#: local runtimes cannot: Ollama queues requests behind one model runner, while
#: each HTTP client's timeout starts immediately.  Five simultaneous calls can
#: therefore make four healthy requests expire in the queue.  Local providers
#: are deliberately serialised below; remote providers retain the speedup.
_MAX_PARALLEL_SECTIONS = 5


class ResumeExtractor:
    """Runs the section pipeline against one provider."""

    def __init__(self, provider: AIProvider):
        self._provider = provider

    def extract(
        self,
        document: ExtractionResult,
        *,
        on_progress: Callable[[SectionProgress], None] | None = None,
    ) -> tuple[ResumeContent, ExtractionReport]:
        """Extract `document` into structured content plus a provenance report.

        Never raises for a partial result: a section that fails is recorded in
        the report and the rest is kept. Raises ``ExtractionError`` only when
        every section failed, since there is nothing to review in that case.
        """
        document.raise_if_unusable()
        text = document.text
        report = ExtractionReport(
            source_filename=document.filename,
            source_chars=len(text),
            diagnosis=str(document.diagnosis),
            diagnosis_message=document.message(),
            document_warnings=list(document.warnings),
            model=self._provider.config.model,
            prompt_version=get_template("resume_section").version,
        )
        content = ResumeContent()
        total = len(SECTIONS)

        def notify(event: SectionProgress) -> None:
            if on_progress:
                on_progress(event)

        results: dict[str, tuple[SectionOutcome, _Section | None]] = {}
        completed = 0
        serial_provider = self._provider.config.kind in {
            ProviderKind.OLLAMA,
            ProviderKind.CLI,
        }
        workers = 1 if serial_provider else min(_MAX_PARALLEL_SECTIONS, total)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for spec in SECTIONS:
                notify(SectionProgress(spec.key, spec.label, "running", completed, total))
                futures[pool.submit(self._call_section, spec, text)] = spec
            for future in as_completed(futures):
                spec = futures[future]
                outcome, section = future.result()
                completed += 1
                results[spec.key] = (outcome, section)
                notify(
                    SectionProgress(
                        spec.key,
                        spec.label,
                        "done" if outcome.ok else "failed",
                        completed,
                        total,
                    )
                )

        # Merge on this thread, in canonical section order, so the result is
        # deterministic regardless of which network call finished first.
        for spec in SECTIONS:
            outcome, section = results[spec.key]
            if section is not None:
                outcome.item_count = _merge(content, section)
            report.sections.append(outcome)

        if not report.any_content:
            failures = report.failed_sections()
            detail = failures[0].error if failures else ""
            raise ExtractionError(
                "The AI could not extract anything from this document. "
                + (
                    f"The first failure was: {detail}"
                    if detail
                    else "It returned empty results for every section. A larger "
                    "model usually fixes this."
                ),
                report,
            )

        report.notes = classify(content, text)
        return content, report

    # -- one section ---------------------------------------------------------

    def _call_section(self, spec: SectionSpec, text: str) -> tuple[SectionOutcome, _Section | None]:
        """Network + validation only — no shared state. Runs on a pool thread;
        merging into the accumulated content happens on the calling thread."""
        template = get_template("resume_section")
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            section_label=spec.label,
            section_instructions=spec.instructions,
            resume_block=wrap_untrusted(text, "RESUME"),
        )
        try:
            section = self._provider.structured(
                [ChatMessage(Role.USER, prompt)],
                spec.schema,
                temperature=0.0,
                min_output_tokens=spec.min_tokens,
                validate_result=_reject_empty_shape,
            )
        except Exception as exc:
            log.warning("Resume section %r failed: %s", spec.key, exc)
            return (
                SectionOutcome(
                    name=spec.label,
                    ok=False,
                    error=getattr(exc, "user_message", str(exc)),
                    raw_output=getattr(exc, "raw_output", "") or "",
                ),
                None,
            )

        return SectionOutcome(name=spec.label, ok=True), section


def _reject_empty_shape(section: _Section) -> str | None:
    """Catch the failure that used to pass silently.

    Every field is optional, so ``{}`` and any response using different key
    names both validate cleanly and produce an empty section. A genuinely empty
    section is possible (not every resume has publications), so this cannot
    simply reject emptiness — but it can reject a response in which *nothing*
    was populated, which is far more often a key-name mismatch than a truthful
    "this resume has no contact details".
    """
    if isinstance(section, ContactSection) and not (
        section.full_name or section.email or section.phone
    ):
        return (
            "No name, email, or phone was returned. Use exactly the key names "
            "shown, and copy the values from the resume header."
        )
    if isinstance(section, ExperienceSection) and not section.experiences:
        return (
            "The experiences list was empty. Almost every resume has work "
            "history — use exactly the key names shown."
        )
    if isinstance(section, ExperienceSection) and any(
        not (entry.title or entry.organization) for entry in section.experiences
    ):
        return (
            "A work-experience entry had neither a job title nor an employer. "
            "Map the resume's role and company into title and organization."
        )
    if isinstance(section, EducationSection) and any(
        not (entry.institution or entry.degree) for entry in section.education
    ):
        return (
            "An education entry had neither an institution nor a degree. "
            "Return the actual school and qualification using the shown keys."
        )
    if isinstance(section, SkillsSection):
        if any(not entry.name for entry in section.skills):
            return "A skill entry had no name. Put the actual skill in the name field."
        if any(not entry.name for entry in section.certifications):
            return "A certification entry had no name. Put the credential in the name field."
        if any(not entry.name for entry in section.languages):
            return "A language entry had no name. Put the language in the name field."
    if isinstance(section, ExtrasSection):
        if any(not entry.name for entry in section.projects):
            return "A project entry had no name. Put the project title in the name field."
        if any(
            not entry.title
            for entries in (section.awards, section.publications, section.volunteer)
            for entry in entries
        ):
            return "An additional resume entry had no title. Use the title key shown."
    return None


def _merge(content: ResumeContent, section: _Section) -> int:
    """Copy a section's fields onto the accumulating content. Returns the
    number of items contributed."""
    count = 0
    for name, value in section.model_dump().items():
        if not hasattr(content, name):
            continue
        if isinstance(value, list):
            if value:
                # model_dump() gave us plain dicts; re-validate so the field
                # holds typed models rather than dicts.
                setattr(content, name, _validated_list(content, name, value))
                count += len(value)
        elif isinstance(value, str) and value.strip():
            setattr(content, name, value)
            count += 1
    return count


def _validated_list(content: ResumeContent, name: str, raw: list) -> list:
    """Coerce raw dicts back into the typed models the field expects."""
    field = type(content).model_fields[name]
    args = getattr(field.annotation, "__args__", ())
    if not args:
        return raw
    item_model = args[0]
    return [item_model.model_validate(item) if isinstance(item, dict) else item for item in raw]
