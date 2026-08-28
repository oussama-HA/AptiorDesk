"""First-run setup wizard.

Design rules for this screen specifically:
- Nothing downloads or installs until the user presses the button for it.
- Every download states its size before it starts.
- Optional integrations can be skipped; core storage checks cannot.
- It can be re-run later from Settings, so nothing here is a one-shot.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai import keystore
from aptiordesk.core import environment as env
from aptiordesk.core.system_health import (
    ComponentState,
    SystemHealthReport,
    build_health_context,
    inspect_system,
)
from aptiordesk.database.models.profile import Profile
from aptiordesk.database.models.provider import (
    DEFAULT_BASE_URLS,
    ProviderConfig,
    ProviderKind,
)
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.database.repositories.settings_repo import SettingsRepository
from aptiordesk.features.interviews.voice.installer import (
    inspect_kokoro_runtime,
    repair_kokoro_runtime,
)
from aptiordesk.ui.components.common import Card, badge
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme import icons as icon_set
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

ONBOARDED_KEY = "onboarding.completed"

_CLOUD_PROVIDER_PRESETS = {
    "openai": (
        "OpenAI",
        ProviderKind.OPENAI_COMPAT,
        DEFAULT_BASE_URLS[ProviderKind.OPENAI_COMPAT],
    ),
    "anthropic": (
        "Anthropic Claude",
        ProviderKind.ANTHROPIC,
        DEFAULT_BASE_URLS[ProviderKind.ANTHROPIC],
    ),
    "gemini": (
        "Google Gemini",
        ProviderKind.GEMINI,
        DEFAULT_BASE_URLS[ProviderKind.GEMINI],
    ),
    "compatible": (
        "Other OpenAI-compatible provider",
        ProviderKind.OPENAI_COMPAT,
        "",
    ),
}


class _ProviderChoiceCard(QFrame):
    """A provider option selected by clicking its surface or using the keyboard."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        cost_text: str,
        cost_tone: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setProperty("selectable", True)
        self.setProperty("providerChoice", True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(156)
        self.setMaximumHeight(156)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        outer.setSpacing(SPACE["md"])
        heading = QHBoxLayout()
        heading.setSpacing(SPACE["sm"])
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "sectionTitle")
        heading.addWidget(self.title_label)
        self.cost_badge = badge(cost_text, cost_tone)
        self.cost_badge.setProperty("role", "providerCost")
        heading.addWidget(self.cost_badge)
        heading.addStretch(1)
        self.selection_indicator = QLabel("✓")
        self.selection_indicator.setProperty("role", "selectionCheck")
        self.selection_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_indicator.setFixedSize(20, 20)
        self.selection_indicator.hide()
        heading.addWidget(self.selection_indicator)
        outer.addLayout(heading)
        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE["md"])
        outer.addLayout(self.body)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.selection_indicator.setVisible(selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def needs_onboarding(conn: sqlite3.Connection) -> bool:
    return not SettingsRepository(conn).get(ONBOARDED_KEY, False)


def mark_onboarded(conn: sqlite3.Connection) -> None:
    SettingsRepository(conn).set(ONBOARDED_KEY, True)


class OnboardingWizard(QDialog):
    """Runs on first launch, and on demand from Settings."""

    finished_setup = Signal()

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self.setWindowTitle("Set up AptiorDesk")
        self.setModal(True)
        self.resize(760, 620)
        self._required_checks_passed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["lg"])
        outer.setSpacing(SPACE["lg"])

        self.step_label = QLabel()
        self.step_label.setProperty("role", "caption")
        outer.addWidget(self.step_label)

        self.stack = QStackedWidget()
        self.steps: list[_Step] = [
            WelcomeStep(self),
            SystemCheckStep(self),
            AIStep(self),
            VoiceStep(self),
            ProfileStep(self),
            SummaryStep(self),
        ]
        for step in self.steps:
            # Steps must survive a short window; a laptop at 768px tall would
            # otherwise clip the footer buttons out of reach.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(step)
            self.stack.addWidget(scroll)
        outer.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.skip_button = QPushButton("Skip optional setup")
        self.skip_button.setProperty("variant", "ghost")
        self.skip_button.clicked.connect(self._skip)
        footer.addWidget(self.skip_button)
        footer.addStretch(1)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        footer.addWidget(self.back_button)
        self.next_button = QPushButton("Next")
        self.next_button.setProperty("accent", True)
        self.next_button.clicked.connect(self._next)
        footer.addWidget(self.next_button)
        outer.addLayout(footer)

        self._index = 0
        self._show_step(0)

    # -- navigation ----------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def _show_step(self, index: int) -> None:
        self._index = max(0, min(index, len(self.steps) - 1))
        self.stack.setCurrentIndex(self._index)
        step = self.steps[self._index]
        step.on_enter()
        self.step_label.setText(f"Step {self._index + 1} of {len(self.steps)} · {step.title}")
        self.back_button.setEnabled(self._index > 0)
        last = self._index == len(self.steps) - 1
        self.next_button.setText("Finish" if last else "Next")
        self.skip_button.setVisible(not last)

    def _next(self) -> None:
        step = self.steps[self._index]
        if not step.on_leave():
            return
        if self._index == len(self.steps) - 1:
            self._complete()
            return
        self._show_step(self._index + 1)

    def _back(self) -> None:
        self._show_step(self._index - 1)

    def _skip(self) -> None:
        if self._index == 0:
            self._show_step(1)
            return
        if isinstance(self.steps[self._index], SystemCheckStep):
            if not self.steps[self._index].on_leave():
                return
        self._show_step(len(self.steps) - 1)

    def _complete(self) -> None:
        mark_onboarded(self._conn)
        self.finished_setup.emit()
        self.accept()

    def reject(self) -> None:
        if needs_onboarding(self._conn) and not self._required_checks_passed:
            QMessageBox.information(
                self,
                "Finish the required checks",
                "AptiorDesk needs to verify its core files, local database, and "
                "writable data directory before opening the workspace. Optional "
                "AI, interview, and extension setup can still be skipped.",
            )
            return
        mark_onboarded(self._conn)
        super().reject()


