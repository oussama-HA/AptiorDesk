"""Candidate profile editor.

Basics/contact/preferences/work-auth as forms, plus per-kind item lists
(experience, education, skills, ...) edited through a dialog whose fields are
derived from the pydantic model for that kind.
"""

from __future__ import annotations

import logging
import sqlite3
import types
import typing

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.models.profile import ITEM_MODELS, Profile, ProfileItem
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.features.profile.legacy_import import import_legacy_config
from aptiordesk.features.resumes.service import ResumeService
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.components.extraction_progress import ExtractionProgressDialog
from aptiordesk.ui.components.extraction_review import ExtractionReviewDialog
from aptiordesk.ui.components.forms import EntryRow, FieldGrid, SectionCard
from aptiordesk.ui.components.profile_import_dialog import ProfileImportDialog
from aptiordesk.ui.components.profile_strength import ProfileStrengthCard
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

_ITEM_TABS: list[tuple[str, str]] = [
    ("experience", "Experience"),
    ("education", "Education"),
    ("skill", "Skills"),
    ("project", "Projects"),
    ("certification", "Certifications"),
    ("language", "Languages"),
    ("award", "Awards"),
    ("publication", "Publications"),
    ("volunteer", "Volunteering"),
]

_MULTILINE_FIELDS = {"description", "details", "notes", "summary"}

_EMPTY_TEXT = {
    "experience": "No roles yet. Import a resume, or add one by hand.",
    "education": "No education yet.",
    "skill": "No skills yet. These feed keyword matching when you tailor a resume.",
    "project": "No projects yet.",
    "certification": "No certifications yet.",
    "language": "No languages yet.",
    "award": "No awards yet.",
    "publication": "No publications yet.",
    "volunteer": "No volunteering yet.",
}


