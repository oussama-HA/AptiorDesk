"""Interview practice: prepare questions, run a mock interview (typed or
spoken), get structured feedback, and keep an answer library."""

from __future__ import annotations

import html
import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ai import keystore
from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.models.interview import (
    PERSONAS,
    STAGES,
    InterviewQuestion,
    SessionReport,
)
from aptiordesk.database.repositories.interview_repo import InterviewRepository
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.database.repositories.settings_repo import SettingsRepository
from aptiordesk.features.interviews.avatar import (
    DEFAULT_AVATAR_ID,
    AvatarController,
    AvatarPickerDialog,
    AvatarStage,
    AvatarState,
    avatar_catalog,
    get_avatar,
    prepare_avatar,
)
from aptiordesk.features.interviews.camera import CandidateCameraTile
from aptiordesk.features.interviews.service import InterviewService
from aptiordesk.features.interviews.voice import recorder as recorder_module
from aptiordesk.features.interviews.voice import transcriber as transcriber_module
from aptiordesk.features.interviews.voice.installer import repair_kokoro_runtime
from aptiordesk.features.interviews.voice.panel import VoiceSettingsPanel
from aptiordesk.features.interviews.voice.playback import SpeechPlayer
from aptiordesk.features.interviews.voice.settings import (
    ELEVENLABS_SECRET,
    KOKORO_VOICES,
    VoiceProvider,
    VoiceSettings,
    VoiceSettingsRepository,
)
from aptiordesk.features.interviews.voice.synthesis import prepare_voice
from aptiordesk.ui.components.common import PageHeader
from aptiordesk.ui.components.dropdown import Dropdown
from aptiordesk.ui.components.forms import FieldGrid, FlowLayout, SectionCard
from aptiordesk.ui.components.level_meter import LevelMeter
from aptiordesk.ui.components.rich_text import rich_document
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

_WELCOME_MESSAGE = (
    "Welcome to your AptiorDesk mock interview. I’ll give you a moment while "
    "your camera and microphone are prepared. When I finish speaking, you can "
    "answer by typing or using the microphone. Let’s begin."
)

_CLOSING_MESSAGE = (
    "Thank you for completing your mock interview. You have taken an important "
    "step forward, and you should be proud of the work you put in. Your "
    "interview report is being generated now."
)


