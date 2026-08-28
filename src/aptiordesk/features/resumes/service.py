"""Resume management: file import, AI structuring, versioning."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from aptiordesk.ai.base import AIProvider
from aptiordesk.database.models.extraction import ExtractionReport
from aptiordesk.database.models.resume import Resume, ResumeContent, ResumeVersion
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.documents.importers import import_document
from aptiordesk.documents.pipeline import ExtractionResult, load_document
from aptiordesk.features.resumes.extraction import ResumeExtractor

log = logging.getLogger(__name__)


class ResumeService:
    def __init__(self, conn: sqlite3.Connection):
        self._repo = ResumeRepository(conn)

    # -- import pipeline -----------------------------------------------------

    def read_document(self, path: str | Path) -> ExtractionResult:
        """Step 1 of import: text plus a diagnosis of how well it was read.

        Returns rather than raises for content problems (scans, near-empty
        files) so the caller can show the raw text next to the explanation.
        """
        return load_document(path)

    def extract_text(self, path: str | Path) -> str:
        """Raw text only, for callers that do not need the diagnosis."""
        return import_document(path)

    def extract_structure(
        self,
        provider: AIProvider,
        document: ExtractionResult,
        *,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> tuple[ResumeContent, ExtractionReport]:
        """Step 2 of import: AI-structured content plus its provenance report.

        The caller MUST show the result to the user for correction before
        saving — extraction is never trusted silently. Runs section by section
        so one bad section cannot lose the rest; see ``services.extraction``.
        """
        return ResumeExtractor(provider).extract(document, on_progress=on_progress)

    def create_imported(
        self,
        name: str,
        source_filename: str,
        content: ResumeContent,
        raw_text: str,
        report: ExtractionReport | None = None,
        diagnosis: str = "",
    ) -> tuple[Resume, ResumeVersion]:
        resume = self._repo.create(
            Resume(name=name, source="imported", source_filename=source_filename)
        )
        version = self._repo.add_version(
            resume.id,
            content,
            label="Imported",
            raw_text=raw_text,
            extraction_report=report,
            source_diagnosis=diagnosis,
        )
        return resume, version

    def create_manual(self, name: str, content: ResumeContent) -> tuple[Resume, ResumeVersion]:
        resume = self._repo.create(Resume(name=name, source="manual"))
        version = self._repo.add_version(resume.id, content, label="Initial")
        return resume, version

    # -- versioning ----------------------------------------------------------

    def save_edited(
        self, version: ResumeVersion, new_content: ResumeContent, label: str = "Edited"
    ) -> ResumeVersion:
        """Edits never overwrite: they always create a new version."""
        return self._repo.add_version(
            version.resume_id,
            new_content,
            label=label,
            raw_text=version.raw_text,
            created_from_version_id=version.id,
        )

    def restore(self, version: ResumeVersion) -> ResumeVersion:
        return self._repo.add_version(
            version.resume_id,
            version.content,
            label=f"Restored from v{version.version_no}",
            raw_text=version.raw_text,
            created_from_version_id=version.id,
        )

    def delete_version(self, version: ResumeVersion) -> None:
        """Delete one historical version while keeping the resume usable."""
        if self._repo.count_versions(version.resume_id) <= 1:
            raise ValueError(
                "A resume must keep at least one version. Delete the resume itself "
                "if you no longer need it."
            )
        if self._repo.version_has_tailoring_dependents(version.id):
            raise ValueError(
                "This version is the source of one or more tailored resumes. "
                "Delete those tailored versions first so their history is not corrupted."
            )
        self._repo.delete_version(version.id)