class ProfilePage(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._repo = ProfileRepository(conn)
        self._profile: Profile = self._repo.get_default()

        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Candidate profile",
            "The source of truth for tailoring, letters, and interview prep.",
            eyebrow="CAREER EVIDENCE",
        )
        outer.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, SPACE["xs"], SPACE["sm"], SPACE["md"])
        layout.setSpacing(SPACE["lg"])

        self.strength_card = ProfileStrengthCard(conn, on_import=self._import_from_resume)
        layout.addWidget(self.strength_card)
        layout.addWidget(self._build_basics_group())
        layout.addWidget(self._build_preferences_group())
        layout.addWidget(self._build_work_auth_group())
        self.background_card = self._build_items_group()
        layout.addWidget(self.background_card)
        layout.addStretch(1)

        footer_bar = QFrame()
        footer_bar.setProperty("role", "actionBar")
        footer = QHBoxLayout(footer_bar)
        footer.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        footer.setSpacing(SPACE["sm"])
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "hint")
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        resume_button = QPushButton("Build profile from a resume…")
        resume_button.setToolTip(
            "Read a PDF, DOCX, TXT, or Markdown resume and fill in these fields "
            "automatically. You review every change before it is applied."
        )
        resume_button.clicked.connect(self._import_from_resume)
        footer.addWidget(resume_button)
        import_button = QPushButton("Import legacy config.json…")
        import_button.setProperty("variant", "ghost")
        import_button.setToolTip(
            "One-time import from the old Whisper Interview app's config.json "
            "(bio, Ollama model, interview notes)."
        )
        import_button.clicked.connect(self._import_legacy)
        footer.addWidget(import_button)
        save_button = QPushButton("Save profile")
        save_button.setProperty("accent", True)
        save_button.clicked.connect(self.save)
        footer.addWidget(save_button)
        outer.addWidget(footer_bar)

        self._load_into_forms()
        self._reload_all_item_lists()

    # -- form construction ---------------------------------------------------

    def _build_basics_group(self) -> SectionCard:
        card = SectionCard(
            "Basics and contact",
            "What appears at the top of a resume or a cover letter.",
            icon="user",
        )
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("Ada Lovelace")
        self.summary = QPlainTextEdit()
        self.summary.setPlaceholderText("Professional summary, in your own voice…")
        self.summary.setFixedHeight(84)
        self.email = QLineEdit()
        self.email.setPlaceholderText("you@example.com")
        self.phone = QLineEdit()
        self.location = QLineEdit()
        self.location.setPlaceholderText("City, country")
        self.linkedin_url = QLineEdit()
        self.portfolio_url = QLineEdit()
        self.github_url = QLineEdit()

        grid = FieldGrid(columns=2)
        grid.add("Full name", self.display_name)
        grid.add("Location", self.location)
        grid.add("Email", self.email)
        grid.add("Phone", self.phone)
        grid.add("LinkedIn", self.linkedin_url)
        grid.add("GitHub", self.github_url)
        grid.add("Portfolio", self.portfolio_url)
        grid.add("Summary", self.summary, span=True)
        card.body.addWidget(grid)
        return card

    def _build_preferences_group(self) -> SectionCard:
        card = SectionCard(
            "What you are looking for",
            "Used to guide career planning, job-fit analysis, and tailoring.",
            icon="target",
        )
        self.target_titles = QLineEdit()
        self.target_titles.setPlaceholderText("Data Engineer, ML Engineer")
        self.target_industries = QLineEdit()
        self.target_industries.setPlaceholderText("Fintech, health")
        self.preferred_locations = QLineEdit()
        self.preferred_locations.setPlaceholderText("London, Berlin")
        self.work_mode = Dropdown()
        self.work_mode.addItems(["", "remote", "hybrid", "onsite", "flexible"])
        self.salary_min = QSpinBox()
        self.salary_min.setRange(0, 10_000_000)
        self.salary_min.setSpecialValueText("—")
        self.salary_min.setGroupSeparatorShown(True)
        self.salary_max = QSpinBox()
        self.salary_max.setRange(0, 10_000_000)
        self.salary_max.setSpecialValueText("—")
        self.salary_max.setGroupSeparatorShown(True)
        self.salary_currency = QLineEdit()
        self.salary_currency.setPlaceholderText("USD")

        grid = FieldGrid(columns=2)
        grid.add("Target titles", self.target_titles, "Comma-separated")
        grid.add("Target industries", self.target_industries, "Comma-separated")
        grid.add("Preferred locations", self.preferred_locations, "Comma-separated")
        grid.add("Work mode", self.work_mode)
        salary = QWidget()
        salary_row = QHBoxLayout(salary)
        salary_row.setContentsMargins(0, 0, 0, 0)
        salary_row.setSpacing(SPACE["sm"])
        salary_row.addWidget(self.salary_min, 1)
        to_label = QLabel("to")
        to_label.setProperty("role", "hint")
        salary_row.addWidget(to_label)
        salary_row.addWidget(self.salary_max, 1)
        salary_row.addWidget(self.salary_currency)
        grid.add("Salary range", salary, span=True)
        card.body.addWidget(grid)
        return card

    def _build_work_auth_group(self) -> SectionCard:
        card = SectionCard(
            "Work authorisation",
            "Only used to flag roles you would need sponsorship for.",
            icon="shield",
        )
        self.authorized_in = QLineEdit()
        self.authorized_in.setPlaceholderText("United States, EU")
        self.needs_sponsorship = Dropdown()
        self.needs_sponsorship.addItems(["Unspecified", "No", "Yes"])
        self.work_auth_notes = QLineEdit()

        grid = FieldGrid(columns=2)
        grid.add("Authorised to work in", self.authorized_in, "Comma-separated")
        grid.add("Needs visa sponsorship", self.needs_sponsorship)
        grid.add("Notes", self.work_auth_notes, span=True)
        card.body.addWidget(grid)
        return card

    def _build_items_group(self) -> SectionCard:
        card = SectionCard(
            "Your background",
            "Everything tailoring, cover letters, and interview prep draw on.",
            icon="briefcase",
        )
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._item_lists: dict[str, QListWidget] = {}
        self._item_empties: dict[str, QLabel] = {}
        for kind, label in _ITEM_TABS:
            tab = QWidget()
            tab.setProperty("role", "layoutOnly")
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, SPACE["sm"], 0, 0)
            tab_layout.setSpacing(SPACE["sm"])
            tab_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            actions = QHBoxLayout()
            actions.addStretch(1)
            add = QPushButton(f"Add {label.rstrip('s').lower()}")
            add.setProperty("size", "sm")
            add.clicked.connect(lambda _=False, k=kind: self._add_item(k))
            add.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            actions.addWidget(add)
            tab_layout.addLayout(actions)

            empty = QLabel(_EMPTY_TEXT.get(kind, "Nothing here yet."))
            empty.setProperty("role", "hint")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            empty.setContentsMargins(0, SPACE["sm"], 0, SPACE["sm"])
            empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            tab_layout.addWidget(empty)
            self._item_empties[kind] = empty

            item_list = QListWidget()
            # Rows are full widgets, so the list must not draw its own frame
            # and selection highlight on top of them.
            item_list.setProperty("role", "bare")
            item_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
            # The page already scrolls. A second scrollbar nested inside it
            # traps the wheel and hides rows, so the list grows to fit instead.
            item_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            item_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            item_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            tab_layout.addWidget(item_list)
            self._item_lists[kind] = item_list

            self.tabs.addTab(tab, label)
        self.tabs.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_background_height)
        )
        card.body.addWidget(self.tabs)
        QTimer.singleShot(0, self._sync_background_height)
        return card

    def _sync_background_height(self) -> None:
        """Keep the active background tab exactly as tall as its content."""
        page = self.tabs.currentWidget()
        if page is None or page.layout() is None:
            return
        page.layout().activate()
        content_height = page.layout().sizeHint().height()
        chrome_height = self.tabs.tabBar().sizeHint().height() + 2
        self.tabs.setFixedHeight(chrome_height + content_height)
        self.tabs.updateGeometry()
        if hasattr(self, "background_card"):
            self.background_card.updateGeometry()

    # -- load/save -----------------------------------------------------------

    def _load_into_forms(self) -> None:
        p = self._profile
        self.display_name.setText(p.display_name)
        self.summary.setPlainText(p.summary)
        c = p.contact
        self.email.setText(c.email)
        self.phone.setText(c.phone)
        self.location.setText(c.location)
        self.linkedin_url.setText(c.linkedin_url)
        self.portfolio_url.setText(c.portfolio_url)
        self.github_url.setText(c.github_url)
        prefs = p.preferences
        self.target_titles.setText(", ".join(prefs.target_titles))
        self.target_industries.setText(", ".join(prefs.target_industries))
        self.preferred_locations.setText(", ".join(prefs.preferred_locations))
        self.work_mode.setCurrentText(prefs.work_mode)
        self.salary_min.setValue(prefs.salary_min or 0)
        self.salary_max.setValue(prefs.salary_max or 0)
        self.salary_currency.setText(prefs.salary_currency)
        auth = p.work_auth
        self.authorized_in.setText(", ".join(auth.authorized_in))
        self.needs_sponsorship.setCurrentIndex(
            0 if auth.needs_sponsorship is None else (2 if auth.needs_sponsorship else 1)
        )
        self.work_auth_notes.setText(auth.notes)

    def save(self) -> None:
        p = self._profile
        p.display_name = self.display_name.text()
        p.summary = self.summary.toPlainText()
        c = p.contact
        c.email = self.email.text()
        c.phone = self.phone.text()
        c.location = self.location.text()
        c.linkedin_url = self.linkedin_url.text()
        c.portfolio_url = self.portfolio_url.text()
        c.github_url = self.github_url.text()
        prefs = p.preferences
        prefs.target_titles = _split_csv(self.target_titles.text())
        prefs.target_industries = _split_csv(self.target_industries.text())
        prefs.preferred_locations = _split_csv(self.preferred_locations.text())
        prefs.work_mode = self.work_mode.currentText()
        prefs.salary_min = self.salary_min.value() or None
        prefs.salary_max = self.salary_max.value() or None
        prefs.salary_currency = self.salary_currency.text()
        auth = p.work_auth
        auth.authorized_in = _split_csv(self.authorized_in.text())
        auth.needs_sponsorship = {0: None, 1: False, 2: True}[self.needs_sponsorship.currentIndex()]
        auth.notes = self.work_auth_notes.text()

        self._repo.save(p)
        self.status_label.setText("Saved.")
        self.status_label.setProperty("role", "success")
        self.status_label.style().polish(self.status_label)
        self.strength_card.refresh()

    def reload_from_store(self) -> None:
        """Re-read the profile after something else changed it (the setup
        wizard, a legacy import)."""
        self._profile = self._repo.get_default()
        self._load_into_forms()
        self._reload_all_item_lists()
        self.strength_card.refresh()

    def _import_from_resume(self) -> None:
        """Read a resume file and offer its contents as profile changes.

        Deliberately does not save a Resume record — this entry point is about
        the profile. Importing on the Resumes page does both.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose your resume",
            "",
            "Documents (*.pdf *.docx *.txt *.md *.markdown)",
        )
        if not path:
            return

        service = ResumeService(self._conn)
        try:
            document = service.read_document(path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not read this file", getattr(exc, "user_message", str(exc))
            )
            return
        if not document.ok:
            QMessageBox.warning(self, "Could not read this file", document.message())
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
            lambda report: service.extract_structure(provider, document, on_progress=report),
            parent=self,
        )
        worker.progress.connect(progress.handle_event)
        worker.result.connect(
            lambda out: (progress.finish(), self._review_resume_profile(document, *out))
        )
        worker.error.connect(lambda exc: (progress.finish(), self._resume_import_failed(exc)))
        worker.start()
        progress.exec()

    def _review_resume_profile(self, document, content, report) -> None:
        self.status_label.setText("")
        # The extraction is reviewed first, then its effect on the profile —
        # correcting a misread here avoids importing the mistake.
        review = ExtractionReviewDialog(content, report, document, parent=self)
        if review.exec() != QDialog.DialogCode.Accepted:
            return
        dialog = ProfileImportDialog(self._conn, review.content(), report, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload_from_store()
            self.status_label.setText(dialog.result_summary)

    def _resume_import_failed(self, exc: Exception) -> None:
        self.status_label.setText("")
        QMessageBox.warning(
            self, "Could not read this resume", getattr(exc, "user_message", str(exc))
        )

    def _import_legacy(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the legacy config.json", "", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            report = import_legacy_config(self._conn, path)
        except Exception as exc:
            log.exception("Legacy import failed")
            QMessageBox.warning(self, "Import failed", f"Could not import this file: {exc}")
            return
        self._profile = self._repo.get_default()
        self._load_into_forms()
        QMessageBox.information(self, "Legacy import", report.summary())

    # -- item CRUD -----------------------------------------------------------

    def _reload_all_item_lists(self) -> None:
        for kind, _ in _ITEM_TABS:
            self._reload_item_list(kind)

    def _reload_item_list(self, kind: str) -> None:
        widget = self._item_lists[kind]
        widget.clear()
        items = self._repo.list_items(self._profile.id, kind)
        self._item_empties[kind].setVisible(not items)
        widget.setVisible(bool(items))
        for item in items:
            row = _entry_row(item)
            row.clicked.connect(lambda _=False, k=kind, i=item: self._edit_item(k, i))
            row.add_action("edit", "Edit", lambda _=False, k=kind, i=item: self._edit_item(k, i))
            row.add_action(
                "trash", "Remove", lambda _=False, k=kind, i=item: self._remove_item(k, i)
            )
            entry = QListWidgetItem()
            entry.setSizeHint(row.sizeHint())
            entry.setData(0x0100, item)  # Qt.UserRole
            widget.addItem(entry)
            widget.setItemWidget(entry, row)
        self._fit_list_to_contents(widget)
        QTimer.singleShot(0, self._sync_background_height)

    @staticmethod
    def _fit_list_to_contents(widget: QListWidget) -> None:
        """Size the list to its rows so the page scrolls, not the list."""
        spacing = 8  # matches the per-item margin in the "bare" list style
        total = sum(widget.sizeHintForRow(row) + spacing for row in range(widget.count()))
        widget.setFixedHeight(max(total, 0))

    def _add_item(self, kind: str) -> None:
        dialog = ItemDialog(kind, data=None, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._repo.add_item(
                ProfileItem(
                    profile_id=self._profile.id,
                    kind=kind,
                    data=dialog.values(),
                    user_edited=True,
                )
            )
            self._reload_item_list(kind)
            self.strength_card.refresh()

    def _edit_item(self, kind: str, item: ProfileItem) -> None:
        dialog = ItemDialog(kind, data=item.data, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item.data = dialog.values()
            self._repo.update_item(item)
            # A hand edit both confirms the entry (clears the review flag) and
            # protects it: a later resume import must ask before replacing it.
            self._repo.mark_user_edited(item.id)
            self._reload_item_list(kind)
            self.strength_card.refresh()

    def _remove_item(self, kind: str, item: ProfileItem) -> None:
        confirm = QMessageBox.question(self, "Remove entry", f"Remove “{_item_summary(item)}”?")
        if confirm == QMessageBox.StandardButton.Yes:
            self._repo.delete_item(item.id)
            self._reload_item_list(kind)
            self.strength_card.refresh()


class ItemDialog(QDialog):
    """Edit dialog whose fields are generated from the kind's pydantic model:
    str → line edit (multiline for description-like fields), list[str] → one
    entry per line."""

    def __init__(self, kind: str, data: dict | None, parent=None):
        super().__init__(parent)
        self._model = ITEM_MODELS[kind]
        self.setWindowTitle(f"{'Edit' if data else 'Add'} {kind}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self._editors: dict[str, QLineEdit | QPlainTextEdit] = {}

        instance = self._model.model_validate(data or {})
        for name, field_info in self._model.model_fields.items():
            value = getattr(instance, name)
            label = name.replace("_", " ").capitalize()
            if _is_str_list(field_info.annotation):
                editor = QPlainTextEdit()
                editor.setPlaceholderText("One per line")
                editor.setMaximumHeight(90)
                editor.setPlainText("\n".join(value))
                form.addRow(label, editor)
            elif name in _MULTILINE_FIELDS:
                editor = QPlainTextEdit()
                editor.setMaximumHeight(80)
                editor.setPlainText(value)
                form.addRow(label, editor)
            else:
                editor = QLineEdit(str(value))
                if name == "end_date":
                    editor.setPlaceholderText("Empty = present")
                form.addRow(label, editor)
            self._editors[name] = editor

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        out: dict = {}
        for name, editor in self._editors.items():
            field_info = self._model.model_fields[name]
            if _is_str_list(field_info.annotation):
                text = editor.toPlainText()
                out[name] = [line.strip() for line in text.splitlines() if line.strip()]
            elif isinstance(editor, QPlainTextEdit):
                out[name] = editor.toPlainText().strip()
            else:
                out[name] = editor.text().strip()
        return out


def _is_str_list(annotation) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (list, types.GenericAlias):
        args = typing.get_args(annotation)
        return bool(args) and args[0] is str
    return origin is list


def _item_summary(item: ProfileItem) -> str:
    """Plain one-line label, used in confirmation prompts."""
    data = item.data
    primary = data.get("title") or data.get("name") or data.get("institution") or "(untitled)"
    secondary = data.get("organization") or data.get("issuer") or data.get("degree") or ""
    return f"{primary} — {secondary}" if secondary else primary


def _entry_row(item: ProfileItem) -> EntryRow:
    """Render one profile entry as a structured row rather than a text line."""
    data = item.data
    kind = item.kind
    if kind == "experience":
        title = data.get("title") or "(untitled role)"
        subtitle = data.get("organization", "")
        meta = " · ".join(part for part in (_date_range(data), data.get("location", "")) if part)
        details = [h for h in (data.get("highlights") or []) if h]
        if not details and data.get("description"):
            details = [data["description"]]
    elif kind == "education":
        degree = " ".join(
            part for part in (data.get("degree", ""), data.get("field_of_study", "")) if part
        )
        title = degree or data.get("institution") or "(untitled)"
        subtitle = data.get("institution", "") if degree else ""
        meta = " · ".join(part for part in (_date_range(data), data.get("details", "")) if part)
        details = []
    elif kind in ("skill", "language"):
        title = data.get("name") or "(unnamed)"
        subtitle = ""
        meta = " · ".join(
            part
            for part in (
                data.get("category", ""),
                data.get("level", "") or data.get("proficiency", ""),
            )
            if part
        )
        details = []
    elif kind == "project":
        title = data.get("name") or "(unnamed project)"
        subtitle = data.get("description", "")
        meta = data.get("url", "")
        details = [h for h in (data.get("highlights") or []) if h]
    elif kind == "certification":
        title = data.get("name") or "(unnamed)"
        subtitle = data.get("issuer", "")
        meta = data.get("date", "")
        details = []
    else:  # award, publication, volunteer
        title = data.get("title") or "(untitled)"
        subtitle = data.get("organization", "")
        meta = data.get("date", "")
        details = [data["description"]] if data.get("description") else []

    return EntryRow(
        title=title,
        subtitle=subtitle,
        meta=meta,
        details=details,
        flagged=item.needs_review,
    )


def _date_range(data: dict) -> str:
    start, end = data.get("start_date", ""), data.get("end_date", "")
    if start:
        return f"{start} – {end or 'present'}"
    return end or ""


def _split_csv(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]
