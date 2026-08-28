"""Candidate webcam tile for the live interview room."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.ui.theme.tokens import SPACE


class CandidateCameraTile(QFrame):
    """A self-explanatory local preview rather than an unexplained black box."""

    state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "pane")
        self.setMinimumHeight(210)
        self._camera: QCamera | None = None
        self._capture: QMediaCaptureSession | None = None
        self._initialized = False
        self._enabled = False
        self._starting = False
        self._start_timeout = QTimer(self)
        self._start_timeout.setSingleShot(True)
        self._start_timeout.setInterval(8_000)
        self._start_timeout.timeout.connect(self._start_timed_out)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        layout.setSpacing(SPACE["sm"])
        heading = QHBoxLayout()
        title = QLabel("You")
        title.setProperty("role", "paneTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.status_badge = QLabel("Camera off")
        self.status_badge.setProperty("role", "badge")
        self.status_badge.setProperty("tone", "neutral")
        heading.addWidget(self.status_badge)
        layout.addLayout(heading)

        self.stack = QStackedWidget()
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        self.stack.addWidget(self.video)
        self.placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        placeholder_layout.addStretch(1)
        self.state_title = QLabel("Camera is off")
        self.state_title.setProperty("role", "sectionTitle")
        self.state_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.state_title)
        self.state_detail = QLabel("Turn on your camera when you want a local self preview.")
        self.state_detail.setProperty("role", "hint")
        self.state_detail.setWordWrap(True)
        self.state_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.state_detail)
        placeholder_layout.addStretch(1)
        self.stack.addWidget(self.placeholder)
        self.stack.setCurrentWidget(self.placeholder)
        layout.addWidget(self.stack, 1)

    @property
    def camera_enabled(self) -> bool:
        return self._enabled

    @property
    def camera_busy(self) -> bool:
        return self._enabled or self._starting or self._camera is not None

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._show_state("Camera is off", "Camera access starts only when you turn it on.")

    def toggle(self) -> None:
        if self.camera_busy:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        self.initialize()
        if self.camera_busy:
            return
        self._starting = True
        self._show_state(
            "Starting camera…",
            "Waiting for the operating system to provide the local preview.",
        )
        self.status_badge.setText("Starting")
        self.status_badge.setProperty("tone", "accent")
        self._repolish_badge()
        self.state_changed.emit("starting")
        # Paint the starting state before device enumeration asks the native
        # multimedia backend for cameras.
        QTimer.singleShot(0, self._open_camera)

    def _open_camera(self) -> None:
        if not self._starting:
            return
        devices = QMediaDevices.videoInputs()
        if not devices:
            self._starting = False
            self._show_state(
                "No camera available",
                "AptiorDesk could not find a webcam. You can continue with audio or text.",
                tone="warning",
            )
            self.state_changed.emit("unavailable")
            return
        try:
            self._camera = QCamera(devices[0], self)
            self._capture = QMediaCaptureSession(self)
            self._capture.setCamera(self._camera)
            self._capture.setVideoOutput(self.video)
            self._camera.errorOccurred.connect(self._camera_error)
            self._camera.activeChanged.connect(self._active_changed)
            self._start_timeout.start()
            self._camera.start()
        except Exception as exc:
            self._camera_error(QCamera.Error.CameraError, str(exc))

    def stop(self) -> None:
        self._release_camera()
        self._enabled = False
        self._starting = False
        self._show_state(
            "Camera is off",
            "Your interview can continue with microphone or typed answers.",
        )
        self.state_changed.emit("disabled")

    def _active_changed(self, active: bool) -> None:
        self._enabled = active
        if active:
            self._starting = False
            self._start_timeout.stop()
            self.stack.setCurrentWidget(self.video)
            self.status_badge.setText("Camera on")
            self.status_badge.setProperty("tone", "success")
            self._repolish_badge()
            self.state_changed.emit("enabled")
        elif (
            not self._starting
            and self._camera is not None
            and self._camera.error() == QCamera.Error.NoError
        ):
            self._release_camera()
            self._show_state(
                "Camera stopped",
                "The operating system stopped the camera. Check whether another "
                "application is using it, then try again.",
                tone="warning",
            )
            self.state_changed.emit("denied")

    def _camera_error(self, _error, message: str) -> None:
        detail = message.strip() or (
            "Camera access was denied or the device is already in use. "
            "Update your privacy settings and try again."
        )
        self._release_camera()
        self._enabled = False
        self._starting = False
        self._show_state("Camera unavailable", detail, tone="warning")
        self.state_changed.emit("denied")

    def _start_timed_out(self) -> None:
        if not self._starting:
            return
        self._release_camera()
        self._enabled = False
        self._starting = False
        self._show_state(
            "Camera start timed out",
            "The camera did not respond within 8 seconds. Close other camera apps "
            "or check privacy permissions, then try again.",
            tone="warning",
        )
        self.state_changed.emit("timeout")

    def _release_camera(self) -> None:
        self._start_timeout.stop()
        camera = self._camera
        capture = self._capture
        self._camera = None
        self._capture = None
        if camera is not None:
            camera.stop()
            camera.deleteLater()
        if capture is not None:
            capture.setVideoOutput(None)
            capture.setCamera(None)
            capture.deleteLater()

    def _show_state(self, title: str, detail: str, *, tone: str = "neutral") -> None:
        self.state_title.setText(title)
        self.state_detail.setText(detail)
        self.status_badge.setText("Camera unavailable" if tone == "warning" else "Camera off")
        self.status_badge.setProperty("tone", tone)
        self._repolish_badge()
        self.stack.setCurrentWidget(self.placeholder)

    def _repolish_badge(self) -> None:
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