# ------------------------------------------------------------------- steps


class _Step(QWidget):
    title = ""

    def __init__(self, wizard: OnboardingWizard):
        super().__init__(wizard)
        self.wizard = wizard
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(SPACE["md"])

    def heading(self, text: str, subtitle: str = "") -> None:
        label = QLabel(text)
        label.setProperty("role", "pageTitle")
        label.setWordWrap(True)
        self.layout_.addWidget(label)
        if subtitle:
            caption = QLabel(subtitle)
            caption.setProperty("role", "hint")
            caption.setWordWrap(True)
            self.layout_.addWidget(caption)

    def on_enter(self) -> None:
        """Called each time the step is shown."""

    def on_leave(self) -> bool:
        """Return False to stay on this step."""
        return True


class WelcomeStep(_Step):
    title = "Welcome"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.heading(
            "Welcome to AptiorDesk",
            "A few minutes now and the rest of your job search is set up.",
        )
        promises = [
            (
                "lock",
                "Everything stays on this computer",
                "Your profile, resumes, and practice answers live in a local database. "
                "No account, no server, no telemetry.",
            ),
            (
                "spark",
                "You choose the AI",
                "Run a model locally so nothing leaves your machine, or bring your own "
                "API key. We will help you pick on the next screen.",
            ),
            (
                "shield",
                "It will not make things up",
                "Nothing invents experience or metrics for you. Every suggestion shows "
                "what in your own background supports it.",
            ),
        ]
        palette = current()
        for icon_name, title, detail in promises:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(SPACE["md"])
            glyph = QLabel()
            glyph.setPixmap(icon_set.pixmap(icon_name, palette.accent, 20))
            row_layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
            column = QVBoxLayout()
            column.setSpacing(1)
            strong = QLabel(title)
            strong.setProperty("role", "sectionTitle")
            column.addWidget(strong)
            caption = QLabel(detail)
            caption.setProperty("role", "hint")
            caption.setWordWrap(True)
            column.addWidget(caption)
            row_layout.addLayout(column, 1)
            self.layout_.addWidget(row)

        self.env_label = QLabel()
        self.env_label.setProperty("role", "caption")
        self.env_label.setWordWrap(True)
        self.layout_.addWidget(self.env_label)
        self.layout_.addStretch(1)

    def on_enter(self) -> None:
        problems = []
        if not env.python_version_ok():
            problems.append(
                f"⚠ Python {env.MIN_PYTHON[0]}.{env.MIN_PYTHON[1]}+ is required "
                f"(running {env.python_version_text()})."
            )
        location = "a virtual environment" if env.in_virtualenv() else "the system Python"
        self.env_label.setText(
            "\n".join(problems) or f"Running Python {env.python_version_text()} in {location}."
        )


