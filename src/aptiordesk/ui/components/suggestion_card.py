"""One tailoring suggestion, shown with its full justification.

Every card answers: what changed, why, which part of the posting motivated it,
and which candidate information supports it. Warnings (missing evidence,
numbers absent from the resume) are shown prominently — the user decides.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from aptiordesk.database.models.tailoring import Suggestion
from aptiordesk.ui.components.common import badge
from aptiordesk.ui.theme import current

_STATUS_STYLE = {
    "pending": ("Pending review", "neutral"),
    "accepted": ("Accepted", "success"),
    "rejected": ("Rejected", "danger"),
    "edited": ("Accepted with your edit", "success"),
}


class SuggestionCard(QFrame):
    accepted = Signal(object)
    rejected = Signal(object)
    edited = Signal(object, str)

    def __init__(self, suggestion: Suggestion, parent=None):
        super().__init__(parent)
        self.suggestion = suggestion
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        palette = current()

        location_text = _readable_path(suggestion.target_path)
        if suggestion.operation == "add_skill":
            location_text = "Add skill"
            if suggestion.skill_category:
                location_text += f" · {suggestion.skill_category}"
        location = QLabel(f"<b>{html.escape(location_text)}</b>")
        layout.addWidget(location)

        before = QLabel(
            f"<span style='color:{palette.text_muted}'>Evidence-backed addition</span>"
            if suggestion.operation == "add_skill"
            else f"<span style='color:{palette.danger}'>− "
            f"{html.escape(suggestion.original_text)}</span>"
        )
        before.setWordWrap(True)
        after = QLabel(
            f"<span style='color:{palette.success}'>+ "
            f"{html.escape(suggestion.suggested_text)}</span>"
        )
        after.setWordWrap(True)
        layout.addWidget(before)
        layout.addWidget(after)

        for label, value in (
            ("Why", suggestion.rationale),
            ("From the posting", suggestion.jd_evidence),
            ("Supported by", suggestion.profile_evidence),
        ):
            if value:
                row = QLabel(f"<i>{label}:</i> {html.escape(value)}")
                row.setWordWrap(True)
                row.setProperty("role", "hint")
                layout.addWidget(row)

        if suggestion.warnings:
            warning = QLabel(f"⚠ {html.escape(suggestion.warnings)}")
            warning.setWordWrap(True)
            warning.setProperty("role", "error")
            layout.addWidget(warning)

        self.edit_box = QPlainTextEdit(suggestion.final_text())
        self.edit_box.setMaximumHeight(70)
        self.edit_box.setVisible(False)
        layout.addWidget(self.edit_box)

        buttons = QHBoxLayout()
        self.status_label = badge("", "neutral")
        buttons.addWidget(self.status_label)
        buttons.addStretch(1)
        accept_button = QPushButton("Accept")
        accept_button.setProperty("accent", True)
        accept_button.clicked.connect(lambda: self.accepted.emit(self.suggestion))
        reject_button = QPushButton("Reject")
        reject_button.clicked.connect(lambda: self.rejected.emit(self.suggestion))
        self.edit_button = QPushButton("Edit…")
        self.edit_button.clicked.connect(self._toggle_edit)
        for b in (accept_button, reject_button, self.edit_button):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self.refresh()

    def _toggle_edit(self) -> None:
        if self.edit_box.isVisible():
            self.edited.emit(self.suggestion, self.edit_box.toPlainText().strip())
            self.edit_box.setVisible(False)
            self.edit_button.setText("Edit…")
        else:
            self.edit_box.setVisible(True)
            self.edit_button.setText("Save edit")
            self.edit_box.setFocus()

    def refresh(self) -> None:
        text, tone = _STATUS_STYLE.get(self.suggestion.status, ("", "neutral"))
        self.status_label.setText(text)
        self.status_label.setProperty("tone", tone)
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)


def _readable_path(pointer: str) -> str:
    """ "/experiences/0/highlights/1" → "Experiences → entry 1 → highlight 2"."""
    tokens = [t for t in pointer.split("/") if t]
    parts: list[str] = []
    for token in tokens:
        if token.isdigit():
            parts.append(f"#{int(token) + 1}")
        else:
            parts.append(token.replace("_", " ").capitalize())
    return " → ".join(parts) or pointer
