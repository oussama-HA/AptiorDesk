"""Reusable presentation widgets: cards, stat tiles, badges, empty states,
and page headers. Used across pages so spacing and tone stay consistent."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ui.theme import current
from aptiordesk.ui.theme import icons as icon_set
from aptiordesk.ui.theme.tokens import SPACE


def elevate(widget: QWidget, blur: int = 24, alpha: int = 55) -> None:
    """Qt Style Sheets have no box-shadow; this is the supported equivalent."""
    from PySide6.QtGui import QColor

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(2)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


class Card(QFrame):
    """A padded surface. Use `body` as the parent for content."""

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["xl"])
        outer.setSpacing(SPACE["md"])
        self.title_label = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setProperty("role", "sectionTitle")
            self.title_label.setWordWrap(True)
            outer.addWidget(self.title_label)
        if subtitle:
            caption = QLabel(subtitle)
            caption.setProperty("role", "hint")
            caption.setWordWrap(True)
            outer.addWidget(caption)
        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE["md"])
        outer.addLayout(self.body)

    def set_title(self, text: str) -> None:
        """Cards whose heading reflects live state (e.g. a status check)."""
        if self.title_label is not None:
            self.title_label.setText(text)


class StatTile(QFrame):
    """A single number with a label and icon — used on the dashboard."""

    def __init__(self, label: str, value: str = "0", icon_name: str = "spark", parent=None):
        super().__init__(parent)
        self.setProperty("role", "tile")
        self.setMinimumWidth(118)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["sm"])

        top = QHBoxLayout()
        top.setSpacing(SPACE["sm"])
        self.icon_label = QLabel()
        self.icon_label.setPixmap(icon_set.pixmap(icon_name, current().text_faint, 16))
        top.addWidget(self.icon_label)
        self.label = QLabel(label)
        self.label.setProperty("role", "tileLabel")
        top.addWidget(self.label, 1)
        layout.addLayout(top)

        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "tileValue")
        layout.addWidget(self.value_label)

    def set_value(self, value: str | int) -> None:
        self.value_label.setText(str(value))


def badge(text: str, tone: str = "neutral") -> QLabel:
    """A small status pill. tone: neutral | accent | success | warning | danger."""
    label = QLabel(text)
    label.setProperty("role", "badge")
    label.setProperty("tone", tone)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    return label


class EmptyState(QFrame):
    """Shown instead of a blank list: says what is missing and what to do."""

    def __init__(
        self,
        message: str,
        detail: str = "",
        icon_name: str = "inbox",
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("role", "emptyState")
        self.setMinimumHeight(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["2xl"])
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACE["sm"])

        glyph = QLabel()
        glyph.setPixmap(icon_set.pixmap(icon_name, current().text_faint, 40))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(glyph)

        headline = QLabel(message)
        headline.setProperty("role", "sectionTitle")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setWordWrap(True)
        self.headline_label = headline
        layout.addWidget(headline)

        self.detail_label: QLabel | None = None
        if detail:
            caption = QLabel(detail)
            caption.setProperty("role", "hint")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)
            caption.setMaximumWidth(420)
            self.detail_label = caption
            layout.addWidget(caption, alignment=Qt.AlignmentFlag.AlignCenter)

        if action_text and on_action is not None:
            button = QPushButton(action_text)
            button.setProperty("accent", True)
            button.clicked.connect(on_action)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_message(self, message: str, detail: str = "") -> None:
        self.headline_label.setText(message)
        if self.detail_label is not None:
            self.detail_label.setText(detail)


class PageHeader(QWidget):
    """Title, optional subtitle, and a right-aligned action slot."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        eyebrow: str = "WORKSPACE",
        parent=None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])

        text_column = QVBoxLayout()
        text_column.setSpacing(SPACE["xs"])
        if eyebrow:
            context = QLabel(eyebrow)
            context.setProperty("role", "eyebrow")
            text_column.addWidget(context)
        heading = QLabel(title)
        heading.setProperty("role", "pageTitle")
        self.title_label = heading
        text_column.addWidget(heading)
        if subtitle:
            caption = QLabel(subtitle)
            caption.setProperty("role", "hint")
            caption.setWordWrap(True)
            text_column.addWidget(caption)
        layout.addLayout(text_column, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE["sm"])
        self.actions.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addLayout(self.actions)

    def add_action(self, button: QPushButton) -> None:
        self.actions.addWidget(button)
