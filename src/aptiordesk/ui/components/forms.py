"""Layout primitives for building pages that read as designed.

The pages were built from ``QGroupBox`` + ``QFormLayout``, which produces a
single column of full-width inputs with labels of the same weight as their
values. That is legible but shapeless: nothing tells the eye where a section
starts, which fields belong together, or what is a label and what is content.

These give that structure:

* ``SectionCard`` — a titled panel with its heading *inside* it, an optional
  description, and a slot for actions on the right.
* ``FieldGrid`` — labels above inputs, in one or two columns, so short fields
  (email, phone) sit side by side instead of each spanning the page.
* ``EntryRow`` — a real row for a list item: title, subtitle, meta, badges and
  hover actions, replacing a single line of concatenated text.
* ``ChipFlow`` — wrapped pills for skills and keywords.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ui.theme import current
from aptiordesk.ui.theme import icons as icon_set
from aptiordesk.ui.theme.tokens import SPACE


class SectionCard(QFrame):
    """A titled panel. Add content to ``body``; add buttons via ``add_action``."""

    def __init__(
        self,
        title: str,
        description: str = "",
        icon: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("role", "section")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        outer.setSpacing(SPACE["lg"])

        header = QWidget()
        header.setObjectName("sectionHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(SPACE["sm"])

        if icon:
            glyph = QLabel(header)
            glyph.setPixmap(icon_set.pixmap(icon, current().text_muted, 16))
            glyph.setFixedWidth(18)
            header_row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        # These labels need a parent before visibility is changed. Calling
        # setVisible(True) on an unparented QWidget briefly promotes it to a
        # native top-level window, which produced the tiny AptiorDesk windows
        # seen during startup while all feature pages were being constructed.
        self.title_label = QLabel(title, header)
        self.title_label.setProperty("role", "sectionTitle")
        text_column.addWidget(self.title_label)
        self.description_label = QLabel(description, header)
        self.description_label.setProperty("role", "hint")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(bool(description))
        text_column.addWidget(self.description_label)
        header_row.addLayout(text_column, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE["sm"])
        self.actions.setAlignment(Qt.AlignmentFlag.AlignTop)
        header_row.addLayout(self.actions)
        outer.addWidget(header)
        outer.addWidget(divider())

        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE["lg"])
        outer.addLayout(self.body)

    def add_action(self, text: str, on_click: Callable[[], None], accent: bool = False):
        button = QPushButton(text)
        button.setProperty("size", "sm")
        if accent:
            button.setProperty("accent", True)
        button.clicked.connect(on_click)
        self.actions.addWidget(button)
        return button

    def set_description(self, text: str) -> None:
        self.description_label.setText(text)
        self.description_label.setVisible(bool(text))


class FieldGrid(QWidget):
    """Labels above inputs, laid out in `columns` columns.

    Full-width fields (a summary box, a long URL) can span the grid via
    ``add(..., span=True)``.
    """

    def __init__(self, columns: int = 2, parent=None):
        super().__init__(parent)
        self.setProperty("role", "layoutOnly")
        self._columns = max(1, columns)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(SPACE["xl"])
        self._grid.setVerticalSpacing(SPACE["lg"])
        for column in range(self._columns):
            self._grid.setColumnStretch(column, 1)
        self._row = 0
        self._column = 0

    def add(self, label: str, widget: QWidget, hint: str = "", span: bool = False) -> QWidget:
        cell = QWidget()
        cell.setProperty("role", "layoutOnly")
        column_layout = QVBoxLayout(cell)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(SPACE["xs"])

        caption = QLabel(label)
        caption.setProperty("role", "fieldLabel")
        caption.setBuddy(widget)
        if not widget.accessibleName():
            widget.setAccessibleName(label)
        column_layout.addWidget(caption)
        column_layout.addWidget(widget)
        if hint:
            note = QLabel(hint)
            note.setProperty("role", "caption")
            note.setWordWrap(True)
            column_layout.addWidget(note)

        if span or self._columns == 1:
            if self._column != 0:
                self._row += 1
                self._column = 0
            self._grid.addWidget(
                cell,
                self._row,
                0,
                1,
                self._columns,
                Qt.AlignmentFlag.AlignTop,
            )
            self._row += 1
        else:
            self._grid.addWidget(
                cell,
                self._row,
                self._column,
                Qt.AlignmentFlag.AlignTop,
            )
            self._column += 1
            if self._column >= self._columns:
                self._column = 0
                self._row += 1
        return cell


class EntryRow(QFrame):
    """One item in a list: title, subtitle, meta line, badges, hover actions."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        meta: str = "",
        details: list[str] | None = None,
        flagged: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("role", "entryRow")
        self.setProperty("flagged", "true" if flagged else "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["sm"])

        top = QHBoxLayout()
        top.setSpacing(SPACE["sm"])
        title_label = QLabel(title or "(untitled)")
        title_label.setProperty("role", "sectionTitle")
        title_label.setWordWrap(True)
        top.addWidget(title_label, 1)

        if flagged:
            warn = QLabel("Check this")
            warn.setProperty("role", "badge")
            warn.setProperty("tone", "warning")
            warn.setToolTip(
                "This came from your resume but could not be found in its text. "
                "Confirm or correct it."
            )
            top.addWidget(warn, 0, Qt.AlignmentFlag.AlignTop)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE["xs"])
        top.addLayout(self.actions)
        layout.addLayout(top)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setProperty("role", "value")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        if meta:
            meta_label = QLabel(meta)
            meta_label.setProperty("role", "caption")
            layout.addWidget(meta_label)

        for detail in (details or [])[:4]:
            bullet = QLabel(f"•  {detail}")
            bullet.setProperty("role", "hint")
            bullet.setWordWrap(True)
            bullet.setContentsMargins(0, 2, 0, 0)
            layout.addWidget(bullet)
        if details and len(details) > 4:
            more = QLabel(f"+ {len(details) - 4} more")
            more.setProperty("role", "caption")
            layout.addWidget(more)

    def add_action(self, icon: str, tooltip: str, on_click: Callable[[], None]):
        button = QPushButton()
        button.setIcon(icon_set.icon(icon, current().text_muted))
        button.setIconSize(QSize(14, 14))
        button.setProperty("variant", "ghost")
        button.setToolTip(tooltip)
        button.setFixedSize(28, 28)
        button.clicked.connect(on_click)
        self.actions.addWidget(button)
        return button

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.clicked.emit()
        super().mouseDoubleClickEvent(event)


class ChipFlow(QWidget):
    """Pills that wrap onto as many lines as they need."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "layoutOnly")
        self._layout = FlowLayout(self, spacing=SPACE["sm"])

    def set_items(self, items: list[str], tone: str = "") -> None:
        while self._layout.count():
            entry = self._layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for text in items:
            chip = QLabel(text)
            chip.setProperty("role", "chip")
            if tone:
                chip.setProperty("tone", tone)
            self._layout.addWidget(chip)
        self.updateGeometry()


class FlowLayout(QLayout):
    """Left-to-right wrapping layout. Qt has no built-in flow layout."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        from PySide6.QtCore import QRect

        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, apply: bool) -> int:
        from PySide6.QtCore import QPoint, QRect

        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line


__all__ = [
    "ChipFlow",
    "EntryRow",
    "FieldGrid",
    "FlowLayout",
    "SectionCard",
    "divider",
]
