"""A concise command center for AptiorDesk's active workflows."""

from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.database.models.provider import ProviderKind
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.dashboard.service import DashboardService
from aptiordesk.ui.components.common import Card, PageHeader, StatTile
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE


class DashboardPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._service = DashboardService(conn)
        self._next_destination = "Profile"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["2xl"], SPACE["xl"], SPACE["2xl"], SPACE["lg"])
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            PageHeader(
                "Workspace overview",
                "Your active materials, captured opportunities, and next useful step.",
                eyebrow="TODAY",
            )
        )

        self.next_card = Card("Recommended next step")
        self.next_card.setProperty("role", "focus")
        self.next_title = QLabel()
        self.next_title.setProperty("role", "focusTitle")
        self.next_title.setWordWrap(True)
        self.next_card.body.addWidget(self.next_title)
        self.next_detail = QLabel()
        self.next_detail.setProperty("role", "hint")
        self.next_detail.setWordWrap(True)
        self.next_card.body.addWidget(self.next_detail)
        self.next_button = QPushButton("Open")
        self.next_button.setProperty("accent", True)
        self.next_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.next_button.clicked.connect(
            lambda: self.navigate_requested.emit(self._next_destination)
        )
        self.next_card.body.addWidget(self.next_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.next_card)

        metrics_title = QLabel("Workspace activity")
        metrics_title.setProperty("role", "sectionTitle")
        layout.addWidget(metrics_title)
        grid = QGridLayout()
        grid.setSpacing(SPACE["md"])
        self.tiles = {
            "profile_items": StatTile("Profile evidence", icon_name="user"),
            "resumes": StatTile("Resumes", icon_name="file"),
            "jobs": StatTile("Captured jobs", icon_name="briefcase"),
            "analyzed_jobs": StatTile("Analyzed jobs", icon_name="spark"),
            "tailoring_sessions": StatTile("Tailoring sessions", icon_name="wand"),
            "interview_sessions": StatTile("Practice sessions", icon_name="mic"),
        }
        for index, tile in enumerate(self.tiles.values()):
            grid.addWidget(tile, index // 3, index % 3)
        layout.addLayout(grid)

        self.activity_card = Card(
            "Application materials",
            "Saved work stays linked to the job and resume evidence it came from.",
        )
        self.activity = QLabel()
        self.activity.setWordWrap(True)
        self.activity_card.body.addWidget(self.activity)
        self.privacy_card = Card("AI boundary")
        self.privacy = QLabel()
        self.privacy.setWordWrap(True)
        self.privacy_card.body.addWidget(self.privacy)
        details = QGridLayout()
        details.setSpacing(SPACE["md"])
        details.addWidget(self.activity_card, 0, 0)
        details.addWidget(self.privacy_card, 0, 1)
        details.setColumnStretch(0, 1)
        details.setColumnStretch(1, 1)
        layout.addLayout(details)
        layout.addStretch(1)
        self.reload()

    def reload(self) -> None:
        snapshot = self._service.snapshot()
        for key, tile in self.tiles.items():
            tile.set_value(getattr(snapshot, key))
        self._next_destination = snapshot.next_destination
        self.next_title.setText(snapshot.next_title)
        self.next_detail.setText(snapshot.next_detail)
        self.next_button.setText(f"Open {snapshot.next_destination}")
        self.activity.setText(
            f"<b>{snapshot.cover_letters}</b> cover letter(s) saved. "
            f"<b>{snapshot.tailoring_sessions}</b> resume tailoring session(s) created."
        )
        self._rebuild_privacy()

    def _rebuild_privacy(self) -> None:
        palette = current()
        provider = ProviderRepository(self._conn).get_active()
        if provider is None:
            body = "No AI provider is configured. No resume or job text is being sent anywhere."
        elif provider.kind == ProviderKind.CLI:
            body = (
                f"<b>{html.escape(provider.name or 'Device AI CLI')}</b> runs through "
                "an installed command-line tool. Its configured service privacy policy applies."
            )
        elif provider.is_local:
            body = (
                f"<b>{html.escape(provider.name or 'Local AI')}</b> runs on this device. "
                "AI actions run only when you request them."
            )
        else:
            body = (
                f"<b>{html.escape(provider.name or 'Cloud AI')}</b> is active. "
                "Only relevant context is sent when you explicitly run an AI action."
            )
        self.privacy.setText(f"<span style='color:{palette.text_muted}'>{body}</span>")


__all__ = ["DashboardPage"]
