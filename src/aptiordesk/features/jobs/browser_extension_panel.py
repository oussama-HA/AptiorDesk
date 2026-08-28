"""Browser-extension setup for the extension-only job import workflow."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.integrations.browser_extension.config import (
    BRIDGE_HOST,
    BRIDGE_PORT,
    CHROME_WEB_STORE_URL,
    EXTENSION_ID,
)
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.forms import SectionCard
from aptiordesk.ui.theme.tokens import SPACE


class BrowserExtensionPanel(QWidget):
    """Explain the separately distributed companion job-capture extension."""

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        del conn  # Kept in the signature for the SettingsPage construction contract.

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, SPACE["lg"], 0, 0)
        outer.setSpacing(SPACE["lg"])
        outer.addWidget(
            PageHeader(
                "Browser extension",
                "Capture a job from any website while you browse. No in-app search, "
                "API keys, manual pairing, or developer-mode installation.",
                eyebrow="JOB CAPTURE",
            )
        )

        status = QFrame()
        status.setProperty("role", "pane")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        status_layout.setSpacing(SPACE["sm"])
        heading = QLabel("Automatic connection")
        heading.setProperty("role", "paneTitle")
        status_layout.addWidget(heading)
        detail = QLabel(
            "The extension pairs automatically with AptiorDesk at "
            f"{BRIDGE_HOST}:{BRIDGE_PORT}. Its temporary session key exists only while "
            "AptiorDesk is running—there is nothing to copy or configure."
        )
        detail.setWordWrap(True)
        detail.setProperty("role", "hint")
        status_layout.addWidget(detail)
        outer.addWidget(status)

        workflow_card = SectionCard(
            "Capture workflow",
            "Four steps from a job page to a saved opportunity.",
            icon="briefcase",
        )
        workflow = QLabel(
            "<b>1.</b> Install the official AptiorDesk companion from the Chrome "
            "Web Store when it is available.<br><br>"
            "<b>2.</b> Open the AptiorDesk browser side panel.<br><br>"
            "<b>3.</b> Choose <b>Capture this job</b>, review its confidence and fields, "
            "then choose <b>Import reviewed job</b>.<br><br>"
            "<b>4.</b> The opportunity appears immediately in AptiorDesk → Jobs."
        )
        workflow.setWordWrap(True)
        workflow_card.body.addWidget(workflow)

        privacy = QLabel(
            "AptiorDesk reads only the active page, and only when you press Capture. "
            "It compares "
            "structured data with visible semantic regions and shows uncertain captures "
            "for review, then sends approved job information only to the AptiorDesk app "
            "on this computer. It does not crawl, search, or apply."
        )
        privacy.setWordWrap(True)
        privacy.setProperty("role", "hint")
        workflow_card.body.addWidget(privacy)
        distribution = QLabel(
            "The companion extension is a separately distributed proprietary "
            "product. Its source code and unpacked build are intentionally not "
            "included with the open-source AptiorDesk desktop repository. "
            f"Official extension ID: {EXTENSION_ID}."
        )
        distribution.setWordWrap(True)
        distribution.setProperty("role", "caption")
        workflow_card.body.addWidget(distribution)
        outer.addWidget(workflow_card)

        row = QHBoxLayout()
        open_store = QPushButton("Open Chrome Web Store")
        open_store.setProperty("accent", True)
        open_store.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CHROME_WEB_STORE_URL)))
        row.addWidget(open_store)

        browser_settings = QPushButton("Open browser extensions")
        browser_settings.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("chrome://extensions"))
        )
        row.addWidget(browser_settings)
        row.addStretch(1)
        actions = QFrame()
        actions.setProperty("role", "actionBar")
        actions.setLayout(row)
        row.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        row.setSpacing(SPACE["sm"])
        outer.addWidget(actions)
        outer.addStretch(1)


# Compatibility name for third-party imports; the old multi-source settings
# panel no longer exists.
JobSourcesPanel = BrowserExtensionPanel

__all__ = ["BrowserExtensionPanel", "JobSourcesPanel"]
