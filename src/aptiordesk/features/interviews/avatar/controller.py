"""One state machine owns every non-speech avatar movement.

The renderer receives normalized blink and head-pose values. It does not run
its own timers, which prevents idle motion, nods, and state transitions from
overwriting each other.
"""

from __future__ import annotations

import random
from enum import StrEnum

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPauseAnimation,
    QSequentialAnimationGroup,
    QTimer,
    QVariantAnimation,
    Signal,
)


class AvatarState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    TRANSITIONING = "transitioning"
    PAUSED = "paused"


class AvatarController(QObject):
    """Natural, conservative motion scheduling for an interviewer avatar."""

    state_changed = Signal(str)
    blink_changed = Signal(float)
    head_pose_changed = Signal(float, float, float, float)
    nod_started = Signal(str)

    def __init__(self, parent=None, *, rng: random.Random | None = None):
        super().__init__(parent)
        self._rng = rng or random.Random()
        self.state = AvatarState.IDLE
        self.visible = True
        self.reduced_motion = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._blink)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._idle_motion)
        self._blink_animation: QSequentialAnimationGroup | None = None
        self._head_animation: QVariantAnimation | None = None
        self._head = (0.0, 0.0, 0.0, 0.0)
        self._last_audio_level = 0.0
        self._phrase_started_ms: int | None = None
        self._last_voiced_ms: int | None = None
        self._last_nod_ms = -30_000
        self._nod_in_progress = False
        self._schedule_blink()
        self._schedule_idle()

    def set_state(self, state: AvatarState | str) -> None:
        state = AvatarState(state)
        if state == self.state:
            return
        self.state = state
        self.state_changed.emit(state.value)
        if state in {
            AvatarState.SPEAKING,
            AvatarState.THINKING,
            AvatarState.TRANSITIONING,
            AvatarState.PAUSED,
        }:
            self._stop_head_motion(return_to_neutral=True)
        if state != AvatarState.LISTENING:
            self._reset_listening_detection()
        self._schedule_idle()

    def set_visible(self, visible: bool) -> None:
        self.visible = visible
        if not visible:
            self._stop_head_motion(return_to_neutral=True)
        else:
            self._schedule_idle()

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion = enabled
        if enabled:
            self._stop_head_motion(return_to_neutral=True)
        self._schedule_idle()

    def observe_candidate_audio(self, level: float, elapsed_ms: int) -> None:
        """Conservatively nod after a voiced phrase ends in a real pause."""
        if self.state != AvatarState.LISTENING or self._nod_in_progress:
            return
        level = max(0.0, min(1.0, level))
        voiced = level >= 0.055
        if voiced:
            if self._phrase_started_ms is None:
                self._phrase_started_ms = elapsed_ms
            self._last_voiced_ms = elapsed_ms
        elif (
            self._phrase_started_ms is not None
            and self._last_voiced_ms is not None
            and elapsed_ms - self._last_voiced_ms >= 650
        ):
            phrase_ms = self._last_voiced_ms - self._phrase_started_ms
            enough_progress = elapsed_ms >= 5_000 and phrase_ms >= 1_500
            enough_spacing = elapsed_ms - self._last_nod_ms >= 10_000
            if enough_progress and enough_spacing and self._rng.random() < 0.42:
                self.request_nod(elapsed_ms=elapsed_ms)
            self._phrase_started_ms = None
            self._last_voiced_ms = None
        self._last_audio_level = level

    def request_nod(self, *, elapsed_ms: int = 0) -> bool:
        if (
            self.state != AvatarState.LISTENING
            or self._nod_in_progress
            or self.reduced_motion
            or not self.visible
        ):
            return False
        kind_roll = self._rng.random()
        kind = "single" if kind_roll < 0.72 else "slow" if kind_roll < 0.94 else "double"
        self._last_nod_ms = elapsed_ms
        self._nod_in_progress = True
        self.nod_started.emit(kind)
        sequence = [(0.0, 0.0), (2.2, 1.0), (0.0, 0.0)]
        duration = 640 if kind == "slow" else 440
        if kind == "double":
            sequence = [(0.0, 0.0), (2.0, 1.0), (0.0, 0.0), (1.4, 1.0), (0.0, 0.0)]
            duration = 720
        self._animate_pitch_sequence(sequence, duration)
        return True

    def shutdown(self) -> None:
        self._blink_timer.stop()
        self._idle_timer.stop()
        if self._blink_animation is not None:
            self._blink_animation.stop()
        self._stop_head_motion(return_to_neutral=True)
        self.blink_changed.emit(0.0)

    # -- blink -------------------------------------------------------------

    def _next_blink_delay_ms(self) -> int:
        # A skewed distribution produces mostly ordinary gaps, with occasional
        # longer attentive holds. Never schedule a rapid accidental loop.
        base = self._rng.triangular(3_200, 8_600, 4_900)
        if self._rng.random() < 0.12:
            base += self._rng.uniform(1_500, 3_800)
        return int(max(2_800, base))

    def _schedule_blink(self) -> None:
        self._blink_timer.start(self._next_blink_delay_ms())

    def _blink(self) -> None:
        if not self.visible or self.state in {
            AvatarState.TRANSITIONING,
            AvatarState.PAUSED,
        }:
            self._blink_timer.start(1_500)
            return
        if self._blink_animation is not None:
            self._blink_animation.stop()
        group = QSequentialAnimationGroup(self)
        self._append_one_blink(group)
        if self._rng.random() < 0.075:
            group.addAnimation(QPauseAnimation(self._rng.randint(110, 180)))
            self._append_one_blink(group, lighter=True)
        group.finished.connect(self._blink_finished)
        self._blink_animation = group
        group.start()

    def _append_one_blink(self, group: QSequentialAnimationGroup, *, lighter: bool = False) -> None:
        closed = 0.88 if lighter else 1.0
        close = QVariantAnimation(group)
        close.setStartValue(0.0)
        close.setEndValue(closed)
        close.setDuration(82 if not lighter else 72)
        close.setEasingCurve(QEasingCurve.Type.OutCubic)
        close.valueChanged.connect(lambda value: self.blink_changed.emit(float(value)))
        group.addAnimation(close)
        group.addAnimation(QPauseAnimation(42 if not lighter else 30))
        opening = QVariantAnimation(group)
        opening.setStartValue(closed)
        opening.setEndValue(0.0)
        opening.setDuration(118 if not lighter else 102)
        opening.setEasingCurve(QEasingCurve.Type.InOutCubic)
        opening.valueChanged.connect(lambda value: self.blink_changed.emit(float(value)))
        group.addAnimation(opening)

    def _blink_finished(self) -> None:
        self.blink_changed.emit(0.0)
        if self._blink_animation is not None:
            self._blink_animation.deleteLater()
        self._blink_animation = None
        self._schedule_blink()

    # -- head motion -------------------------------------------------------

    def _schedule_idle(self) -> None:
        self._idle_timer.stop()
        if (
            not self.visible
            or self.reduced_motion
            or self.state
            not in {
                AvatarState.IDLE,
                AvatarState.LISTENING,
                AvatarState.SPEAKING,
            }
        ):
            return
        if self.state == AvatarState.SPEAKING:
            self._idle_timer.start(self._rng.randint(1_900, 3_800))
        else:
            self._idle_timer.start(self._rng.randint(3_600, 7_800))

    def _idle_motion(self) -> None:
        if (
            not self.visible
            or self.reduced_motion
            or self.state
            not in {
                AvatarState.IDLE,
                AvatarState.LISTENING,
                AvatarState.SPEAKING,
            }
            or self._nod_in_progress
        ):
            self._schedule_idle()
            return
        intensity = (
            0.55
            if self.state == AvatarState.SPEAKING
            else 0.65
            if self.state == AvatarState.LISTENING
            else 1.0
        )
        target = (
            self._rng.uniform(-1.7, 1.7) * intensity,
            self._rng.uniform(-0.8, 0.9) * intensity,
            self._rng.uniform(-0.65, 0.65) * intensity,
            self._rng.uniform(-0.0025, 0.0025) * intensity,
        )
        self._animate_head(target, self._rng.randint(900, 1_550), return_after=True)

    def _animate_head(
        self, target: tuple[float, float, float, float], duration: int, *, return_after: bool
    ) -> None:
        self._stop_head_motion(return_to_neutral=False)
        start = self._head
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.InOutSine)

        def update(value) -> None:
            progress = float(value)
            self._head = tuple(
                origin + (destination - origin) * progress
                for origin, destination in zip(start, target, strict=True)
            )
            self.head_pose_changed.emit(*self._head)

        animation.valueChanged.connect(update)
        if return_after:
            animation.finished.connect(
                lambda: QTimer.singleShot(
                    self._rng.randint(650, 1_900),
                    lambda: self._animate_head((0.0, 0.0, 0.0, 0.0), 900, return_after=False),
                )
            )
            animation.finished.connect(self._schedule_idle)
        self._head_animation = animation
        animation.start()

    def _animate_pitch_sequence(self, points: list[tuple[float, float]], duration: int) -> None:
        self._stop_head_motion(return_to_neutral=False)
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.InOutSine)

        def update(value) -> None:
            progress = float(value)
            scaled = progress * (len(points) - 1)
            index = min(len(points) - 2, int(scaled))
            local = scaled - index
            pitch = points[index][0] + (points[index + 1][0] - points[index][0]) * local
            self._head = (0.0, pitch, 0.0, 0.0)
            self.head_pose_changed.emit(*self._head)

        animation.valueChanged.connect(update)

        def finish() -> None:
            self._head = (0.0, 0.0, 0.0, 0.0)
            self.head_pose_changed.emit(*self._head)
            self._nod_in_progress = False
            self._head_animation = None
            self._schedule_idle()

        animation.finished.connect(finish)
        self._head_animation = animation
        animation.start()

    def _stop_head_motion(self, *, return_to_neutral: bool) -> None:
        if self._head_animation is not None:
            self._head_animation.stop()
            self._head_animation.deleteLater()
            self._head_animation = None
        self._nod_in_progress = False
        if return_to_neutral and self._head != (0.0, 0.0, 0.0, 0.0):
            self._head = (0.0, 0.0, 0.0, 0.0)
            self.head_pose_changed.emit(*self._head)

    def _reset_listening_detection(self) -> None:
        self._last_audio_level = 0.0
        self._phrase_started_ms = None
        self._last_voiced_ms = None
