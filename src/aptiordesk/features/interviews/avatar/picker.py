"""Curated AptiorDesk interviewer-avatar picker."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.features.interviews.avatar.assets import avatar_catalog
from aptiordesk.ui.theme.tokens import SPACE


class AvatarPickerDialog(QDialog):
    """Choose from the branded avatars shipped with AptiorDesk."""

    def __init__(self, selected_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Choose your interviewer")
        self.setModal(True)
        self.resize(720, 510)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["2xl"])
        layout.setSpacing(SPACE["lg"])

        title = QLabel("AptiorDesk interviewers")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        detail = QLabel(
            "Choose an AptiorDesk interviewer for your practice session. "
            "Every avatar is optimized for the built-in expressions, listening "
            "behavior, and speech synchronization."
        )
        detail.setProperty("role", "hint")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        self.list = QListWidget()
        self.list.setObjectName("avatarLibrary")
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setIconSize(QSize(260, 174))
        self.list.setGridSize(QSize(292, 244))
        self.list.setSpacing(SPACE["md"])
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for avatar in avatar_catalog():
            item = QListWidgetItem(
                QIcon(str(avatar.thumbnail_path)),
                f"{avatar.name}\n{avatar.description}",
            )
            item.setData(Qt.ItemDataRole.UserRole, avatar.id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setToolTip(f"{avatar.name} — {avatar.description}")
            self.list.addItem(item)
            if avatar.id == selected_id:
                item.setSelected(True)
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        layout.addWidget(self.list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use this interviewer")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("accent", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(buttons)

    @property
    def selected_avatar_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))

    @classmethod
    def choose(cls, selected_id: str, parent: QWidget | None = None) -> str | None:
        dialog = cls(selected_id, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_avatar_id
