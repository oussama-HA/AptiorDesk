"""Theme application and the currently-active palette.

`current()` is deliberately module-level state: widgets need the active
palette to tint icons and inline HTML, and threading a theme object through
every constructor would add noise for no benefit in a single-window app.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication

from aptiordesk.ui.theme.tokens import DEFAULT_THEME, THEMES, Palette, build_stylesheet

log = logging.getLogger(__name__)

_current: Palette = THEMES[DEFAULT_THEME]

SETTING_KEY = "ui.theme"


def current() -> Palette:
    return _current


def apply_theme(name: str, app: QApplication | None = None) -> Palette:
    """Set the active palette and restyle the running application."""
    global _current
    _current = THEMES.get(name, THEMES[DEFAULT_THEME])
    target = app or QApplication.instance()
    if target is not None:
        target.setStyleSheet(stylesheet())
    return _current


def stylesheet() -> str:
    return build_stylesheet(_current, _chevron_path())


def _chevron_path() -> str:
    """Cache a themed combo-box arrow on disk; QSS needs a real image file.
    Failure is non-fatal — Qt falls back to its native arrow."""
    from aptiordesk.ui.theme import icons

    try:
        from aptiordesk.core import paths

        target = paths.data_dir() / "assets" / f"chevron-{_current.name}.png"
        return icons.write_png("chevron-down", _current.text_muted, 20, target)
    except Exception as exc:  # read-only home, no QGuiApplication yet, ...
        log.debug("Could not cache combo-box arrow: %s", exc)
        return ""


__all__ = ["Palette", "SETTING_KEY", "apply_theme", "current", "stylesheet"]
