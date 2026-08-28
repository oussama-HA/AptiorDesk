"""One predictable, accessible dropdown implementation for AptiorDesk."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QListView,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
)

from aptiordesk.ui.theme.tokens import CONTROL_HEIGHT, SPACE


class Dropdown(QComboBox):
    """A QComboBox with consistent popup geometry and interaction behavior.

    Qt's native combo already provides the correct accessible role, keyboard
    navigation, Escape/outside-click dismissal, focus restoration, and a
    top-level popup that is not clipped by dialogs or panels. This class keeps
    those semantics and standardizes the parts Qt otherwise leaves to each
    screen: sizing, scrolling, elision, tooltips, and editable completion.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        popup = QListView(self)
        popup.setObjectName("dropdownMenu")
        popup.setUniformItemSizes(True)
        popup.setTextElideMode(Qt.TextElideMode.ElideRight)
        popup.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setMouseTracking(True)
        self.setView(popup)
        self.setMinimumHeight(CONTROL_HEIGHT)
        self.setMaxVisibleItems(10)
        self.setMinimumContentsLength(14)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setAccessibleDescription(
            "Choose an option. Use arrow keys to move, Enter to select, and Escape to close."
        )
        self.model().rowsInserted.connect(lambda *_: self._refresh_item_tooltips())
        self.model().modelReset.connect(self._refresh_item_tooltips)

    def setEditable(self, editable: bool) -> None:  # noqa: N802 - Qt API name
        super().setEditable(editable)
        if not editable:
            return
        editor = self.lineEdit()
        if editor is not None:
            editor.setClearButtonEnabled(True)
        completer = self.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.popup().setTextElideMode(Qt.TextElideMode.ElideRight)

    def showPopup(self) -> None:  # noqa: N802 - Qt API name
        """Make the popup readable without letting it escape the screen."""
        view = self.view()
        scrollbar_width = self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent, None, self
        )
        desired = max(
            self.width(),
            view.sizeHintForColumn(0) + scrollbar_width + SPACE["xl"],
        )
        screen = self.screen().availableGeometry()
        popup_width = min(desired, max(self.width(), screen.width() - SPACE["2xl"]))
        view.setMinimumWidth(popup_width)
        view.setMaximumWidth(popup_width)
        self.setMaxVisibleItems(min(10, max(1, self.count())))
        super().showPopup()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        """Elide long closed-state labels without changing their real value."""
        if self.isEditable():
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        label_width = max(0, self.width() - SPACE["3xl"] - SPACE["md"])
        option.currentText = self.fontMetrics().elidedText(
            option.currentText,
            Qt.TextElideMode.ElideRight,
            label_width,
        )
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and self.currentText():
            self.setToolTip(self.currentText())
        return super().event(event)

    def _refresh_item_tooltips(self) -> None:
        for row in range(self.count()):
            text = self.itemText(row)
            if text:
                self.setItemData(row, text, Qt.ItemDataRole.ToolTipRole)


__all__ = ["Dropdown"]
