"""Cover letter generation, versioning, and export."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from aptiordesk.ai.base import AIProvider, ChatMessage, Role
from aptiordesk.ai.prompts.engine import get_template
from aptiordesk.ai.prompts.guards import FABRICATION_RULES, UNTRUSTED_PREAMBLE, wrap_untrusted
from aptiordesk.database.models.cover_letter import (
    LENGTHS,
    TONES,
    CoverLetter,
    CoverLetterDraft,
    CoverLetterInputs,
    CoverLetterVersion,
)
from aptiordesk.database.models.job import Job
from aptiordesk.database.models.profile import Profile
from aptiordesk.database.models.resume import ResumeVersion
from aptiordesk.database.repositories.cover_letter_repo import CoverLetterRepository
from aptiordesk.documents.render import resume_to_markdown

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedCoverLetterDraft:
    """AI output prepared without touching SQLite.

    SQLite connections belong to the thread that created them. This transport
    value lets the slow provider request run in a worker and be persisted later
    by the UI thread through its own repository.
    """

    cover_letter_id: int
    draft: CoverLetterDraft
    label: str
    rationale: dict[str, object]


class CoverLetterService:
    def __init__(self, conn: sqlite3.Connection):
        self._repo = CoverLetterRepository(conn)

    def create(
        self, job: Job, resume_version: ResumeVersion | None, inputs: CoverLetterInputs
    ) -> CoverLetter:
        if inputs.tone not in TONES:
            raise ValueError(f"Unknown tone: {inputs.tone}")
        if inputs.length not in LENGTHS:
            raise ValueError(f"Unknown length: {inputs.length}")
        return self._repo.create(
            CoverLetter(
                job_id=job.id,
                resume_version_id=resume_version.id if resume_version else None,
                tone=inputs.tone,
                length=inputs.length,
            )
        )

    def generate(
        self,
        provider: AIProvider,
        letter: CoverLetter,
        job: Job,
        resume_version: ResumeVersion | None,
        profile: Profile | None,
        inputs: CoverLetterInputs,
        *,
        label: str = "",
    ) -> tuple[CoverLetterVersion, CoverLetterDraft]:
        """Synchronous compatibility wrapper: generate, then persist."""
        generated = self.generate_draft(
            provider,
            letter,
            job,
            resume_version,
            profile,
            inputs,
            label=label,
        )
        return self.persist_generated_draft(generated)

    @staticmethod
    def generate_draft(
        provider: AIProvider,
        letter: CoverLetter,
        job: Job,
        resume_version: ResumeVersion | None,
        profile: Profile | None,
        inputs: CoverLetterInputs,
        *,
        label: str = "",
    ) -> GeneratedCoverLetterDraft:
        """Generate a cover-letter draft without reading or writing SQLite."""
        if letter.id is None:
            raise ValueError("The cover letter must be saved before generating a draft.")
        template = get_template("cover_letter")
        resume_md = resume_to_markdown(resume_version.content) if resume_version else ""
        profile_md = _profile_summary(profile)
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            fabrication_rules=FABRICATION_RULES,
            tone_name=inputs.tone,
            tone_description=TONES[inputs.tone],
            length_name=inputs.length,
            length_description=LENGTHS[inputs.length],
            motivation=inputs.motivation or "(not provided)",
            company_notes=inputs.company_notes or "(not provided)",
            personal_connection=inputs.personal_connection or "(none)",
            hiring_manager=inputs.hiring_manager or "(unknown — use a neutral salutation)",
            jd_block=wrap_untrusted(job.raw_description, "JOB DESCRIPTION"),
            resume_block=wrap_untrusted(resume_md, "RESUME"),
            profile_block=wrap_untrusted(profile_md, "CANDIDATE PROFILE"),
        )
        draft = provider.structured(
            [ChatMessage(Role.USER, prompt)], CoverLetterDraft, temperature=0.6
        )
        return GeneratedCoverLetterDraft(
            cover_letter_id=letter.id,
            draft=draft,
            label=label or f"{inputs.tone}, {inputs.length}",
            rationale={
                "selected_experiences": draft.selected_experiences,
                "selection_rationale": draft.selection_rationale,
                "claims_needing_confirmation": draft.claims_needing_confirmation,
                "tone": inputs.tone,
                "length": inputs.length,
                "prompt_id": template.id,
                "prompt_version": template.version,
            },
        )

    def persist_generated_draft(
        self, generated: GeneratedCoverLetterDraft
    ) -> tuple[CoverLetterVersion, CoverLetterDraft]:
        """Persist worker output on the SQLite connection-owner thread."""
        version = self._repo.add_version(
            generated.cover_letter_id,
            generated.draft.body_markdown,
            label=generated.label,
            rationale=generated.rationale,
        )
        return version, generated.draft

    def save_edited(self, letter: CoverLetter, content_md: str) -> CoverLetterVersion:
        """Edits create a new version; earlier drafts stay available.

        The previous version's rationale is carried forward (marked as
        inherited) so the "why these points" context is not lost when the
        candidate edits a draft.
        """
        previous = self._repo.latest_version(letter.id)
        rationale = dict(previous.rationale) if previous else {}
        if rationale:
            rationale["inherited_from_version"] = previous.version_no
        return self._repo.add_version(letter.id, content_md, label="Your edit", rationale=rationale)

    def list_versions(self, letter: CoverLetter) -> list[CoverLetterVersion]:
        return self._repo.list_versions(letter.id)


def _profile_summary(profile: Profile | None) -> str:
    if profile is None:
        return ""
    parts = []
    if profile.display_name:
        parts.append(f"Name: {profile.display_name}")
    if profile.summary:
        parts.append(f"Summary: {profile.summary}")
    prefs = profile.preferences
    if prefs.target_titles:
        parts.append(f"Target roles: {', '.join(prefs.target_titles)}")
    auth = profile.work_auth
    if auth.authorized_in:
        parts.append(f"Authorized to work in: {', '.join(auth.authorized_in)}")
    if auth.needs_sponsorship is not None:
        parts.append(f"Needs sponsorship: {'yes' if auth.needs_sponsorship else 'no'}")
    return "\n".join(parts)


__all__ = ["CoverLetterService", "GeneratedCoverLetterDraft"]
