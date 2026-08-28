"""Generic form widgets generated from pydantic models.

``ModelDialog`` edits one instance (str fields → line edits, description-like
fields → multiline, ``list[str]`` → one-per-line). ``ModelListEditor`` manages
a list of instances in memory with add/edit/remove — used by the resume
editor for experiences, education, skills, etc.
"""

from __future__ import annotations

import types
import typing

from pydantic import BaseModel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MULTILINE_FIELDS = {"description", "details", "notes", "summary"}


def is_str_list(annotation) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (list, types.GenericAlias) or origin is list:
        args = typing.get_args(annotation)
        return bool(args) and args[0] is str
    return False


class ModelDialog(QDialog):
    def __init__(self, model_cls: type[BaseModel], data: dict | None, title: str, parent=None):
        super().__init__(parent)
        self._model_cls = model_cls
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self._editors: dict[str, QLineEdit | QPlainTextEdit] = {}

        instance = model_cls.model_validate(data or {})
        for name, field_info in model_cls.model_fields.items():
            value = getattr(instance, name)
            label = name.replace("_", " ").capitalize()
            if is_str_list(field_info.annotation):
                editor = QPlainTextEdit()
                editor.setPlaceholderText("One per line")
                editor.setMaximumHeight(90)
                editor.setPlainText("\n".join(value))
            elif name in _MULTILINE_FIELDS:
                editor = QPlainTextEdit()
                editor.setMaximumHeight(80)
                editor.setPlainText(str(value))
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
            annotation = self._model_cls.model_fields[name].annotation
            if is_str_list(annotation):
                out[name] = [
                    line.strip() for line in editor.toPlainText().splitlines() if line.strip()
                ]
            elif isinstance(editor, QPlainTextEdit):
                out[name] = editor.toPlainText().strip()
            else:
                out[name] = editor.text().strip()
        return out


def summarize(data: dict) -> str:
    primary = data.get("title") or data.get("name") or data.get("institution") or "(untitled)"
    secondary = data.get("organization") or data.get("issuer") or data.get("degree") or ""
    return f"{primary} — {secondary}" if secondary else str(primary)


class ModelListEditor(QWidget):
    """List of model instances (held as dicts) with add/edit/remove."""

    def __init__(self, model_cls: type[BaseModel], noun: str, parent=None):
        super().__init__(parent)
        self._model_cls = model_cls
        self._noun = noun
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _: self._edit())
        layout.addWidget(self.list_widget)
        buttons = QHBoxLayout()
        for text, handler in (("Add", self._add), ("Edit", self._edit), ("Remove", self._remove)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_items(self, items: list[dict]) -> None:
        self.list_widget.clear()
        for data in items:
            entry = QListWidgetItem(summarize(data))
            entry.setData(Qt.ItemDataRole.UserRole, dict(data))
            self.list_widget.addItem(entry)

    def items(self) -> list[dict]:
        return [
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
        ]

    def _add(self) -> None:
        dialog = ModelDialog(self._model_cls, None, f"Add {self._noun}", self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = QListWidgetItem(summarize(dialog.values()))
            entry.setData(Qt.ItemDataRole.UserRole, dialog.values())
            self.list_widget.addItem(entry)

    def _edit(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            return
        dialog = ModelDialog(
            self._model_cls, current.data(Qt.ItemDataRole.UserRole), f"Edit {self._noun}", self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            current.setData(Qt.ItemDataRole.UserRole, dialog.values())
            current.setText(summarize(dialog.values()))

    def _remove(self) -> None:
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)
