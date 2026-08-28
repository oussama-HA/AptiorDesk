"""Settings: AI provider management (BYOK).

API keys go straight to the OS keyring; the database stores configuration
only. "Test connection" and "Fetch models" run on a background worker so the
UI never blocks on network calls.
"""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai import keystore
from aptiordesk.ai.base import HealthStatus
from aptiordesk.ai.providers.cli import adapter_display_name, detect_cli_executable
from aptiordesk.ai.registry import build_provider
from aptiordesk.database.models.provider import (
    DEFAULT_BASE_URLS,
    KEYLESS_KINDS,
    CLIAdapterKind,
    ProviderConfig,
    ProviderKind,
)
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.interviews.voice.panel import VoiceSettingsPanel
from aptiordesk.features.jobs.browser_extension_panel import BrowserExtensionPanel
from aptiordesk.features.settings.system_setup import SystemSetupPanel
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.components.forms import FlowLayout, SectionCard
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

_KIND_LABELS = {
    ProviderKind.OLLAMA: "Ollama (local)",
    ProviderKind.OPENAI_COMPAT: "OpenAI-compatible (OpenAI, LM Studio, OpenRouter, Groq, …)",
    ProviderKind.ANTHROPIC: "Anthropic",
    ProviderKind.GEMINI: "Google Gemini",
    ProviderKind.CLI: "Device AI CLI (Codex, Claude Code, or Gemini)",
}


