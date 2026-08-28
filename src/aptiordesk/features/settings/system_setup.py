"""System Setup and secret-free diagnostics UI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.core.system_health import (
    ComponentCheck,
    ComponentState,
    SystemHealthReport,
    build_health_context,
    inspect_system,
    write_diagnostics,
)
from aptiordesk.features.interviews.voice.installer import repair_kokoro_runtime
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.forms import SectionCard
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker


class SystemSetupPanel(QWidget):
    """Rerunnable component health checks and repair entry points."""

    configure_ai_requested = Signal()
    configure_voice_requested = Signal()
    configure_extension_requested = Signal()

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._worker: Worker | None = None
        self._repair_worker: Worker | None = None
        self._report: SystemHealthReport | None = None
        self._rows: dict[str, tuple[QLabel, QLabel, QPushButton]] = {}

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setProperty("role", "layoutOnly")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, SPACE["lg"], 0, 0)
        outer.setSpacing(SPACE["lg"])

        header = PageHeader(
            "System setup",
            "Verify AptiorDesk, local AI, interview devices, and the browser "
            "extension without exposing keys or personal application data.",
            eyebrow="HEALTH & REPAIR",
        )
        self.retry_button = QPushButton("Run all checks")
        self.retry_button.setProperty("accent", True)
        self.retry_button.clicked.connect(self.run_checks)
        header.actions.addWidget(self.retry_button)
        self.export_button = QPushButton("Export diagnostics")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)
        header.actions.addWidget(self.export_button)
        outer.addWidget(header)

        explanation = SectionCard(
            "Required and feature-specific components",
            "Core storage must be healthy to use AptiorDesk. Voice, AI, camera, "
            "microphone, and the extension are required only by their related features.",
        )
        self.summary = QLabel("Checks have not run yet.")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "hint")
        explanation.body.addWidget(self.summary)
        outer.addWidget(explanation)

        self.core_card = self._component_card("Required to launch AptiorDesk")
        self.feature_card = self._component_card("Required for specific features")
        outer.addWidget(self.core_card)
        outer.addWidget(self.feature_card)
        outer.addStretch(1)
        scroll.setWidget(content)
        shell.addWidget(scroll)

    def _component_card(self, title: str) -> SectionCard:
        return SectionCard(title)

    def run_checks(self, *, full: bool = True) -> None:
        if self._worker is not None:
            return
        context = build_health_context(self._conn)
        self.retry_button.setEnabled(False)
        self.summary.setText("Checking components…")
        worker = Worker(
            lambda: inspect_system(context, full=full),
            parent=QApplication.instance(),
        )
        worker.result.connect(self._render)
        worker.error.connect(self._failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_worker", None),
                self.retry_button.setEnabled(True),
            )
        )
        self._worker = worker
        worker.start()

    def _render(self, report: SystemHealthReport) -> None:
        self._report = report
        self.export_button.setEnabled(True)
        self._clear_rows(self.core_card)
        self._clear_rows(self.feature_card)
        self._rows.clear()
        for component in report.components:
            card = self.core_card if component.required else self.feature_card
            self._add_row(card, component)
        ready = sum(component.ready for component in report.components)
        total = len(report.components)
        if report.critical_ready:
            self.summary.setText(
                f"Core application ready · {ready} of {total} components ready. "
                "Unavailable optional features remain clearly identified below."
            )
            self.summary.setProperty("role", "success")
        else:
            self.summary.setText(
                "A required AptiorDesk component needs attention. Repair it before "
                "continuing with the main workspace."
            )
            self.summary.setProperty("role", "error")
        self._repolish(self.summary)

    def _clear_rows(self, card: SectionCard) -> None:
        while card.body.count():
            item = card.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_row(self, card: SectionCard, component: ComponentCheck) -> None:
        row = QFrame()
        row.setProperty("role", "subtle")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        layout.setSpacing(SPACE["md"])
        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(component.name)
        heading.setProperty("role", "sectionTitle")
        copy.addWidget(heading)
        detail = QLabel(component.detail)
        detail.setWordWrap(True)
        detail.setProperty("role", "hint")
        copy.addWidget(detail)
        layout.addLayout(copy, 1)
        badge = QLabel(component.state.value)
        badge.setProperty("role", "badge")
        badge.setProperty("tone", self._tone(component.state))
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        action = QPushButton(self._action_label(component.action))
        action.setVisible(bool(component.action))
        action.clicked.connect(
            lambda _checked=False, value=component.action: self._run_action(value)
        )
        layout.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addWidget(row)
        self._rows[component.id] = (detail, badge, action)

    def _run_action(self, action: str) -> None:
        if action == "configure_ai":
            self.configure_ai_requested.emit()
        elif action == "configure_voice":
            self.configure_voice_requested.emit()
        elif action == "configure_extension":
            self.configure_extension_requested.emit()
        elif action == "repair_kokoro" or action == "repair":
            self._repair_kokoro()
        elif action == "start_ollama":
            self._start_ollama()
        elif action in {"test_microphone", "test_camera"}:
            QMessageBox.information(
                self,
                "Device permission",
                "Device access is requested only inside the mock interview when you "
                "turn this device on. The system check verifies the packaged runtime "
                "without activating your camera or microphone.",
            )

    def _repair_kokoro(self) -> None:
        if self._repair_worker is not None:
            return
        worker = Worker(lambda report: repair_kokoro_runtime(report), parent=self)
        worker.result.connect(
            lambda message: (
                QMessageBox.information(self, "Kokoro repaired", message),
                self.run_checks(),
            )
        )
        worker.error.connect(
            lambda exc: QMessageBox.critical(
                self,
                "Repair needs the installer",
                f"{exc}\n\nRerun the AptiorDesk setup installer to restore packaged "
                "Python or native runtime files. Your local data will be preserved.",
            )
        )
        worker.finished.connect(
            lambda: setattr(self, "_repair_worker", None) if self._repair_worker is worker else None
        )
        worker.show_progress(
            "Repairing Kokoro",
            "Verifying the installed runtime and restoring trusted model assets.",
        )
        self._repair_worker = worker
        worker.start()

    def _start_ollama(self) -> None:
        try:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
            subprocess.Popen(  # noqa: S603
                ["ollama", "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Could not start Ollama",
                f"{exc}\n\nOpen the Ollama application manually or configure a "
                "different AI provider.",
            )
            return
        QMessageBox.information(
            self,
            "Starting Ollama",
            "Ollama is starting in the background. Wait a moment, then run the checks again.",
        )

    def _export(self) -> None:
        if self._report is None:
            return
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export AptiorDesk diagnostics",
            str(Path.home() / "AptiorDesk-diagnostics.json"),
            "JSON files (*.json)",
        )
        if selected:
            write_diagnostics(self._report, Path(selected))

    def _failed(self, exc: Exception) -> None:
        self.summary.setText(f"System checks failed: {exc}")
        self.summary.setProperty("role", "error")
        self._repolish(self.summary)

    @staticmethod
    def _tone(state: ComponentState) -> str:
        if state == ComponentState.READY:
            return "success"
        if state in {ComponentState.REPAIR_AVAILABLE, ComponentState.CONNECTION_FAILED}:
            return "danger"
        if state in {ComponentState.NOT_CONFIGURED, ComponentState.NOT_INSTALLED}:
            return "warning"
        return "neutral"

    @staticmethod
    def _action_label(action: str) -> str:
        return {
            "configure_ai": "Configure",
            "configure_voice": "Set up",
            "configure_extension": "Open setup",
            "repair_kokoro": "Repair",
            "repair": "Repair",
            "start_ollama": "Start Ollama",
            "test_microphone": "How to test",
            "test_camera": "How to test",
        }.get(action, "")

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


__all__ = ["SystemSetupPanel"]
