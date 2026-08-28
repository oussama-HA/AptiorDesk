"""Profile completeness, shown as fact rather than judgement.

Answers "is my profile ready to use?" at a glance: a percentage bar, and one
chip per section stating exactly what is there ("Experience · 3") or what is
absent ("No certifications"). Counts only — no scoring of quality, because
the app has no basis for judging whether three roles are *good* roles, and
pretending otherwise is the kind of vague meter that makes users doubt the
whole screen. The one call to action is the empty state: importing a resume.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
)

from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.ui.components.common import Card, badge
from aptiordesk.ui.theme.tokens import SPACE

#: (field-or-kind, label, weight). Weights sum to 100. Contact and experience
#: dominate because everything downstream (tailoring, letters, interviews)
#: draws on them first.
_PARTS = (
    ("name", "Name", 10),
    ("contact", "Contact", 15),
    ("summary", "Summary", 10),
    ("experience", "Experience", 30),
    ("education", "Education", 10),
    ("skill", "Skills", 15),
    ("extras", "Extras", 10),
)

_EXTRA_KINDS = ("project", "certification", "language", "award", "publication", "volunteer")


class ProfileStrengthCard(Card):
    """Lives at the top of the Profile page; refresh() after any change."""

    def __init__(self, conn: sqlite3.Connection, on_import=None, parent=None):
        super().__init__("Profile", parent=parent)
        self._conn = conn

        top = QHBoxLayout()
        top.setSpacing(SPACE["md"])
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top.addWidget(self.bar, 1)
        self.percent_label = QLabel("")
        self.percent_label.setProperty("role", "sectionTitle")
        top.addWidget(self.percent_label)
        self.body.addLayout(top)

        self.chips = QHBoxLayout()
        self.chips.setSpacing(SPACE["sm"])
        self.body.addLayout(self.chips)

        self.hint = QLabel("")
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)

        self.import_button = QPushButton("Build my profile from a resume…")
        self.import_button.setProperty("accent", True)
        if on_import is not None:
            self.import_button.clicked.connect(on_import)
        self.import_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.body.addWidget(self.import_button)

        self.refresh()

    def refresh(self) -> None:
        repo = ProfileRepository(self._conn)
        profile = repo.get_default()
        items = repo.list_items(profile.id)
        by_kind: dict[str, int] = {}
        for item in items:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1

        percent = 0
        _clear(self.chips)
        for key, label, weight in _PARTS:
            filled, chip_text = _evaluate(key, label, profile, by_kind)
            if filled:
                percent += weight
            self.chips.addWidget(badge(chip_text, "success" if filled else "neutral"))
        self.chips.addStretch(1)

        needs_review = sum(1 for item in items if item.needs_review)
        if needs_review:
            self.chips.insertWidget(
                self.chips.count() - 1,
                badge(f"{needs_review} to confirm", "warning"),
            )

        self.bar.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        self.set_title(_title_for(percent, profile.display_name))
        self.hint.setText(_hint_for(percent, needs_review))
        self.import_button.setVisible(percent < 50)


def _evaluate(key: str, label: str, profile, by_kind: dict[str, int]) -> tuple[bool, str]:
    if key == "name":
        filled = bool(profile.display_name.strip())
        return filled, label if filled else "No name"
    if key == "summary":
        filled = bool(profile.summary.strip())
        return filled, label if filled else "No summary"
    if key == "contact":
        contact = profile.contact
        have = sum(1 for v in (contact.email, contact.phone, contact.location) if v.strip())
        return have >= 2, f"{label} · {have}/3"
    if key == "extras":
        count = sum(by_kind.get(kind, 0) for kind in _EXTRA_KINDS)
        return count > 0, (f"{label} · {count}" if count else "No extras")
    count = by_kind.get(key, 0)
    return count > 0, (f"{label} · {count}" if count else f"No {label.lower()}")


def _title_for(percent: int, name: str) -> str:
    if percent == 0:
        return "Your profile is empty"
    who = name.strip() or "Your profile"
    if percent < 50:
        return f"{who} — just getting started"
    if percent < 85:
        return f"{who} — nearly there"
    return f"{who} — ready to use"


def _hint_for(percent: int, needs_review: int) -> str:
    if percent == 0:
        return (
            "The fastest way to fill this in is importing your resume — the AI "
            "reads it, you approve every field, nothing is saved without you."
        )
    if needs_review:
        return (
            f"{needs_review} entr{'y' if needs_review == 1 else 'ies'} came from "
            "your resume but could not be verified against its text — they are "
            "marked in the lists below. Confirm or correct them."
        )
    if percent < 85:
        return "Everything here feeds tailoring, cover letters, and interview prep."
    return "This profile is what tailoring, letters, and interview prep draw from."


def _clear(layout: QHBoxLayout) -> None:
    while layout.count():
        entry = layout.takeAt(0)
        widget = entry.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


__all__ = ["ProfileStrengthCard"]
