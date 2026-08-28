"""Structured resume editor.

``ResumeEditorWidget`` is the form itself, so it can be embedded (in the import
review screen, which surrounds it with the source text and provenance) as well
as shown standalone. ``ResumeEditorDialog`` is the standalone wrapper, used for
manual resume creation and for editing a version — which always saves as a NEW
version, never in place.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.database.models.profile import (
    Certification,
    Education,
    Language,
    Project,
    SimpleEntry,
    Skill,
    WorkExperience,
)
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.ui.components.forms import FieldGrid, SectionCard
from aptiordesk.ui.components.model_forms import ModelListEditor
from aptiordesk.ui.theme.tokens import SPACE

_SECTIONS = [
    ("experiences", WorkExperience, "experience", "Experience"),
    ("education", Education, "education", "Education"),
    ("skills", Skill, "skill", "Skills"),
    ("projects", Project, "project", "Projects"),
    ("certifications", Certification, "certification", "Certifications"),
    ("languages", Language, "language", "Languages"),
    ("awards", SimpleEntry, "award", "Awards"),
    ("publications", SimpleEntry, "publication", "Publications"),
    ("volunteer", SimpleEntry, "entry", "Volunteering"),
    ("other", SimpleEntry, "entry", "Other"),
]

_BASICS = [
    ("full_name", "Full name"),
    ("professional_title", "Professional title"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("location", "Location"),
    ("linkedin_url", "LinkedIn"),
    ("github_url", "GitHub"),
    ("portfolio_url", "Portfolio"),
]


class ResumeEditorWidget(QWidget):
    """Editable form over a ``ResumeContent``."""

    def __init__(self, content: ResumeContent, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])

        basics = SectionCard(
            "Basics", "Correct anything the AI misread before saving.", icon="user"
        )
        grid = FieldGrid(columns=2)
        self._fields: dict[str, QLineEdit] = {}
        for name, label in _BASICS:
            edit = QLineEdit(getattr(content, name, "") or "")
            grid.add(label, edit)
            self._fields[name] = edit
        self.summary = QPlainTextEdit()
        self.summary.setPlainText(content.summary)
        self.summary.setFixedHeight(96)
        grid.add("Summary", self.summary, span=True)
        basics.body.addWidget(grid)
        layout.addWidget(basics)

        tabs = QTabWidget()
        self._editors: dict[str, ModelListEditor] = {}
        for field_name, model_cls, noun, label in _SECTIONS:
            editor = ModelListEditor(model_cls, noun)
            entries = getattr(content, field_name, None) or []
            editor.set_items([item.model_dump() for item in entries])
            tabs.addTab(editor, f"{label} ({len(entries)})" if entries else label)
            self._editors[field_name] = editor
        layout.addWidget(tabs, 1)

    def content(self) -> ResumeContent:
        data: dict[str, object] = {name: edit.text() for name, edit in self._fields.items()}
        data["summary"] = self.summary.toPlainText()
        for field_name, editor in self._editors.items():
            data[field_name] = editor.items()
        return ResumeContent.model_validate(data)


class ResumeEditorDialog(QDialog):
    def __init__(self, content: ResumeContent, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 700)
        outer = QVBoxLayout(self)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "hint")
            hint_label.setWordWrap(True)
            outer.addWidget(hint_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._editor = ResumeEditorWidget(content)
        scroll.setWidget(self._editor)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def content(self) -> ResumeContent:
        return self._editor.content()
