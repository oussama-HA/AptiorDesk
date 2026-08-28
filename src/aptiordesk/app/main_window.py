"""Main window: branded sidebar navigation + stacked pages."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aptiordesk import APP_NAME, CREATOR_COMPANY, CREATOR_NAME
from aptiordesk.database.models.provider import ProviderKind
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.cover_letters.page import CoverLettersPage
from aptiordesk.features.dashboard.page import DashboardPage
from aptiordesk.features.interviews.page import InterviewPage
from aptiordesk.features.jobs.page import JobsPage
from aptiordesk.features.privacy.page import PrivacyPage
from aptiordesk.features.profile.page import ProfilePage
from aptiordesk.features.resumes.page import ResumesPage
from aptiordesk.features.settings.page import SettingsPage
from aptiordesk.features.tailoring.page import TailoringPage
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme import icons as icon_set
from aptiordesk.ui.theme.brand import application_icon, application_mark
from aptiordesk.ui.theme.tokens import SPACE

# (nav label, icon name)
_NAV_ICONS = {
    "Home": "home",
    "Profile": "user",
    "Resumes": "file",
    "Jobs": "briefcase",
    "Tailoring": "wand",
    "Cover Letters": "mail",
    "Interview": "mic",
    "Settings": "settings",
    "Privacy & Data": "shield",
}


def _with_page_padding(page: QWidget) -> QWidget:
    """Give every page the same breathing room, in one place, instead of
    each page choosing its own margins."""
    if page.layout() is not None:
        page.layout().setContentsMargins(0, 0, 0, 0)
    container = QWidget()
    container.setObjectName("pageBody")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(SPACE["2xl"], SPACE["xl"], SPACE["2xl"], SPACE["xl"])
    layout.addWidget(page)
    return container


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self._conn = conn
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(application_icon())
        self.resize(1420, 900)
        self.setMinimumSize(1024, 700)

        shell = QFrame()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        content = QWidget()
        content.setObjectName("shellContent")
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()

        self.dashboard_page = DashboardPage(conn)
        self.profile_page = ProfilePage(conn)
        self.resumes_page = ResumesPage(conn)
        # Importing a resume can update the profile, so the Profile page must
        # re-read rather than keep showing pre-import values.
        self.resumes_page.profile_updated.connect(self.profile_page.reload_from_store)
        self.jobs_page = JobsPage(conn)
        self.tailoring_page = TailoringPage(conn)
        self.cover_letters_page = CoverLettersPage(conn)
        self.interview_page = InterviewPage(conn)
        self.settings_page = SettingsPage(conn)
        self.privacy_page = PrivacyPage(conn)

        pages: list[tuple[str, QWidget]] = [
            ("Home", self.dashboard_page),
            ("Profile", self.profile_page),
            ("Resumes", self.resumes_page),
            ("Jobs", self.jobs_page),
            ("Tailoring", self.tailoring_page),
            ("Cover Letters", self.cover_letters_page),
            ("Interview", self.interview_page),
            ("Settings", self.settings_page),
            ("Privacy & Data", self.privacy_page),
        ]

        layout.addWidget(self._build_sidebar([label for label, _ in pages]))
        for _label, page in pages:
            self.stack.addWidget(_with_page_padding(page))

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_workspace_bar())
        workspace_layout.addWidget(self.stack, 1)
        layout.addWidget(workspace, 1)
        shell_layout.addWidget(content, 1)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(0)

        self.jobs_page.tailoring_requested.connect(self._open_tailoring)
        self.tailoring_page.view_resume_requested.connect(self._view_resume_version)
        self.dashboard_page.navigate_requested.connect(self.go_to)
        self.settings_page.provider_changed.connect(self._on_provider_changed)

        self.setCentralWidget(shell)
        self.statusBar().hide()
        self._refresh_provider_status()

    # -- sidebar -------------------------------------------------------------

    def _build_sidebar(self, labels: list[str]) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(0, SPACE["lg"], 0, SPACE["sm"])
        column.setSpacing(SPACE["md"])

        # wordmark
        brand_widget = QWidget()
        brand_widget.setObjectName("brandRow")
        brand = QHBoxLayout(brand_widget)
        brand.setContentsMargins(SPACE["lg"], 0, SPACE["md"], 0)
        brand.setSpacing(SPACE["sm"])
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(application_mark(34))
        mark.setToolTip(APP_NAME)
        brand.addWidget(mark)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("wordmark")
        brand_text.addWidget(wordmark)
        tagline = QLabel("CAREER WORKSPACE")
        tagline.setObjectName("wordmarkSub")
        brand_text.addWidget(tagline)
        brand.addLayout(brand_text, 1)
        column.addWidget(brand_widget)

        section = QLabel("WORKSPACE")
        section.setObjectName("navSection")
        column.addWidget(section)
        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label in labels:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, 40))
            self.nav.addItem(item)
        column.addWidget(self.nav, 1)

        # footer: active provider
        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], 0)
        footer_layout.setSpacing(SPACE["sm"])

        provider_card = QFrame()
        provider_card.setObjectName("providerCard")
        provider_row = QHBoxLayout(provider_card)
        provider_row.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        provider_row.setSpacing(SPACE["sm"])
        self._provider_icon = QLabel()
        provider_row.addWidget(self._provider_icon)
        self.provider_status = QLabel("")
        self.provider_status.setObjectName("providerStatus")
        self.provider_status.setWordWrap(True)
        provider_row.addWidget(self.provider_status, 1)
        footer_layout.addWidget(provider_card)

        credits = QLabel(f"Created by {CREATOR_NAME}\n{CREATOR_COMPANY}")
        credits.setObjectName("sidebarCredits")
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setToolTip(f"{APP_NAME} was created by {CREATOR_NAME} at {CREATOR_COMPANY}.")
        footer_layout.addWidget(credits)

        column.addWidget(footer)

        self._paint_nav_icons()
        self.nav.currentRowChanged.connect(lambda _: self._paint_nav_icons())
        return sidebar

    def _build_workspace_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("workspaceBar")
        bar.setFixedHeight(64)
        row = QHBoxLayout(bar)
        row.setContentsMargins(SPACE["lg"], 0, SPACE["lg"], 0)
        row.setSpacing(SPACE["sm"])

        self.workspace_context = QLabel("Workspace  /  Home")
        self.workspace_context.setObjectName("workspaceContext")
        row.addWidget(self.workspace_context)
        row.addStretch(1)

        jobs_shortcut = QPushButton("Captured jobs")
        jobs_shortcut.setObjectName("toolbarButton")
        jobs_shortcut.setIcon(icon_set.icon("briefcase", current().text_muted, 14))
        jobs_shortcut.clicked.connect(lambda: self.go_to("Jobs"))
        row.addWidget(jobs_shortcut)

        practice_shortcut = QPushButton("Practice")
        practice_shortcut.setObjectName("toolbarButton")
        practice_shortcut.setIcon(icon_set.icon("mic", current().text_muted, 14))
        practice_shortcut.clicked.connect(lambda: self.go_to("Interview"))
        row.addWidget(practice_shortcut)

        return bar

    def _paint_nav_icons(self) -> None:
        """Selected rows use the same restrained accent as their rail."""
        palette = current()
        selected = self.nav.currentRow()
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            name = _NAV_ICONS.get(item.text(), "spark")
            colour = palette.accent if row == selected else palette.text_muted
            item.setIcon(icon_set.icon(name, colour))

    def _refresh_provider_status(self) -> None:
        """Surface where AI requests go — the privacy story belongs in view,
        not buried in a settings page."""
        palette = current()
        config = ProviderRepository(self._conn).get_active()
        if config is None:
            text, name, colour = "No AI provider set", "alert", palette.warning
        elif config.kind == ProviderKind.CLI:
            text, name, colour = (
                f"{config.name or 'Device CLI'} · provider policy applies",
                "terminal",
                palette.accent,
            )
        elif config.is_local:
            text, name, colour = (
                f"{config.name or 'Local model'} · on this device",
                "lock",
                palette.success,
            )
        else:
            text, name, colour = (
                f"{config.name or 'Cloud provider'} · sends data out",
                "alert",
                palette.warning,
            )
        self.provider_status.setText(text)
        self._provider_icon.setPixmap(icon_set.pixmap(name, colour, 14))

    # -- navigation ----------------------------------------------------------

    def _page_index(self, label: str) -> int:
        matches = self.nav.findItems(label, Qt.MatchFlag.MatchExactly)
        return self.nav.row(matches[0]) if matches else -1

    def go_to(self, label: str) -> None:
        index = self._page_index(label)
        if index >= 0:
            self.nav.setCurrentRow(index)

    def _on_page_changed(self, row: int) -> None:
        """Refresh pages whose contents depend on other pages' data."""
        label = self.nav.item(row).text() if row >= 0 else ""
        if hasattr(self, "workspace_context"):
            self.workspace_context.setText(f"Workspace  /  {label}")
        refreshers = {
            "Home": self.dashboard_page.reload,
            "Jobs": self.jobs_page.reload,
            "Resumes": self.resumes_page.reload,
            "Tailoring": self.tailoring_page.reload,
            "Cover Letters": self.cover_letters_page.reload,
            "Interview": self.interview_page.reload,
            "Privacy & Data": self.privacy_page.reload,
        }
        refresh = refreshers.get(label)
        if refresh is not None:
            refresh()
        if label in ("Settings", "Home", "Privacy & Data"):
            self._refresh_provider_status()

    def refresh_after_setup(self) -> None:
        """Setup may have configured a provider or filled in the profile."""
        self._refresh_provider_status()
        self.dashboard_page.reload()
        self.settings_page._reload()
        self.profile_page.reload_from_store()

    def _on_provider_changed(self) -> None:
        """Keep the always-visible sidebar provider card authoritative."""
        self._refresh_provider_status()
        self.dashboard_page.reload()
        self.privacy_page.reload()

    def on_browser_job_imported(self, job_id: int) -> None:
        """Refresh views after the local browser-extension bridge saves a job."""
        self.jobs_page.reload()
        self.dashboard_page.reload()

    def run_setup_again(self) -> None:
        from aptiordesk.app.onboarding import OnboardingWizard

        wizard = OnboardingWizard(self._conn, self)
        wizard.finished_setup.connect(self.refresh_after_setup)
        wizard.exec()
        self.refresh_after_setup()

    def _open_tailoring(self, session_id: int) -> None:
        self.tailoring_page.load_session(session_id)
        self.go_to("Tailoring")

    def _view_resume_version(self, resume_id: int, version_id: int) -> None:
        self.go_to("Resumes")
        self.resumes_page.select_version(resume_id, version_id)
