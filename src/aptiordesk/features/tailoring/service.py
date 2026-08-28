"""Resume tailoring: evidence-backed suggestions, per-suggestion review,
and applying accepted changes as a new resume version.

Safety model:
- The AI proposes rewrites of existing string fields or an explicit
  evidence-backed skill addition.
- Every suggestion is validated against the actual base content; proposals
  whose target doesn't exist or whose `original_text` doesn't match are
  dropped (the model hallucinated the target).
- Numbers not present in the base resume are flagged as warnings, never
  silently accepted.
- Nothing changes until the user applies their accepted/edited suggestions,
  which creates a NEW version — the base version is immutable.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass

from aptiordesk.ai.base import AIProvider, ChatMessage, Role
from aptiordesk.ai.prompts.engine import get_template
from aptiordesk.ai.prompts.guards import (
    FABRICATION_RULES,
    UNTRUSTED_PREAMBLE,
    find_unverified_numbers,
    wrap_untrusted,
)
from aptiordesk.core import jsonptr
from aptiordesk.database.models.job import Job, JobExtraction, JobFit
from aptiordesk.database.models.resume import ResumeContent, ResumeVersion
from aptiordesk.database.models.tailoring import (
    STRATEGIES,
    Suggestion,
    SuggestionList,
    TailoringSession,
)
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.database.repositories.tailoring_repo import TailoringRepository

log = logging.getLogger(__name__)

# Tailoring sends the entire resume, posting, analysis keywords, and a strict
# structured-output contract. Local models and device CLIs routinely need more
# than the standard short request deadline for that workload.
TAILORING_REQUEST_TIMEOUT_S = 300


@dataclass(frozen=True)
class GeneratedTailoringSuggestions:
    """Validated AI output that has not touched SQLite yet."""

    session_id: int
    suggestions: list[Suggestion]


@dataclass(frozen=True)
class TailoringAnalysisContext:
    """Relevant terms and evidence recovered from stored job analysis."""

    identified_keywords: tuple[str, ...] = ()
    supported_keywords: tuple[str, ...] = ()
    evidence_lines: tuple[str, ...] = ()

    def prompt_json(self) -> str:
        return json.dumps(
            {
                "identified_keywords": list(self.identified_keywords),
                "truthfully_supported_keywords": list(self.supported_keywords),
                "candidate_evidence_from_fit_analysis": list(self.evidence_lines),
            },
            indent=2,
        )


class TailoringService:
    def __init__(self, conn: sqlite3.Connection):
        self._repo = TailoringRepository(conn)
        self._resumes = ResumeRepository(conn)
        self._jobs = JobRepository(conn)

    def analysis_context(
        self, session: TailoringSession, job: Job, base: ResumeVersion
    ) -> TailoringAnalysisContext:
        """Load keyword guidance before an AI worker starts.

        This method intentionally owns the SQLite reads. The returned frozen
        value can safely cross into a worker thread with no database object.
        """
        identified: list[str] = list(job.skills)
        supported: list[str] = []
        evidence: list[str] = []

        extraction_row = self._jobs.latest_analysis(job.id, "extraction")
        if extraction_row is not None:
            extraction = JobExtraction.model_validate(extraction_row.result)
            identified.extend(extraction.keywords)
            identified.extend(extraction.technical_skills)
            identified.extend(extraction.soft_skills)
            identified.extend(extraction.tools_and_platforms)

        fit_row = self._jobs.latest_fit_analysis(job.id, base.id)
        if fit_row is not None:
            fit = JobFit.model_validate(fit_row.result)
            supported.extend(fit.keywords_to_include)
            identified.extend(fit.keywords_to_include)
            for item in [
                *fit.strong_matches,
                *fit.partial_matches,
                *fit.transferable_experience,
            ]:
                if item.requirement and item.candidate_evidence:
                    evidence.append(f"{item.requirement}: {item.candidate_evidence}")

        return TailoringAnalysisContext(
            identified_keywords=tuple(_unique_terms(identified)),
            supported_keywords=tuple(_unique_terms(supported)),
            evidence_lines=tuple(_unique_terms(evidence)),
        )

    def create_session(
        self, job: Job, base_version: ResumeVersion, strategy: str = "balanced"
    ) -> TailoringSession:
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy}")
        return self._repo.create_session(
            TailoringSession(
                job_id=job.id,
                base_resume_version_id=base_version.id,
                strategy=strategy,
            )
        )

    def generate_suggestions(
        self, provider: AIProvider, session: TailoringSession, job: Job
    ) -> list[Suggestion]:
        """Synchronous compatibility wrapper: load, generate, then persist."""
        base = self._resumes.get_version(session.base_resume_version_id)
        context = self.analysis_context(session, job, base)
        generated = self.generate_suggestions_for_version(provider, session, job, base, context)
        return self.persist_generated_suggestions(generated)

    @staticmethod
    def generate_suggestions_for_version(
        provider: AIProvider,
        session: TailoringSession,
        job: Job,
        base: ResumeVersion,
        context: TailoringAnalysisContext | None = None,
    ) -> GeneratedTailoringSuggestions:
        """Call the AI and validate its output without accessing SQLite."""
        context = context or TailoringAnalysisContext(
            identified_keywords=tuple(_unique_terms(job.skills))
        )
        template = get_template("tailoring")
        content_json = base.content.model_dump_json(indent=2)
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            fabrication_rules=FABRICATION_RULES,
            strategy_name=session.strategy,
            strategy_description=STRATEGIES[session.strategy],
            jd_block=wrap_untrusted(job.raw_description, "JOB DESCRIPTION"),
            resume_json_block=wrap_untrusted(content_json, "RESUME JSON"),
            analysis_keyword_block=wrap_untrusted(
                context.prompt_json(), "ANALYSIS KEYWORD GUIDANCE"
            ),
        )

        def keyword_coverage(result: SuggestionList) -> str | None:
            supported = list(context.supported_keywords)
            if not supported:
                return None
            covered = _covered_keywords(result, supported)
            minimum = 1 if len(supported) <= 3 else 2
            if len(covered) >= minimum:
                return None
            return (
                "The suggestions did not materially use the truthfully supported "
                f"analysis keywords. Naturally incorporate at least {minimum} of: "
                + ", ".join(supported)
            )

        result = provider.structured(
            [ChatMessage(Role.USER, prompt)],
            SuggestionList,
            temperature=0.4,
            request_timeout_s=max(provider.config.timeout_s, TAILORING_REQUEST_TIMEOUT_S),
            validate_result=keyword_coverage,
        )
        validated = TailoringService._validate_suggestions(
            result,
            base.content,
            base.raw_text,
            job.raw_description,
            context,
        )
        return GeneratedTailoringSuggestions(session_id=int(session.id), suggestions=validated)

    def persist_generated_suggestions(
        self, generated: GeneratedTailoringSuggestions
    ) -> list[Suggestion]:
        """Persist generated suggestions on the SQLite connection-owner thread."""
        self._repo.add_suggestions(generated.session_id, generated.suggestions)
        return generated.suggestions

    @staticmethod
    def _validate_suggestions(
        result: SuggestionList,
        content: ResumeContent,
        raw_text: str,
        job_text: str = "",
        context: TailoringAnalysisContext | None = None,
    ) -> list[Suggestion]:
        context = context or TailoringAnalysisContext()
        document = content.model_dump()
        source_texts = [content.model_dump_json(), raw_text]
        source_blob = "\n".join(source_texts)
        existing_skills = {
            skill.name.strip().casefold() for skill in content.skills if skill.name.strip()
        }
        validated: list[Suggestion] = []
        for proposal in result.suggestions:
            if not proposal.target_path or not proposal.suggested_text:
                continue
            suggestion = Suggestion(**proposal.model_dump())
            suggestion.suggested_text = suggestion.suggested_text.strip()

            if suggestion.operation == "add_skill":
                if suggestion.target_path != "/skills/-":
                    log.info("Dropping skill addition with invalid path %r", suggestion.target_path)
                    continue
                skill_key = suggestion.suggested_text.casefold()
                if (
                    not skill_key
                    or skill_key in existing_skills
                    or len(suggestion.suggested_text) > 100
                    or "\n" in suggestion.suggested_text
                ):
                    continue
                if not _evidence_is_grounded(suggestion.profile_evidence, source_blob):
                    log.info(
                        "Dropping unsupported skill addition %r",
                        suggestion.suggested_text,
                    )
                    continue
                if not _skill_evidence_is_specific(
                    suggestion.suggested_text,
                    suggestion.profile_evidence,
                    context.evidence_lines,
                ):
                    log.info(
                        "Dropping skill addition whose evidence does not support the term %r",
                        suggestion.suggested_text,
                    )
                    continue
                job_terms = [*context.identified_keywords, *context.supported_keywords]
                if not _term_is_job_relevant(suggestion.suggested_text, job_text, job_terms):
                    log.info(
                        "Dropping job-irrelevant skill addition %r",
                        suggestion.suggested_text,
                    )
                    continue
                suggestion.original_text = ""
                suggestion.skill_category = suggestion.skill_category.strip()[:50]
                existing_skills.add(skill_key)
                invented = find_unverified_numbers(suggestion.suggested_text, source_texts)
                if invented:
                    suggestion.warnings = "Contains numbers not found in your resume: " + ", ".join(
                        invented
                    )
                validated.append(suggestion)
                continue

            try:
                current = jsonptr.get(document, proposal.target_path)
            except jsonptr.PointerError:
                log.info("Dropping suggestion with invalid path %r", proposal.target_path)
                continue
            if not isinstance(current, str):
                log.info("Dropping suggestion targeting non-string %r", proposal.target_path)
                continue
            # Repair original_text from the actual document if the model misquoted.
            if suggestion.original_text != current:
                suggestion.original_text = current
            warnings: list[str] = []
            if not suggestion.profile_evidence.strip():
                warnings.append("No supporting candidate evidence was cited.")
            invented = find_unverified_numbers(suggestion.suggested_text, source_texts)
            if invented:
                warnings.append("Contains numbers not found in your resume: " + ", ".join(invented))
            suggestion.warnings = " ".join(warnings)
            validated.append(suggestion)
        return validated

    # -- review --------------------------------------------------------------

    def list_suggestions(self, session_id: int) -> list[Suggestion]:
        return self._repo.list_suggestions(session_id)

    def accept(self, suggestion: Suggestion) -> None:
        self._repo.set_suggestion_status(suggestion.id, "accepted")

    def reject(self, suggestion: Suggestion) -> None:
        self._repo.set_suggestion_status(suggestion.id, "rejected")

    def edit(self, suggestion: Suggestion, edited_text: str) -> None:
        self._repo.set_suggestion_status(suggestion.id, "edited", edited_text)

    # -- apply ---------------------------------------------------------------

    def apply(self, session: TailoringSession, job: Job) -> ResumeVersion | None:
        """Apply accepted/edited suggestions to the base content and store the
        result as a new resume version. Returns None if nothing was accepted."""
        chosen = [
            s for s in self._repo.list_suggestions(session.id) if s.status in ("accepted", "edited")
        ]
        if not chosen:
            return None
        base = self._resumes.get_version(session.base_resume_version_id)
        document = base.content.model_dump()
        applied = 0
        for suggestion in chosen:
            if suggestion.operation == "add_skill":
                skill_name = suggestion.final_text().strip()
                existing = {
                    str(skill.get("name", "")).strip().casefold()
                    for skill in document.get("skills", [])
                }
                if skill_name and skill_name.casefold() not in existing:
                    document.setdefault("skills", []).append(
                        {
                            "name": skill_name,
                            "category": suggestion.skill_category or "Relevant",
                            "level": "",
                        }
                    )
                    applied += 1
                continue
            try:
                jsonptr.set_(document, suggestion.target_path, suggestion.final_text())
                applied += 1
            except jsonptr.PointerError:
                log.warning("Skipping unapplicable suggestion %s", suggestion.target_path)
        if applied == 0:
            return None
        new_content = ResumeContent.model_validate(document)
        label = f"Tailored for {job.title or 'job'}" + (f" @ {job.company}" if job.company else "")
        version = self._resumes.add_version(
            base.resume_id,
            new_content,
            label=label,
            raw_text=base.raw_text,
            created_from_version_id=base.id,
            tailoring_session_id=session.id,
        )
        self._repo.set_session_status(session.id, "applied")
        return version


_WORD = re.compile(r"[a-z0-9+#.]+")
_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "using",
    "skill",
    "skills",
    "experience",
    "experienced",
    "work",
    "worked",
}


def _tokens(text: str) -> set[str]:
    output: set[str] = set()
    for token in _WORD.findall(text.casefold()):
        if len(token) <= 2 or token in _STOPWORDS:
            continue
        output.add(token[:-1] if token.endswith("s") and len(token) > 4 else token)
    return output


def _evidence_is_grounded(evidence: str, source: str) -> bool:
    evidence = " ".join(evidence.split()).casefold()
    source = " ".join(source.split()).casefold()
    if not evidence:
        return False
    if evidence in source:
        return True
    evidence_tokens = _tokens(evidence)
    if not evidence_tokens:
        return False
    overlap = evidence_tokens & _tokens(source)
    required = min(3, max(1, (len(evidence_tokens) + 1) // 2))
    return len(overlap) >= required


def _term_is_job_relevant(term: str, job_text: str, job_terms: list[str]) -> bool:
    key = term.casefold()
    if key in job_text.casefold():
        return True
    term_tokens = _tokens(term)
    return any(
        key == candidate.casefold() or bool(term_tokens and term_tokens <= _tokens(candidate))
        for candidate in job_terms
    )


def _skill_evidence_is_specific(
    skill: str, evidence: str, fit_evidence_lines: tuple[str, ...]
) -> bool:
    """Ensure a grounded passage supports this skill, not merely *some* skill."""
    skill_tokens = _tokens(skill)
    evidence_tokens = _tokens(evidence)
    if skill_tokens & evidence_tokens:
        return True
    for line in fit_evidence_lines:
        requirement, separator, candidate_evidence = line.partition(":")
        if not separator:
            continue
        if (
            skill.casefold() in requirement.casefold()
            and evidence_tokens
            and bool(evidence_tokens & _tokens(candidate_evidence))
        ):
            return True
    return False


def _unique_terms(terms: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = " ".join(str(term).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _covered_keywords(result: SuggestionList, keywords: list[str]) -> list[str]:
    proposed = "\n".join(s.suggested_text for s in result.suggestions).casefold()
    return [keyword for keyword in keywords if keyword.casefold() in proposed]


__all__ = [
    "GeneratedTailoringSuggestions",
    "TAILORING_REQUEST_TIMEOUT_S",
    "TailoringAnalysisContext",
    "TailoringService",
]
