"""Interview voice preferences and an honest preview workflow."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai import keystore
from aptiordesk.features.interviews.voice.installer import repair_kokoro_runtime
from aptiordesk.features.interviews.voice.playback import SpeechPlayer
from aptiordesk.features.interviews.voice.settings import (
    ELEVENLABS_SECRET,
    KOKORO_VOICES,
    VoiceProvider,
    VoiceSettings,
    VoiceSettingsRepository,
)
from aptiordesk.features.interviews.voice.synthesis import kokoro_available
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.components.forms import FieldGrid, SectionCard
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

PREVIEW_TEXT = (
    "Welcome to your mock interview. Take a moment to settle in. "
    "When you are ready, tell me about a project you are proud of."
)


class VoiceSettingsPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._repository = VoiceSettingsRepository(conn)
        self._player = SpeechPlayer(self)
        self._install_worker: Worker | None = None
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
        outer.addWidget(
            PageHeader(
                "Interviewer voice",
                "Choose and preview how interview questions sound before practice.",
                eyebrow="SPEECH & DELIVERY",
            )
        )
        card = SectionCard(
            "Voice profile",
            "Kokoro is the default private neural voice. AptiorDesk never switches "
            "to an operating-system voice when initialization fails.",
            icon="mic",
        )
        self.provider_status = QLabel("")
        self.provider_status.setWordWrap(True)
        self.provider_status.setProperty("role", "hint")
        card.body.addWidget(self.provider_status)
        self.install_button = QPushButton("Repair Kokoro")
        self.install_button.setProperty("accent", True)
        self.install_button.clicked.connect(self._install_kokoro)
        self.install_button.hide()
        card.body.addWidget(self.install_button, alignment=Qt.AlignmentFlag.AlignLeft)

        fields = FieldGrid(columns=2)
        self.provider_combo = Dropdown()
        self.provider_combo.addItem("Kokoro — private local neural voice", VoiceProvider.KOKORO)
        self.provider_combo.addItem("ElevenLabs — cloud neural voice", VoiceProvider.ELEVENLABS)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        fields.add(
            "Voice provider",
            self.provider_combo,
            "Kokoro is included and runs privately on this device.",
        )

        self.voice_combo = Dropdown()
        self.voice_combo.setEditable(True)
        fields.add("Interviewer voice", self.voice_combo)

        self.accent_combo = Dropdown()
        self.accent_combo.addItem("Neutral / American English", "en-us")
        self.accent_combo.addItem("British English", "en-gb")
        fields.add("Accent", self.accent_combo)

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.75, 1.25)
        self.speed_spin.setSingleStep(0.02)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSuffix("×")
        fields.add("Speaking speed", self.speed_spin, "0.96× is calm and conversational.")

        self.expression_spin = QDoubleSpinBox()
        self.expression_spin.setRange(0.0, 1.0)
        self.expression_spin.setSingleStep(0.05)
        self.expression_spin.setDecimals(2)
        self.expression_cell = fields.add(
            "Cloud expressiveness",
            self.expression_spin,
            "Available when ElevenLabs exposes a style control.",
        )

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Stored in the operating-system keyring")
        self.api_key_cell = fields.add(
            "ElevenLabs API key",
            self.api_key_edit,
            "Stored securely in the operating-system credential manager.",
        )
        card.body.addWidget(fields)

        self.reduced_motion_check = QCheckBox(
            "Reduce idle head movement and disable listening nods"
        )
        options = QFrame()
        options.setProperty("role", "subtle")
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        options_layout.setSpacing(SPACE["sm"])
        options_layout.addWidget(self.reduced_motion_check)
        card.body.addWidget(options)

        actions = QHBoxLayout()
        self.preview_button = QPushButton("Preview voice")
        self.preview_button.clicked.connect(self._preview)
        self.save_button = QPushButton("Save voice settings")
        self.save_button.setProperty("accent", True)
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "hint")
        card.body.addWidget(self.status)
        outer.addWidget(card)
        outer.addStretch(1)
        scroll.setWidget(content)
        shell.addWidget(scroll)

        self._player.started.connect(
            lambda label: self._set_status(f"Playing preview with {label}.", "success")
        )
        self._player.finished.connect(lambda: self.preview_button.setEnabled(True))
        self._player.failed.connect(self._preview_failed)
        self._load()

    def _load(self) -> None:
        settings = self._repository.load()
        provider_index = self.provider_combo.findData(settings.provider)
        self.provider_combo.setCurrentIndex(max(0, provider_index))
        self._provider_changed()
        self.voice_combo.setCurrentText(settings.voice)
        accent_index = self.accent_combo.findData(settings.accent)
        self.accent_combo.setCurrentIndex(max(0, accent_index))
        self.speed_spin.setValue(settings.speed)
        self.expression_spin.setValue(settings.expressiveness)
        self.reduced_motion_check.setChecked(settings.reduced_motion)

    def _settings(self) -> VoiceSettings:
        provider = self.provider_combo.currentData()
        voice = (
            self.voice_combo.currentData()
            if provider == VoiceProvider.KOKORO
            else self.voice_combo.currentText().strip()
        )
        return VoiceSettings(
            provider=provider,
            voice=voice or "af_heart",
            accent=self.accent_combo.currentData(),
            speed=self.speed_spin.value(),
            pitch=0.0,
            expressiveness=self.expression_spin.value(),
            allow_fallback=False,
            reduced_motion=self.reduced_motion_check.isChecked(),
        )

    def _save(self) -> None:
        settings = self._settings()
        self._repository.save(settings)
        if self.api_key_edit.text():
            try:
                keystore.set_secret(ELEVENLABS_SECRET, self.api_key_edit.text())
            except Exception as exc:
                self._set_status(str(exc), "error")
                return
            finally:
                self.api_key_edit.clear()
        self._set_status("Voice preferences saved locally.", "success")

    def _preview(self) -> None:
        settings = self._settings()
        # Previewing a voice is an explicit selection; persist it so the mock
        # interview does not unexpectedly keep using an older provider.
        self._repository.save(settings)
        self.preview_button.setEnabled(False)
        self._set_status("Preparing voice preview…", "hint")
        self._player.speak(PREVIEW_TEXT, settings)

    def _preview_failed(self, message: str) -> None:
        self.preview_button.setEnabled(True)
        self._set_status(message, "error")

    def _provider_changed(self) -> None:
        provider = self.provider_combo.currentData()
        current_voice = self.voice_combo.currentData() or self.voice_combo.currentText()
        self.voice_combo.clear()
        if provider == VoiceProvider.KOKORO:
            for voice_id, label in KOKORO_VOICES.items():
                self.voice_combo.addItem(label, voice_id)
            self.voice_combo.setEditable(False)
            if current_voice in KOKORO_VOICES:
                self.voice_combo.setCurrentIndex(self.voice_combo.findData(current_voice))
        elif provider == VoiceProvider.ELEVENLABS:
            self.voice_combo.setEditable(True)
            self.voice_combo.setPlaceholderText("Enter an ElevenLabs voice ID")
            self.voice_combo.setCurrentText(
                current_voice if current_voice not in KOKORO_VOICES else ""
            )
        is_cloud = provider == VoiceProvider.ELEVENLABS
        self.api_key_cell.setVisible(is_cloud)
        self.expression_cell.setVisible(is_cloud)
        if provider == VoiceProvider.KOKORO:
            available = kokoro_available()
            self.install_button.setVisible(not available)
            self.provider_status.setText(
                "Bundled and ready · private Kokoro neural voice is running locally."
                if available
                else "Kokoro is unavailable. Repair the bundled neural voice "
                "components, then preview it before starting an interview."
            )
            self.provider_status.setProperty("role", "success" if available else "warning")
        elif provider == VoiceProvider.ELEVENLABS:
            self.install_button.hide()
            self.provider_status.setText(
                "Cloud provider · an API key and internet connection are required."
            )
            self.provider_status.setProperty("role", "hint")
        self.provider_status.style().unpolish(self.provider_status)
        self.provider_status.style().polish(self.provider_status)

    def _install_kokoro(self) -> None:
        if self._install_worker is not None:
            return
        answer = QMessageBox.question(
            self,
            "Repair Kokoro neural voice?",
            "AptiorDesk will verify its bundled runtime and restore verified model "
            "assets to your writable AptiorDesk data folder. It will not install "
            "Python packages or modify the application.\n\nContinue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.install_button.setEnabled(False)
        self._set_status("Starting Kokoro repair...", "hint")
        worker = Worker(
            lambda report: repair_kokoro_runtime(report),
            parent=self,
        )
        worker.progress.connect(lambda message: self._set_status(str(message), "hint"))
        worker.result.connect(self._kokoro_installed)
        worker.error.connect(self._kokoro_install_failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_install_worker", None) if self._install_worker is worker else None
            )
        )
        worker.show_progress(
            "Repairing Kokoro",
            "Verifying the packaged runtime and restoring trusted voice assets.",
        )
        self._install_worker = worker
        worker.start()

    def _kokoro_installed(self, message: str) -> None:
        self.install_button.setEnabled(True)
        self._provider_changed()
        self._set_status(f"{message} You can preview the voice now.", "success")

    def _kokoro_install_failed(self, exc: Exception) -> None:
        self.install_button.setEnabled(True)
        self.install_button.show()
        self._set_status(str(exc), "error")

    def _set_status(self, text: str, role: str) -> None:
        self.status.setText(text)
        self.status.setProperty("role", role)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
