"""Application bootstrap."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtQuick3D import QQuick3D
from PySide6.QtWidgets import QApplication, QMessageBox

from aptiordesk import APP_NAME, CREATOR_COMPANY, __version__
from aptiordesk.app.main_window import MainWindow
from aptiordesk.app.onboarding import OnboardingWizard, needs_onboarding
from aptiordesk.core import paths
from aptiordesk.core.logging import setup_logging
from aptiordesk.core.system_health import (
    HEALTH_SNAPSHOT_KEY,
    build_health_context,
    inspect_system,
)
from aptiordesk.database.db import open_database
from aptiordesk.database.repositories.settings_repo import SettingsRepository
from aptiordesk.integrations.browser_extension.bridge import BrowserImportServer
from aptiordesk.ui.theme import SETTING_KEY, apply_theme, stylesheet
from aptiordesk.ui.theme.brand import application_icon
from aptiordesk.ui.theme.tokens import DEFAULT_THEME
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)


class _BrowserImportEvents(QObject):
    job_imported = Signal(int)


def _enforce_dark_theme_setting(settings: SettingsRepository) -> str:
    """One-way compatibility migration for the retired light preference."""
    if settings.get(SETTING_KEY, DEFAULT_THEME) != DEFAULT_THEME:
        settings.set(SETTING_KEY, DEFAULT_THEME)
    return DEFAULT_THEME


def main() -> int:
    setup_logging()
    log.info("Starting %s — data dir: %s", APP_NAME, paths.data_dir())

    conn = open_database(paths.db_path())

    QSurfaceFormat.setDefaultFormat(QQuick3D.idealSurfaceFormat(4))
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(CREATOR_COMPANY)
    app.setOrganizationDomain("glidd.io")
    app.setWindowIcon(application_icon())
    # Fusion gives the custom stylesheet the same geometry on Windows, macOS,
    # and Linux instead of leaking platform-native control chrome through it.
    app.setStyle("Fusion")

    settings = SettingsRepository(conn)
    apply_theme(_enforce_dark_theme_setting(settings), app)

    window = MainWindow(conn)

    # A loopback-only bridge lets the companion extension save job pages the
    # user explicitly selects.  The signal safely crosses from the HTTP worker
    # thread back to Qt's UI thread.
    browser_events = _BrowserImportEvents(app)
    browser_server = BrowserImportServer(
        paths.db_path(), on_import=browser_events.job_imported.emit
    )
    browser_events.job_imported.connect(window.on_browser_job_imported)
    browser_server.start()
    app.aboutToQuit.connect(browser_server.stop)
    # Keep both alive for the QApplication lifetime.
    app._browser_import_events = browser_events
    app._browser_import_server = browser_server

    first_launch = needs_onboarding(conn)
    if first_launch:
        log.info("First run — showing setup")
        wizard = OnboardingWizard(conn)
        wizard.finished_setup.connect(window.refresh_after_setup)
        wizard.exec()
        window.refresh_after_setup()
    window.show()
    if not first_launch:
        QTimer.singleShot(500, lambda: _run_background_health_check(app, window, conn))

    code = app.exec()
    conn.close()
    return code


def _run_background_health_check(app, window, conn) -> None:
    """Run later-launch checks without moving a SQLite connection across threads."""
    context = build_health_context(conn)
    settings = SettingsRepository(conn)
    worker = Worker(lambda: inspect_system(context, full=False), parent=app)

    def checked(report) -> None:
        previous = settings.get(HEALTH_SNAPSHOT_KEY, "")
        current = report.changed_signature
        settings.set(HEALTH_SNAPSHOT_KEY, current)
        if not previous or previous == current:
            return
        attention = [
            item
            for item in report.components
            if not item.ready and item.state.value not in {"Optional", "Not configured"}
        ]
        if not attention:
            return
        message = QMessageBox(window)
        message.setWindowTitle("AptiorDesk setup changed")
        message.setIcon(QMessageBox.Icon.Warning)
        message.setText("A component used by AptiorDesk needs attention.")
        message.setInformativeText(
            "\n".join(f"• {item.name}: {item.state.value}" for item in attention[:5])
            + "\n\nOpen Settings → System setup for diagnostics and repair."
        )
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        message.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        message.show()

    worker.result.connect(checked)
    worker.error.connect(lambda exc: log.warning("Background health check failed: %s", exc))
    worker.start()
    app._health_worker = worker


def _load_stylesheet() -> str:
    """The active theme's stylesheet (kept for scripts and tests)."""
    return stylesheet()