class SettingsPage(QWidget):
    """AI-provider settings and browser-extension installation."""

    provider_changed = Signal()

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._repo = ProviderRepository(conn)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        shell.addWidget(self.tabs)

        providers = QWidget()
        providers.setProperty("role", "layoutOnly")
        self.tabs.addTab(providers, "AI providers")
        self.tabs.addTab(VoiceSettingsPanel(conn), "Interview voice")
        self.tabs.addTab(BrowserExtensionPanel(conn), "Browser extension")
        self.system_setup_panel = SystemSetupPanel(conn)
        self.tabs.addTab(self.system_setup_panel, "System setup")
        self.system_setup_panel.configure_ai_requested.connect(lambda: self.tabs.setCurrentIndex(0))
        self.system_setup_panel.configure_voice_requested.connect(
            lambda: self.tabs.setCurrentIndex(1)
        )
        self.system_setup_panel.configure_extension_requested.connect(
            lambda: self.tabs.setCurrentIndex(2)
        )
        self.tabs.currentChanged.connect(self._settings_tab_changed)

        providers_shell = QVBoxLayout(providers)
        providers_shell.setContentsMargins(0, SPACE["lg"], 0, 0)
        providers_shell.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "AI providers",
            "Choose the model that powers AptiorDesk and handle everyday actions "
            "without opening advanced configuration.",
            eyebrow="MODEL ROUTING",
        )
        add = QPushButton("Add provider")
        add.setProperty("accent", True)
        add.clicked.connect(self._add)
        self.header.actions.addWidget(add)
        providers_shell.addWidget(self.header)

        provider_scroll = QScrollArea()
        provider_scroll.setObjectName("settingsProviderScroll")
        provider_scroll.setWidgetResizable(True)
        provider_scroll.setFrameShape(QFrame.Shape.NoFrame)
        provider_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        provider_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        provider_content = QWidget()
        provider_content.setProperty("role", "layoutOnly")
        layout = QVBoxLayout(provider_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        provider_scroll.setWidget(provider_content)
        self.provider_scroll = provider_scroll

        quick_setup = SectionCard(
            "Quick connections",
            "Start with the connection you already use. Endpoints, credentials, "
            "timeouts, and generation limits remain available under Advanced settings.",
        )
        quick_setup.setMinimumHeight(248)
        choices = QHBoxLayout()
        choices.setSpacing(SPACE["md"])
        self.local_choice = self._connection_choice(
            "Local model",
            "Private Ollama models running on this computer.",
            "Add Ollama",
            lambda: self._add_kind(ProviderKind.OLLAMA),
        )
        self.cli_choice = self._connection_choice(
            "Device AI CLI",
            "Use Codex, Claude Code, or Gemini with its existing login.",
            "Connect CLI",
            lambda: self._add_kind(ProviderKind.CLI),
        )
        self.cloud_choice = self._connection_choice(
            "Cloud API",
            "Connect OpenAI-compatible, Anthropic, Gemini, or another endpoint.",
            "Connect API",
            lambda: self._add_kind(ProviderKind.OPENAI_COMPAT),
        )
        for choice in (self.local_choice, self.cli_choice, self.cloud_choice):
            choices.addWidget(choice, 1)
        quick_setup.body.addLayout(choices)

        if not keystore.available():
            warning = QLabel(
                "No secure credential store was found. Cloud API keys "
                "cannot be saved; local Ollama still works."
            )
            warning.setProperty("role", "error")
            warning.setWordWrap(True)
            quick_setup.body.addWidget(warning)
        layout.addWidget(quick_setup)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(SPACE["md"])
        workspace.setMinimumHeight(500)
        self.provider_workspace = workspace

        configured = SectionCard(
            "Configured providers",
            "Select a provider to manage it or double-click for advanced settings.",
        )
        configured.setMinimumHeight(500)
        self.provider_list = QListWidget()
        self.provider_list.setObjectName("contentList")
        self.provider_list.setMinimumWidth(300)
        self.provider_list.setMinimumHeight(330)
        self.provider_list.currentItemChanged.connect(lambda *_: self._render_selected())
        self.provider_list.itemDoubleClicked.connect(lambda _: self._edit_selected())
        configured.body.addWidget(self.provider_list, 1)
        workspace.addWidget(configured)

        details = SectionCard(
            "Selected provider",
            "The active provider powers tailoring, cover letters, fit analysis, "
            "and interview coaching.",
        )
        details.setMinimumHeight(500)
        self.detail_heading = QLabel("Select a provider")
        self.detail_heading.setProperty("role", "paneTitle")
        details.body.addWidget(self.detail_heading)
        self.detail_status = QLabel("No provider selected")
        self.detail_status.setProperty("role", "badge")
        self.detail_status.setProperty("tone", "neutral")
        details.body.addWidget(self.detail_status, alignment=Qt.AlignmentFlag.AlignLeft)
        self.detail_summary = QLabel("")
        self.detail_summary.setWordWrap(True)
        self.detail_summary.setProperty("role", "hint")
        details.body.addWidget(self.detail_summary)

        model_card = QFrame()
        model_card.setProperty("role", "subtle")
        model_card_layout = QVBoxLayout(model_card)
        model_card_layout.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        model_card_layout.setSpacing(SPACE["sm"])
        model_label = QLabel("Model used by AptiorDesk")
        model_label.setProperty("role", "fieldLabel")
        model_card_layout.addWidget(model_label)
        model_row = QHBoxLayout()
        self.quick_model_combo = Dropdown()
        self.quick_model_combo.setEditable(True)
        self.quick_model_combo.setPlaceholderText("Choose or enter a model")
        self.save_model_button = QPushButton("Use model")
        self.save_model_button.clicked.connect(self._save_quick_model)
        model_row.addWidget(self.quick_model_combo, 1)
        model_row.addWidget(self.save_model_button)
        model_card_layout.addLayout(model_row)
        details.body.addWidget(model_card)

        self.advanced_summary = QLabel("")
        self.advanced_summary.setWordWrap(True)
        self.advanced_summary.setProperty("role", "caption")
        details.body.addWidget(self.advanced_summary)

        action_host = QWidget()
        action_host.setProperty("role", "layoutOnly")
        actions = FlowLayout(action_host, spacing=SPACE["sm"])
        self.activate_button = QPushButton("Set active")
        self.activate_button.setProperty("accent", True)
        self.activate_button.clicked.connect(self._activate_selected)
        self.test_selected_button = QPushButton("Test connection")
        self.test_selected_button.clicked.connect(self._test_selected)
        self.refresh_models_button = QPushButton("Refresh models")
        self.refresh_models_button.clicked.connect(self._refresh_selected_models)
        self.advanced_button = QPushButton("Advanced settings")
        self.advanced_button.clicked.connect(self._edit_selected)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setProperty("variant", "danger")
        self.remove_button.clicked.connect(self._remove_selected)
        for button in (
            self.activate_button,
            self.test_selected_button,
            self.refresh_models_button,
            self.advanced_button,
            self.remove_button,
        ):
            actions.addWidget(button)
        details.body.addWidget(action_host)
        self.quick_status = QLabel("")
        self.quick_status.setWordWrap(True)
        self.quick_status.setProperty("role", "hint")
        details.body.addWidget(self.quick_status)
        details.body.addStretch(1)
        workspace.addWidget(details)
        workspace.setSizes([390, 760])
        layout.addWidget(workspace, 1)
        providers_shell.addWidget(provider_scroll, 1)

        footer = QFrame()
        footer.setProperty("role", "actionBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        footer_layout.setSpacing(SPACE["sm"])
        privacy = QLabel("Cloud keys stay in the operating-system credential manager.")
        privacy.setProperty("role", "hint")
        footer_layout.addWidget(privacy)
        footer_layout.addStretch(1)
        setup = QPushButton("Run setup again…")
        setup.setProperty("variant", "ghost")
        setup.setToolTip(
            "Re-open the first-run setup: check for a local model, download one, "
            "install voice support, and review your basics."
        )
        setup.clicked.connect(self._run_setup)
        footer_layout.addWidget(setup)
        providers_shell.addWidget(footer)

        self._reload()

    def _settings_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.system_setup_panel:
            self.system_setup_panel.run_checks()

    def _connection_choice(
        self,
        title: str,
        description: str,
        button_text: str,
        callback,
    ) -> QFrame:
        card = QFrame()
        card.setProperty("role", "subtle")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card.setMinimumWidth(220)
        card.setMinimumHeight(146)
        box = QVBoxLayout(card)
        box.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        box.setSpacing(SPACE["sm"])
        heading = QLabel(title)
        heading.setProperty("role", "sectionTitle")
        box.addWidget(heading)
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setProperty("role", "hint")
        box.addWidget(detail, 1)
        button = QPushButton(button_text)
        button.clicked.connect(callback)
        box.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        return card

    def _reload(self, selected_id: int | None = None) -> None:
        if selected_id is None:
            selected = self._selected()
            selected_id = selected.id if selected else None
        self.provider_list.clear()
        selected_row = -1
        active_row = -1
        for config in self._repo.list():
            marker = "Active" if config.is_active else "Available"
            detail = config.model or "no model set"
            if config.kind == ProviderKind.CLI:
                detail = adapter_display_name(config.cli_adapter)
                if config.model:
                    detail += f" · {config.model}"
            entry = QListWidgetItem(f"{config.name or config.kind.value}\n{marker} · {detail}")
            entry.setData(Qt.ItemDataRole.UserRole, config)
            self.provider_list.addItem(entry)
            row = self.provider_list.count() - 1
            if config.id == selected_id:
                selected_row = row
            if config.is_active:
                active_row = row
        if self.provider_list.count():
            self.provider_list.setCurrentRow(
                selected_row if selected_row >= 0 else max(0, active_row)
            )
        else:
            self._render_selected()

    def _run_setup(self) -> None:
        """Delegate to the window so one code path owns the wizard."""
        window = self.window()
        if hasattr(window, "run_setup_again"):
            window.run_setup_again()

    def _selected(self) -> ProviderConfig | None:
        item = self.provider_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _render_selected(self) -> None:
        config = self._selected()
        available = config is not None
        for button in (
            self.activate_button,
            self.test_selected_button,
            self.refresh_models_button,
            self.advanced_button,
            self.remove_button,
            self.save_model_button,
        ):
            button.setEnabled(available)
        if config is None:
            self.detail_heading.setText("Select a provider")
            self.detail_status.setText("No provider selected")
            self.detail_status.setProperty("tone", "neutral")
            self.detail_summary.setText(
                "Choose a configured provider, or use a quick connection above."
            )
            self.advanced_summary.clear()
            self.quick_model_combo.clear()
            self.quick_status.clear()
            self._polish_detail_status()
            return

        self.detail_heading.setText(config.name or _KIND_LABELS[config.kind])
        self.detail_status.setText("Active provider" if config.is_active else "Ready to activate")
        self.detail_status.setProperty("tone", "success" if config.is_active else "neutral")
        if config.kind == ProviderKind.CLI:
            route = (
                f"Runs through {adapter_display_name(config.cli_adapter)} on this "
                "device. That CLI may send prompts to its configured cloud service."
            )
            endpoint = config.cli_executable or "Auto-detect from PATH"
        elif config.is_local:
            route = "Private local connection. Prompts remain on this computer."
            endpoint = config.effective_base_url()
        else:
            route = "Cloud connection. Prompts are sent to the configured provider."
            endpoint = config.effective_base_url()
        self.detail_summary.setText(f"{_KIND_LABELS[config.kind]}\n{route}")
        self.quick_model_combo.clear()
        self.quick_model_combo.setCurrentText(config.model)
        self.quick_model_combo.setPlaceholderText(
            "CLI default model" if config.kind == ProviderKind.CLI else "Choose or enter a model"
        )
        self.advanced_summary.setText(
            f"Connection: {endpoint}\n"
            f"Temperature: {config.temperature:g} · Max output: "
            f"{config.max_tokens:,} tokens · Timeout: {config.timeout_s}s"
        )
        self.activate_button.setEnabled(not config.is_active)
        self.refresh_models_button.setEnabled(config.kind != ProviderKind.CLI)
        self.quick_status.clear()
        self._polish_detail_status()

    def _polish_detail_status(self) -> None:
        self.detail_status.style().unpolish(self.detail_status)
        self.detail_status.style().polish(self.detail_status)

    def _set_quick_status(self, text: str, role: str = "hint") -> None:
        self.quick_status.setText(text)
        self.quick_status.setProperty("role", role)
        self.quick_status.style().unpolish(self.quick_status)
        self.quick_status.style().polish(self.quick_status)

    def _add_kind(self, kind: ProviderKind) -> None:
        dialog = ProviderDialog(config=None, parent=self)
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(kind))
        names = {
            ProviderKind.OLLAMA: "Local Ollama",
            ProviderKind.CLI: "Device AI CLI",
            ProviderKind.OPENAI_COMPAT: "Cloud AI",
        }
        dialog.name_edit.setText(names.get(kind, _KIND_LABELS[kind]))
        self._save_new_dialog(dialog)

    def _add(self) -> None:
        dialog = ProviderDialog(config=None, parent=self)
        self._save_new_dialog(dialog)

    def _save_new_dialog(self, dialog: ProviderDialog) -> None:
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.result_config()
            config = self._repo.create(config)
            dialog.store_key_if_entered(config.id)
            if len(self._repo.list()) == 1:
                self._repo.set_active(config.id)
            self._reload(config.id)
            self.provider_changed.emit()

    def _edit_selected(self) -> None:
        config = self._selected()
        if config is None:
            return
        dialog = ProviderDialog(config=config, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.result_config()
            updated.id = config.id
            self._repo.update(updated)
            dialog.store_key_if_entered(config.id)
            self._reload(config.id)
            self.provider_changed.emit()

    def _remove_selected(self) -> None:
        config = self._selected()
        if config is None:
            return
        credential_note = (
            "configuration?"
            if config.kind in KEYLESS_KINDS
            else "configuration and its stored API key?"
        )
        confirm = QMessageBox.question(
            self, "Remove provider", f"Remove “{config.name}” {credential_note}"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            keystore.delete_key(config.id)
            self._repo.delete(config.id)
            self._reload()
            self.provider_changed.emit()

    def _activate_selected(self) -> None:
        config = self._selected()
        if config is not None:
            self._repo.set_active(config.id)
            self._reload(config.id)
            self.provider_changed.emit()

    def _save_quick_model(self) -> None:
        config = self._selected()
        if config is None:
            return
        config.model = self.quick_model_combo.currentText().strip()
        self._repo.update(config)
        self._reload(config.id)
        self._set_quick_status("Model preference saved.", "success")
        self.provider_changed.emit()

    def _saved_provider(self, config: ProviderConfig):
        api_key = None if config.kind in KEYLESS_KINDS else keystore.get_key(config.id)
        return build_provider(config, api_key)

    def _test_selected(self) -> None:
        config = self._selected()
        if config is None:
            return
        try:
            provider = self._saved_provider(config)
        except Exception as exc:
            self._set_quick_status(getattr(exc, "user_message", str(exc)), "error")
            return
        self.test_selected_button.setEnabled(False)
        self._set_quick_status("Testing connection…")
        worker = Worker(lambda: provider.health_check(), parent=self)
        worker.result.connect(self._selected_health_ready)
        worker.error.connect(
            lambda exc: self._set_quick_status(getattr(exc, "user_message", str(exc)), "error")
        )
        worker.finished.connect(lambda: self.test_selected_button.setEnabled(True))
        worker.show_progress(
            "Testing AI provider",
            f"Checking {config.name or config.kind.value} without blocking settings.",
        )
        worker.start()

    def _selected_health_ready(self, status: HealthStatus) -> None:
        self._set_quick_status(
            status.message if status.ok else f"Connection failed: {status.message}",
            "success" if status.ok else "error",
        )

    def _refresh_selected_models(self) -> None:
        config = self._selected()
        if config is None:
            return
        try:
            provider = self._saved_provider(config)
        except Exception as exc:
            self._set_quick_status(getattr(exc, "user_message", str(exc)), "error")
            return
        self.refresh_models_button.setEnabled(False)
        self._set_quick_status("Loading available models…")
        worker = Worker(lambda: provider.list_models(), parent=self)
        worker.result.connect(self._selected_models_ready)
        worker.error.connect(
            lambda exc: self._set_quick_status(getattr(exc, "user_message", str(exc)), "error")
        )
        worker.finished.connect(lambda: self.refresh_models_button.setEnabled(True))
        worker.show_progress(
            "Refreshing models",
            f"Requesting the current model catalog from {config.name}.",
        )
        worker.start()

    def _selected_models_ready(self, models: list[str]) -> None:
        current = self.quick_model_combo.currentText()
        self.quick_model_combo.clear()
        self.quick_model_combo.addItems(models)
        self.quick_model_combo.setCurrentText(current or (models[0] if models else ""))
        self._set_quick_status(
            f"{len(models)} model{'s' if len(models) != 1 else ''} available. "
            "Choose one and select Use model.",
            "success",
        )


class ProviderDialog(QDialog):
    def __init__(self, config: ProviderConfig | None, parent=None):
        super().__init__(parent)
        self._existing_id = config.id if config else None
        self.setWindowTitle("AI Provider" if config else "Add AI Provider")
        self.setMinimumWidth(640)
        self.resize(700, 580)
        config = config or ProviderConfig(name="Local Ollama")

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Connection contains the fields most people need. Advanced controls "
            "request behavior and output limits."
        )
        intro.setProperty("role", "hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        editor_tabs = QTabWidget()
        connection_page = QWidget()
        form = QFormLayout(connection_page)
        form.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])
        advanced_page = QWidget()
        advanced_form = QFormLayout(advanced_page)
        advanced_form.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        advanced_form.setHorizontalSpacing(SPACE["lg"])
        advanced_form.setVerticalSpacing(SPACE["md"])
        editor_tabs.addTab(connection_page, "Connection")
        editor_tabs.addTab(advanced_page, "Advanced")
        layout.addWidget(editor_tabs, 1)

        self.name_edit = QLineEdit(config.name)
        form.addRow("Name", self.name_edit)

        self.kind_combo = Dropdown()
        for kind in ProviderKind:
            self.kind_combo.addItem(_KIND_LABELS[kind], kind)
        self.kind_combo.setCurrentIndex(list(ProviderKind).index(config.kind))
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Provider type", self.kind_combo)

        self.base_url_edit = QLineEdit(config.base_url)
        form.addRow("Base URL", self.base_url_edit)

        self.cli_adapter_combo = Dropdown()
        for adapter in CLIAdapterKind:
            self.cli_adapter_combo.addItem(adapter_display_name(adapter), adapter)
        self.cli_adapter_combo.setCurrentIndex(list(CLIAdapterKind).index(config.cli_adapter))
        self.cli_adapter_combo.currentIndexChanged.connect(self._cli_adapter_changed)
        form.addRow("CLI adapter", self.cli_adapter_combo)

        self.cli_executable_row = QWidget()
        executable_layout = QHBoxLayout(self.cli_executable_row)
        executable_layout.setContentsMargins(0, 0, 0, 0)
        executable_layout.setSpacing(SPACE["sm"])
        self.cli_executable_edit = QLineEdit(config.cli_executable)
        self.cli_executable_edit.setPlaceholderText("Auto-detect from PATH")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_cli)
        detect = QPushButton("Detect")
        detect.clicked.connect(lambda: self._detect_cli())
        executable_layout.addWidget(self.cli_executable_edit, 1)
        executable_layout.addWidget(browse)
        executable_layout.addWidget(detect)
        form.addRow("Executable", self.cli_executable_row)

        self.cli_help = QLabel(
            "The CLI keeps its own login. AptiorDesk sends prompts through stdin in an "
            "isolated temporary folder; the CLI may still send that content to its "
            "configured AI service."
        )
        self.cli_help.setWordWrap(True)
        self.cli_help.setProperty("role", "hint")
        form.addRow("", self.cli_help)

        model_row = QHBoxLayout()
        self.model_combo = Dropdown()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(config.model)
        self.fetch_models_button = QPushButton("Fetch models")
        self.fetch_models_button.clicked.connect(self._fetch_models)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.fetch_models_button)
        form.addRow("Model", model_row)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(
            "Unchanged if left blank" if self._existing_id else "Stored in the OS keyring"
        )
        form.addRow("API key", self.api_key_edit)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(config.temperature)
        self.temperature_spin.setToolTip(
            "Lower values are more consistent; higher values increase variation."
        )
        advanced_form.addRow("Temperature", self.temperature_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(64, 200_000)
        self.max_tokens_spin.setValue(config.max_tokens)
        self.max_tokens_spin.setToolTip("Maximum output length requested from the provider.")
        advanced_form.addRow("Maximum output", self.max_tokens_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setValue(config.timeout_s)
        self.timeout_spin.setToolTip(
            "Standard request deadline. Complex operations such as resume tailoring "
            "automatically receive at least five minutes."
        )
        advanced_form.addRow("Request timeout", self.timeout_spin)
        advanced_note = QLabel(
            "AptiorDesk automatically extends the deadline for long operations such "
            "as resume tailoring. These values are defaults for normal requests."
        )
        advanced_note.setWordWrap(True)
        advanced_note.setProperty("role", "hint")
        advanced_form.addRow("", advanced_note)

        self._base_url_label = form.labelForField(self.base_url_edit)
        self._cli_adapter_label = form.labelForField(self.cli_adapter_combo)
        self._cli_executable_label = form.labelForField(self.cli_executable_row)
        self._api_key_label = form.labelForField(self.api_key_edit)
        self._temperature_label = advanced_form.labelForField(self.temperature_spin)
        self._max_tokens_label = advanced_form.labelForField(self.max_tokens_spin)

        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._test_connection)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.test_result, 1)
        layout.addLayout(test_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._kind_changed()

    # -- helpers -------------------------------------------------------------

    def _current_kind(self) -> ProviderKind:
        return self.kind_combo.currentData()

    def _kind_changed(self) -> None:
        kind = self._current_kind()
        is_cli = kind == ProviderKind.CLI
        default_url = DEFAULT_BASE_URLS[kind]
        self.base_url_edit.setPlaceholderText(f"Default: {default_url}" if default_url else "")
        self.api_key_edit.setEnabled(kind not in KEYLESS_KINDS)
        for widget in (
            self.base_url_edit,
            self._base_url_label,
            self.api_key_edit,
            self._api_key_label,
        ):
            widget.setVisible(not is_cli)
        for widget in (
            self.cli_adapter_combo,
            self._cli_adapter_label,
            self.cli_executable_row,
            self._cli_executable_label,
            self.cli_help,
        ):
            widget.setVisible(is_cli)
        self.fetch_models_button.setVisible(not is_cli)
        for widget in (
            self.temperature_spin,
            self._temperature_label,
            self.max_tokens_spin,
            self._max_tokens_label,
        ):
            widget.setVisible(not is_cli)
        self.model_combo.setPlaceholderText(
            "Optional — use the CLI default" if is_cli else "Provider model name"
        )
        if is_cli and not self.cli_executable_edit.text().strip():
            self._detect_cli(quiet=True)

    def _current_cli_adapter(self) -> CLIAdapterKind:
        return self.cli_adapter_combo.currentData()

    def _cli_adapter_changed(self) -> None:
        if self._current_kind() == ProviderKind.CLI:
            self.cli_executable_edit.clear()
            self._detect_cli(quiet=True)

    def _browse_cli(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select AI CLI executable",
            "",
            "Executables (*.exe *.cmd *.bat);;All files (*)",
        )
        if path:
            self.cli_executable_edit.setText(path)

    def _detect_cli(self, *, quiet: bool = False) -> None:
        path = detect_cli_executable(self._current_cli_adapter())
        if path:
            self.cli_executable_edit.setText(path)
            if not quiet:
                self.test_result.setText(f"✓ Found {path}")
                self.test_result.setProperty("role", "success")
                self._polish_result()
        elif not quiet:
            self.test_result.setText(
                "Could not find this CLI on PATH. Install it or choose the executable."
            )
            self.test_result.setProperty("role", "error")
            self._polish_result()

    def result_config(self) -> ProviderConfig:
        return ProviderConfig(
            name=self.name_edit.text().strip() or self._current_kind().value,
            kind=self._current_kind(),
            base_url=self.base_url_edit.text().strip(),
            model=self.model_combo.currentText().strip(),
            temperature=self.temperature_spin.value(),
            max_tokens=self.max_tokens_spin.value(),
            timeout_s=self.timeout_spin.value(),
            cli_adapter=self._current_cli_adapter(),
            cli_executable=self.cli_executable_edit.text().strip(),
        )

    def store_key_if_entered(self, provider_id: int) -> None:
        key = self.api_key_edit.text()
        if not key:
            return
        try:
            keystore.set_key(provider_id, key)
        except Exception as exc:
            QMessageBox.warning(self, "API key not saved", getattr(exc, "user_message", str(exc)))
        finally:
            self.api_key_edit.clear()

    def _build_probe_provider(self):
        config = self.result_config()
        config.id = self._existing_id
        api_key = self.api_key_edit.text() or None
        if api_key is None and self._existing_id is not None and config.kind not in KEYLESS_KINDS:
            api_key = keystore.get_key(self._existing_id)
        return build_provider(config, api_key)

    def _test_connection(self) -> None:
        self._probe("Testing…", lambda p: p.health_check(), self._show_health)

    def _fetch_models(self) -> None:
        self._probe("Fetching models…", lambda p: p.list_models(), self._show_models)

    def _probe(self, busy_text, fn, on_result) -> None:
        try:
            provider = self._build_probe_provider()
        except Exception as exc:
            self._show_error(exc)
            return
        self.test_button.setEnabled(False)
        self.test_result.setText(busy_text)
        self.test_result.setProperty("role", "hint")
        self._polish_result()
        worker = Worker(lambda: fn(provider), parent=self)
        worker.result.connect(on_result)
        worker.error.connect(self._show_error)
        worker.finished.connect(lambda: self.test_button.setEnabled(True))
        worker.show_progress(
            busy_text.rstrip("…"),
            f"Contacting {provider.config.name or provider.config.kind.value}. "
            "This may take a moment if the model is starting up.",
        )
        worker.start()

    def _show_health(self, status: HealthStatus) -> None:
        if status.ok:
            if self._current_kind() == ProviderKind.CLI:
                self.test_result.setText(f"✓ {status.message}")
            else:
                count = len(status.models)
                self.test_result.setText(f"✓ Connected — {count} model(s) available")
            self.test_result.setProperty("role", "success")
        else:
            self.test_result.setText(f"✗ {status.message}")
            self.test_result.setProperty("role", "error")
        self._polish_result()

    def _show_models(self, models: list[str]) -> None:
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(current or (models[0] if models else ""))
        self.test_result.setText(f"✓ {len(models)} model(s) loaded into the dropdown")
        self.test_result.setProperty("role", "success")
        self._polish_result()

    def _show_error(self, exc: Exception) -> None:
        self.test_result.setText(f"✗ {getattr(exc, 'user_message', str(exc))}")
        self.test_result.setProperty("role", "error")
        self._polish_result()

    def _polish_result(self) -> None:
        style = self.test_result.style()
        style.unpolish(self.test_result)
        style.polish(self.test_result)