class SystemCheckStep(_Step):
    title = "System check"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.heading(
            "Preparing your AptiorDesk workspace",
            "Required components must be healthy. Feature-specific components can "
            "be configured now or later from Settings → System setup.",
        )
        self._worker = None
        self._report: SystemHealthReport | None = None
        self.card = Card("Component status")
        self.status_label = QLabel("Waiting to run checks…")
        self.status_label.setWordWrap(True)
        self.card.body.addWidget(self.status_label)
        self.check_progress = QProgressBar()
        self.check_progress.setRange(0, 0)
        self.check_progress.setFormat("Indeterminate")
        self.check_progress.hide()
        self.card.body.addWidget(self.check_progress)
        self.results = QLabel("")
        self.results.setWordWrap(True)
        self.results.setTextFormat(Qt.TextFormat.RichText)
        self.card.body.addWidget(self.results)
        retry = QPushButton("Retry checks")
        retry.clicked.connect(self._run)
        self.card.body.addWidget(retry, alignment=Qt.AlignmentFlag.AlignLeft)
        self.layout_.addWidget(self.card)
        self.layout_.addStretch(1)

    def on_enter(self) -> None:
        if self._report is None:
            self._run()

    def _run(self) -> None:
        if self._worker is not None:
            return
        context = build_health_context(self.wizard.conn)
        self.check_progress.setRange(0, 0)
        self.check_progress.setFormat("Indeterminate")
        self.check_progress.show()
        self.status_label.setText("Checking AptiorDesk components…")
        # Health checks can outlive a wizard page transition. Parent the thread
        # to QApplication so closing/back navigation never destroys a running
        # QThread.
        worker = Worker(
            lambda: inspect_system(context, full=True),
            parent=QApplication.instance(),
        )
        worker.result.connect(self._show_report)
        worker.error.connect(self._show_error)
        worker.finished.connect(
            lambda: setattr(self, "_worker", None) if self._worker is worker else None
        )
        self._worker = worker
        worker.start()

    def _show_report(self, report: SystemHealthReport) -> None:
        self._report = report
        self.check_progress.setRange(0, 100)
        self.check_progress.setValue(100)
        self.check_progress.setFormat("Complete")
        self.wizard._required_checks_passed = report.critical_ready
        palette = current()
        lines = []
        for item in report.components:
            colour = (
                palette.success
                if item.state == ComponentState.READY
                else (
                    palette.danger
                    if item.required or item.state == ComponentState.REPAIR_AVAILABLE
                    else palette.text_muted
                )
            )
            requirement = "required" if item.required else "feature-specific"
            lines.append(
                f"<p style='color:{colour}'><b>{item.name}</b> · "
                f"{item.state.value} <span>({requirement})</span><br>"
                f"{item.detail}</p>"
            )
        self.results.setText("".join(lines))
        self.status_label.setText(
            "Core application is ready. Optional items can be configured in the next steps."
            if report.critical_ready
            else "A required component needs repair before setup can continue."
        )

    def _show_error(self, exc: Exception) -> None:
        self.check_progress.setRange(0, 100)
        self.check_progress.setValue(0)
        self.check_progress.setFormat("Failed")
        self.status_label.setText(f"System checks failed: {exc}")

    def on_leave(self) -> bool:
        if self._report is None:
            self.status_label.setText("Wait for the system checks to finish.")
            return False
        if not self._report.critical_ready:
            self.status_label.setText(
                "Repair the required component and retry checks before continuing."
            )
            return False
        return True


