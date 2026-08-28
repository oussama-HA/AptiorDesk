"""Captured jobs, structured extraction, fit analysis, and tailoring."""

from __future__ import annotations

import html
import logging
import sqlite3

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.models.job import Job, JobExtraction, JobFit
from aptiordesk.database.models.resume import ResumeVersion
from aptiordesk.database.models.tailoring import STRATEGIES
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.features.jobs.service import JobService
from aptiordesk.features.tailoring.service import TailoringService
from aptiordesk.ui.components.common import EmptyState, PageHeader
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.components.fit_ratio import JobFitRatioCard
from aptiordesk.ui.components.rich_text import rich_document
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

_JOB_ROW_HEIGHT = 82


class JobsPage(QWidget):
    tailoring_requested = Signal(int)  # session id

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._jobs = JobRepository(conn)
        self._resumes = ResumeRepository(conn)
        self._service = JobService(conn)
        self._analysis_worker: Worker | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Jobs",
            "Opportunities captured from any job page with the AptiorDesk browser sidebar.",
            eyebrow="OPPORTUNITY LIBRARY",
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
        list_header = QHBoxLayout()
        saved_title = QLabel("Captured jobs")
        saved_title.setProperty("role", "paneTitle")
        list_header.addWidget(saved_title)
        list_header.addStretch(1)
        self.job_count = QLabel("0")
        self.job_count.setProperty("role", "badge")
        list_header.addWidget(self.job_count)
        left_layout.addLayout(list_header)
        self.job_list = QListWidget()
        self.job_list.setObjectName("contentList")
        self.job_list.setSpacing(SPACE["sm"])
        self.job_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.job_list.currentItemChanged.connect(lambda *_: self._show_job())
        self.job_empty = EmptyState(
            "No captured jobs yet",
            "Open a job page in your browser and save it from the AptiorDesk side panel.",
            icon_name="briefcase",
        )
        self.job_stack = QStackedWidget()
        self.job_stack.addWidget(self.job_empty)
        self.job_stack.addWidget(self.job_list)
        left_layout.addWidget(self.job_stack, 1)
        row = QHBoxLayout()
        delete_button = QPushButton("Delete")
        delete_button.setProperty("variant", "danger")
        delete_button.clicked.connect(self._delete_job)
        row.addStretch(1)
        row.addWidget(delete_button)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        right = QWidget()
        right.setProperty("role", "pane")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        right_layout.setSpacing(SPACE["md"])
        self.job_title_label = QLabel("Choose a captured job")
        self.job_title_label.setProperty("role", "focusTitle")
        self.job_title_label.setWordWrap(True)
        right_layout.addWidget(self.job_title_label)
        self.job_meta_label = QLabel("Select a job on the left to review its posting and analysis.")
        self.job_meta_label.setProperty("role", "hint")
        self.job_meta_label.setWordWrap(True)
        right_layout.addWidget(self.job_meta_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.analyze_button = QPushButton("Analyze posting")
        self.analyze_button.clicked.connect(self._analyze)
        actions.addWidget(self.analyze_button)
        self.tailor_button = QPushButton("Tailor resume…")
        self.tailor_button.setProperty("accent", True)
        self.tailor_button.clicked.connect(self._start_tailoring)
        actions.addWidget(self.tailor_button)
        right_layout.addLayout(actions)

        fit_row = QHBoxLayout()
        fit_label = QLabel("Fit against")
        fit_label.setProperty("role", "fieldLabel")
        fit_row.addWidget(fit_label)
        self.version_combo = Dropdown()
        self.version_combo.setAccessibleName("Resume version for job-fit analysis")
        self.version_combo.currentIndexChanged.connect(self._refresh_fit_ratio)
        fit_row.addWidget(self.version_combo, 1)
        self.fit_button = QPushButton("Run job-fit analysis")
        self.fit_button.clicked.connect(self._run_fit)
        fit_row.addWidget(self.fit_button)
        right_layout.addLayout(fit_row)

        self.fit_ratio_card = JobFitRatioCard()
        right_layout.addWidget(self.fit_ratio_card)

        self.tabs = QTabWidget()
        self.extraction_view = QTextBrowser()
        self.fit_view = QTextBrowser()
        self.jd_view = QPlainTextEdit()
        self.jd_view.setReadOnly(True)
        self.tabs.addTab(self.extraction_view, "Analysis")
        self.tabs.addTab(self.fit_view, "Job fit")
        self.tabs.addTab(self.jd_view, "Original posting")
        right_layout.addWidget(self.tabs, 1)

        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        right_layout.addWidget(self.status)
        splitter.addWidget(right)
        splitter.setSizes([310, 760])

        self.reload()

    def _on_job_imported(self, job_id: int) -> None:
        """Move the user to the saved job so the next step is obvious."""
        self.reload()
        for index in range(self.job_list.count()):
            item = self.job_list.item(index)
            job = item.data(Qt.ItemDataRole.UserRole)
            if job is not None and job.id == job_id:
                self.job_list.setCurrentItem(item)
                break

    # -- loading -------------------------------------------------------------

    def reload(self) -> None:
        selected = self._current_job()
        selected_id = selected.id if selected is not None else None
        self.job_list.clear()
        jobs = self._jobs.list()
        self.job_count.setText(str(len(jobs)))
        self.job_stack.setCurrentWidget(self.job_list if jobs else self.job_empty)
        target_row = 0 if jobs else -1
        for index, job in enumerate(jobs):
            entry = QListWidgetItem()
            entry.setData(Qt.ItemDataRole.UserRole, job)
            self.job_list.addItem(entry)
            row = _JobListRow(job)
            entry.setSizeHint(QSize(0, _JOB_ROW_HEIGHT))
            self.job_list.setItemWidget(entry, row)
            if selected_id is not None and job.id == selected_id:
                target_row = index
        self._reload_versions()
        if target_row >= 0:
            self.job_list.setCurrentRow(target_row)
        else:
            self._show_job()

    def _reload_versions(self) -> None:
        self.version_combo.clear()
        for resume in self._resumes.list():
            for version in self._resumes.list_versions(resume.id):
                label = f"{resume.name} — v{version.version_no}"
                if version.label:
                    label += f" ({version.label})"
                self.version_combo.addItem(label, version)

    def _current_job(self) -> Job | None:
        item = self.job_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _current_version(self) -> ResumeVersion | None:
        return self.version_combo.currentData()

    def _show_job(self) -> None:
        job = self._current_job()
        enabled = job is not None
        for widget in (
            self.analyze_button,
            self.fit_button,
            self.tailor_button,
        ):
            widget.setEnabled(enabled)
        if job is None:
            self.fit_ratio_card.set_comparison(None)
            self.job_title_label.setText("Choose a captured job")
            self.job_meta_label.setText(
                "Select a job on the left to review its posting and analysis."
            )
            self.extraction_view.setHtml(
                rich_document("<h3>No job selected</h3><p>Your analysis will appear here.</p>")
            )
            self.fit_view.setHtml(
                rich_document("<h3>No job selected</h3><p>Fit evidence will appear here.</p>")
            )
            self.jd_view.setPlainText("Select a captured job to read the original posting.")
            return
        self._refresh_fit_ratio()
        self.job_title_label.setText(job.title or "(untitled job)")
        self.job_meta_label.setText(_job_meta(job))
        self.jd_view.setPlainText(job.raw_description)
        extraction = self._jobs.latest_analysis(job.id, "extraction")
        self.extraction_view.setHtml(
            _extraction_html(JobExtraction.model_validate(extraction.result))
            if extraction
            else rich_document(
                "<h3>Not analyzed yet</h3><p>Press Analyze posting to structure this job.</p>"
            )
        )
        fit = self._jobs.latest_analysis(job.id, "fit")
        self.fit_view.setHtml(
            _fit_html(JobFit.model_validate(fit.result))
            if fit
            else rich_document(
                "<h3>No fit analysis yet</h3><p>Choose a resume version and run job-fit analysis.</p>"
            )
        )

    # -- actions -------------------------------------------------------------

    def _delete_job(self) -> None:
        job = self._current_job()
        if job is None:
            return
        confirm = QMessageBox.question(
            self, "Delete job", "Delete this job and its analyses? This cannot be undone."
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._jobs.delete(job.id)
            self.reload()

    def _provider_or_warn(self):
        try:
            return get_active_provider(self._conn)
        except Exception as exc:
            QMessageBox.warning(self, "No AI provider", getattr(exc, "user_message", str(exc)))
            return None

    def _analyze(self) -> None:
        job = self._current_job()
        provider = self._provider_or_warn()
        if job is None or provider is None:
            return
        self._busy("Analyzing posting…")
        worker = Worker(lambda: self._service.generate_analysis(provider, job), parent=self)
        self._analysis_worker = worker
        worker.result.connect(self._analysis_ready)
        worker.error.connect(self._error)
        worker.finished.connect(lambda: self._analysis_worker_finished(worker))
        worker.show_progress(
            "Analyzing the job posting",
            f"Extracting responsibilities, requirements, skills, and keywords from "
            f"{job.title or 'this role'} with "
            f"{provider.config.name or provider.config.kind.value}.",
        )
        worker.start()

    def _run_fit(self) -> None:
        job = self._current_job()
        version = self._current_version()
        provider = self._provider_or_warn()
        if job is None or provider is None:
            return
        if version is None:
            QMessageBox.information(
                self, "Job fit", "Add a resume first (Resumes page) to run a fit analysis."
            )
            return
        self._busy("Running job-fit analysis…")
        ratio = self._service.calculate_fit_ratio(job, version)
        self.fit_ratio_card.set_comparison(self._service.fit_comparison(job, version))
        worker = Worker(
            lambda: self._service.generate_fit_analysis(provider, job, version, ratio),
            parent=self,
        )
        self._analysis_worker = worker
        worker.result.connect(self._analysis_ready)
        worker.error.connect(self._error)
        worker.finished.connect(lambda: self._analysis_worker_finished(worker))
        worker.show_progress(
            "Running job-fit analysis",
            f"Comparing {version.label or 'the selected resume'} with "
            f"{job.title or 'this role'} and mapping evidence-backed gaps.",
        )
        worker.start()

    @Slot()
    def _refresh_fit_ratio(self) -> None:
        job = self._current_job()
        version = self._current_version()
        if job is None or version is None:
            self.fit_ratio_card.set_comparison(None)
            return
        try:
            comparison = self._service.fit_comparison(job, version)
        except Exception:
            log.exception("Could not calculate Job Fit Ratio")
            self.fit_ratio_card.set_comparison(None)
            return
        self.fit_ratio_card.set_comparison(comparison)

    def _start_tailoring(self) -> None:
        job = self._current_job()
        version = self._current_version()
        if job is None:
            return
        if version is None:
            QMessageBox.information(
                self, "Tailoring", "Add a resume first (Resumes page) to tailor it."
            )
            return
        strategy, ok = _pick_strategy(self)
        if not ok:
            return
        session = TailoringService(self._conn).create_session(job, version, strategy)
        self.tailoring_requested.emit(session.id)

    # -- helpers -------------------------------------------------------------

    def _analysis_worker_finished(self, worker: Worker) -> None:
        if self._analysis_worker is worker:
            self._analysis_worker = None

    def _busy(self, message: str) -> None:
        self.status.setText(message)
        self.analyze_button.setEnabled(False)
        self.fit_button.setEnabled(False)

    @Slot(object)
    def _analysis_ready(self, generated) -> None:
        """Runs on Qt's UI thread, which owns ``self._conn``."""
        try:
            self._service.persist_generated_analysis(generated)
        except Exception as exc:
            self._error(exc)
            return
        message = (
            "Fit analysis complete." if generated.analysis.kind == "fit" else "Analysis complete."
        )
        self._done(message)

    def _done(self, message: str) -> None:
        self.status.setText(message)
        self.analyze_button.setEnabled(True)
        self.fit_button.setEnabled(True)
        # Refresh the selected row label (title may have been filled in).
        # reload() preserves selection by job id rather than fragile row index.
        self.reload()

    def _error(self, exc: Exception) -> None:
        self.status.setText("")
        self.analyze_button.setEnabled(True)
        self.fit_button.setEnabled(True)
        QMessageBox.warning(self, "AI error", getattr(exc, "user_message", str(exc)))


class _JobListRow(QWidget):
    """Compact two-line job summary used inside the opportunity list."""

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.setProperty("role", "layoutOnly")
        self.setMinimumHeight(_JOB_ROW_HEIGHT)
        self.setMaximumHeight(_JOB_ROW_HEIGHT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        layout.setSpacing(SPACE["xs"])
        title = QLabel(job.title or "Untitled job")
        title.setProperty("role", "listTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(title.fontMetrics().lineSpacing() * 2 + SPACE["xs"])
        layout.addWidget(title)
        meta = QLabel(_job_meta(job))
        meta.setProperty("role", "listMeta")
        meta.setWordWrap(False)
        meta.setToolTip(_job_meta(job))
        layout.addWidget(meta)


def _job_meta(job: Job) -> str:
    parts = [part for part in (job.company, job.location, job.source_name or job.source) if part]
    return "  ·  ".join(parts) or "Captured job"


def _pick_strategy(parent) -> tuple[str, bool]:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Tailoring strategy")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Choose the strategy for this tailoring session:"))
    combo = Dropdown()
    for key, description in STRATEGIES.items():
        combo.addItem(f"{key} — {description[:60]}…", key)
    layout.addWidget(combo)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return combo.currentData(), accepted


# -- HTML rendering -----------------------------------------------------------


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    bullets = "".join(f"<li>{html.escape(i)}</li>" for i in items)
    return f"<h3>{html.escape(title)}</h3><ul>{bullets}</ul>"


def _kv(title: str, value: str) -> str:
    if not value:
        return ""
    return f"<p><b>{html.escape(title)}:</b> {html.escape(value)}</p>"


def _extraction_html(extraction: JobExtraction) -> str:
    parts = ["<h2>Posting analysis</h2>"]
    parts.append(_kv("Title", extraction.title))
    parts.append(_kv("Company", extraction.company))
    parts.append(_kv("Location", extraction.location))
    parts.append(_kv("Seniority", extraction.seniority))
    parts.append(_kv("Experience", extraction.experience_requirements))
    parts.append(_kv("Salary", extraction.salary_info))
    parts.append(_kv("Work authorization", extraction.work_authorization))
    parts.append(_section("Responsibilities", extraction.responsibilities))
    parts.append(_section("Required qualifications", extraction.required_qualifications))
    parts.append(_section("Preferred qualifications", extraction.preferred_qualifications))
    parts.append(_section("Technical skills", extraction.technical_skills))
    parts.append(_section("Soft skills", extraction.soft_skills))
    parts.append(_section("Tools & platforms", extraction.tools_and_platforms))
    parts.append(_section("Education", extraction.education_requirements))
    parts.append(_section("Keywords", extraction.keywords))
    parts.append(_section("⚠ Potential red flags", extraction.red_flags))
    parts.append(_section("Missing / ambiguous information", extraction.missing_or_ambiguous))
    return rich_document("".join(parts))


def _fit_items(title: str, items) -> str:
    if not items:
        return ""
    rows = []
    for item in items:
        row = f"<b>{html.escape(item.requirement)}</b>"
        if item.candidate_evidence:
            row += f"<br><i>Evidence:</i> {html.escape(item.candidate_evidence)}"
        if item.comment:
            row += f"<br>{html.escape(item.comment)}"
        rows.append(f"<li>{row}</li>")
    return f"<h3>{html.escape(title)}</h3><ul>{''.join(rows)}</ul>"


def _fit_html(fit: JobFit) -> str:
    palette = current()
    parts = ["<h2>Job-fit analysis</h2>"]
    if fit.ratio is not None:
        ratio = fit.ratio
        parts.append(
            f"<h3>Job Fit Ratio: {ratio.score}%</h3>"
            f"<p>Measured score before critical-gap penalties: {ratio.base_score}%"
            + (
                f"; visible critical-gap penalty: -{ratio.critical_penalty} points."
                if ratio.critical_penalty
                else "."
            )
            + "</p>"
        )
        factor_rows = "".join(
            "<li>"
            f"<b>{html.escape(factor.label)}: {factor.score}%</b> "
            f"({factor.matched_count}/{factor.total_count} matched)"
            f"<br>{html.escape(factor.explanation)}"
            "</li>"
            for factor in ratio.factors
            if factor.total_count > 0
        )
        if factor_rows:
            parts.append(f"<h3>Scoring factors</h3><ul>{factor_rows}</ul>")
        parts.append(f"<p style='color:{palette.text_muted}'>{html.escape(ratio.methodology)}</p>")
    if fit.summary:
        parts.append(f"<p>{html.escape(fit.summary)}</p>")
    parts.append(_fit_items("✅ Strong matches", fit.strong_matches))
    parts.append(_fit_items("🟡 Partial matches", fit.partial_matches))
    parts.append(_fit_items("❌ Missing qualifications", fit.missing_qualifications))
    parts.append(_fit_items("↔ Transferable experience", fit.transferable_experience))
    parts.append(_section("Gaps / risks", fit.gaps_or_risks))
    parts.append(_section("Worth clarifying", fit.clarifications_needed))
    parts.append(_section("Keywords you can truthfully use", fit.keywords_to_include))
    if fit.methodology:
        parts.append(
            "<h3>How this was assessed</h3>"
            f"<p style='color:{palette.text_muted}'>{html.escape(fit.methodology)}</p>"
        )
    return rich_document("".join(parts))
