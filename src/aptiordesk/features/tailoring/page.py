"""Tailoring review page: generate suggestions, review each one, apply the
accepted set as a new resume version."""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.models.tailoring import STRATEGIES, Suggestion
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.features.jobs.service import JobService
from aptiordesk.features.tailoring.service import TailoringService
from aptiordesk.ui.components.common import EmptyState, PageHeader
from aptiordesk.ui.components.fit_ratio import JobFitRatioCard
from aptiordesk.ui.components.forms import SectionCard
from aptiordesk.ui.components.suggestion_card import SuggestionCard
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

_EMPTY_HINT = (
    "Open the Jobs page, select a job and a resume version, then press "
    "“Tailor resume…” to start a session here."
)


class TailoringPage(QWidget):
    view_resume_requested = Signal(int, int)

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._service = TailoringService(conn)
        self._fit_service = JobService(conn)
        self._jobs = JobRepository(conn)
        self._resumes = ResumeRepository(conn)
        self._session = None
        self._job = None
        self._cards: list[SuggestionCard] = []
        self._worker: Worker | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Resume tailoring",
            "Review each suggested change before any of it reaches your resume.",
            eyebrow="EVIDENCE-BASED EDITING",
        )
        outer.addWidget(self.header)

        history = SectionCard(
            "Tailored resume history",
            "Every applied tailoring result is a normal resume version you can review, "
            "download, compare, or edit.",
        )
        history_row = QHBoxLayout()
        history_row.setSpacing(SPACE["md"])
        self.history_list = QListWidget()
        self.history_list.setObjectName("tailoredResumeHistory")
        self.history_list.setMaximumHeight(138)
        self.history_list.currentItemChanged.connect(lambda *_: self._update_history_action())
        history_row.addWidget(self.history_list, 1)
        self.view_resume_button = QPushButton("View in Resumes")
        self.view_resume_button.clicked.connect(self._view_selected_resume)
        self.view_resume_button.setEnabled(False)
        history_row.addWidget(self.view_resume_button, alignment=Qt.AlignmentFlag.AlignTop)
        history.body.addLayout(history_row)
        outer.addWidget(history)

        session_bar = QFrame()
        session_bar.setProperty("role", "actionBar")
        session_layout = QVBoxLayout(session_bar)
        session_layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        session_layout.setSpacing(SPACE["md"])
        self.context_label = QLabel(_EMPTY_HINT)
        self.context_label.setWordWrap(True)
        self.context_label.setProperty("role", "hint")
        session_layout.addWidget(self.context_label)

        controls = QHBoxLayout()
        self.generate_button = QPushButton("Generate suggestions")
        self.generate_button.setProperty("accent", True)
        self.generate_button.clicked.connect(self._generate)
        self.generate_button.setEnabled(False)
        controls.addWidget(self.generate_button)
        self.accept_all_button = QPushButton("Accept all unflagged")
        self.accept_all_button.clicked.connect(self._accept_all_unflagged)
        self.accept_all_button.setEnabled(False)
        controls.addWidget(self.accept_all_button)
        controls.addStretch(1)
        self.apply_button = QPushButton("Apply accepted → new version")
        self.apply_button.setProperty("accent", True)
        self.apply_button.clicked.connect(self._apply)
        self.apply_button.setEnabled(False)
        controls.addWidget(self.apply_button)
        session_layout.addLayout(controls)
        outer.addWidget(session_bar)

        self.fit_ratio_card = JobFitRatioCard()
        self.fit_ratio_card.set_comparison(None)
        outer.addWidget(self.fit_ratio_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container.setProperty("role", "layoutOnly")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, SPACE["sm"], 0)
        self._container_layout.setSpacing(SPACE["md"])
        self.empty_state = EmptyState(
            "No tailoring session selected",
            "Open a captured job, choose a resume version, and start tailoring from the Jobs page.",
            icon_name="wand",
        )
        self._container_layout.addWidget(self.empty_state)
        self._container_layout.addStretch(1)
        scroll.setWidget(self._container)
        outer.addWidget(scroll, 1)

        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        outer.addWidget(self.status)
        self.reload()

    # -- session -------------------------------------------------------------

    def reload(self, selected_version_id: int | None = None) -> None:
        self.history_list.clear()
        selected_row = -1
        for resume, version in self._resumes.list_tailored_versions():
            label = f"{resume.name} · v{version.version_no}"
            if version.label:
                label += f"\n{version.label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (resume, version))
            self.history_list.addItem(item)
            if version.id == selected_version_id:
                selected_row = self.history_list.count() - 1
        if self.history_list.count():
            self.history_list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        self._update_history_action()

    def _update_history_action(self) -> None:
        item = self.history_list.currentItem()
        self.view_resume_button.setEnabled(item is not None)
        if item is None:
            return
        _resume, version = item.data(Qt.ItemDataRole.UserRole)
        if version.tailoring_session_id is None:
            return
        session = self._service._repo.get_session(version.tailoring_session_id)
        job = self._jobs.get(session.job_id) if session is not None else None
        if job is not None:
            self.fit_ratio_card.set_comparison(self._fit_service.fit_comparison(job, version))

    def _view_selected_resume(self) -> None:
        item = self.history_list.currentItem()
        if item is None:
            return
        resume, version = item.data(Qt.ItemDataRole.UserRole)
        self.view_resume_requested.emit(resume.id, version.id)

    def load_session(self, session_id: int) -> None:
        self.reload()
        self._session = self._service._repo.get_session(session_id)
        if self._session is None:
            return
        self._job = self._jobs.get(self._session.job_id)
        version = self._resumes.get_version(self._session.base_resume_version_id)
        resume = self._resumes.get(version.resume_id) if version else None
        self.context_label.setText(
            f"Tailoring <b>{resume.name if resume else '?'} v{version.version_no if version else '?'}</b> "
            f"for <b>{self._job.title or 'this job'}</b>"
            f"{f' at {self._job.company}' if self._job.company else ''} — "
            f"strategy: {self._session.strategy} ({STRATEGIES[self._session.strategy]})"
        )
        if self._job is not None and version is not None:
            self.fit_ratio_card.set_comparison(self._fit_service.fit_comparison(self._job, version))
        self.generate_button.setEnabled(True)
        self._render_suggestions()

    def _render_suggestions(self) -> None:
        for card in self._cards:
            card.setParent(None)
        self._cards.clear()
        if self._session is None:
            return
        suggestions = self._service.list_suggestions(self._session.id)
        self.empty_state.setVisible(not suggestions)
        for suggestion in suggestions:
            card = SuggestionCard(suggestion)
            card.accepted.connect(self._on_accept)
            card.rejected.connect(self._on_reject)
            card.edited.connect(self._on_edit)
            self._container_layout.insertWidget(self._container_layout.count() - 1, card)
            self._cards.append(card)
        has_any = bool(suggestions)
        if not has_any:
            self.empty_state.set_message(
                "Ready for suggestions",
                "Generate suggestions when you are ready. Nothing changes until you approve it.",
            )
        self.accept_all_button.setEnabled(has_any)
        self._update_apply_state()
        if has_any:
            flagged = sum(1 for s in suggestions if s.warnings)
            self.status.setText(
                f"{len(suggestions)} suggestion(s)"
                + (f", {flagged} flagged for review" if flagged else "")
            )

    def _update_apply_state(self) -> None:
        chosen = [c for c in self._cards if c.suggestion.status in ("accepted", "edited")]
        self.apply_button.setEnabled(bool(chosen))

    # -- actions -------------------------------------------------------------

    def _generate(self) -> None:
        try:
            provider = get_active_provider(self._conn)
        except Exception as exc:
            QMessageBox.warning(self, "No AI provider", getattr(exc, "user_message", str(exc)))
            return
        self.generate_button.setEnabled(False)
        self.status.setText("Generating suggestions — this can take a moment…")
        session, job = self._session, self._job
        base = self._resumes.get_version(session.base_resume_version_id)
        # Read analysis data on the UI connection before the worker starts.
        # The frozen context contains no SQLite objects and is safe to pass on.
        context = self._service.analysis_context(session, job, base)
        worker = Worker(
            lambda: self._service.generate_suggestions_for_version(
                provider, session, job, base, context
            ),
            parent=self,
        )
        self._worker = worker
        worker.result.connect(self._on_generated)
        worker.error.connect(self._error)
        worker.finished.connect(lambda: self._worker_finished(worker))
        worker.show_progress(
            "Tailoring your resume",
            f"Using {provider.config.name or provider.config.kind.value} to integrate "
            "supported job keywords and build evidence-grounded suggestions. Large "
            "resumes and local models can take several minutes; AptiorDesk will keep waiting.",
        )
        worker.start()

    def _worker_finished(self, worker: Worker) -> None:
        if self._worker is worker:
            self._worker = None

    @Slot(object)
    def _on_generated(self, generated) -> None:
        """Persist only after Qt delivers the worker result to the UI thread."""
        try:
            self._service.persist_generated_suggestions(generated)
        except Exception as exc:
            self._error(exc)
            return
        self.generate_button.setEnabled(True)
        self._render_suggestions()

    def _on_accept(self, suggestion: Suggestion) -> None:
        self._service.accept(suggestion)
        suggestion.status = "accepted"
        self._refresh_cards()

    def _on_reject(self, suggestion: Suggestion) -> None:
        self._service.reject(suggestion)
        suggestion.status = "rejected"
        self._refresh_cards()

    def _on_edit(self, suggestion: Suggestion, text: str) -> None:
        if not text:
            return
        self._service.edit(suggestion, text)
        suggestion.status = "edited"
        suggestion.edited_text = text
        self._refresh_cards()

    def _accept_all_unflagged(self) -> None:
        for card in self._cards:
            if card.suggestion.status == "pending" and not card.suggestion.warnings:
                self._service.accept(card.suggestion)
                card.suggestion.status = "accepted"
        self._refresh_cards()

    def _refresh_cards(self) -> None:
        for card in self._cards:
            card.refresh()
        self._update_apply_state()

    def _apply(self) -> None:
        version = self._service.apply(self._session, self._job)
        if version is None:
            QMessageBox.information(
                self, "Nothing applied", "Accept at least one suggestion first."
            )
            return
        QMessageBox.information(
            self,
            "Tailored resume created",
            f"Created version v{version.version_no} — “{version.label}”.\n\n"
            "Your original version is unchanged; find both on the Resumes page.",
        )
        self.apply_button.setEnabled(False)
        self.status.setText(f"Applied → v{version.version_no}")
        self.reload(version.id)
        self.fit_ratio_card.set_comparison(self._fit_service.fit_comparison(self._job, version))

    def _error(self, exc: Exception) -> None:
        self.generate_button.setEnabled(True)
        self.status.setText("")
        QMessageBox.warning(self, "AI error", getattr(exc, "user_message", str(exc)))
