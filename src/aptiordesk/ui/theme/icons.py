"""Inline SVG icon set.

Icons are stroke paths defined here as plain strings, tinted at runtime to
whatever colour the current theme needs and rasterised through Qt's SVG
renderer. No icon font, no image assets, no third-party licence to track.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24 viewBox, 1.6 stroke, round caps — a consistent geometric set.
_PATHS: dict[str, str] = {
    "home": "M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5M9.5 20v-6h5v6",
    "user": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4.5 20c0-3.6 3.4-5.5 7.5-5.5s7.5 1.9 7.5 5.5",
    "file": "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z M14 3v5h5 M9 13h6 M9 17h6",
    "briefcase": (
        "M3.5 8.5h17v10a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-10Z "
        "M9 8.5V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2.5 M3.5 13h17"
    ),
    "wand": ("M15 4V2 M15 10V8 M12.5 6h-2 M19.5 6h-2 M4 20l10-10 M13 5.5 18.5 11 M6.5 17.5 3 21"),
    "mail": "M3.5 6.5h17v11h-17z M3.5 7l8.5 6 8.5-6",
    "mic": (
        "M12 3a2.5 2.5 0 0 1 2.5 2.5v6a2.5 2.5 0 0 1-5 0v-6A2.5 2.5 0 0 1 12 3Z "
        "M6 11a6 6 0 0 0 12 0 M12 17v4 M9 21h6"
    ),
    "settings": (
        "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z "
        "M19.5 12a7.5 7.5 0 0 0-.15-1.5l2-1.5-2-3.4-2.3.9a7.5 7.5 0 0 0-2.6-1.5L14 2h-4"
        "l-.45 2.5a7.5 7.5 0 0 0-2.6 1.5l-2.3-.9-2 3.4 2 1.5a7.5 7.5 0 0 0 0 3l-2 1.5 "
        "2 3.4 2.3-.9a7.5 7.5 0 0 0 2.6 1.5L10 22h4l.45-2.5a7.5 7.5 0 0 0 2.6-1.5l2.3.9 "
        "2-3.4-2-1.5c.1-.5.15-1 .15-1.5Z"
    ),
    "shield": ("M12 3l7 3v5.5c0 4.3-2.9 8.2-7 9.5-4.1-1.3-7-5.2-7-9.5V6l7-3Z M9 12l2 2 4-4"),
    "target": (
        "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z "
        "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Z "
        "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"
    ),
    "edit": "M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3Z M14.5 6.5l3 3",
    "trash": (
        "M4.5 7h15 M9.5 7V5.5a1.5 1.5 0 0 1 1.5-1.5h2a1.5 1.5 0 0 1 1.5 1.5V7 "
        "M6.5 7l.8 12a2 2 0 0 0 2 1.9h5.4a2 2 0 0 0 2-1.9L17.5 7 "
        "M10.5 11v6 M13.5 11v6"
    ),
    "plus": "M12 5v14 M5 12h14",
    "check": "M4 12.5 9.5 18 20 6.5",
    "spark": "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z",
    "inbox": ("M3.5 12.5h4l1.5 3h6l1.5-3h4 M5 5.5h14l1.5 7v6h-17v-6L5 5.5Z"),
    "lock": ("M6.5 10.5h11v9h-11z M9 10.5V7.5a3 3 0 0 1 6 0v3 M12 14v2.5"),
    "alert": "M12 8v5 M12 16.5v.5 M12 3 2.5 20h19L12 3Z",
    "terminal": "M4 5h16v14H4z M7 9l3 3-3 3 M12 15h5",
    "chevron-down": "M6 9.5 12 15.5 18 9.5",
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="{color}" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


def available() -> list[str]:
    return sorted(_PATHS)


@lru_cache(maxsize=256)
def _render(name: str, color: str, size: int) -> QPixmap:
    # Paths are stored as one string of sub-paths separated by " M"; splitting
    # drops that leading M on every continuation segment, so restore it.
    segments = _PATHS[name].split(" M")
    body = "".join(f'<path d="{seg if i == 0 else "M" + seg}"/>' for i, seg in enumerate(segments))
    renderer = QSvgRenderer(_SVG.format(color=color, body=body).encode("utf-8"))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def icon(name: str, color: str, size: int = 18) -> QIcon:
    """A single-colour icon. Unknown names return an empty icon rather than
    raising — a missing glyph should never crash a page."""
    if name not in _PATHS:
        return QIcon()
    return QIcon(_render(name, color, size))


def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    if name not in _PATHS:
        return QPixmap()
    return _render(name, color, size)


ICON_SIZE = QSize(18, 18)


def write_png(name: str, color: str, size: int, path) -> str:
    """Rasterise an icon to disk and return a QSS-friendly url() path.

    Qt Style Sheets cannot draw an arbitrary shape for sub-controls such as
    QComboBox::down-arrow — the CSS border-triangle trick renders as a square
    — so those need a real image file.
    """
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pixmap(name, color, size).save(str(target), "PNG")
    return target.as_posix()
