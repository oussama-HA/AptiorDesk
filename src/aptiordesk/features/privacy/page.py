"""Privacy & data: what is stored, where it lives, what leaves the machine,
and full control to back up, restore, or destroy it."""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aptiordesk import APP_NAME, CREATOR_COMPANY, CREATOR_NAME
from aptiordesk.ai import keystore
from aptiordesk.core import paths
from aptiordesk.database.models.provider import ProviderKind
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.privacy import service as export_service
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.rich_text import rich_document
from aptiordesk.ui.theme.tokens import SPACE

log = logging.getLogger(__name__)

_CONFIRM_PHRASE = "DELETE"


class PrivacyPage(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Privacy & data",
            "What is stored, what leaves this machine, and how to erase it.",
            eyebrow="DATA CONTROL",
        )
        layout.addWidget(self.header)

        self.info = QTextBrowser()
        layout.addWidget(self.info, 1)

        backup_bar = QFrame()
        backup_bar.setProperty("role", "actionBar")
        buttons = QHBoxLayout(backup_bar)
        buttons.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        buttons.setSpacing(SPACE["sm"])
        backup = QPushButton("Export backup…")
        backup.setProperty("accent", True)
        backup.clicked.connect(self._export)
        restore = QPushButton("Restore from backup…")
        restore.clicked.connect(self._restore)
        buttons.addWidget(backup)
        buttons.addWidget(restore)
        buttons.addStretch(1)
        layout.addWidget(backup_bar)

        danger_bar = QFrame()
        danger_bar.setProperty("role", "actionBar")
        danger = QHBoxLayout(danger_bar)
        danger.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        danger.setSpacing(SPACE["sm"])
        self.delete_models_check = QCheckBox("Also delete downloaded speech models")
        danger.addWidget(self.delete_models_check)
        danger.addStretch(1)
        delete = QPushButton("Delete all local data…")
        delete.setProperty("variant", "danger")
        delete.clicked.connect(self._delete_all)
        danger.addWidget(delete)
        layout.addWidget(danger_bar)

        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.reload()

    def reload(self) -> None:
        self.info.setHtml(rich_document(self._build_html()))

    def _build_html(self) -> str:
        summary = export_service.data_summary(self._conn)
        providers = ProviderRepository(self._conn).list()
        active = next((p for p in providers if p.is_active), None)

        rows = "".join(
            f"<tr><td style='padding-right:18px'>{name.replace('_', ' ')}</td><td>{count}</td></tr>"
            for name, count in sorted(summary.items())
        )
        stored = f"<table>{rows}</table>" if rows else "<p><i>Nothing stored yet.</i></p>"

        if active is None:
            destination = (
                "<p><b>No AI provider is configured</b>, so nothing is being sent "
                "anywhere at all.</p>"
            )
        elif active.kind == ProviderKind.CLI:
            destination = (
                f"<p>Your active AI provider is <b>{_esc(active.name)}</b>, invoked "
                "through an executable on this device. AptiorDesk runs it in an "
                "isolated temporary folder, but the CLI may send the relevant text to "
                "the AI service configured in that CLI. That service's account and "
                "privacy settings apply.</p>"
            )
        elif active.is_local:
            destination = (
                f"<p>Your active AI provider is <b>{_esc(active.name)}</b> at "
                f"<code>{_esc(active.effective_base_url())}</code>, which is on this "
                "machine. <b>Nothing leaves your computer.</b></p>"
            )
        else:
            destination = (
                f"<p>Your active AI provider is <b>{_esc(active.name)}</b> at "
                f"<code>{_esc(active.effective_base_url())}</code>. When you run an "
                "AI action, the relevant text (your resume, the job description, "
                "your interview answers) is sent <b>to that provider only</b>, and "
                "only at the moment you press the button. AptiorDesk sends nothing on "
                "its own.</p>"
            )

        keyring_note = (
            "API keys are stored in your operating system's credential manager, "
            "never in files, the database, logs, or backups."
            if keystore.available()
            else "<b>No secure credential store was found</b>, so cloud API keys "
            "cannot be saved on this system."
        )

        return f"""
        <h2>Where your data lives</h2>
        <p>Everything is on this computer, in:<br>
        <code>{_esc(str(paths.data_dir()))}</code></p>
        {stored}

        <h2>What leaves this computer</h2>
        {destination}
        <p>There is no telemetry, no analytics, and no account. Network requests
        happen only after your action: an AI task goes to your configured provider,
        and optional local models download only after confirmation. Browser job
        capture sends extracted posting information only to AptiorDesk on this
        computer at <code>127.0.0.1</code>.</p>

        <h2>Voice recordings</h2>
        <p>Spoken answers are transcribed by a model running on this machine.
        The audio is written to a temporary file, transcribed, and never uploaded.</p>

        <h2>API keys</h2>
        <p>{keyring_note}</p>

        <h2>Your control</h2>
        <p>Export everything to a readable zip, restore it on another machine, or
        delete all of it permanently using the buttons below.</p>

        <h2>Credits</h2>
        <p><b>{APP_NAME}</b> was created by <b>{CREATOR_NAME}</b> at
        <b>{CREATOR_COMPANY}</b>, with contributions from the open-source
        community.</p>
        """

    # -- actions -------------------------------------------------------------

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export backup", "aptiordesk-backup.zip", "Zip archive (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            export_service.export_backup(self._conn, path)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", getattr(exc, "user_message", str(exc)))
            return
        self.status.setText(
            f"Backup written to {path}. It contains your data but not your API keys."
        )

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore from backup", "", "Zip archive (*.zip)"
        )
        if not path:
            return
        try:
            manifest = export_service.read_manifest(path)
        except Exception as exc:
            QMessageBox.warning(self, "Not a backup", getattr(exc, "user_message", str(exc)))
            return
        total = sum(manifest.get("tables", {}).values())
        confirm = QMessageBox.warning(
            self,
            "Replace all data?",
            f"This backup contains {total} record(s).\n\n"
            "Restoring REPLACES everything currently in AptiorDesk on this computer. "
            "Consider exporting a backup of your current data first.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = export_service.restore_backup(self._conn, path)
        except Exception as exc:
            QMessageBox.warning(self, "Restore failed", getattr(exc, "user_message", str(exc)))
            return
        self.reload()
        QMessageBox.information(
            self,
            "Restored",
            f"Restored {sum(restored.values())} record(s).\n\n"
            "Re-enter your API keys in Settings — backups never contain them.\n\n"
            "Restart AptiorDesk so every page reloads from the restored data.",
        )

    def _delete_all(self) -> None:
        summary = export_service.data_summary(self._conn)
        total = sum(summary.values())
        text, ok = QInputDialog.getText(
            self,
            "Delete all local data",
            f"This permanently deletes {total} record(s) — your profile, resumes, "
            "jobs, analyses, tailored resumes, cover letters, interview answers, "
            "profile data, and stored API keys. "
            "It cannot be undone.\n\n"
            f"Type {_CONFIRM_PHRASE} to confirm:",
        )
        if not ok or text.strip() != _CONFIRM_PHRASE:
            self.status.setText("Deletion cancelled — nothing was removed.")
            return
        try:
            removed = export_service.delete_all_data(
                self._conn, delete_models=self.delete_models_check.isChecked()
            )
        except Exception as exc:
            QMessageBox.warning(self, "Deletion failed", getattr(exc, "user_message", str(exc)))
            return
        self.reload()
        QMessageBox.information(
            self,
            "Data deleted",
            "Deleted:\n"
            + "\n".join(f"• {item}" for item in removed)
            + "\n\nRestart AptiorDesk so every page reloads.",
        )


def _esc(text: str) -> str:
    import html

    return html.escape(text)
