"""Resume management page: import with mandatory review, versions, compare,
restore. Every mutation creates a new version; nothing is overwritten."""

from __future__ import annotations

import difflib
import logging
import re
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.models.extraction import ExtractionReport
from aptiordesk.database.models.resume import Resume, ResumeContent, ResumeVersion
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.documents.exporters import export_document
from aptiordesk.documents.pipeline import ExtractionResult
from aptiordesk.documents.render import resume_to_markdown
from aptiordesk.features.resumes.service import ResumeService
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.extraction_progress import ExtractionProgressDialog
from aptiordesk.ui.components.extraction_review import ExtractionReviewDialog
from aptiordesk.ui.components.profile_import_dialog import ProfileImportDialog
from aptiordesk.ui.components.resume_editor import ResumeEditorDialog
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)


class ResumesPage(QWidget):
    #: Emitted after an import updates the profile, so the Profile page reloads.
    profile_updated = Signal()

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._repo = ResumeRepository(conn)
        self._service = ResumeService(conn)

        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Resumes",
            "Import or write a resume, then keep every version you produce.",
            eyebrow="DOCUMENT WORKSPACE",
        )
        outer.addWidget(self.header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # left: resumes
        left = QWidget()
        left.setProperty("role", "pane")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        left_layout.setSpacing(SPACE["md"])
        left_title = QLabel("Resume library")
        left_title.setProperty("role", "paneTitle")
        left_layout.addWidget(left_title)
        self.resume_list = QListWidget()
        self.resume_list.setObjectName("contentList")
        self.resume_list.currentItemChanged.connect(lambda *_: self._reload_versions())
        left_layout.addWidget(self.resume_list, 1)
        row = QGridLayout()
        import_button = QPushButton("Import file…")
        import_button.setProperty("accent", True)
        import_button.clicked.connect(self._import_file)
        new_button = QPushButton("New")
        new_button.clicked.connect(self._create_manual)
        delete_button = QPushButton("Delete")
        delete_button.setProperty("variant", "danger")
        delete_button.clicked.connect(self._delete_resume)
        row.addWidget(import_button, 0, 0, 1, 2)
        row.addWidget(new_button, 1, 0)
        row.addWidget(delete_button, 1, 1)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        # middle: versions
        middle = QWidget()
        middle.setProperty("role", "pane")
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        middle_layout.setSpacing(SPACE["md"])
        versions_title = QLabel("Version history")
        versions_title.setProperty("role", "paneTitle")
        middle_layout.addWidget(versions_title)
        self.version_list = QListWidget()
        self.version_list.setObjectName("contentList")
        self.version_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.version_list.currentItemChanged.connect(lambda *_: self._preview())
        middle_layout.addWidget(self.version_list, 1)
        version_row = QGridLayout()
        edit_button = QPushButton("Edit → new version")
        edit_button.clicked.connect(self._edit_version)
        restore_button = QPushButton("Restore")
        restore_button.clicked.connect(self._restore_version)
        compare_button = QPushButton("Compare selected")
        compare_button.clicked.connect(self._compare)
        self.delete_version_button = QPushButton("Delete version")
        self.delete_version_button.setProperty("variant", "danger")
        self.delete_version_button.clicked.connect(self._delete_version)
        version_row.addWidget(edit_button, 0, 0, 1, 2)
        version_row.addWidget(restore_button, 1, 0)
        version_row.addWidget(compare_button, 1, 1)
        version_row.addWidget(self.delete_version_button, 2, 0, 1, 2)
        middle_layout.addLayout(version_row)
        splitter.addWidget(middle)

        # right: preview
        right = QWidget()
        right.setProperty("role", "pane")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        right_layout.setSpacing(SPACE["md"])
        preview_header = QHBoxLayout()
        preview_title = QLabel("Resume preview")
        preview_title.setProperty("role", "paneTitle")
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        self.download_pdf_button = QPushButton("Download PDF")
        self.download_pdf_button.clicked.connect(lambda: self._export_version("pdf"))
        self.download_docx_button = QPushButton("Download DOCX")
        self.download_docx_button.setProperty("accent", True)
        self.download_docx_button.clicked.connect(lambda: self._export_version("docx"))
        preview_header.addWidget(self.download_pdf_button)
        preview_header.addWidget(self.download_docx_button)
        right_layout.addLayout(preview_header)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setHtml(
            "<h3>No resume selected</h3><p>Choose a resume and version to preview it.</p>"
        )
        right_layout.addWidget(self.preview, 1)
        splitter.addWidget(right)
        splitter.setSizes([250, 270, 570])

        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        outer.addWidget(self.status)

        self.reload()

    # -- data loading --------------------------------------------------------

    def reload(self) -> None:
        self.resume_list.clear()
        for resume in self._repo.list():
            entry = QListWidgetItem(f"{resume.name}  ({resume.source})")
            entry.setData(Qt.ItemDataRole.UserRole, resume)
            self.resume_list.addItem(entry)
        self._reload_versions()

    def select_version(self, resume_id: int, version_id: int) -> bool:
        """Select an exact version for cross-feature navigation."""
        for row in range(self.resume_list.count()):
            resume = self.resume_list.item(row).data(Qt.ItemDataRole.UserRole)
            if resume.id == resume_id:
                self.resume_list.setCurrentRow(row)
                break
        else:
            return False
        for row in range(self.version_list.count()):
            version = self.version_list.item(row).data(Qt.ItemDataRole.UserRole)
            if version.id == version_id:
                self.version_list.setCurrentRow(row)
                return True
        return False

    def _current_resume(self) -> Resume | None:
        item = self.resume_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _current_version(self) -> ResumeVersion | None:
        item = self.version_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _reload_versions(self) -> None:
        self.version_list.clear()
        self.preview.setHtml(
            "<h3>No resume selected</h3><p>Choose a resume and version to preview it.</p>"
        )
        resume = self._current_resume()
        if resume is None:
            return
        for version in self._repo.list_versions(resume.id):
            label = f"v{version.version_no}"
            if version.label:
                label += f" — {version.label}"
            entry = QListWidgetItem(label)
            entry.setData(Qt.ItemDataRole.UserRole, version)
            self.version_list.addItem(entry)
        if self.version_list.count():
            self.version_list.setCurrentRow(0)

    def _preview(self) -> None:
        version = self._current_version()
        has_version = version is not None
        self.download_pdf_button.setEnabled(has_version)
        self.download_docx_button.setEnabled(has_version)
        self.delete_version_button.setEnabled(
            has_version and self._repo.count_versions(version.resume_id) > 1
        )
        if version is None:
            self.preview.setHtml(
                "<h3>No version selected</h3><p>Choose a version to preview it.</p>"
            )
            return
        self.preview.setMarkdown(resume_to_markdown(version.content))

    def _export_version(self, fmt: str) -> None:
        version = self._current_version()
        resume = self._current_resume()
        if version is None or resume is None:
            return
        extension = f".{fmt}"
        default_name = f"{_safe_filename(resume.name)}-v{version.version_no}{extension}"
        file_filter = "PDF (*.pdf)" if fmt == "pdf" else "Word document (*.docx)"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Download resume as {fmt.upper()}",
            default_name,
            file_filter,
        )
        if not path:
            return
        if not path.lower().endswith(extension):
            path += extension
        try:
            exported = export_document(resume_to_markdown(version.content), path, fmt)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Download failed",
                getattr(exc, "user_message", str(exc)),
            )
            return
        self.status.setText(f"Saved {fmt.upper()} to {exported}.")

    # -- import flow ---------------------------------------------------------

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import resume",
            "",
            "Documents (*.pdf *.docx *.txt *.md *.markdown)",
        )
        if not path:
            return
        try:
            document = self._service.read_document(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", getattr(exc, "user_message", str(exc)))
            return

        # A file we could not read properly is stopped here, with the reason,
        # rather than being sent to the AI to produce an empty result.
        if not document.ok:
            QMessageBox.warning(self, "Could not read this file", document.message())
            return
        if document.message():
            proceed = QMessageBox.question(
                self,
                "Check this first",
                f"{document.message()}\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        try:
            provider = get_active_provider(self._conn)
        except Exception as exc:
            QMessageBox.warning(self, "No AI provider", getattr(exc, "user_message", str(exc)))
            return

        progress = ExtractionProgressDialog(
            document.filename, document.char_count, provider.config.model, parent=self
        )
        worker = Worker(
            lambda report: self._service.extract_structure(provider, document, on_progress=report),
            parent=self,
        )
        worker.progress.connect(progress.handle_event)
        worker.result.connect(
            lambda out: (progress.finish(), self._review_import(path, document, *out))
        )
        worker.error.connect(lambda exc: (progress.finish(), self._show_extraction_error(exc)))
        worker.start()
        progress.exec()

    def _review_import(
        self,
        path: str,
        document: ExtractionResult,
        content: ResumeContent,
        report: ExtractionReport,
    ) -> None:
        self.status.setText("")
        dialog = ExtractionReviewDialog(content, report, document, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, ok = QInputDialog.getText(
            self, "Resume name", "Name for this resume:", text=_suggest_name(path)
        )
        if not ok or not name.strip():
            return
        corrected = dialog.content()
        _, version = self._service.create_imported(
            name.strip(),
            document.filename,
            corrected,
            document.text,
            report=report,
            diagnosis=str(document.diagnosis),
        )
        self.reload()
        self.status.setText(f"Imported “{name.strip()}”.")
        self._offer_profile_import(corrected, report, version.id)

    def _offer_profile_import(
        self, content: ResumeContent, report: ExtractionReport, version_id: int
    ) -> None:
        """The point of importing a resume is usually to fill in the profile,
        so offer it here instead of making the user find it themselves."""
        answer = QMessageBox.question(
            self,
            "Update your profile?",
            "Use this resume to fill in your candidate profile?\n\n"
            "You will see exactly what would change and can approve each item.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        dialog = ProfileImportDialog(
            self._conn, content, report, source_resume_version_id=version_id, parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.profile_updated.emit()

    def _show_extraction_error(self, exc: Exception) -> None:
        """Extraction failures carry a report and often the raw model output;
        show that rather than a generic message."""
        self.status.setText("")
        message = getattr(exc, "user_message", str(exc))
        box = QMessageBox(self)
        box.setWindowTitle("Could not read this resume")
        box.setText(message)
        raw = getattr(exc, "raw_output", "")
        report = getattr(exc, "report", None)
        details = []
        if report is not None:
            details.extend(s.summary() for s in report.sections)
        if raw:
            details.append("\nRaw model output:\n" + str(raw)[:2000])
        if details:
            box.setDetailedText("\n".join(details))
        box.exec()

    def _create_manual(self) -> None:
        dialog = ResumeEditorDialog(ResumeContent(), "New resume", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, ok = QInputDialog.getText(self, "Resume name", "Name for this resume:")
        if not ok or not name.strip():
            return
        self._service.create_manual(name.strip(), dialog.content())
        self.reload()

    # -- version actions -----------------------------------------------------

    def _edit_version(self) -> None:
        version = self._current_version()
        if version is None:
            return
        dialog = ResumeEditorDialog(
            version.content.model_copy(deep=True),
            f"Edit v{version.version_no} — saves as a new version",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._service.save_edited(version, dialog.content())
            self._reload_versions()

    def _restore_version(self) -> None:
        version = self._current_version()
        if version is None:
            return
        self._service.restore(version)
        self._reload_versions()

    def _delete_version(self) -> None:
        version = self._current_version()
        if version is None:
            return
        if self._repo.count_versions(version.resume_id) <= 1:
            QMessageBox.information(
                self,
                "Keep one version",
                "This is the resume’s only version. Delete the resume itself if "
                "you no longer need it.",
            )
            return
        confirm = QMessageBox.question(
            self,
            "Delete resume version?",
            f"Delete v{version.version_no}"
            f"{f' — {version.label}' if version.label else ''}?\n\n"
            "Any feature linked to this exact version will no longer use it. "
            "This cannot be undone.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_version(version)
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not delete version", getattr(exc, "user_message", str(exc))
            )
            return
        self._reload_versions()
        self.status.setText(f"Deleted v{version.version_no}.")

    def _compare(self) -> None:
        selected = self.version_list.selectedItems()
        if len(selected) != 2:
            QMessageBox.information(
                self, "Compare", "Select exactly two versions (Ctrl+click) to compare."
            )
            return
        versions = sorted(
            (item.data(Qt.ItemDataRole.UserRole) for item in selected),
            key=lambda v: v.version_no,
        )
        old_lines = resume_to_markdown(versions[0].content).splitlines()
        new_lines = resume_to_markdown(versions[1].content).splitlines()
        html = difflib.HtmlDiff(wrapcolumn=60).make_table(
            old_lines,
            new_lines,
            f"v{versions[0].version_no}",
            f"v{versions[1].version_no}",
        )
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Compare v{versions[0].version_no} → v{versions[1].version_no}")
        dialog.resize(980, 640)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(_diff_css() + html)
        layout.addWidget(browser)
        dialog.exec()

    def _delete_resume(self) -> None:
        resume = self._current_resume()
        if resume is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete resume",
            f"Delete “{resume.name}” and ALL of its versions? This cannot be undone.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._repo.delete(resume.id)
            self.reload()

    def _show_error(self, exc: Exception) -> None:
        self.status.setText("")
        QMessageBox.warning(self, "AI error", getattr(exc, "user_message", str(exc)))


def _diff_css() -> str:
    palette = current()
    return f"""
    <style>
    table.diff {{font-family: Consolas, monospace; font-size: 9pt; border: none;}}
    .diff_header {{background: {palette.surface_raised}; color: {palette.text_muted};}}
    td.diff_header {{text-align: right; padding: 0 6px;}}
    .diff_next {{display: none;}}
    .diff_add {{background-color: {palette.success_soft};}}
    .diff_chg {{background-color: {palette.warning_soft};}}
    .diff_sub {{background-color: {palette.danger_soft};}}
    </style>
    """


def _suggest_name(path: str) -> str:
    filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", name).strip(" .-")
    return cleaned or "resume"
