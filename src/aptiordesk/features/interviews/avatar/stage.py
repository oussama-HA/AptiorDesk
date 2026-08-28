"""Live Qt Quick 3D stage for an AptiorDesk interviewer model."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.features.interviews.avatar.controller import AvatarController
from aptiordesk.ui.theme.tokens import SPACE


class AvatarStage(QFrame):
    """Renderer adapter; all scheduling remains in :class:`AvatarController`."""

    library_requested = Signal()
    ready = Signal(int)

    def __init__(self, controller: AvatarController, parent=None):
        super().__init__(parent)
        self.setProperty("role", "pane")
        self.setMinimumSize(300, 240)
        self._controller = controller
        self._quick: QQuickWidget | None = None
        self._controls: dict[str, list[QObject]] = {}
        self._blink_controls: tuple[str, ...] = ()
        self._viseme_controls: dict[str, tuple[str, ...]] = {}
        self._viseme_profiles: dict[str, tuple[tuple[str, float, float], ...]] = {}
        self._mouth_current: dict[str, float] = {}
        self._mouth_target: dict[str, float] = {}
        self._mouth_timer = QTimer(self)
        self._mouth_timer.setInterval(16)
        self._mouth_timer.timeout.connect(self._animate_mouth)
        self._bind_attempts = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        toolbar = QWidget()
        toolbar.setProperty("role", "layoutOnly")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        self.avatar_name = QLabel("AptiorDesk interviewer")
        self.avatar_name.setProperty("role", "paneTitle")
        toolbar_layout.addWidget(self.avatar_name)
        toolbar_layout.addStretch(1)
        change = QPushButton("Change")
        change.setToolTip("Choose a different interviewer")
        change.setProperty("size", "sm")
        change.clicked.connect(self.library_requested)
        toolbar_layout.addWidget(change)
        layout.addWidget(toolbar)

        self._stage_host = QWidget()
        self._stage_host.setProperty("role", "layoutOnly")
        self._stack = QStackedLayout(self._stage_host)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._placeholder = self._build_placeholder()
        self._stack.addWidget(self._placeholder)
        layout.addWidget(self._stage_host, 1)
        controller.blink_changed.connect(self.set_blink)
        controller.head_pose_changed.connect(self.set_head_pose)
        controller.state_changed.connect(self.set_state)

    def _build_placeholder(self) -> QWidget:
        placeholder = QWidget()
        placeholder.setProperty("role", "layoutOnly")
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["2xl"])
        layout.setSpacing(SPACE["md"])
        layout.addStretch(1)
        title = QLabel("Preparing your interviewer")
        title.setProperty("role", "sectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        detail = QLabel(
            "AptiorDesk is loading the selected interviewer from its built-in avatar library."
        )
        detail.setProperty("role", "hint")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        layout.addWidget(detail)
        choose = QPushButton("Browse AptiorDesk avatars")
        choose.setProperty("accent", True)
        choose.clicked.connect(self.library_requested)
        layout.addWidget(choose, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return placeholder

    def load_component(self, component_path: str | Path) -> None:
        component_path = Path(component_path)
        if not component_path.is_file():
            return
        if self._quick is None:
            quick = QQuickWidget(self._stage_host)
            quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            quick.setClearColor(Qt.GlobalColor.transparent)
            qml = Path(__file__).with_name("avatar_stage.qml")
            quick.setSource(QUrl.fromLocalFile(str(qml)))
            self._quick = quick
            self._stack.addWidget(quick)
        root = self._quick.rootObject()
        if root is None:
            return
        root.setProperty("componentSource", QUrl.fromLocalFile(str(component_path.resolve())))
        root.setProperty("avatarState", self._controller.state.value)
        self._stack.setCurrentWidget(self._quick)
        self._controls = {}
        self._blink_controls = ()
        self._viseme_controls = {}
        self._viseme_profiles = {}
        self._mouth_current = {}
        self._mouth_target = {}
        self._mouth_timer.stop()
        self._bind_attempts = 0
        QTimer.singleShot(250, self._bind_model)

    def set_avatar_name(self, name: str) -> None:
        self.avatar_name.setText(f"Interviewer · {name}")

    @property
    def has_avatar(self) -> bool:
        return self._quick is not None

    @property
    def is_ready(self) -> bool:
        return bool(self._controls)

    def show_loading(self, detail: str = "Preparing avatar…") -> None:
        labels = self._placeholder.findChildren(QLabel)
        if labels:
            labels[-1].setText(detail)
        self._stack.setCurrentWidget(self._placeholder)

    def show_error(self, message: str) -> None:
        labels = self._placeholder.findChildren(QLabel)
        if labels:
            labels[-1].setText(message)
            labels[-1].setProperty("role", "error")
        self._stack.setCurrentWidget(self._placeholder)

    def set_blink(self, weight: float) -> None:
        # A conditioned model can expose the same expression through several
        # naming conventions. Driving every alias compounds the deformation
        # (Ari's brows and eyelids were being moved by 20+ targets at once).
        # ``_select_control_families`` chooses exactly one compatible pair.
        for name in self._blink_controls:
            self._set_weight(name, weight)

    def set_viseme(self, name: str | None, weight: float) -> None:
        active_controls = {
            control
            for profile in self._viseme_profiles.values()
            for control, _scale, _maximum in profile
        }
        self._mouth_target = {control: 0.0 for control in active_controls}
        if name:
            for control, scale, maximum in self._viseme_profiles.get(name, ()):
                self._mouth_target[control] = min(maximum, max(0.0, weight) * scale)
        if active_controls and not self._mouth_timer.isActive():
            self._mouth_timer.start()

    def _animate_mouth(self) -> None:
        """Ease lip targets so the lower lip follows the jaw instead of snapping."""
        if not self._mouth_target:
            self._mouth_timer.stop()
            return
        settled = True
        for control, target in self._mouth_target.items():
            current = self._mouth_current.get(control, 0.0)
            # Retain natural interpolation while reaching the audio target
            # quickly enough to avoid visible lip lag.
            response = 0.58 if target < current else 0.46
            value = current + (target - current) * response
            if abs(target - value) < 0.004:
                value = target
            else:
                settled = False
            self._mouth_current[control] = value
            self._set_weight(control, value)
        if settled:
            self._mouth_timer.stop()

    def set_head_pose(self, yaw: float, pitch: float, roll: float, vertical: float) -> None:
        if self._quick is None or self._quick.rootObject() is None:
            return
        root = self._quick.rootObject()
        root.setProperty("headYaw", yaw)
        root.setProperty("headPitch", pitch)
        root.setProperty("headRoll", roll)
        root.setProperty("headVertical", vertical)

    def set_state(self, state: str) -> None:
        if self._quick is not None and self._quick.rootObject() is not None:
            self._quick.rootObject().setProperty("avatarState", state)

    def _bind_model(self) -> None:
        if self._quick is None or self._quick.rootObject() is None:
            return
        root = self._quick.rootObject()
        controls: dict[str, list[QObject]] = {}
        for child in root.findChildren(QObject):
            name = child.objectName()
            if name and child.metaObject().indexOfProperty("weight") >= 0:
                controls.setdefault(name, []).append(child)
        if not controls and self._bind_attempts < 80:
            # Loader instantiation can take several seconds for a detailed
            # bundled model. Keep polling without blocking the interface.
            self._bind_attempts += 1
            QTimer.singleShot(250, self._bind_model)
            return
        self._controls = controls
        self._select_control_families()
        self.set_blink(0.0)
        self.set_viseme(None, 0.0)
        if controls:
            self.ready.emit(len(controls))

    def _select_control_families(self) -> None:
        names = set(self._controls)
        blink_families = (
            ("eyeBlinkLeft", "eyeBlinkRight"),
            ("Eye_Blink_L", "Eye_Blink_R"),
            ("A14_Eye_Blink_Left", "A15_Eye_Blink_Right"),
            ("Eyes_Blink",),
        )
        self._blink_controls = next(
            (family for family in blink_families if all(name in names for name in family)),
            (),
        )

        # Prefer ARKit controls because Ari's validated GLB uses them on the
        # visible head mesh. The similarly named V_* controls belong to a
        # second facial family and do not animate that mesh reliably.
        if "jawOpen" in names:
            # `mouthClose` is intentionally absent. ARKit defines it as a
            # corrective shape used while jawOpen is active; driving it alone
            # at a neutral jaw is what made Ari's lower lip jump upward.
            profiles = {
                "open": (("jawOpen", 0.62, 0.38),),
                "explosive": (
                    ("mouthPressLeft", 0.28, 0.18),
                    ("mouthPressRight", 0.28, 0.18),
                ),
                "dental_lip": (("mouthRollLower", 0.26, 0.17),),
                "tight_o": (
                    ("mouthPucker", 0.52, 0.34),
                    ("jawOpen", 0.14, 0.09),
                ),
                "tight": (
                    ("mouthPressLeft", 0.16, 0.11),
                    ("mouthPressRight", 0.16, 0.11),
                ),
                "wide": (
                    ("mouthStretchLeft", 0.30, 0.20),
                    ("mouthStretchRight", 0.30, 0.20),
                    ("jawOpen", 0.12, 0.08),
                ),
                "affricate": (
                    ("mouthFunnel", 0.34, 0.22),
                    ("jawOpen", 0.12, 0.08),
                ),
                "lip_open": (("jawOpen", 0.48, 0.30),),
            }
            self._set_viseme_profiles(names, profiles)
            return
        legacy = {
            "open": ("V_Open",),
            "explosive": ("V_Explosive",),
            "dental_lip": ("V_Dental_Lip",),
            "tight_o": ("V_Tight_O",),
            "tight": ("V_Tight",),
            "wide": ("V_Wide",),
            "affricate": ("V_Affricate",),
            "lip_open": ("V_Lip_Open",),
        }
        profiles = {
            viseme: tuple((control, 0.72, 0.52) for control in controls)
            for viseme, controls in legacy.items()
        }
        self._set_viseme_profiles(names, profiles)

    def _set_viseme_profiles(
        self,
        names: set[str],
        profiles: dict[str, tuple[tuple[str, float, float], ...]],
    ) -> None:
        self._viseme_profiles = {
            viseme: tuple(
                (control, scale, maximum) for control, scale, maximum in profile if control in names
            )
            for viseme, profile in profiles.items()
        }
        self._viseme_controls = {
            viseme: tuple(control for control, _scale, _maximum in profile)
            for viseme, profile in self._viseme_profiles.items()
        }
        active_controls = {
            control
            for profile in self._viseme_profiles.values()
            for control, _scale, _maximum in profile
        }
        self._mouth_current = {control: 0.0 for control in active_controls}
        self._mouth_target = dict(self._mouth_current)

    def _set_weight(self, name: str, value: float) -> None:
        for target in self._controls.get(name, ()):
            target.setProperty("weight", max(0.0, min(1.0, value)))
