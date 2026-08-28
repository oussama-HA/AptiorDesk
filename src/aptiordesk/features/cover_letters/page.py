"""Cover letters: generate from job + resume + your own context, edit,
version, and export."""

from __future__ import annotations

import html
import logging
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.models.cover_letter import (
    LENGTHS,
    TONES,
    CoverLetter,
    CoverLetterInputs,
    CoverLetterVersion,
)
from aptiordesk.database.repositories.cover_letter_repo import CoverLetterRepository
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.documents.exporters import EXPORT_FORMATS, export_document
from aptiordesk.features.cover_letters.service import CoverLetterService
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.components.rich_text import rich_document
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)


class CoverLettersPage(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._repo = CoverLetterRepository(conn)
        self._jobs = JobRepository(conn)
        self._resumes = ResumeRepository(conn)
        self._profiles = ProfileRepository(conn)
        self._service = CoverLetterService(conn)
        self._generation_worker: Worker | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Cover letters",
            "Grounded in your resume and your own reasons for applying.",
            eyebrow="APPLICATION WRITING",
        )
        outer.addWidget(self.header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        left = QWidget()
        left.setProperty("role", "pane")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        left_layout.setSpacing(SPACE["md"])
        letters_title = QLabel("Letter library")
        letters_title.setProperty("role", "paneTitle")
        left_layout.addWidget(letters_title)
        self.letter_list = QListWidget()
        self.letter_list.setObjectName("contentList")
        self.letter_list.currentItemChanged.connect(lambda *_: self._reload_versions())
        left_layout.addWidget(self.letter_list, 1)
        versions_title = QLabel("Versions")
        versions_title.setProperty("role", "fieldLabel")
        left_layout.addWidget(versions_title)
        self.version_list = QListWidget()
        self.version_list.setObjectName("contentList")
        self.version_list.currentItemChanged.connect(lambda *_: self._show_version())
        left_layout.addWidget(self.version_list, 1)
        buttons = QHBoxLayout()
        new_button = QPushButton("New letter…")
        new_button.setProperty("accent", True)
        new_button.clicked.connect(self._new_letter)
        delete_button = QPushButton("Delete")
        delete_button.setProperty("variant", "danger")
        delete_button.clicked.connect(self._delete_letter)
        buttons.addWidget(new_button)
        buttons.addWidget(delete_button)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right.setProperty("role", "pane")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        right_layout.setSpacing(SPACE["md"])
        workspace_title = QLabel("Letter workspace")
        workspace_title.setProperty("role", "paneTitle")
        right_layout.addWidget(workspace_title)
        self.tabs = QTabWidget()
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Generate a letter, or write one here. Everything is editable."
        )
        self.preview = QTextBrowser()
        self.rationale_view = QTextBrowser()
        self.tabs.addTab(self.editor, "Edit")
        self.tabs.addTab(self.preview, "Preview")
        self.tabs.addTab(self.rationale_view, "Why these points")
        self.tabs.currentChanged.connect(self._sync_preview)
        right_layout.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.regenerate_button = QPushButton("Regenerate…")
        self.regenerate_button.clicked.connect(self._regenerate)
        self.save_button = QPushButton("Save edit → new version")
        self.save_button.clicked.connect(self._save_edit)
        self.export_button = QPushButton("Export…")
        self.export_button.setProperty("accent", True)
        self.export_button.clicked.connect(self._export)
        for b in (self.regenerate_button, self.save_button, self.export_button):
            actions.addWidget(b)
        right_layout.addLayout(actions)

        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        right_layout.addWidget(self.status)
        splitter.addWidget(right)
        splitter.setSizes([320, 770])

        self.reload()

    # -- loading -------------------------------------------------------------

    def reload(self) -> None:
        self.letter_list.clear()
        for letter in self._repo.list_all():
            job = self._jobs.get(letter.job_id)
            label = job.title or "(untitled job)" if job else "(job deleted)"
            if job and job.company:
                label += f" — {job.company}"
            entry = QListWidgetItem(f"{label}  [{letter.tone}]")
            entry.setData(Qt.ItemDataRole.UserRole, letter)
            self.letter_list.addItem(entry)
        if self.letter_list.count():
            self.letter_list.setCurrentRow(0)
        else:
            self._reload_versions()

    def _current_letter(self) -> CoverLetter | None:
        item = self.letter_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _current_version(self) -> CoverLetterVersion | None:
        item = self.version_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _reload_versions(self) -> None:
        self.version_list.clear()
        letter = self._current_letter()
        enabled = letter is not None
        for widget in (self.regenerate_button, self.save_button, self.export_button):
            widget.setEnabled(enabled)
        if letter is None:
            self.editor.clear()
            self.preview.clear()
            self.rationale_view.clear()
            return
        for version in self._repo.list_versions(letter.id):
            label = f"v{version.version_no}"
            if version.label:
                label += f" — {version.label}"
            entry = QListWidgetItem(label)
            entry.setData(Qt.ItemDataRole.UserRole, version)
            self.version_list.addItem(entry)
        if self.version_list.count():
            self.version_list.setCurrentRow(0)

    def _show_version(self) -> None:
        version = self._current_version()
        if version is None:
            return
        self.editor.setPlainText(version.content_md)
        self._sync_preview()
        self.rationale_view.setHtml(_rationale_html(version.rationale))

    def _sync_preview(self) -> None:
        self.preview.setMarkdown(self.editor.toPlainText())

    # -- actions -------------------------------------------------------------

    def _new_letter(self) -> None:
        jobs = self._jobs.list()
        if not jobs:
            QMessageBox.information(
                self,
                "No jobs",
                "Capture a job with the browser extension first—a letter needs a posting.",
            )
            return
        dialog = _LetterDialog(jobs, self._resume_versions(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        job = dialog.job_combo.currentData()
        resume_version = dialog.resume_combo.currentData()
        inputs = dialog.inputs()
        letter = self._service.create(job, resume_version, inputs)
        self._generate(letter, job, resume_version, inputs)

    def _delete_letter(self) -> None:
        letter = self._current_letter()
        if letter is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete cover letter",
            "Delete this letter and all of its versions? This cannot be undone.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._repo.delete(letter.id)
            self.reload()

    def _regenerate(self) -> None:
        letter = self._current_letter()
        if letter is None:
            return
        job = self._jobs.get(letter.job_id)
        if job is None:
            QMessageBox.warning(self, "Job missing", "The job for this letter was deleted.")
            return
        dialog = _LetterDialog([job], self._resume_versions(), self, initial=letter, lock_job=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._generate(letter, job, dialog.resume_combo.currentData(), dialog.inputs())

    def _generate(self, letter, job, resume_version, inputs: CoverLetterInputs) -> None:
        try:
            provider = get_active_provider(self._conn)
        except Exception as exc:
            QMessageBox.warning(self, "No AI provider", getattr(exc, "user_message", str(exc)))
            return
        profile = self._profiles.get_default()
        self.status.setText("Writing the letter — this can take a moment…")
        self.regenerate_button.setEnabled(False)
        worker = Worker(
            lambda: self._service.generate_draft(
                provider, letter, job, resume_version, profile, inputs
            ),
            parent=self,
        )
        self._generation_worker = worker
        worker.result.connect(self._on_generated)
        worker.error.connect(self._error)
        worker.finished.connect(lambda: self._generation_finished(worker))
        worker.show_progress(
            "Writing your cover letter",
            f"Drafting a {inputs.tone} letter for {job.title or 'the selected role'} "
            f"with {provider.config.name or provider.config.kind.value}.",
        )
        worker.start()

    def _on_generated(self, generated) -> None:
        """Persist the worker's database-free result on Qt's UI thread."""
        try:
            _version, draft = self._service.persist_generated_draft(generated)
        except Exception as exc:
            self._error(exc)
            return
        self.status.setText("Draft ready — review it, edit anything, then export.")
        self.regenerate_button.setEnabled(True)
        self.reload()
        if draft.claims_needing_confirmation:
            QMessageBox.information(
                self,
                "Please confirm these points",
                "The draft contains points you should verify before sending:\n\n"
                + "\n".join(f"• {c}" for c in draft.claims_needing_confirmation),
            )

    def _generation_finished(self, worker: Worker) -> None:
        if self._generation_worker is worker:
            self._generation_worker = None

    def _save_edit(self) -> None:
        letter = self._current_letter()
        if letter is None:
            return
        text = self.editor.toPlainText().strip()
        if not text:
            return
        self._service.save_edited(letter, text)
        self._reload_versions()
        self.status.setText("Saved as a new version.")

    def _export(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Nothing to export", "The letter is empty.")
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export cover letter", "cover-letter", ";;".join(EXPORT_FORMATS.values())
        )
        if not path:
            return
        fmt = next(
            (key for key, label in EXPORT_FORMATS.items() if label == selected),
            path.rsplit(".", 1)[-1].lower(),
        )
        if not path.lower().endswith(f".{fmt}"):
            path = f"{path}.{fmt}"
        try:
            export_document(text, path, fmt)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", getattr(exc, "user_message", str(exc)))
            return
        self.status.setText(f"Exported to {path}")

    def _resume_versions(self) -> list[tuple[str, object]]:
        out = []
        for resume in self._resumes.list():
            for version in self._resumes.list_versions(resume.id):
                label = f"{resume.name} — v{version.version_no}"
                if version.label:
                    label += f" ({version.label})"
                out.append((label, version))
        return out

    def _error(self, exc: Exception) -> None:
        self.status.setText("")
        self.regenerate_button.setEnabled(True)
        QMessageBox.warning(self, "AI error", getattr(exc, "user_message", str(exc)))


class _LetterDialog(QDialog):
    def __init__(self, jobs, resume_versions, parent=None, initial=None, lock_job=False):
        super().__init__(parent)
        self.setWindowTitle("Cover letter")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.job_combo = Dropdown()
        for job in jobs:
            label = job.title or "(untitled job)"
            if job.company:
                label += f" — {job.company}"
            self.job_combo.addItem(label, job)
        self.job_combo.setEnabled(not lock_job)
        form.addRow("Job", self.job_combo)

        self.resume_combo = Dropdown()
        self.resume_combo.addItem("(none — use profile only)", None)
        for label, version in resume_versions:
            self.resume_combo.addItem(label, version)
        form.addRow("Resume version", self.resume_combo)

        self.tone_combo = Dropdown()
        for key, description in TONES.items():
            self.tone_combo.addItem(f"{key} — {description}", key)
        form.addRow("Tone", self.tone_combo)

        self.length_combo = Dropdown()
        for key, description in LENGTHS.items():
            self.length_combo.addItem(f"{key} — {description}", key)
        self.length_combo.setCurrentIndex(1)
        form.addRow("Length", self.length_combo)

        self.hiring_manager = QLineEdit()
        self.hiring_manager.setPlaceholderText("Optional — leave blank for a neutral salutation")
        form.addRow("Hiring manager", self.hiring_manager)

        if initial is not None:
            self.tone_combo.setCurrentIndex(list(TONES).index(initial.tone))
            self.length_combo.setCurrentIndex(list(LENGTHS).index(initial.length))

        layout.addWidget(QLabel("Why do you want this role? (your words, used directly)"))
        self.motivation = QPlainTextEdit()
        self.motivation.setMaximumHeight(70)
        layout.addWidget(self.motivation)

        layout.addWidget(QLabel("What do you know about the company?"))
        self.company_notes = QPlainTextEdit()
        self.company_notes.setMaximumHeight(70)
        layout.addWidget(self.company_notes)

        layout.addWidget(QLabel("Any personal connection to the role or company?"))
        self.personal_connection = QPlainTextEdit()
        self.personal_connection.setMaximumHeight(60)
        layout.addWidget(self.personal_connection)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def inputs(self) -> CoverLetterInputs:
        return CoverLetterInputs(
            tone=self.tone_combo.currentData(),
            length=self.length_combo.currentData(),
            company_notes=self.company_notes.toPlainText(),
            motivation=self.motivation.toPlainText(),
            personal_connection=self.personal_connection.toPlainText(),
            hiring_manager=self.hiring_manager.text(),
        )


def _rationale_html(rationale: dict) -> str:
    if not rationale:
        return "<i>No rationale recorded for this version.</i>"
    palette = current()
    parts = ["<h2>Why these points were chosen</h2>"]
    if rationale.get("selection_rationale"):
        parts.append(f"<p>{html.escape(rationale['selection_rationale'])}</p>")
    experiences = rationale.get("selected_experiences") or []
    if experiences:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in experiences)
        parts.append(f"<h3>Experiences drawn on</h3><ul>{items}</ul>")
    claims = rationale.get("claims_needing_confirmation") or []
    if claims:
        items = "".join(f"<li>{html.escape(c)}</li>" for c in claims)
        parts.append(
            f"<h3 style='color:{palette.danger}'>⚠ Confirm before sending</h3><ul>{items}</ul>"
        )
    meta = []
    if rationale.get("inherited_from_version"):
        meta.append(f"carried over from v{rationale['inherited_from_version']} (you edited this)")
    if rationale.get("tone"):
        meta.append(f"tone: {rationale['tone']}")
    if rationale.get("length"):
        meta.append(f"length: {rationale['length']}")
    if rationale.get("prompt_id"):
        meta.append(f"prompt: {rationale['prompt_id']} v{rationale.get('prompt_version', '?')}")
    if meta:
        parts.append(f"<p style='color:{palette.text_muted}'>{html.escape(' · '.join(meta))}</p>")
    return rich_document("".join(parts))