class _ResponsiveQuestionLabel(QLabel):
    """Fit an interview question to its tile without truncating its text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fitting = False
        self._last_size = 0.0
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumHeight(112)
        self.setAccessibleName("Current interview question")

    def setText(self, text: str) -> None:
        super().setText(text)
        QTimer.singleShot(0, self._fit_text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self) -> None:
        if self._fitting or not self.text() or self.width() < 40 or self.height() < 30:
            return
        self._fitting = True
        try:
            available_width = max(40, self.contentsRect().width() - 2)
            available_height = max(30, self.contentsRect().height() - 2)
            chosen = 10.5
            flags = int(
                Qt.TextFlag.TextWordWrap
                | Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
            )
            for point_size in (15.0, 14.0, 13.0, 12.0, 11.0, 10.5):
                font = QFont(self.font())
                font.setPointSizeF(point_size)
                font.setWeight(QFont.Weight.DemiBold)
                bounds = QFontMetrics(font).boundingRect(
                    0,
                    0,
                    available_width,
                    10_000,
                    flags,
                    self.text(),
                )
                chosen = point_size
                if bounds.height() <= available_height:
                    break
            if abs(chosen - self._last_size) > 0.01:
                font = QFont(self.font())
                font.setPointSizeF(chosen)
                font.setWeight(QFont.Weight.DemiBold)
                self.setFont(font)
                self._last_size = chosen
        finally:
            self._fitting = False


class InterviewPage(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._repo = InterviewRepository(conn)
        self._jobs = JobRepository(conn)
        self._resumes = ResumeRepository(conn)
        self._service = InterviewService(conn)

        outer = QVBoxLayout(self)
        outer.setSpacing(SPACE["lg"])
        self.header = PageHeader(
            "Interview practice",
            "Prepare questions, then answer them out loud or in writing.",
            eyebrow="PRACTICE STUDIO",
        )
        self.session_context = QFrame()
        self.session_context.setProperty("role", "subtle")
        self.session_context.setMaximumWidth(430)
        session_context_layout = QVBoxLayout(self.session_context)
        session_context_layout.setContentsMargins(
            SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"]
        )
        session_context_layout.setSpacing(SPACE["xs"])
        self.session_context_title = QLabel("Mock interview locked")
        self.session_context_title.setProperty("role", "sectionTitle")
        session_context_layout.addWidget(self.session_context_title)
        self.session_context_detail = QLabel("Complete Prepare, then click Start Mock Interview.")
        self.session_context_detail.setProperty("role", "hint")
        self.session_context_detail.setWordWrap(True)
        session_context_layout.addWidget(self.session_context_detail)
        self.header.actions.addWidget(self.session_context)
        outer.addWidget(self.header)

        self.tabs = QTabWidget()
        self.setup_tab = _SetupTab(self)
        self.mock_tab = MockTab(conn, self)
        self.library_tab = _LibraryTab(conn, self)
        self.tabs.addTab(self.setup_tab, "Prepare")
        self._mock_tab_index = self.tabs.addTab(self.mock_tab, "Mock interview")
        self._library_tab_index = self.tabs.addTab(self.library_tab, "Answer library")
        self.tabs.setTabEnabled(self._mock_tab_index, False)
        self.tabs.setTabToolTip(
            self._mock_tab_index,
            "Complete the Prepare tab and click Start Mock Interview to unlock.",
        )
        self.set_library_available(
            bool(self._repo.list_library() or self._repo.list_completed_reports())
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabs, 1)

        self.setup_tab.session_started.connect(self._on_session_started)

    def reload(self) -> None:
        self.setup_tab.reload()
        self.library_tab.reload()

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.library_tab:
            self.library_tab.reload()
        elif self.tabs.widget(index) is self.mock_tab:
            self.mock_tab.ensure_environment()

    def _on_session_started(self, session_id: int) -> None:
        self.tabs.setTabEnabled(self._mock_tab_index, True)
        self.tabs.setTabToolTip(self._mock_tab_index, "Active mock interview")
        self.mock_tab.load_session(session_id)
        self.tabs.setCurrentWidget(self.mock_tab)

    def update_session_context(self, title: str, detail: str) -> None:
        self.session_context_title.setText(title)
        self.session_context_detail.setText(detail)

    def lock_mock_interview(self, detail: str) -> None:
        self.tabs.setTabEnabled(self._mock_tab_index, False)
        self.tabs.setTabToolTip(self._mock_tab_index, detail)
        if self.tabs.currentWidget() is self.mock_tab:
            self.tabs.setCurrentWidget(self.setup_tab)
        self.mock_tab.view_stack.setCurrentWidget(self.mock_tab.locked_view)
        self.update_session_context("Mock interview locked", detail)

    def set_library_available(self, available: bool) -> None:
        self.tabs.setTabEnabled(self._library_tab_index, available)
        self.tabs.setTabToolTip(
            self._library_tab_index,
            (
                "Review completed interview reports and saved answers."
                if available
                else "Complete an interview or save an answer to unlock the Answer Library."
            ),
        )
        if hasattr(self.mock_tab, "library_button"):
            self.mock_tab.library_button.setEnabled(available)
        if not available and self.tabs.currentWidget() is self.library_tab:
            self.tabs.setCurrentWidget(self.setup_tab)


class _SetupTab(QWidget):
    session_started = Signal(int)

    def __init__(self, page: InterviewPage):
        super().__init__(page)
        self._page = page
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameStyle(0)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setProperty("role", "layoutOnly")
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, SPACE["md"], SPACE["sm"], SPACE["md"])
        layout.setSpacing(SPACE["lg"])

        self.config_card = SectionCard(
            "Configure your practice",
            "Choose the context and interview style. Job and resume are optional for general practice.",
            icon="settings",
        )
        self.config_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        fields = FieldGrid(columns=3)

        self.job_combo = Dropdown()
        self.resume_combo = Dropdown()
        fields.add(
            "Target job",
            self.job_combo,
            "Use a captured job or practise generally.",
        )
        fields.add(
            "Resume",
            self.resume_combo,
            "Select the experience the interviewer should draw from.",
        )

        self.stage_combo = Dropdown()
        for key, description in STAGES.items():
            self.stage_combo.addItem(f"{key.replace('_', ' ').title()} — {description}", key)
        self.persona_combo = Dropdown()
        for key, description in PERSONAS.items():
            self.persona_combo.addItem(f"{key.replace('_', ' ').title()} — {description}", key)
        fields.add("Interview stage", self.stage_combo)
        fields.add("Interviewer style", self.persona_combo)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(3, 20)
        self.count_spin.setValue(8)
        self.count_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.difficulty_combo = Dropdown()
        for value in ("mixed", "easy", "medium", "hard"):
            self.difficulty_combo.addItem(value.title(), value)
        fields.add(
            "Number of questions",
            self.count_spin,
            "Between 3 and 20 questions.",
        )
        fields.add("Difficulty", self.difficulty_combo)
        self.config_card.body.addWidget(fields)

        actions = QHBoxLayout()
        action_hint = QLabel("AptiorDesk will build the question set and open the interview room.")
        action_hint.setProperty("role", "hint")
        action_hint.setWordWrap(True)
        actions.addWidget(action_hint, 1)
        self.start_button = QPushButton("Start mock interview")
        self.start_button.setProperty("accent", True)
        self.start_button.clicked.connect(self._start)
        actions.addWidget(self.start_button)
        self.config_card.body.addLayout(actions)

        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        self.config_card.body.addWidget(self.status)
        layout.addWidget(self.config_card)
        layout.addStretch(1)
        self.reload()

    def reload(self) -> None:
        self.job_combo.clear()
        self.job_combo.addItem("(no job — general practice)", None)
        for job in self._page._jobs.list():
            label = job.title or "(untitled job)"
            if job.company:
                label += f" — {job.company}"
            self.job_combo.addItem(label, job)
        self.resume_combo.clear()
        self.resume_combo.addItem("(no resume)", None)
        for resume in self._page._resumes.list():
            for version in self._page._resumes.list_versions(resume.id):
                self.resume_combo.addItem(f"{resume.name} — v{version.version_no}", version)

    def _provider(self):
        try:
            return get_active_provider(self._page._conn)
        except Exception as exc:
            QMessageBox.warning(self, "No AI provider", getattr(exc, "user_message", str(exc)))
            return None

    def _start(self) -> None:
        job = self.job_combo.currentData()
        resume_version = self.resume_combo.currentData()
        provider = self._provider()
        if provider is None:
            return
        self._page.lock_mock_interview(
            "Preparing your question set. The room unlocks when this step completes."
        )
        stage = self.stage_combo.currentData()
        persona = self.persona_combo.currentData()
        session = self._page._service.start_session(
            job,
            resume_version,
            persona=persona,
            stage=stage,
            feedback_mode="realistic",
        )
        self.status.setText("Preparing your interview…")
        self.start_button.setEnabled(False)
        worker = Worker(
            lambda: self._page._service.generate_questions_ai(
                provider,
                job,
                resume_version,
                stage=stage,
                count=self.count_spin.value(),
                difficulty=self.difficulty_combo.currentData(),
                session=session,
            ),
            parent=self,
        )
        worker.result.connect(
            lambda generated: self._on_session_questions_ready(generated, session.id)
        )
        worker.error.connect(lambda exc: self._session_start_failed(session.id, exc))
        worker.show_progress(
            "Preparing your mock interview",
            f"Creating {self.count_spin.value()} questions for the "
            f"{persona.replace('_', ' ')} persona with "
            f"{provider.config.name or provider.config.kind.value}.",
        )
        worker.start()

    def _on_session_questions_ready(self, generated, session_id: int) -> None:
        try:
            self._page._service.persist_questions(generated)
        except Exception as exc:
            self._page._service.discard_session(session_id)
            self._error(exc)
            return
        self._on_ready(session_id)

    def _session_start_failed(self, session_id: int, exc: Exception) -> None:
        try:
            self._page._service.discard_session(session_id)
        except Exception:
            log.exception("Could not remove failed interview session %s", session_id)
        self._page.lock_mock_interview(
            "Preparation did not complete. Review the setup and click Start Mock Interview again."
        )
        self._error(exc)

    def _on_ready(self, session_id: int) -> None:
        self.start_button.setEnabled(True)
        self.status.setText("")
        self.session_started.emit(session_id)

    def _error(self, exc: Exception) -> None:
        self.start_button.setEnabled(True)
        self.status.setText("")
        QMessageBox.warning(self, "AI error", getattr(exc, "user_message", str(exc)))


class MockTab(QWidget):
    """One question at a time with one analysis pass after the session."""

    audio_level_received = Signal(float)

    def __init__(self, conn: sqlite3.Connection, page: InterviewPage):
        super().__init__(page)
        self._conn = conn
        self._page = page
        self._repo = InterviewRepository(conn)
        self._service = InterviewService(conn)
        self._session = None
        self._queue: list[InterviewQuestion] = []
        self._index = 0
        self._followups = 0
        self._recorder = None
        self._recording_path = None
        self._transcriber = transcriber_module.LocalTranscriber()
        self._transcriber_ready = False
        self._microphone_prepare_worker: Worker | None = None
        self._microphone_start_worker: Worker | None = None
        self._recording_stop_worker: Worker | None = None
        self._transcription_worker: Worker | None = None
        self._microphone_prime_worker: Worker | None = None
        self._latest_audio_level = 0.0
        self._paused = False
        self._speech_active = False
        self._pending_speech = False
        self._pause_enabled: dict[QWidget, bool] = {}
        self._spoken_text = ""
        self._avatar = AvatarController(self)
        self._voice_settings = VoiceSettingsRepository(conn)
        self._speech = SpeechPlayer(self)
        self._speech.started.connect(self._speech_started)
        self._speech.finished.connect(self._speech_finished)
        self._speech.failed.connect(self._speech_failed)
        self._speech.frame_changed.connect(self._speech_frame)
        self._speech.preloaded.connect(self._speech_preloaded)
        self._speech.preload_failed.connect(self._speech_preload_failed)
        self.audio_level_received.connect(self._on_audio_level)
        self._avatar_ready_flag = False
        self._avatar_worker: Worker | None = None
        self._voice_ready_flag = False
        self._first_question_audio_ready = False
        self._environment_error = ""
        self._voice_worker: Worker | None = None
        self._kokoro_install_worker: Worker | None = None
        self._report_worker: Worker | None = None
        self._report_ready = False
        self._welcome_active = False
        self._welcome_started = False
        self._speaking_welcome = False
        self._speaking_closing = False
        self._report_dialog_pending = False
        self._countdown_value = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view_stack = QStackedWidget()
        layout.addWidget(self.view_stack)
        self.locked_view = self._build_locked_view()
        self.loading_view = self._build_loading_view()
        self.room_view = self._build_room_view()
        self.room_container = QWidget()
        self.room_container.setProperty("role", "layoutOnly")
        self.room_container_layout = QGridLayout(self.room_container)
        self.room_container_layout.setContentsMargins(0, 0, 0, 0)
        self.room_container_layout.addWidget(self.room_view, 0, 0)
        self.view_stack.addWidget(self.locked_view)
        self.view_stack.addWidget(self.loading_view)
        self.view_stack.addWidget(self.room_container)
        self.view_stack.setCurrentWidget(self.locked_view)
        self._build_countdown_overlay()

        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._update_timer)
        self._welcome_timer = QTimer(self)
        self._welcome_timer.setInterval(1_000)
        self._welcome_timer.timeout.connect(self._countdown_tick)
        settings = self._voice_settings.load()
        self._avatar.set_reduced_motion(settings.reduced_motion)
        self._update_voice_badge(settings)
        stored_avatar = str(SettingsRepository(conn).get("interview.avatar.id", DEFAULT_AVATAR_ID))
        known_ids = {avatar.id for avatar in avatar_catalog()}
        self._avatar_id = stored_avatar if stored_avatar in known_ids else DEFAULT_AVATAR_ID
        self._avatar_loading = False
        self.avatar_stage.set_avatar_name(get_avatar(self._avatar_id).name)
        self._set_active(False)

    def _build_locked_view(self) -> QWidget:
        view = QFrame()
        view.setProperty("role", "pane")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(SPACE["3xl"], SPACE["3xl"], SPACE["3xl"], SPACE["3xl"])
        layout.setSpacing(SPACE["md"])
        layout.addStretch(1)
        title = QLabel("Prepare your interview first")
        title.setProperty("role", "pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        detail = QLabel(
            "Choose the job, resume, interview style, and feedback mode in Prepare. "
            "Then click Start Mock Interview to build the question set and unlock "
            "this room."
        )
        detail.setProperty("role", "hint")
        detail.setWordWrap(True)
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setMaximumWidth(560)
        layout.addWidget(detail, alignment=Qt.AlignmentFlag.AlignHCenter)
        back = QPushButton("Go to Prepare")
        back.setProperty("accent", True)
        back.clicked.connect(lambda: self._page.tabs.setCurrentWidget(self._page.setup_tab))
        layout.addWidget(back, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return view

    def _build_loading_view(self) -> QWidget:
        view = QFrame()
        view.setProperty("role", "pane")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(SPACE["3xl"], SPACE["3xl"], SPACE["3xl"], SPACE["3xl"])
        layout.setSpacing(SPACE["md"])
        layout.addStretch(1)
        brand = QLabel("AptiorDesk")
        brand.setProperty("role", "eyebrow")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)
        title = QLabel("Preparing your interview room")
        title.setProperty("role", "pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        detail = QLabel(
            "Loading the interviewer and confirming the selected neural voice "
            "before the session begins."
        )
        detail.setProperty("role", "hint")
        detail.setWordWrap(True)
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(detail)
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setMaximumWidth(460)
        layout.addWidget(self.loading_progress, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.loading_avatar = QLabel("○ Loading interviewer")
        self.loading_voice = QLabel("○ Preparing Kokoro voice")
        self.loading_camera = QLabel("○ Camera will be checked when enabled")
        for label in (
            self.loading_avatar,
            self.loading_voice,
            self.loading_camera,
        ):
            label.setProperty("role", "hint")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        self.loading_error = QLabel("")
        self.loading_error.setProperty("role", "error")
        self.loading_error.setWordWrap(True)
        self.loading_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.loading_error)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.loading_install_button = QPushButton("Repair Kokoro")
        self.loading_install_button.setProperty("accent", True)
        self.loading_install_button.clicked.connect(self._install_kokoro)
        self.loading_install_button.hide()
        actions.addWidget(self.loading_install_button)
        self.loading_settings_button = QPushButton("Voice settings")
        self.loading_settings_button.clicked.connect(self._open_voice_settings)
        self.loading_settings_button.hide()
        actions.addWidget(self.loading_settings_button)
        self.loading_repair_button = QPushButton("Open System setup")
        self.loading_repair_button.clicked.connect(self._open_system_setup)
        self.loading_repair_button.hide()
        actions.addWidget(self.loading_repair_button)
        self.loading_retry_button = QPushButton("Retry initialization")
        self.loading_retry_button.setProperty("accent", True)
        self.loading_retry_button.clicked.connect(self._retry_environment)
        self.loading_retry_button.hide()
        actions.addWidget(self.loading_retry_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return view

    def _build_countdown_overlay(self) -> None:
        # The overlay is a sibling of the room content so the content can be
        # blurred without blurring the countdown itself.
        self.countdown_overlay = QFrame(self.room_container)
        self.countdown_overlay.setObjectName("interviewCountdownOverlay")
        self.countdown_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.countdown_overlay.setStyleSheet(
            """
            QFrame#interviewCountdownOverlay {
                background-color: rgba(8, 8, 9, 222);
                border: none;
            }
            QLabel#interviewCountdownNumber {
                color: #ffffff;
                font-size: 68px;
                font-weight: 800;
            }
            QLabel#interviewCountdownDetail {
                color: rgba(255, 255, 255, 210);
                font-size: 16px;
                font-weight: 600;
            }
            """
        )
        overlay_layout = QVBoxLayout(self.countdown_overlay)
        overlay_layout.setContentsMargins(SPACE["3xl"], SPACE["3xl"], SPACE["3xl"], SPACE["3xl"])
        overlay_layout.addStretch(1)
        self.countdown_label = QLabel("3")
        self.countdown_label.setObjectName("interviewCountdownNumber")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.countdown_label)
        self.countdown_detail = QLabel("Settling the room and preparing your camera and microphone")
        self.countdown_detail.setObjectName("interviewCountdownDetail")
        self.countdown_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_detail.setWordWrap(True)
        overlay_layout.addWidget(self.countdown_detail)
        overlay_layout.addStretch(1)
        self.room_container_layout.addWidget(self.countdown_overlay, 0, 0)
        self.countdown_overlay.hide()

    def _show_countdown_overlay(self) -> None:
        # QGraphicsBlurEffect forces Qt Quick and the webcam surface through a
        # temporary off-screen render target. On Windows that target is cleared
        # white for one frame, which caused the launch flash, and its first
        # geometry pass visibly rearranged the splitters. The nearly opaque
        # overlay freezes the same UI safely without rebuilding native surfaces.
        self.room_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.countdown_overlay.show()
        self.countdown_overlay.raise_()

    def _hide_countdown_overlay(self) -> None:
        self._welcome_timer.stop()
        self.countdown_overlay.hide()
        self.room_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def _build_room_view(self) -> QWidget:
        room_view = QWidget()
        room_view.setProperty("role", "layoutOnly")
        room_view_layout = QVBoxLayout(room_view)
        room_view_layout.setContentsMargins(0, 0, 0, 0)
        room_view_layout.setSpacing(SPACE["sm"])

        room_scroll = QScrollArea()
        room_scroll.setWidgetResizable(True)
        room_scroll.setFrameStyle(0)
        room_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        room_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        room = QWidget()
        room.setProperty("role", "layoutOnly")
        room_scroll.setWidget(room)
        self.room_content = room
        self.room_scroll = room_scroll
        room_scroll.viewport().installEventFilter(self)
        room_view_layout.addWidget(room_scroll, 1)
        layout = QVBoxLayout(room)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])
        self.header = QLabel("No active interview — start one from the Prepare tab.")
        self.header.setProperty("role", "hint")
        self.header.setWordWrap(True)
        # The page header already shows the session context. Avoid repeating
        # the same stage/persona sentence inside the interview room.
        self.header.hide()

        self.room_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.room_splitter.setChildrenCollapsible(False)
        self.room_splitter.setHandleWidth(SPACE["md"])

        self.video_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.video_splitter.setChildrenCollapsible(False)
        self.video_splitter.setHandleWidth(SPACE["md"])
        self.avatar_stage = AvatarStage(self._avatar, self.video_splitter)
        self.avatar_stage.setMinimumSize(300, 300)
        self.avatar_stage.library_requested.connect(self._choose_avatar)
        self.avatar_stage.ready.connect(self._avatar_ready)
        self.video_splitter.addWidget(self.avatar_stage)
        self.camera_tile = CandidateCameraTile()
        self.camera_tile.setMinimumSize(300, 300)
        self.camera_tile.state_changed.connect(self._camera_state_changed)
        self.video_splitter.addWidget(self.camera_tile)

        self.context_splitter = QSplitter(Qt.Orientation.Vertical)
        self.context_splitter.setChildrenCollapsible(False)
        self.context_splitter.setHandleWidth(SPACE["md"])
        self.question_panel = QFrame()
        self.question_panel.setProperty("role", "pane")
        self.question_panel.setMinimumHeight(240)
        question_layout = QVBoxLayout(self.question_panel)
        question_layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        question_layout.setSpacing(SPACE["md"])
        question_heading = QHBoxLayout()
        question_title = QLabel("Current question")
        question_title.setProperty("role", "paneTitle")
        question_heading.addWidget(question_title)
        question_heading.addStretch(1)
        self.voice_badge = QLabel("")
        self.voice_badge.setProperty("role", "badge")
        self.voice_badge.setProperty("tone", "accent")
        question_heading.addWidget(self.voice_badge)
        question_layout.addLayout(question_heading)
        question_meta = QHBoxLayout()
        question_meta.setSpacing(SPACE["sm"])
        self.question_progress = QLabel("Question")
        self.question_progress.setProperty("role", "badge")
        self.question_progress.setProperty("tone", "accent")
        question_meta.addWidget(self.question_progress)
        self.question_category = QLabel("")
        self.question_category.setProperty("role", "caption")
        self.question_category.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.question_category.setWordWrap(True)
        question_meta.addWidget(self.question_category, 1)
        question_layout.addLayout(question_meta)

        self.question_label = _ResponsiveQuestionLabel()
        question_layout.addWidget(self.question_label, 1)
        question_actions = QHBoxLayout()
        self.repeat_button = QPushButton("Repeat question")
        self.repeat_button.clicked.connect(self._repeat_question)
        question_actions.addWidget(self.repeat_button)
        question_actions.addStretch(1)
        self.timer_label = QLabel("0:00")
        self.timer_label.setProperty("role", "badge")
        question_actions.addWidget(self.timer_label)
        question_layout.addLayout(question_actions)
        self.context_splitter.addWidget(self.question_panel)

        self.transcript_panel = QFrame()
        self.transcript_panel.setProperty("role", "pane")
        self.transcript_panel.setMinimumHeight(240)
        transcript_layout = QVBoxLayout(self.transcript_panel)
        transcript_layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        transcript_layout.setSpacing(SPACE["sm"])
        transcript_heading = QHBoxLayout()
        transcript_title = QLabel("Your answer")
        transcript_title.setProperty("role", "paneTitle")
        transcript_heading.addWidget(transcript_title)
        transcript_heading.addStretch(1)
        self.transcript_status = QLabel("Ready for typed or spoken answers")
        self.transcript_status.setProperty("role", "badge")
        self.transcript_status.setProperty("tone", "neutral")
        transcript_heading.addWidget(self.transcript_status)
        transcript_layout.addLayout(transcript_heading)
        transcript_hint = QLabel(
            "While recording, AptiorDesk shows a clear recording state. Your "
            "local transcript appears after you press Stop."
        )
        transcript_hint.setProperty("role", "caption")
        transcript_hint.setWordWrap(True)
        transcript_layout.addWidget(transcript_hint)
        self.answer_edit = QPlainTextEdit()
        self.answer_edit.setPlaceholderText(
            "Type your answer, or start the microphone for local speech-to-text."
        )
        self.answer_edit.setMinimumHeight(100)
        transcript_layout.addWidget(self.answer_edit, 1)
        self.level_meter = LevelMeter()
        transcript_layout.addWidget(self.level_meter)
        self.answer_panel = self.transcript_panel
        self.context_splitter.addWidget(self.transcript_panel)

        self.room_splitter.addWidget(self.video_splitter)
        self.room_splitter.addWidget(self.context_splitter)
        for splitter in (
            self.room_splitter,
            self.video_splitter,
            self.context_splitter,
        ):
            splitter.handle(1).setEnabled(False)
        layout.addWidget(self.room_splitter, 1)
        self._apply_room_layout(1600)

        controls = QFrame()
        controls.setProperty("role", "pane")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        controls_layout.setSpacing(SPACE["lg"])
        media_controls = QWidget()
        media_controls.setProperty("role", "layoutOnly")
        media_controls.setMinimumWidth(0)
        media_controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        media_controls_layout = FlowLayout(media_controls, spacing=SPACE["sm"])
        session_controls = QWidget()
        session_controls.setProperty("role", "layoutOnly")
        session_controls.setMinimumWidth(0)
        session_controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        session_controls_layout = FlowLayout(session_controls, spacing=SPACE["sm"])
        controls_layout.addWidget(media_controls, 42)
        controls_layout.addWidget(session_controls, 58)
        self.record_button = QPushButton("Microphone")
        self.record_button.clicked.connect(self._toggle_recording)
        media_controls_layout.addWidget(self.record_button)
        self.camera_button = QPushButton("Camera")
        self.camera_button.clicked.connect(self._toggle_camera)
        media_controls_layout.addWidget(self.camera_button)
        self.voice_settings_button = QPushButton("Voice")
        self.voice_settings_button.setToolTip("Configure the interviewer voice")
        self.voice_settings_button.clicked.connect(self._open_voice_settings)
        media_controls_layout.addWidget(self.voice_settings_button)
        self.library_button = QPushButton("Answers")
        self.library_button.setToolTip("Open the Answer Library")
        self.library_button.clicked.connect(self._open_library)
        media_controls_layout.addWidget(self.library_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._toggle_pause)
        session_controls_layout.addWidget(self.pause_button)
        self.save_button = QPushButton("Keep in answer library")
        self.save_button.setCheckable(True)
        self.save_button.setToolTip(
            "When selected, this answer is also saved to the Answer Library."
        )
        session_controls_layout.addWidget(self.save_button)
        self.submit_button = QPushButton("Submit answer")
        self.submit_button.setProperty("accent", True)
        self.submit_button.clicked.connect(self._submit)
        session_controls_layout.addWidget(self.submit_button)
        self.end_button = QPushButton("End interview")
        self.end_button.setToolTip("End interview and create the session report")
        self.end_button.clicked.connect(self._end_interview)
        session_controls_layout.addWidget(self.end_button)
        # Session controls remain fixed while the room itself scrolls. This
        # keeps the primary actions reachable on short and compact screens.
        room_view_layout.addWidget(controls)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "hint")
        self.status.setMinimumHeight(20)
        room_view_layout.addWidget(self.status)
        return room_view

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "room_splitter"):
            self._refresh_room_layout()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            hasattr(self, "room_scroll")
            and watched is self.room_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._schedule_room_layout()
        return super().eventFilter(watched, event)

    def _refresh_room_layout(self) -> None:
        viewport_width = self.room_scroll.viewport().width()
        # A stacked scroll page can retain a small hidden-page geometry for one
        # event cycle. The visible MockTab width is already authoritative.
        self._apply_room_layout(max(viewport_width, self.width()))

    def _schedule_room_layout(self) -> None:
        """Reflow after the stacked page receives its final visible geometry."""
        QTimer.singleShot(0, self._refresh_room_layout)
        QTimer.singleShot(80, self._refresh_room_layout)

    def _apply_room_layout(self, width: int) -> None:
        """Reflow the room without allowing its content to grow horizontally."""
        width = max(320, width)
        self.room_content.setMinimumWidth(0)
        if width >= 720:
            # Stable two-by-two interview grid:
            # interviewer / candidate on the left, question / transcript right.
            self.room_splitter.setOrientation(Qt.Orientation.Horizontal)
            self.room_splitter.insertWidget(0, self.video_splitter)
            self.room_splitter.insertWidget(1, self.context_splitter)
            self.video_splitter.setOrientation(Qt.Orientation.Vertical)
            self.context_splitter.setOrientation(Qt.Orientation.Vertical)
            visible_height = max(620, self.room_scroll.viewport().height())
            square_side = max(
                300,
                min(
                    480,
                    (visible_height - SPACE["md"]) // 2,
                    width - 400 - SPACE["md"],
                ),
            )
            grid_height = square_side * 2 + SPACE["md"]
            self.room_content.setMinimumHeight(grid_height)
            self.room_splitter.setSizes([square_side, max(400, width - square_side - SPACE["md"])])
            aligned_rows = [square_side, square_side]
            self.video_splitter.setSizes(aligned_rows)
            self.context_splitter.setSizes(aligned_rows)
        else:
            # Compact screens retain the same semantic order without forcing
            # four unusably narrow tiles or any horizontal scrolling.
            self.room_splitter.setOrientation(Qt.Orientation.Vertical)
            self.room_splitter.insertWidget(0, self.context_splitter)
            self.room_splitter.insertWidget(1, self.video_splitter)
            self.context_splitter.setOrientation(Qt.Orientation.Vertical)
            self.video_splitter.setOrientation(Qt.Orientation.Vertical)
            compact_side = width
            context_height = 600
            video_height = compact_side * 2 + SPACE["md"]
            self.room_content.setMinimumHeight(context_height + video_height + SPACE["md"])
            self.room_splitter.setSizes([context_height, video_height])
            self.context_splitter.setSizes([300, 300])
            self.video_splitter.setSizes([compact_side, compact_side])

    # -- session -------------------------------------------------------------

    def load_session(self, session_id: int) -> None:
        self._speech.stop()
        self._avatar.set_state(AvatarState.TRANSITIONING)
        self._session = self._repo.get_session(session_id)
        self._queue = [q for q in self._repo.list_questions(session_id) if not q.is_followup]
        self._index = 0
        self._followups = 0
        self._report_worker = None
        self._report_ready = False
        self._welcome_active = True
        self._welcome_started = False
        self._speaking_welcome = False
        self._speaking_closing = False
        self._report_dialog_pending = False
        self._countdown_value = 0
        self._hide_countdown_overlay()
        self.end_button.setText("End interview")
        self.end_button.setToolTip("End interview and create the session report")
        if not self._queue:
            self.header.setText("This interview has no questions.")
            return
        settings = self._voice_settings.load()
        self._first_question_audio_ready = self._speech.is_preloaded(
            self._queue[0].text,
            settings,
        )
        self.view_stack.setCurrentWidget(self.loading_view)
        self.header.setText(
            f"<b>{self._session.stage}</b> interview with the "
            f"<b>{self._session.persona.replace('_', ' ')}</b>. "
            "Answers save immediately; analysis appears in the final report."
        )
        self._show_welcome()
        self.ensure_environment()

    def _set_active(self, active: bool) -> None:
        for widget in (
            self.answer_edit,
            self.record_button,
            self.submit_button,
            self.save_button,
            self.pause_button,
            self.repeat_button,
            self.end_button,
            self.camera_button,
        ):
            widget.setEnabled(active)
        if not active:
            self.answer_edit.setEnabled(False)

    def _set_answering_enabled(self, enabled: bool) -> None:
        for widget in (
            self.answer_edit,
            self.submit_button,
            self.save_button,
            self.repeat_button,
        ):
            widget.setEnabled(enabled)
        self.record_button.setEnabled(
            enabled
            and self._microphone_prime_worker is None
            and self._microphone_prepare_worker is None
        )

    def _show_welcome(self) -> None:
        self.question_progress.setText("Welcome")
        self.question_category.setText("Getting ready")
        self.question_label.setText("Your interviewer will welcome you before the first question.")
        self.answer_edit.clear()
        self.answer_edit.setPlaceholderText(
            "Answers unlock after the interviewer finishes the welcome."
        )
        self._set_transcript_status(
            "Welcome in progress · answering is temporarily disabled",
            "accent",
        )
        self._set_status(
            "Please wait. AptiorDesk is preparing the camera and microphone.",
            "hint",
        )
        self.timer_label.setText("0:00")
        self._set_active(True)
        self._set_answering_enabled(False)
        self.pause_button.setEnabled(False)
        self.end_button.setEnabled(False)
        self.camera_button.setEnabled(False)
        self._page.update_session_context(
            "Preparing your interview",
            "The welcome begins after a short room-ready countdown.",
        )

    @property
    def environment_ready(self) -> bool:
        return self._avatar_ready_flag and self._voice_ready_flag

    @property
    def initial_audio_ready(self) -> bool:
        return not self._queue or self._first_question_audio_ready

    def ensure_environment(self) -> None:
        if QGuiApplication.platformName() in {"offscreen", "minimal"}:
            self._avatar_ready_flag = True
            self._voice_ready_flag = True
            self._first_question_audio_ready = True
            self._show_room()
            return
        if not self.isVisible():
            return
        if self.environment_ready and self.initial_audio_ready:
            self._show_room()
            return
        self.view_stack.setCurrentWidget(self.loading_view)
        self.loading_progress.setRange(0, 0)
        self.loading_error.clear()
        self.loading_retry_button.hide()
        self.loading_settings_button.hide()
        self.loading_repair_button.hide()
        self.loading_install_button.hide()
        if not self._avatar_ready_flag:
            self.loading_avatar.setText("◌ Loading interviewer")
            self.ensure_avatar()
        if not self._voice_ready_flag and self._voice_worker is None:
            self._prepare_voice()
        elif self._voice_ready_flag and not self._first_question_audio_ready:
            self.loading_voice.setText("◌ Preparing the first question")
            self._preload_question(self._index)

    def _prepare_voice(self) -> None:
        settings = self._voice_settings.load()
        self._update_voice_badge(settings)
        self.loading_voice.setText(f"◌ Preparing {_voice_settings_label(settings)}")
        api_key = (
            keystore.get_secret(ELEVENLABS_SECRET)
            if settings.provider == VoiceProvider.ELEVENLABS
            else None
        )
        worker = Worker(
            lambda: prepare_voice(settings, elevenlabs_api_key=api_key),
            parent=self,
        )
        worker.result.connect(self._voice_prepared)
        worker.error.connect(self._voice_prepare_failed)
        worker.finished.connect(
            lambda: setattr(self, "_voice_worker", None) if self._voice_worker is worker else None
        )
        self._voice_worker = worker
        worker.start()

    def _voice_prepared(self, provider_label: str) -> None:
        self._voice_ready_flag = True
        self._environment_error = ""
        self._speech.prepare_output()
        self._speech.preload(_WELCOME_MESSAGE, self._voice_settings.load())
        self._preload_question(self._index)
        self.loading_install_button.hide()
        self.loading_voice.setText(
            f"✓ {provider_label} ready"
            if self.initial_audio_ready
            else "◌ Preparing the first question"
        )
        self._maybe_open_room()

    def _voice_prepare_failed(self, exc: Exception) -> None:
        self._voice_ready_flag = False
        self._environment_error = str(exc)
        self.loading_progress.setRange(0, 1)
        self.loading_voice.setText("! Neural voice unavailable")
        self.loading_error.setText(
            f"{exc}\n\nThe interview has not started and no fallback voice was used."
        )
        self.loading_retry_button.show()
        self.loading_settings_button.show()
        self.loading_install_button.setVisible(
            self._voice_settings.load().provider == VoiceProvider.KOKORO
        )

    def _retry_environment(self) -> None:
        self._environment_error = ""
        self.loading_error.clear()
        self.loading_retry_button.hide()
        self.loading_settings_button.hide()
        self.loading_install_button.hide()
        self.ensure_environment()

    def _install_kokoro(self) -> None:
        if self._kokoro_install_worker is not None:
            return
        answer = QMessageBox.question(
            self,
            "Repair Kokoro neural voice?",
            "AptiorDesk will verify the packaged neural-voice runtime and restore "
            "trusted model assets to your writable data folder. It will not modify "
            "the embedded Python runtime.\n\nContinue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.loading_install_button.setEnabled(False)
        self.loading_retry_button.hide()
        self.loading_settings_button.hide()
        self.loading_progress.setRange(0, 0)
        self.loading_error.setText("Starting Kokoro repair...")
        worker = Worker(
            lambda report: repair_kokoro_runtime(report),
            parent=self,
        )
        worker.progress.connect(lambda message: self.loading_error.setText(str(message)))
        worker.result.connect(self._kokoro_installed)
        worker.error.connect(self._kokoro_install_failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_kokoro_install_worker", None)
                if self._kokoro_install_worker is worker
                else None
            )
        )
        worker.show_progress(
            "Repairing Kokoro",
            "Verifying the packaged runtime and restoring trusted voice assets.",
        )
        self._kokoro_install_worker = worker
        worker.start()

    def _kokoro_installed(self, message: str) -> None:
        self.loading_install_button.setEnabled(True)
        self.loading_install_button.hide()
        self.loading_error.setText(f"{message} Preparing the interviewer voice...")
        self._voice_ready_flag = False
        self._environment_error = ""
        self._prepare_voice()

    def _kokoro_install_failed(self, exc: Exception) -> None:
        self.loading_progress.setRange(0, 1)
        self.loading_install_button.setEnabled(True)
        self.loading_install_button.show()
        self.loading_retry_button.show()
        self.loading_settings_button.show()
        self.loading_install_button.setVisible(
            self._voice_settings.load().provider == VoiceProvider.KOKORO
        )
        self.loading_error.setText(
            f"{exc}\n\nKokoro was not enabled and no fallback voice was used."
        )

    def _maybe_open_room(self) -> None:
        if self.environment_ready and self.initial_audio_ready:
            self._show_room()

    def _show_room(self) -> None:
        self.loading_progress.setRange(0, 1)
        self.loading_progress.setValue(1)
        self.loading_camera.setText("Camera and microphone are preparing")
        # Build and settle the complete room while the deliberate loading page
        # is still the only visible widget. Previously the stack switched first,
        # exposing the splitters' provisional geometry and the Qt Quick clear
        # frame before the countdown overlay was installed.
        self.camera_tile.initialize()
        self._refresh_room_layout()
        self.room_content.layout().activate()
        self.room_view.layout().activate()
        if self._welcome_active:
            self._begin_welcome()
        else:
            self._set_active(self._session is not None and bool(self._queue))
        self.view_stack.setCurrentWidget(self.room_container)
        if self._welcome_active:
            self.countdown_overlay.raise_()
        self._schedule_room_layout()
        if (
            self._pending_speech
            and not self._welcome_active
            and self._session is not None
            and self.isVisible()
            and not self._paused
        ):
            self._pending_speech = False
            QTimer.singleShot(0, self._speak_current)

    def _begin_welcome(self) -> None:
        """Prepare local devices behind a short, locked room countdown."""
        if self._welcome_started or not self._welcome_active:
            return
        self._welcome_started = True
        self._show_welcome()
        if QGuiApplication.platformName() not in {"offscreen", "minimal"}:
            self.camera_tile.start()
            self._prime_microphone()
        self._avatar.set_state(AvatarState.IDLE)
        self._countdown_value = 3
        self.countdown_label.setText("3")
        self._show_countdown_overlay()
        self._welcome_timer.start()

    def _countdown_tick(self) -> None:
        if not self._welcome_active:
            self._hide_countdown_overlay()
            return
        self._countdown_value -= 1
        if self._countdown_value > 0:
            self.countdown_label.setText(str(self._countdown_value))
            return
        self._hide_countdown_overlay()
        self._speak_welcome()

    def _prime_microphone(self) -> None:
        """Warm an installed local speech model without starting a download."""
        if (
            self._transcriber_ready
            or self._microphone_prime_worker is not None
            or not recorder_module.sounddevice_available()
            or not transcriber_module.faster_whisper_available()
            or not transcriber_module.model_is_downloaded()
        ):
            return
        self.record_button.setText("Preparing microphone...")
        worker = Worker(
            lambda: transcriber_module.prepare_model(self._transcriber.size),
            parent=self,
        )
        worker.result.connect(self._microphone_primed)
        worker.error.connect(self._microphone_prime_failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_microphone_prime_worker", None)
                if self._microphone_prime_worker is worker
                else None
            )
        )
        self._microphone_prime_worker = worker
        worker.start()

    def _microphone_primed(self, _message: str) -> None:
        self._transcriber_ready = True
        self.record_button.setText("Microphone")
        if not self._welcome_active:
            self.record_button.setEnabled(True)

    def _microphone_prime_failed(self, exc: Exception) -> None:
        self._transcriber_ready = False
        self.record_button.setText("Set up microphone")
        log.info("Background microphone preparation was skipped: %s", exc)
        if not self._welcome_active:
            self.record_button.setEnabled(True)

    def _speak_welcome(self) -> None:
        if (
            not self._welcome_active
            or self._session is None
            or self._paused
            or not self.environment_ready
        ):
            return
        settings = self._voice_settings.load()
        self._speaking_welcome = True
        self._spoken_text = _WELCOME_MESSAGE
        self._avatar.set_state(AvatarState.TRANSITIONING)
        self._set_status(
            "Your interviewer is welcoming you. Answering unlocks when the welcome is complete.",
            "hint",
        )
        self._speech.speak(_WELCOME_MESSAGE, settings)

    def _complete_welcome(self) -> None:
        """Unlock the room and move to the first real question."""
        if not self._welcome_active:
            return
        self._hide_countdown_overlay()
        self._speaking_welcome = False
        self._welcome_active = False
        self.answer_edit.setPlaceholderText("Type your answer, or use the microphone to record it.")
        self._set_active(True)
        self._set_answering_enabled(True)
        self._set_status("", "hint")
        self._show_current()

    def _current(self) -> InterviewQuestion | None:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    def _preload_question(self, index: int) -> None:
        if not self._voice_ready_flag:
            return
        settings = self._voice_settings.load()
        if index == len(self._queue):
            self._speech.preload(_CLOSING_MESSAGE, settings)
            return
        if not (0 <= index < len(self._queue)):
            return
        question = self._queue[index]
        self._speech.preload(question.text, settings)

    def _speech_preloaded(self, text: str) -> None:
        current = self._current()
        if (
            current is not None
            and text == current.text
            and self.view_stack.currentWidget() is self.loading_view
        ):
            self._first_question_audio_ready = True
            self.loading_voice.setText("✓ Kokoro voice and first question ready")
            self._maybe_open_room()

    def _speech_preload_failed(self, text: str, message: str) -> None:
        current = self._current()
        if current is None or text != current.text:
            return
        self._first_question_audio_ready = False
        self._voice_ready_flag = False
        self.loading_progress.setRange(0, 1)
        self.loading_voice.setText("! Could not prepare the interviewer voice")
        self.loading_error.setText(message)
        self.loading_retry_button.show()

    def _show_current(self) -> None:
        if self._welcome_active:
            self._show_welcome()
            return
        question = self._current()
        if question is None:
            self._finish()
            return
        prefix = "Follow-up" if question.is_followup else f"Question {self._index + 1}"
        self.question_progress.setText(f"{prefix} of {len(self._queue)}")
        self.question_category.setText(question.category.replace("_", " ").title())
        self.question_label.setText(question.text)
        self.answer_edit.clear()
        self.answer_edit.setPlaceholderText("Type your answer, or use the microphone to record it.")
        self.level_meter.reset()
        self._set_transcript_status("Ready for typed or spoken answers")
        self.timer_label.setText("0:00")
        self.save_button.setChecked(False)
        self._set_answering_enabled(True)
        if self._session is not None:
            self._page.update_session_context(
                f"{self._session.stage.replace('_', ' ').title()} interview",
                f"{prefix} of {len(self._queue)} · "
                f"{self._session.persona.replace('_', ' ').title()} · "
                "full analysis after the interview",
            )
        self._pending_speech = False
        if self._voice_ready_flag:
            self._preload_question(self._index)
        if (
            self.isVisible()
            and not self._paused
            and self.environment_ready
            and self.avatar_stage.is_ready
        ):
            QTimer.singleShot(0, self._speak_current)
        elif self.isVisible() and not self._paused:
            self._pending_speech = True
            self.ensure_environment()
            self._set_status(
                "Preparing the interview room before the question begins…",
                "hint",
            )
        else:
            self._avatar.set_state(AvatarState.IDLE)

    def _repeat_question(self) -> None:
        if self._welcome_active or self._current() is None or not self.environment_ready:
            return
        self._speech.stop()
        QTimer.singleShot(0, self._speak_current)

    def _toggle_camera(self) -> None:
        self.camera_tile.toggle()

    def _camera_state_changed(self, state: str) -> None:
        if state == "enabled":
            self.camera_button.setText("Stop camera")
        elif state == "starting":
            self.camera_button.setText("Cancel camera")
        else:
            self.camera_button.setText("Camera")

    def _toggle_transcript(self) -> None:
        self.answer_panel.show()
        self.room_scroll.ensureWidgetVisible(self.transcript_panel)
        self.answer_edit.setFocus()

    def _open_voice_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Interview voice settings")
        dialog.resize(820, 700)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(VoiceSettingsPanel(self._conn, dialog))
        dialog.exec()

    def _open_system_setup(self) -> None:
        window = self.window()
        if hasattr(window, "go_to"):
            window.go_to("Settings")
            settings_page = getattr(window, "settings_page", None)
            if settings_page is not None:
                settings_page.tabs.setCurrentWidget(settings_page.system_setup_panel)
            return
        self.loading_error.setText(
            "Open Settings → System setup to verify the installation, then retry."
        )
        self._speech.clear_cache()
        self._first_question_audio_ready = False
        self._voice_ready_flag = False
        self.view_stack.setCurrentWidget(self.loading_view)
        self.ensure_environment()

    def _open_library(self) -> None:
        self._page.tabs.setCurrentWidget(self._page.library_tab)

    def _end_interview(self) -> None:
        if self._session is None:
            return
        if self._report_ready:
            self._exit_interview()
            return
        if self._report_worker is not None:
            return
        choice = QMessageBox.question(
            self,
            "End interview?",
            "End this mock interview and create the session report now?",
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.end_button.setEnabled(False)
            self.end_button.setText("Generating report…")
            self._release_live_devices()
            self._finish()

    def _exit_interview(self, *, open_library: bool | None = None) -> None:
        if open_library is None:
            open_library = self._report_ready
        self._release_live_devices()
        self._session = None
        self._queue.clear()
        self._report_ready = False
        self._welcome_active = False
        self._welcome_started = False
        self._speaking_welcome = False
        self._speaking_closing = False
        self._report_dialog_pending = False
        self.end_button.setText("End interview")
        self._page.lock_mock_interview(
            "Start a new session from Prepare when you are ready to practise again."
        )
        self._page.tabs.setCurrentWidget(
            self._page.library_tab if open_library else self._page.setup_tab
        )

    def _release_live_devices(self) -> None:
        self._hide_countdown_overlay()
        if self.camera_tile.camera_busy:
            self.camera_tile.stop()
        if self._recorder is not None and self._recorder.is_recording:
            self._tick.stop()
            try:
                self._recorder.cancel()
            except Exception:
                log.exception("Could not close the active interview microphone")
            self._recorder = None
            self.record_button.setText("Microphone")
            self._avatar.set_state(AvatarState.IDLE)

    # -- recording -----------------------------------------------------------

    def _toggle_recording(self) -> None:
        if any(
            worker is not None
            for worker in (
                self._microphone_prepare_worker,
                self._microphone_start_worker,
                self._recording_stop_worker,
                self._transcription_worker,
            )
        ):
            return
        if self._recorder is not None and self._recorder.is_recording:
            self._stop_recording()
            return
        if not recorder_module.sounddevice_available():
            QMessageBox.information(
                self,
                "Microphone unavailable",
                "The microphone component is unavailable in this installation. "
                "Open Settings → System setup to run diagnostics or repair "
                "AptiorDesk. You can keep answering by typing.",
            )
            return
        if not transcriber_module.faster_whisper_available():
            QMessageBox.information(
                self,
                "Speech-to-text unavailable",
                "The local speech-to-text component is unavailable in this "
                "installation. Open Settings → System setup to run diagnostics "
                "or repair AptiorDesk. Audio is never uploaded.",
            )
            return
        if not transcriber_module.model_is_downloaded():
            QMessageBox.information(
                self,
                "Speech model needs repair",
                "The offline speech-to-text model should be included with "
                "AptiorDesk. Rerun the installer to repair the voice components, "
                "then retry. You can keep answering by typing.",
            )
            return
        if not self._transcriber_ready:
            self._prepare_microphone()
            return
        self._start_recording()

    def _prepare_microphone(self) -> None:
        self.record_button.setEnabled(False)
        self.record_button.setText("Preparing microphone…")
        self._set_status("Preparing local transcription before recording begins.", "hint")
        self._avatar.set_state(AvatarState.THINKING)
        worker = Worker(
            lambda report: transcriber_module.prepare_model(self._transcriber.size, report),
            parent=self,
        )
        worker.progress.connect(lambda message: self._set_status(str(message), "hint"))
        worker.result.connect(self._microphone_prepared)
        worker.error.connect(self._microphone_prepare_failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_microphone_prepare_worker", None)
                if self._microphone_prepare_worker is worker
                else None
            )
        )
        worker.show_progress(
            "Preparing microphone",
            "Checking the local speech model before AptiorDesk opens the microphone.",
        )
        self._microphone_prepare_worker = worker
        worker.start()

    def _microphone_prepared(self, message: str) -> None:
        self._transcriber_ready = True
        self.record_button.setEnabled(True)
        self.record_button.setText("Microphone")
        self._set_status(f"{message} Press Microphone when you are ready.", "success")
        self._avatar.set_state(AvatarState.IDLE)

    def _microphone_prepare_failed(self, exc: Exception) -> None:
        self._transcriber_ready = False
        self.record_button.setEnabled(True)
        self.record_button.setText("Set up microphone")
        self._set_status(
            "Microphone setup did not complete. Typed answers remain available.",
            "warning",
        )
        self._avatar.set_state(AvatarState.IDLE)
        QMessageBox.warning(
            self,
            "Microphone setup failed",
            getattr(exc, "user_message", str(exc)),
        )

    def _start_recording(self) -> None:
        self._speech.stop()
        self.record_button.setEnabled(False)
        self.record_button.setText("Opening microphone…")
        self._set_transcript_status("Opening microphone", "accent")
        self._set_status("Requesting microphone access from the operating system.", "hint")

        def open_microphone():
            recorder = recorder_module.Recorder()
            recorder.level_callback = self.audio_level_received.emit
            recorder.start()
            return recorder

        worker = Worker(open_microphone, parent=self)
        worker.result.connect(self._recording_started)
        worker.error.connect(self._recording_start_failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_microphone_start_worker", None)
                if self._microphone_start_worker is worker
                else None
            )
        )
        self._microphone_start_worker = worker
        worker.start()

    def _recording_started(self, recorder) -> None:
        self._recorder = recorder
        self.record_button.setEnabled(True)
        self.record_button.setText("Stop recording")
        self._set_status("Recording your answer... Press Stop when you finish.", "success")
        self._set_transcript_status("Recording · transcript appears after Stop", "success")
        self._avatar.set_state(AvatarState.LISTENING)
        self._tick.start()

    def _recording_start_failed(self, exc: Exception) -> None:
        self._recorder = None
        self.record_button.setEnabled(True)
        self.record_button.setText("Microphone")
        self._set_transcript_status("Microphone unavailable", "warning")
        self._set_status("The microphone could not be opened.", "warning")
        QMessageBox.warning(
            self,
            "Recording failed",
            getattr(exc, "user_message", str(exc)),
        )

    def _stop_recording(self) -> None:
        self._tick.stop()
        self._avatar.set_state(AvatarState.THINKING)
        recorder = self._recorder
        self._recorder = None
        self.record_button.setEnabled(False)
        self.record_button.setText("Finalizing recording…")
        self._set_transcript_status("Finalizing your answer", "accent")
        self._set_status("Closing the microphone and saving your recording locally.", "hint")
        worker = Worker(
            lambda: (recorder.stop(), recorder.elapsed_s),
            parent=self,
        )
        worker.result.connect(self._recording_stopped)
        worker.error.connect(self._recording_stop_failed)
        worker.finished.connect(
            lambda: (
                setattr(self, "_recording_stop_worker", None)
                if self._recording_stop_worker is worker
                else None
            )
        )
        self._recording_stop_worker = worker
        worker.start()

    def _recording_stopped(self, result) -> None:
        path, duration = result
        self._recording_path = path
        self.record_button.setText("Transcribing…")
        self._set_transcript_status("Creating final transcript", "accent")
        self._set_status("Transcribing locally with a responsive CPU limit.", "hint")
        worker = Worker(lambda: self._transcriber.transcribe(path), parent=self)
        worker.result.connect(lambda text: self._on_transcribed(text, duration))
        worker.error.connect(self._transcription_error)
        worker.finished.connect(
            lambda: (
                setattr(self, "_transcription_worker", None)
                if self._transcription_worker is worker
                else None
            )
        )
        worker.show_progress(
            "Transcribing your answer",
            f"Processing {duration:.0f} seconds of audio locally on this device.",
        )
        self._transcription_worker = worker
        worker.start()

    def _recording_stop_failed(self, exc: Exception) -> None:
        self.record_button.setEnabled(True)
        self.record_button.setText("Microphone")
        self._set_transcript_status("Recording could not be saved", "warning")
        self._avatar.set_state(AvatarState.IDLE)
        self._set_status("The recording could not be finalized.", "warning")
        QMessageBox.warning(
            self,
            "Recording failed",
            getattr(exc, "user_message", str(exc)),
        )

    def _on_transcribed(self, text: str, duration: float) -> None:
        self.record_button.setEnabled(True)
        self.record_button.setText("Microphone")
        self._recording_duration = duration
        self.answer_edit.setPlainText(text)
        self.answer_edit.moveCursor(QTextCursor.MoveOperation.End)
        self._set_transcript_status("Transcript ready to review", "success")
        self.status.setText(
            f"Transcribed {duration:.0f}s locally — edit the text if the "
            "transcription got anything wrong, then submit."
        )
        self._avatar.set_state(AvatarState.IDLE)

    def _transcription_error(self, exc: Exception) -> None:
        self.record_button.setEnabled(True)
        self.record_button.setText("Microphone")
        self.status.setText("")
        self._set_transcript_status("Transcription failed · typing is available", "warning")
        self._avatar.set_state(AvatarState.IDLE)
        QMessageBox.warning(self, "Transcription failed", getattr(exc, "user_message", str(exc)))

    def _update_timer(self) -> None:
        if self._recorder is None:
            return
        elapsed = self._recorder.elapsed_s
        self.timer_label.setText(f"{int(elapsed // 60)}:{int(elapsed % 60):02d}")
        self._avatar.observe_candidate_audio(self._latest_audio_level, int(elapsed * 1000))

    def _on_audio_level(self, level: float) -> None:
        self._latest_audio_level = level
        self.level_meter.set_level(level)

    # -- avatar and interviewer speech --------------------------------------

    def _update_voice_badge(self, settings: VoiceSettings) -> None:
        self.voice_badge.setText(_voice_settings_label(settings))
        self.voice_badge.setProperty("tone", "accent")
        self._repolish(self.voice_badge)

    def _set_status(self, text: str, role: str) -> None:
        self.status.setText(text)
        self.status.setProperty("role", role)
        self._repolish(self.status)

    def _set_transcript_status(self, text: str, tone: str = "neutral") -> None:
        self.transcript_status.setText(text)
        self.transcript_status.setProperty("tone", tone)
        self._repolish(self.transcript_status)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def ensure_avatar(self) -> None:
        if QGuiApplication.platformName() in {"offscreen", "minimal"}:
            return
        if not self.isVisible():
            return
        if not self.avatar_stage.has_avatar and not self._avatar_loading:
            self._load_avatar(self._avatar_id)

    def _choose_avatar(self) -> None:
        avatar_id = AvatarPickerDialog.choose(self._avatar_id, self)
        if avatar_id is None:
            return
        if avatar_id == self._avatar_id and self.avatar_stage.has_avatar:
            return
        self._load_avatar(avatar_id)

    def _load_avatar(self, avatar_id: str) -> None:
        if self._avatar_loading or self._avatar_worker is not None:
            return
        avatar = get_avatar(avatar_id)
        self._avatar_loading = True
        self._avatar_ready_flag = False
        self.avatar_stage.set_avatar_name(avatar.name)
        self.avatar_stage.show_loading(f"Preparing {avatar.name}…")
        worker = Worker(
            lambda: (avatar_id, prepare_avatar(avatar_id)),
            parent=self,
        )
        worker.result.connect(self._avatar_prepared)
        worker.error.connect(self._avatar_prepare_failed)
        worker.finished.connect(
            lambda: setattr(self, "_avatar_worker", None) if self._avatar_worker is worker else None
        )
        self._avatar_worker = worker
        worker.start()

    def _avatar_prepared(self, result: tuple[str, Path]) -> None:
        avatar_id, component_path = result
        self._avatar_loading = False
        self._avatar_id = avatar_id
        SettingsRepository(self._conn).set("interview.avatar.id", avatar_id)
        avatar = get_avatar(avatar_id)
        self.avatar_stage.set_avatar_name(avatar.name)
        self.avatar_stage.load_component(component_path)
        self.loading_avatar.setText(f"◌ Connecting {avatar.name}'s expressions and speech controls")
        self._set_status(
            f"Loading {avatar.name}'s expressions and speech controls…",
            "hint",
        )

    def _avatar_ready(self, control_count: int) -> None:
        avatar = get_avatar(self._avatar_id)
        self._avatar_ready_flag = True
        self.loading_avatar.setText(f"✓ {avatar.name} ready · {control_count} facial controls")
        self._set_status("", "hint")
        self._maybe_open_room()

    def _avatar_prepare_failed(self, exc: Exception) -> None:
        self._avatar_loading = False
        self._avatar_ready_flag = False
        self.avatar_stage.show_error(str(exc))
        self.loading_progress.setRange(0, 1)
        self.loading_avatar.setText("! Interviewer unavailable")
        self.loading_error.setText(str(exc))
        self.loading_repair_button.show()
        self.loading_retry_button.show()

    def _speak_current(self) -> None:
        question = self._current()
        if question is None or self._paused or not self.isVisible():
            return
        if not self.environment_ready:
            self._pending_speech = True
            self.ensure_environment()
            return
        settings = self._voice_settings.load()
        self._avatar.set_reduced_motion(settings.reduced_motion)
        self._update_voice_badge(settings)
        self._spoken_text = question.text
        self._avatar.set_state(AvatarState.TRANSITIONING)
        if self._speech.is_preloaded(question.text, settings):
            self._set_status("Starting the interviewer…", "hint")
        else:
            self._set_status(
                f"Preparing the question with {_voice_settings_label(settings)}…",
                "hint",
            )
        self._speech.speak(question.text, settings)

    def _speak_closing(self) -> None:
        if self._session is None:
            return
        settings = self._voice_settings.load()
        self._speaking_closing = True
        self._spoken_text = _CLOSING_MESSAGE
        self._avatar.set_state(AvatarState.TRANSITIONING)
        self._set_status(
            "The interviewer is closing the session while your report is generated.",
            "hint",
        )
        self._speech.speak(_CLOSING_MESSAGE, settings)

    def _speech_started(self, provider_label: str) -> None:
        self._speech_active = True
        self._avatar.set_state(AvatarState.SPEAKING)
        if not self._speaking_welcome and not self._speaking_closing:
            self._preload_question(self._index + 1)
        self.voice_badge.setText(provider_label)
        self.voice_badge.setProperty("tone", "accent")
        self._repolish(self.voice_badge)
        if self._speaking_welcome:
            self._set_status(
                f"Welcome in progress with {provider_label}. Answering is locked.",
                "success",
            )
        elif self._speaking_closing:
            self._set_status(
                f"Closing message playing with {provider_label}. Your report is being generated.",
                "success",
            )
        else:
            self._set_status(f"Interviewer speaking with {provider_label}.", "success")

    def _speech_finished(self) -> None:
        self._speech_active = False
        self.avatar_stage.set_viseme(None, 0.0)
        if not self._paused:
            self._avatar.set_state(AvatarState.IDLE)
        if self._speaking_welcome:
            self._complete_welcome()
            return
        if self._speaking_closing:
            self._speaking_closing = False
            if self._report_dialog_pending:
                QTimer.singleShot(0, self._present_report_ready)
            elif self.end_button.text() != "Retry report":
                self._set_status("Writing your session report…", "hint")
            return
        self._preload_question(self._index + 1)
        if self.status.text().startswith(
            (
                "Interviewer speaking",
                "Preparing the question",
                "Starting the interviewer",
            )
        ):
            self._set_status("", "hint")

    def _speech_failed(self, message: str) -> None:
        self._speech_active = False
        if self._speaking_closing:
            self._speaking_closing = False
            self.avatar_stage.set_viseme(None, 0.0)
            self._avatar.set_state(AvatarState.IDLE)
            log.warning("Closing interview message could not play: %s", message)
            if self._report_dialog_pending:
                QTimer.singleShot(0, self._present_report_ready)
            elif self.end_button.text() != "Retry report":
                self._set_status("Writing your session report…", "hint")
            return
        self._speaking_welcome = False
        self.avatar_stage.set_viseme(None, 0.0)
        self._avatar.set_state(AvatarState.IDLE)
        self._voice_ready_flag = False
        self.view_stack.setCurrentWidget(self.loading_view)
        self.loading_progress.setRange(0, 1)
        self.loading_voice.setText("! Neural voice unavailable")
        self.loading_error.setText(
            f"{message}\n\nNo fallback voice was used. Retry Kokoro initialization "
            "or choose another supported neural provider."
        )
        self.loading_retry_button.show()
        self.loading_settings_button.show()
        self.loading_install_button.setVisible(
            self._voice_settings.load().provider == VoiceProvider.KOKORO
        )

    def _speech_position(self, position_ms: int, duration_ms: int) -> None:
        letters = [character for character in self._spoken_text if character.isalpha()]
        if not letters or duration_ms <= 0:
            return
        progress = max(0.0, min(1.0, position_ms / duration_ms))
        character = letters[min(len(letters) - 1, int(progress * len(letters)))]
        self.avatar_stage.set_viseme(_viseme_for_character(character), 0.72)

    def _speech_frame(
        self,
        position_ms: int,
        duration_ms: int,
        viseme: str | None,
        weight: float,
        has_neural_cues: bool,
    ) -> None:
        if has_neural_cues:
            self.avatar_stage.set_viseme(viseme, weight)
            return
        self._speech_position(position_ms, duration_ms)

    def _toggle_pause(self) -> None:
        if self._recorder is not None and self._recorder.is_recording:
            QMessageBox.information(
                self,
                "Finish recording first",
                "Stop the current answer recording before pausing the interview.",
            )
            return
        self._paused = not self._paused
        if self._paused:
            self._pause_enabled = {
                widget: widget.isEnabled()
                for widget in (
                    self.answer_edit,
                    self.record_button,
                    self.submit_button,
                    self.save_button,
                )
            }
            for widget in self._pause_enabled:
                widget.setEnabled(False)
            self._speech.pause()
            self._avatar.set_state(AvatarState.PAUSED)
            self.pause_button.setText("Resume")
            self.status.setText("Interview paused.")
        else:
            for widget, enabled in self._pause_enabled.items():
                widget.setEnabled(enabled)
            self._pause_enabled.clear()
            self._speech.resume()
            self._avatar.set_state(
                AvatarState.SPEAKING if self._speech_active else AvatarState.IDLE
            )
            self.pause_button.setText("Pause")
            self.status.setText("")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._avatar.set_visible(True)
        self._schedule_room_layout()
        self.ensure_environment()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._avatar.set_visible(False)
        self._release_live_devices()
        super().hideEvent(event)

    # -- answering -----------------------------------------------------------

    def _submit(self) -> None:
        question = self._current()
        text = self.answer_edit.toPlainText().strip()
        if question is None or not text:
            return
        duration = getattr(self, "_recording_duration", None)
        answer = self._service.record_answer(
            question,
            text,
            session=self._session,
            input_mode="voice" if duration else "typed",
            duration_s=duration,
        )
        if self.save_button.isChecked():
            self._service.save_to_library(answer)
            self._page.set_library_available(True)
            self._page.library_tab.reload()
        self._recording_duration = None
        self.submit_button.setEnabled(False)
        self.status.setText("Answer saved. Opening the next question…")
        self._avatar.set_state(AvatarState.TRANSITIONING)
        QTimer.singleShot(0, self._advance)

    def _advance(self) -> None:
        self._index += 1
        if self._current() is None:
            self._finish()
            return
        if not self._current().is_followup:
            self._followups = 0
        self._show_current()

    def _finish(self) -> None:
        if self._report_worker is not None or self._report_ready:
            return
        self._speech.stop()
        self._release_live_devices()
        self.avatar_stage.set_viseme(None, 0.0)
        self._avatar.set_state(AvatarState.IDLE)
        self.question_progress.setText("Complete")
        self.question_category.clear()
        self.question_label.setText("No more questions.")
        self._page.update_session_context(
            "Interview complete",
            "Your session report is being prepared.",
        )
        self.answer_edit.clear()
        self.submit_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.end_button.setEnabled(False)
        self.end_button.setText("Generating report…")
        try:
            provider = get_active_provider(self._conn)
        except Exception as exc:
            self._report_failed(exc)
            return
        self.status.setText("Writing your session report…")
        session = self._session
        try:
            context = self._service.report_context(session)
        except Exception as exc:
            self._report_failed(exc)
            return
        worker = Worker(lambda: self._service.generate_report(provider, context), parent=self)
        worker.result.connect(lambda report: self._show_report(context, report))
        worker.error.connect(self._report_failed)
        worker.finished.connect(
            lambda: setattr(self, "_report_worker", None) if self._report_worker is worker else None
        )
        worker.show_progress(
            "Writing your interview report",
            "Reviewing the complete session and identifying practice priorities with "
            f"{provider.config.name or provider.config.kind.value}.",
        )
        self._report_worker = worker
        worker.start()
        self._speak_closing()

    def _show_report(self, context, report) -> None:
        try:
            self._service.persist_report(context, report)
        except Exception as exc:
            self._report_failed(exc)
            return
        self._report_ready = True
        self._page.library_tab.reload()
        self._page.set_library_available(True)
        self.status.setText("Session report saved to the Answer Library.")
        self._page.update_session_context(
            "Interview report ready",
            "Your report is saved in the Answer Library.",
        )
        self.end_button.setText("Exit interview")
        self.end_button.setToolTip("Leave this completed interview")
        if self._speaking_closing or self._speech_active:
            self._report_dialog_pending = True
            self.status.setText("Report saved. The interviewer is finishing the closing message.")
            return
        self._present_report_ready()

    def _present_report_ready(self) -> None:
        if not self._report_ready or self._session is None:
            return
        self._report_dialog_pending = False
        self._exit_interview(open_library=self._choose_report_destination())

    def _choose_report_destination(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle("Interview report ready")
        dialog.setText("Your interview report has been saved.")
        dialog.setInformativeText(
            "View it now in the Answer Library, or leave the interview and review it later."
        )
        view_button = dialog.addButton(
            "View in Answer Library",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.addButton(
            "Exit interview",
            QMessageBox.ButtonRole.RejectRole,
        )
        dialog.setDefaultButton(view_button)
        dialog.exec()
        return dialog.clickedButton() is view_button

    def _report_failed(self, exc: Exception) -> None:
        self.status.setText("The report could not be generated. Your answers are saved.")
        self.end_button.setEnabled(True)
        self.end_button.setText("Retry report")
        self.end_button.setToolTip("Retry generating the final session report")
        self._avatar.set_state(AvatarState.IDLE)
        QMessageBox.warning(
            self, "Report generation failed", getattr(exc, "user_message", str(exc))
        )

    def _error(self, exc: Exception) -> None:
        self.status.setText("")
        self.submit_button.setEnabled(True)
        self._avatar.set_state(AvatarState.IDLE)
        QMessageBox.warning(self, "AI error", getattr(exc, "user_message", str(exc)))


class _LibraryTab(QWidget):
    def __init__(self, conn: sqlite3.Connection, page: InterviewPage):
        super().__init__(page)
        self._page = page
        self._service = InterviewService(conn)
        self._repo = InterviewRepository(conn)
        self._jobs = JobRepository(conn)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Review completed interview reports and the answers you chose to "
            "save for future practice."
        )
        hint.setProperty("role", "hint")
        layout.addWidget(hint)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.answer_list = QListWidget()
        self.answer_list.currentItemChanged.connect(lambda *_: self._show())
        splitter.addWidget(self.answer_list)
        self.detail = QTextBrowser()
        splitter.addWidget(self.detail)
        splitter.setSizes([320, 620])
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.practice_button = QPushButton("Practice this answer")
        self.practice_button.clicked.connect(self._practice_again)
        actions.addWidget(self.practice_button)
        self.remove_button = QPushButton("Remove from library")
        self.remove_button.clicked.connect(self._remove)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.reload()

    def reload(self) -> None:
        self.answer_list.clear()
        for session in self._repo.list_completed_reports():
            stage = session.stage.replace("_", " ").title()
            date = (session.ended_at or session.started_at or "")[:10]
            suffix = f" · {date}" if date else ""
            entry = QListWidgetItem(f"Session report · {stage}{suffix}")
            entry.setData(Qt.ItemDataRole.UserRole, ("report", session))
            self.answer_list.addItem(entry)
        for answer, question_text in self._service.library():
            entry = QListWidgetItem(question_text[:70])
            entry.setData(
                Qt.ItemDataRole.UserRole,
                ("answer", answer, question_text),
            )
            self.answer_list.addItem(entry)
        if self.answer_list.count():
            self.answer_list.setCurrentRow(0)
        else:
            self.detail.setHtml(
                rich_document(
                    "<h3>No interview history yet</h3>"
                    "<p>Completed reports and answers you save during practice "
                    "will appear here.</p>"
                )
            )
        if hasattr(self._page, "_library_tab_index"):
            self._page.set_library_available(bool(self.answer_list.count()))

    def _show(self) -> None:
        item = self.answer_list.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload[0] == "report":
            session = payload[1]
            report = SessionReport.model_validate(session.report)
            self.detail.setHtml(_report_html(report))
            self.practice_button.setText("Practice this stage again")
            self.practice_button.setEnabled(True)
            self.remove_button.setEnabled(False)
            return
        _, answer, question_text = payload
        self.practice_button.setText("Practice this answer")
        self.practice_button.setEnabled(True)
        self.remove_button.setEnabled(True)
        question = self._repo.get_question(answer.question_id)
        feedback = self._repo.get_feedback(answer.id)
        job = self._jobs.get(question.job_id) if question and question.job_id else None
        parts = [
            f"<h3>{html.escape(question_text)}</h3>",
            "<h4>Original answer</h4>",
            f"<p>{html.escape(answer.text)}</p>",
        ]
        metadata = []
        if job:
            metadata.append(
                f"{html.escape(job.title or 'Captured job')} · "
                f"{html.escape(job.company or 'Unknown company')}"
            )
        if question:
            metadata.extend(
                [
                    html.escape(question.category.replace("_", " ").title()),
                    html.escape(question.stage.replace("_", " ").title()),
                ]
            )
        if answer.created_at:
            metadata.append(html.escape(answer.created_at[:10]))
        if metadata:
            palette = current()
            parts.append(f"<p style='color:{palette.text_muted}'>{' · '.join(metadata)}</p>")
        if feedback and feedback.stronger_version:
            parts.extend(
                [
                    "<h4>Improved answer</h4>",
                    f"<p>{html.escape(feedback.stronger_version)}</p>",
                ]
            )
        if answer.words_per_minute:
            palette = current()
            parts.append(
                f"<p style='color:{palette.text_muted}'>Spoken · "
                f"{answer.words_per_minute:.0f} words/min"
                f"{f' · {answer.duration_s:.0f}s' if answer.duration_s else ''}</p>"
            )
        self.detail.setHtml(rich_document("".join(parts)))

    def _practice_again(self) -> None:
        item = self.answer_list.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload[0] == "report":
            session = payload[1]
            stage_index = self._page.setup_tab.stage_combo.findData(session.stage)
            if stage_index >= 0:
                self._page.setup_tab.stage_combo.setCurrentIndex(stage_index)
            persona_index = self._page.setup_tab.persona_combo.findData(session.persona)
            if persona_index >= 0:
                self._page.setup_tab.persona_combo.setCurrentIndex(persona_index)
            self._page.tabs.setCurrentWidget(self._page.setup_tab)
            self._page.setup_tab.status.setText(
                "Interview style restored. Start a new session when ready."
            )
            return
        _, answer, _ = payload
        question = self._repo.get_question(answer.question_id)
        if question is not None:
            stage_index = self._page.setup_tab.stage_combo.findData(question.stage)
            if stage_index >= 0:
                self._page.setup_tab.stage_combo.setCurrentIndex(stage_index)
            if question.job_id:
                for index in range(self._page.setup_tab.job_combo.count()):
                    job = self._page.setup_tab.job_combo.itemData(index)
                    if job is not None and job.id == question.job_id:
                        self._page.setup_tab.job_combo.setCurrentIndex(index)
                        break
        self._page.tabs.setCurrentWidget(self._page.setup_tab)
        self._page.setup_tab.status.setText(
            "Context restored. Start a new session to practise this answer again."
        )

    def _remove(self) -> None:
        item = self.answer_list.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload[0] != "answer":
            return
        _, answer, _ = payload
        self._service.remove_from_library(answer)
        self.reload()


# -- HTML ---------------------------------------------------------------------


def _viseme_for_character(character: str) -> str | None:
    lowered = character.casefold()
    if lowered in "bmp":
        return "explosive"
    if lowered in "fv":
        return "dental_lip"
    if lowered in "oquw":
        return "tight_o"
    if lowered in "eiy":
        return "wide"
    if lowered in "cjgxz":
        return "affricate"
    if lowered == "a":
        return "open"
    if lowered in "dlnrsthk":
        return "tight"
    return "lip_open" if lowered.isalpha() else None


def _voice_settings_label(settings: VoiceSettings) -> str:
    if settings.provider == VoiceProvider.KOKORO:
        description = KOKORO_VOICES.get(settings.voice, settings.voice)
        voice_name = description.split(" — ", 1)[0]
        return f"Kokoro · {voice_name}"
    if settings.provider == VoiceProvider.ELEVENLABS:
        return f"ElevenLabs · {settings.voice or 'selected voice'}"
    return "Neural voice required"


def _report_card(title: str, items: list[str], color: str, fallback: str) -> str:
    content = (
        "<ul style='margin-top:8px'>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in items)
        + "</ul>"
        if items
        else f"<p style='color:{current().text_muted}'>{html.escape(fallback)}</p>"
    )
    palette = current()
    return (
        f"<td width='50%' valign='top' style='background:{palette.surface_raised};"
        f"border:1px solid {palette.border};padding:16px'>"
        f"<div style='color:{color};font-size:16px;font-weight:600'>"
        f"{html.escape(title)}</div>{content}</td>"
    )


def _report_html(report) -> str:
    palette = current()
    summary = html.escape(
        report.overall_summary
        or "Your answers were saved. Review the priorities below before your next practice."
    )
    parts = [
        "<h2>Session report</h2>",
        f"<div style='background:{palette.surface_raised};border-left:4px solid "
        f"{palette.accent};padding:16px;margin-bottom:18px'>"
        "<div style='font-size:13px;font-weight:600;"
        f"color:{palette.accent};margin-bottom:6px'>READINESS SUMMARY</div>"
        f"<p style='margin:0'>{summary}</p></div>",
        "<table width='100%' cellspacing='10' cellpadding='0'>",
        "<tr>",
        _report_card(
            "What worked",
            report.strongest_answers,
            palette.success,
            "No clear strength was identified from this session.",
        ),
        _report_card(
            "Where to improve",
            report.weakest_answers,
            palette.warning,
            "No specific weak answer was identified.",
        ),
        "</tr><tr>",
        _report_card(
            "Patterns across answers",
            report.recurring_patterns,
            palette.text,
            "No recurring pattern was identified.",
        ),
        _report_card(
            "Next practice plan",
            report.priorities,
            palette.accent,
            "Repeat this session with more specific examples and outcomes.",
        ),
        "</tr></table>",
    ]
    return rich_document("".join(parts))
