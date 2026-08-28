"""Access to the canonical packaged AptiorDesk artwork."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from aptiordesk.ui.theme.shared import token


def application_icon_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "aptior.png"


def application_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(application_mark(size))
    return icon


def application_mark(size: int) -> QPixmap:
    inset = max(2, round(size * 0.08))
    artwork = QPixmap(str(application_icon_path())).scaled(
        size - inset * 2,
        size - inset * 2,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(token("brand-coral")))
    radius = max(4, round(size * 0.23))
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    painter.drawPixmap(
        (size - artwork.width()) // 2,
        (size - artwork.height()) // 2,
        artwork,
    )
    painter.end()
    return canvas


__all__ = ["application_icon", "application_icon_path", "application_mark"]