class AIStep(_Step):
    title = "AI provider"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.heading(
            "Choose how AptiorDesk thinks",
            "This is the one decision that determines whether your documents ever "
            "leave this computer.",
        )
        self._worker = None
        self._model_worker: Worker | None = None
        self._model_download_started = 0.0
        self._provider_choice: str | None = None
        self._status = env.OllamaStatus()

        self.status_card = _ProviderChoiceCard(
            "Local AI with Ollama",
            "FREE",
            "success",
        )
        choice_hint = QLabel(
            "Choose one. You can switch providers later from Settings without "
            "changing your resumes or saved jobs."
        )
        choice_hint.setProperty("role", "hint")
        choice_hint.setWordWrap(True)
        self.layout_.addWidget(choice_hint)
        self.status_card.setAccessibleName("Use Ollama local AI")
        self.status_card.clicked.connect(lambda: self._select_provider("ollama"))
        self.ollama_cost_badge = self.status_card.cost_badge
        local_summary = QLabel("Private data  ·  No usage fees  ·  Works offline")
        local_summary.setProperty("role", "caption")
        local_summary.setWordWrap(True)
        self.status_card.body.addWidget(local_summary)

        self.local_details_card = Card(
            "Local AI setup",
            "AptiorDesk checks your existing Ollama installation and uses an "
            "installed model whenever possible.",
        )
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.local_details_card.body.addWidget(self.status_label)

        self.installed_models_row = QWidget()
        self.installed_models_row.setProperty("role", "layoutOnly")
        installed_models_layout = QHBoxLayout(self.installed_models_row)
        installed_models_layout.setContentsMargins(0, 0, 0, 0)
        installed_model_label = QLabel("Use installed model")
        installed_model_label.setProperty("role", "fieldLabel")
        installed_models_layout.addWidget(installed_model_label)
        self.installed_model_combo = Dropdown()
        self.installed_model_combo.activated.connect(lambda _index: self._select_provider("ollama"))
        installed_models_layout.addWidget(self.installed_model_combo, 1)
        self.installed_models_row.setVisible(False)
        self.local_details_card.body.addWidget(self.installed_models_row)

        self.install_row = QHBoxLayout()
        self.get_ollama_button = QPushButton("Get Ollama (opens ollama.com)")
        self.get_ollama_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(env.OLLAMA_URL))
        )
        self.recheck_button = QPushButton("Check again")
        self.recheck_button.clicked.connect(self._probe)
        self.install_row.addWidget(self.get_ollama_button)
        self.install_row.addWidget(self.recheck_button)
        self.install_row.addStretch(1)
        self.local_details_card.body.addLayout(self.install_row)
        # model picker (shown when Ollama is running)
        self.model_card = Card(
            "Download a model",
            "Downloads once, then works offline. Pick by what your machine can handle.",
        )
        self.model_group = QButtonGroup(self)
        for index, suggestion in enumerate(env.RECOMMENDED_MODELS):
            button = QRadioButton(f"{suggestion.name}  ·  {suggestion.size}  —  {suggestion.note}")
            button.setProperty("model_name", suggestion.name)
            if index == 1:
                button.setChecked(True)
            self.model_group.addButton(button, index)
            self.model_card.body.addWidget(button)

        self.pull_button = QPushButton("Download selected model")
        self.pull_button.setProperty("accent", True)
        self.pull_button.clicked.connect(self._pull)
        download_actions = QHBoxLayout()
        download_actions.addWidget(self.pull_button)
        self.cancel_pull_button = QPushButton("Cancel")
        self.cancel_pull_button.clicked.connect(self._cancel_pull)
        self.cancel_pull_button.hide()
        download_actions.addWidget(self.cancel_pull_button)
        download_actions.addStretch(1)
        self.model_card.body.addLayout(download_actions)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.model_card.body.addWidget(self.progress)
        self.progress_label = QLabel()
        self.progress_label.setProperty("role", "caption")
        self.progress_label.setWordWrap(True)
        self.model_card.body.addWidget(self.progress_label)
        # cloud fallback
        self.cloud_card = _ProviderChoiceCard(
            "Cloud AI provider",
            "MAY COST MONEY",
            "warning",
        )
        self.cloud_card.setAccessibleName("Use a cloud AI provider")
        self.cloud_card.clicked.connect(lambda: self._select_provider("cloud"))
        self.cloud_cost_badge = self.cloud_card.cost_badge
        cloud_description = QLabel("Use OpenAI, Anthropic, Gemini, or another compatible API.")
        cloud_description.setProperty("role", "hint")
        cloud_description.setWordWrap(True)
        self.cloud_card.body.addWidget(cloud_description)
        cloud_summary = QLabel("Fast setup  ·  Provider billing  ·  Content leaves this device")
        cloud_summary.setProperty("role", "caption")
        cloud_summary.setWordWrap(True)
        self.cloud_card.body.addWidget(cloud_summary)
        self.cloud_details_card = Card(
            "Connect a cloud provider",
            "Your content is sent to the provider you choose. AptiorDesk stores "
            "the API key in this computer's credential manager.",
        )
        form = QFormLayout()
        self.cloud_kind = Dropdown()
        for key, (label, _kind, _base_url) in _CLOUD_PROVIDER_PRESETS.items():
            self.cloud_kind.addItem(label, key)
        self.cloud_kind.currentIndexChanged.connect(self._cloud_provider_changed)
        self.cloud_kind.activated.connect(lambda _index: self._select_provider("cloud"))
        self.cloud_key = QLineEdit()
        self.cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_key.setPlaceholderText("Paste an API key to configure it now")
        self.cloud_model = QLineEdit()
        self.cloud_model.setPlaceholderText("Model ID supplied by your provider")
        self.cloud_base_url = QLineEdit()
        self.cloud_base_url.setPlaceholderText("https://provider.example/v1")
        form.addRow("Provider", self.cloud_kind)
        form.addRow("API key", self.cloud_key)
        form.addRow("Model", self.cloud_model)
        form.addRow("Base URL", self.cloud_base_url)
        self._cloud_base_url_label = form.labelForField(self.cloud_base_url)
        self.cloud_details_card.body.addLayout(form)
        self.cloud_status = QLabel()
        self.cloud_status.setWordWrap(True)
        self.cloud_status.setProperty("role", "hint")
        self.cloud_details_card.body.addWidget(self.cloud_status)
        self.cloud_key.textEdited.connect(lambda _text: self._select_provider("cloud"))
        self.cloud_model.textEdited.connect(lambda _text: self._select_provider("cloud"))
        self.cloud_base_url.textEdited.connect(lambda _text: self._select_provider("cloud"))
        choice_row = QHBoxLayout()
        choice_row.setSpacing(SPACE["md"])
        choice_row.addWidget(self.status_card, 1)
        choice_row.addWidget(self.cloud_card, 1)
        self.layout_.addLayout(choice_row)
        self.layout_.addWidget(self.local_details_card)
        self.layout_.addWidget(self.model_card)
        self.layout_.addWidget(self.cloud_details_card)
        self.cloud_details_card.hide()
        self.layout_.addStretch(1)
        self._cloud_provider_changed()

    def on_enter(self) -> None:
        self._probe()

    def _probe(self) -> None:
        self.status_label.setText("Looking for Ollama on this computer…")
        worker = Worker(env.probe_ollama, parent=self)
        worker.result.connect(self._show_status)
        worker.error.connect(lambda exc: self.status_label.setText(str(exc)))
        # The provider card already presents this live status. A second modal
        # activity window only causes startup/step-transition flashing.
        worker.start()

    def _show_status(self, status: env.OllamaStatus) -> None:
        self._status = status
        palette = current()
        self.installed_model_combo.clear()
        self.installed_model_combo.addItems(status.models)
        self.installed_models_row.setVisible(bool(status.models))
        if status.running:
            models = ", ".join(status.models[:4]) or "none yet"
            self.local_details_card.set_title(
                "Local models ready" if status.models else "Ollama is ready — download a model"
            )
            self.status_label.setText(
                f"<span style='color:{palette.success}'>Ollama is running</span>"
                f"{f' (v{status.version})' if status.version else ''}. "
                f"Models installed: {models}."
            )
            self.get_ollama_button.setVisible(False)
            if self._provider_choice is None:
                self._select_provider("ollama")
            self.model_card.setVisible(status.needs_model and self._provider_choice == "ollama")
            self.pull_button.setEnabled(status.needs_model)
        elif status.installed:
            self.local_details_card.set_title("Ollama is not running")
            self.status_label.setText(
                "Ollama is installed but not running. Start it (open the Ollama app, "
                "or run <code>ollama serve</code>), then press Check again."
            )
            self.get_ollama_button.setVisible(False)
            self.model_card.setVisible(False)
        else:
            self.local_details_card.set_title("No local model yet")
            self.status_label.setText(
                "No local model found. Install Ollama to keep everything on this "
                "machine — it is free and takes a couple of minutes. Or skip this and "
                "use a cloud key below."
            )
            self.get_ollama_button.setVisible(True)
            self.model_card.setVisible(False)

    def _select_provider(self, choice: str) -> None:
        self._provider_choice = choice
        ollama_selected = choice == "ollama"
        self.status_card.set_selected(ollama_selected)
        self.cloud_card.set_selected(not ollama_selected)
        self.local_details_card.setVisible(ollama_selected)
        self.cloud_details_card.setVisible(not ollama_selected)
        self.model_card.setVisible(
            ollama_selected and self._status.running and self._status.needs_model
        )

    def _cloud_provider_changed(self) -> None:
        key = self.cloud_kind.currentData() or "openai"
        _label, _kind, base_url = _CLOUD_PROVIDER_PRESETS[key]
        custom = key == "compatible"
        self.cloud_base_url.setVisible(custom)
        self._cloud_base_url_label.setVisible(custom)
        if not custom:
            self.cloud_base_url.setText(base_url)
        elif self.cloud_base_url.text() in {
            value[2] for value in _CLOUD_PROVIDER_PRESETS.values() if value[2]
        }:
            self.cloud_base_url.clear()
        self.cloud_status.clear()
        self.cloud_status.setProperty("role", "hint")

    def _pull(self) -> None:
        if self._model_worker is not None:
            return
        self._select_provider("ollama")
        button = self.model_group.checkedButton()
        if button is None:
            return
        model = button.property("model_name")
        self.pull_button.setEnabled(False)
        self.cancel_pull_button.setEnabled(True)
        self.cancel_pull_button.show()
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Indeterminate")
        self._model_download_started = time.monotonic()
        self.progress_label.setText(f"Starting download of {model}…")

        def run(report):
            last = None
            for progress in env.pull_ollama_model(model):
                if worker.isInterruptionRequested():
                    return False
                last = progress
                report(progress)
            return bool(last)

        worker = Worker(run, parent=self)
        worker.progress.connect(self._report)  # delivered on the UI thread
        worker.result.connect(
            lambda completed: self._pull_done(model) if completed else self._pull_cancelled()
        )
        worker.error.connect(self._pull_failed)
        worker.finished.connect(
            lambda: setattr(self, "_model_worker", None) if self._model_worker is worker else None
        )
        self._model_worker = worker
        worker.start()

    def _report(self, progress: env.PullProgress) -> None:
        # Ollama's final "success" line carries no byte counts, and some
        # interim lines (manifest, verifying) don't either — leave the bar
        # where it is rather than snapping it back to zero.
        if progress.total:
            self.progress.setRange(0, 100)
            self.progress.setValue(progress.percent)
            self.progress.setFormat(f"{progress.percent}%")
        detail = (
            f" — {progress.completed / 1e9:.1f} of {progress.total / 1e9:.1f} GB"
            if progress.total
            else ""
        )
        eta = ""
        elapsed = max(0.001, time.monotonic() - self._model_download_started)
        if progress.total and 0 < progress.completed < progress.total:
            seconds = (progress.total - progress.completed) / (progress.completed / elapsed)
            eta = (
                f" · about {max(1, round(seconds / 60))} min remaining"
                if seconds >= 60
                else f" · about {max(1, round(seconds))} sec remaining"
            )
        self.progress_label.setText(
            f"{progress.status} · {progress.percent}%{detail}{eta}"
            if progress.total
            else f"{progress.status} · progress not measurable yet"
        )

    def _pull_done(self, model: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100%")
        self.progress_label.setText(f"{model} is ready.")
        self.pull_button.setEnabled(True)
        self.cancel_pull_button.hide()
        self._save_ollama_provider(model)
        self._status = env.OllamaStatus(
            running=True,
            installed=True,
            models=[model],
        )
        self.installed_model_combo.clear()
        self.installed_model_combo.addItem(model)
        self.installed_models_row.setVisible(True)
        self._probe()

    def _pull_failed(self, exc: Exception) -> None:
        self.pull_button.setEnabled(True)
        self.cancel_pull_button.hide()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Failed")
        self.progress_label.setText(f"Download failed: {getattr(exc, 'user_message', str(exc))}")

    def _cancel_pull(self) -> None:
        if self._model_worker is None:
            return
        self.cancel_pull_button.setEnabled(False)
        self.progress_label.setText("Cancelling after the current download chunk…")
        self._model_worker.requestInterruption()

    def _pull_cancelled(self) -> None:
        self.pull_button.setEnabled(True)
        self.cancel_pull_button.setEnabled(True)
        self.cancel_pull_button.hide()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Cancelled")
        self.progress_label.setText("Download cancelled. You can retry when ready.")

    def _save_ollama_provider(self, model: str) -> None:
        repo = ProviderRepository(self.wizard.conn)
        for existing in repo.list():
            if existing.kind == ProviderKind.OLLAMA:
                existing.model = model
                repo.update(existing)
                repo.set_active(existing.id)
                return
        created = repo.create(
            ProviderConfig(name="Local Ollama", kind=ProviderKind.OLLAMA, model=model)
        )
        repo.set_active(created.id)

    def on_leave(self) -> bool:
        if self._provider_choice == "ollama":
            model = self.installed_model_combo.currentText().strip()
            if self._status.running and model:
                self._save_ollama_provider(model)
                return True
            self.status_label.setText(
                "Ollama is selected. Start Ollama and download or choose a model before continuing."
            )
            return False

        key = self.cloud_key.text().strip()
        if self._provider_choice == "cloud":
            if not key:
                self.cloud_status.setText("Enter the API key for the selected cloud provider.")
                self.cloud_status.setProperty("role", "error")
                return False
            preset_key = self.cloud_kind.currentData() or "openai"
            name, kind, preset_url = _CLOUD_PROVIDER_PRESETS[preset_key]
            model = self.cloud_model.text().strip()
            base_url = (
                self.cloud_base_url.text().strip() if preset_key == "compatible" else preset_url
            )
            if not model:
                self.cloud_status.setText("Enter the model ID provided by your cloud provider.")
                self.cloud_status.setProperty("role", "error")
                return False
            if preset_key == "compatible" and not base_url:
                self.cloud_status.setText(
                    "Enter the API base URL for this OpenAI-compatible provider."
                )
                self.cloud_status.setProperty("role", "error")
                return False
            repo = ProviderRepository(self.wizard.conn)
            created = repo.create(
                ProviderConfig(
                    name=name,
                    kind=kind,
                    base_url=base_url,
                    model=model,
                )
            )
            try:
                keystore.set_key(created.id, key)
            except Exception as exc:
                log.warning("Could not store key: %s", exc)
            if ProviderRepository(self.wizard.conn).get_active() is None:
                repo.set_active(created.id)
            self.cloud_key.clear()
        return True


class VoiceStep(_Step):
    title = "Voice practice"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.heading(
            "Practise answering out loud",
            "Optional. Speaking an answer is very different from typing one, and "
            "this is how you find that out before the real interview.",
        )
        self.card = Card("What this needs")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.card.body.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.install_button = QPushButton("Repair bundled voice")
        self.install_button.setProperty("accent", True)
        self.install_button.clicked.connect(self._repair)
        buttons.addWidget(self.install_button)
        buttons.addStretch(1)
        self.card.body.addLayout(buttons)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(150)
        self.output.setVisible(False)
        self.card.body.addWidget(self.output)
        self.layout_.addWidget(self.card)

        note = QLabel(
            "Recordings are transcribed by a model running on this computer. "
            "Audio is never uploaded — not to us, not to your AI provider."
        )
        note.setProperty("role", "caption")
        note.setWordWrap(True)
        self.layout_.addWidget(note)
        self.layout_.addStretch(1)

    def on_enter(self) -> None:
        input_ready, missing = env.feature_status("voice")
        kokoro = inspect_kokoro_runtime()
        has_model = env.whisper_model_present()
        palette = current()
        if kokoro.ready and input_ready and has_model:
            self.status_label.setText(
                f"<span style='color:{palette.success}'>Kokoro voice, microphone "
                "runtime, and speech-to-text are ready.</span>"
            )
            self.install_button.setVisible(False)
            return
        self.install_button.setVisible(not kokoro.ready or not input_ready or not has_model)
        self.install_button.setText("Verify / repair voice components")
        parts = []
        if not kokoro.ready:
            parts.append(kokoro.detail)
        if not input_ready:
            parts.append(
                "Packaged microphone/transcription components are missing: <code>"
                + "</code>, <code>".join(missing)
                + "</code>. Rerun the AptiorDesk installer to repair them."
            )
        if not has_model:
            parts.append(
                "The bundled speech-to-text model is missing. Rerun the AptiorDesk "
                "installer to repair it; no separate model download is required."
            )
        parts.append("You can skip this and type your answers instead.")
        self.status_label.setText("<br>".join(parts))

    def _repair(self) -> None:
        self.install_button.setEnabled(False)
        self.output.setVisible(True)
        self.output.clear()
        worker = Worker(lambda report: repair_kokoro_runtime(report), parent=self)
        worker.progress.connect(self._append)
        worker.result.connect(
            lambda message: (
                self._append("\n" + message),
                self.install_button.setEnabled(True),
                self.on_enter(),
            )
        )
        worker.error.connect(
            lambda exc: (
                self.install_button.setEnabled(True),
                self._append(f"\nFailed: {exc}\n"),
            )
        )
        worker.show_progress(
            "Repairing voice support",
            "Verifying packaged libraries and restoring trusted Kokoro model assets.",
        )
        worker.start()

    def _append(self, text: str) -> None:
        self.output.appendPlainText(text.rstrip())


class ProfileStep(_Step):
    title = "About you"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.heading(
            "Tell AptiorDesk who you are",
            "Just the basics for now — you can fill in the rest, or import a resume, "
            "any time from the Profile page.",
        )
        card = Card()
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Your full name")
        self.email_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("City, country")
        self.titles_edit = QLineEdit()
        self.titles_edit.setPlaceholderText("Comma-separated, e.g. Data Engineer")
        form.addRow("Name", self.name_edit)
        form.addRow("Email", self.email_edit)
        form.addRow("Location", self.location_edit)
        form.addRow("Roles you want", self.titles_edit)
        card.body.addLayout(form)
        self.layout_.addWidget(card)
        self.layout_.addStretch(1)

    def on_enter(self) -> None:
        profile = ProfileRepository(self.wizard.conn).get_default()
        self.name_edit.setText(profile.display_name)
        self.email_edit.setText(profile.contact.email)
        self.location_edit.setText(profile.contact.location)
        self.titles_edit.setText(", ".join(profile.preferences.target_titles))

    def on_leave(self) -> bool:
        repo = ProfileRepository(self.wizard.conn)
        profile: Profile = repo.get_default()
        profile.display_name = self.name_edit.text().strip()
        profile.contact.email = self.email_edit.text().strip()
        profile.contact.location = self.location_edit.text().strip()
        profile.preferences.target_titles = [
            part.strip() for part in self.titles_edit.text().split(",") if part.strip()
        ]
        repo.save(profile)
        return True


class SummaryStep(_Step):
    title = "Ready"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.heading("You are set up", "")
        self.card = Card()
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.card.body.addWidget(self.summary_label)
        self.layout_.addWidget(self.card)

        hint = QLabel(
            "You can re-run this setup at any time from Settings, and change "
            "anything it configured."
        )
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        self.layout_.addWidget(hint)
        self.layout_.addStretch(1)

    def on_enter(self) -> None:
        palette = current()
        provider = ProviderRepository(self.wizard.conn).get_active()
        profile = ProfileRepository(self.wizard.conn).get_default()
        voice_input_ready, _ = env.feature_status("voice")
        kokoro_ready = inspect_kokoro_runtime().ready

        def line(ok: bool, ready_text: str, todo_text: str) -> str:
            colour = palette.success if ok else palette.text_muted
            mark = "✓" if ok else "•"
            return f"<p style='color:{colour}'>{mark} {ready_text if ok else todo_text}</p>"

        rows = [
            line(
                provider is not None,
                f"AI provider: <b>{provider.name}</b>"
                + (
                    " — device CLI"
                    if provider and provider.kind == ProviderKind.CLI
                    else (
                        " — runs on this computer"
                        if provider and provider.is_local
                        else " — a cloud service"
                    )
                )
                if provider
                else "",
                "No AI provider yet — add one in Settings before generating anything.",
            ),
            line(
                bool(profile.display_name),
                f"Profile started for <b>{profile.display_name}</b>",
                "Profile is empty — fill it in from the Profile page.",
            ),
            line(
                kokoro_ready and voice_input_ready and env.whisper_model_present(),
                "Voice practice is ready",
                "Voice practice not installed — you can still type your answers.",
            ),
        ]
        rows.append(
            "<p style='margin-top:12px'>Next: add a resume, then paste a job "
            "description and let AptiorDesk compare them.</p>"
        )
        self.summary_label.setText("".join(rows))
