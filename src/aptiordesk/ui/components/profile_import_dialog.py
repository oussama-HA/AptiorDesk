"""Approve, per line, what a resume import does to the candidate profile.

The service computes a plan; this dialog is where the user sees it and decides.
Nothing is written until Apply, and lines that would overwrite the user's own
edits arrive unticked so that ignoring this dialog is always the safe outcome.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from aptiordesk.database.models.extraction import ExtractionReport, Provenance
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.features.profile.import_service import (
    Action,
    ImportPlan,
    ProfileImporter,
    ProposedChange,
    Strategy,
)
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.theme.tokens import SPACE

_STRATEGIES = [
    (
        Strategy.MERGE,
        "Merge with my profile",
        "Add what is new and update what changed. Entries you edited by hand are "
        "kept unless you tick them.",
    ),
    (
        Strategy.FILL_GAPS,
        "Only fill in what is empty",
        "Never changes anything you already have. The safest option.",
    ),
    (
        Strategy.REPLACE,
        "Replace my profile with this resume",
        "Also removes profile entries that are not in this resume.",
    ),
]

_ACTION_LABEL = {
    Action.ADD: ("Add", "success"),
    Action.UPDATE: ("Update", "accent"),
    Action.CONFLICT: ("You edited this", "warning"),
    Action.SKIP_DUPLICATE: ("Already there", "neutral"),
    Action.REMOVE: ("Remove", "danger"),
}


class ProfileImportDialog(QDialog):
    def __init__(
        self,
        conn: sqlite3.Connection,
        content: ResumeContent,
        report: ExtractionReport | None = None,
        *,
        source_resume_version_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Import resume into your profile")
        self.resize(920, 640)
        self._importer = ProfileImporter(conn)
        self._content = content
        self._report = report
        self._version_id = source_resume_version_id
        self._plan: ImportPlan | None = None
        self.result_summary = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["md"])

        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("How should this be applied?"))
        self.strategy_box = Dropdown()
        for strategy, label, _ in _STRATEGIES:
            self.strategy_box.addItem(label, strategy)
        self.strategy_box.currentIndexChanged.connect(self._rebuild)
        chooser.addWidget(self.strategy_box, 1)
        layout.addLayout(chooser)

        self.strategy_hint = QLabel()
        self.strategy_hint.setProperty("role", "hint")
        self.strategy_hint.setWordWrap(True)
        layout.addWidget(self.strategy_hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Apply", "What", "Change", "Why"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        selectors = QHBoxLayout()
        for text, handler in (
            ("Select all", lambda: self._set_all(True)),
            ("Select none", lambda: self._set_all(False)),
            ("Only new items", self._select_new_only),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            selectors.addWidget(button)
        selectors.addStretch(1)
        self.summary_label = QLabel()
        self.summary_label.setProperty("role", "hint")
        selectors.addWidget(self.summary_label)
        layout.addLayout(selectors)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Apply to my profile")
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._rebuild()

    # -- plan rendering ------------------------------------------------------

    def _rebuild(self) -> None:
        # Qt stores item data as a plain str, not the StrEnum member, so this
        # must be re-coerced — an `is` comparison against Strategy would fail.
        strategy = Strategy(self.strategy_box.currentData())
        self.strategy_hint.setText(next(hint for s, _, hint in _STRATEGIES if s == strategy))
        self._plan = self._importer.build_plan(
            self._content,
            self._report,
            strategy=strategy,
            source_resume_version_id=self._version_id,
        )
        self._populate()

    def _populate(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for change in self._plan.changes:
            self.tree.addTopLevelItem(_row(change))
        self.tree.blockSignals(False)
        for column in range(4):
            self.tree.resizeColumnToContents(column)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        selected = len(self._plan.included()) if self._plan else 0
        total = len(self._plan.changes) if self._plan else 0
        self.summary_label.setText(
            f"{selected} of {total} selected — {self._plan.summary()}"
            if total
            else "Your profile already matches this resume."
        )

    # -- interaction ---------------------------------------------------------

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        change = item.data(0, Qt.ItemDataRole.UserRole)
        if change is not None:
            change.include = item.checkState(0) == Qt.CheckState.Checked
        self._refresh_summary()

    def _set_all(self, selected: bool) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            change = item.data(0, Qt.ItemDataRole.UserRole)
            if change.action is Action.SKIP_DUPLICATE:
                continue  # nothing to apply either way
            item.setCheckState(0, Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def _select_new_only(self) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            change = item.data(0, Qt.ItemDataRole.UserRole)
            item.setCheckState(
                0,
                Qt.CheckState.Checked if change.action is Action.ADD else Qt.CheckState.Unchecked,
            )

    def _apply(self) -> None:
        if self._plan is None:
            return
        removals = [c for c in self._plan.included() if c.action is Action.REMOVE]
        if removals:
            confirm = QMessageBox.question(
                self,
                "Confirm removals",
                f"{len(removals)} existing profile entry/entries will be deleted. "
                "This cannot be undone. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        result = self._importer.apply_plan(self._plan)
        self.result_summary = result.summary()
        QMessageBox.information(self, "Profile updated", self.result_summary)
        self.accept()


# --- row construction ---------------------------------------------------------


def _row(change: ProposedChange) -> QTreeWidgetItem:
    label, _tone = _ACTION_LABEL[change.action]
    describe = change.new_value or change.current_value
    if change.action is Action.UPDATE and change.current_value:
        describe = f"{change.current_value}  →  {change.new_value}"
    elif change.action is Action.CONFLICT:
        describe = f"keep: {change.current_value}   |   resume: {change.new_value}"

    item = QTreeWidgetItem([label, change.label, describe, change.reason])
    item.setData(0, Qt.ItemDataRole.UserRole, change)

    if change.action is Action.SKIP_DUPLICATE:
        # Nothing to decide; showing it explains why the count is what it is.
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        item.setDisabled(True)
    else:
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if change.include else Qt.CheckState.Unchecked)

    if change.provenance is Provenance.INFERRED:
        item.setToolTip(
            2,
            "The AI could not find this text in your document. Check it before "
            "adding it to your profile.",
        )
        item.setText(1, f"⚠ {change.label}")
    return item


__all__ = ["ProfileImportDialog"]
