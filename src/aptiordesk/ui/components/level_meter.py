"""Audio level meter for voice practice.

A simplified PySide6 port of the legacy qt_audio_visualizer: a gradient bar
driven by `set_level`, which is safe to call from the UI thread only (the
recorder marshals levels across via a signal).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from aptiordesk.ui.theme import current


class LevelMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(120)
        self._level = 0.0
        self._smoothed = 0.0

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))
        # light smoothing so the bar does not strobe
        self._smoothed = self._smoothed * 0.6 + self._level * 0.4
        self.update()

    def reset(self) -> None:
        self._level = self._smoothed = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        palette = current()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.surface_raised))
        painter.drawRoundedRect(rect, 4, 4)

        if self._smoothed <= 0.01:
            return
        filled = rect.adjusted(0, 0, 0, 0)
        filled.setWidth(int(rect.width() * self._smoothed))
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        gradient.setColorAt(0.0, QColor(palette.success))
        gradient.setColorAt(0.7, QColor(palette.warning))
        gradient.setColorAt(1.0, QColor(palette.danger))
        painter.setBrush(gradient)
        painter.drawRoundedRect(filled, 4, 4)
