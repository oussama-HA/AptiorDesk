"""Live progress for resume extraction.

Replaces a single mutating status label. The user watches each section go
pending → reading → done in place, with an overall bar and elapsed time, so a
ten-second extraction reads as visible work instead of a frozen app. Sections
run concurrently, so rows light up and complete out of order — which is
exactly what is happening.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from aptiordesk.features.resumes.extraction import SECTIONS, SectionProgress
from aptiordesk.ui.theme.tokens import SPACE

#: Row states, mapped to a glyph and a theme role for its colour.
_STATES = {
    "pending": ("○", "hint"),
    "running": ("◉", "accent"),
    "done": ("✓", "success"),
    "failed": ("!", "error"),
}

_FRIENDLY = {
    "contact": "Contact details and summary",
    "experience": "Work experience",
    "education": "Education",
    "skills": "Skills, certifications, and languages",
    "extras": "Projects, awards, and volunteering",
}

_STATUS_TEXT = {
    "pending": "waiting",
    "running": "reading…",
    "done": "done",
    "failed": "failed — kept for review",
}


class ExtractionProgressDialog(QDialog):
    """Shows the five sections being read, live.

    The dialog never blocks the work: extraction runs on a Worker thread and
    keeps going even if this window is closed. The pages close it via
    ``finish()`` when the result or error arrives.
    """

    def __init__(self, filename: str, char_count: int, model: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reading your resume")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["md"])

        title = QLabel("Reading your resume")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        source = QLabel(
            f"{filename} · {char_count:,} characters" + (f" · using {model}" if model else "")
        )
        source.setProperty("role", "hint")
        source.setWordWrap(True)
        layout.addWidget(source)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE["md"])
        grid.setVerticalSpacing(SPACE["sm"])
        self._rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for row, spec in enumerate(SECTIONS):
            glyph = QLabel()
            glyph.setFixedWidth(18)
            glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(_FRIENDLY.get(spec.key, spec.label.capitalize()))
            status = QLabel()
            status.setProperty("role", "hint")
            grid.addWidget(glyph, row, 0)
            grid.addWidget(name, row, 1)
            grid.addWidget(status, row, 2, alignment=Qt.AlignmentFlag.AlignRight)
            grid.setColumnStretch(1, 1)
            self._rows[spec.key] = (glyph, name, status)
            self._set_state(spec.key, "pending")
        layout.addLayout(grid)

        self.bar = QProgressBar()
        self.bar.setRange(0, len(SECTIONS))
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        footer = QHBoxLayout()
        note = QLabel("The sections are read in parallel, so they finish in any order.")
        note.setProperty("role", "hint")
        footer.addWidget(note, 1)
        self.elapsed_label = QLabel("0 s")
        self.elapsed_label.setProperty("role", "hint")
        footer.addWidget(self.elapsed_label)
        layout.addLayout(footer)

        self._seconds = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # -- updates (delivered on the UI thread via Worker.progress) -------------

    def handle_event(self, event: SectionProgress) -> None:
        if event.key not in self._rows:
            return
        self._set_state(event.key, event.status)
        if event.status in ("done", "failed"):
            self.bar.setValue(event.completed)

    def finish(self) -> None:
        """Stop the clock and close. Safe to call whether or not visible."""
        self._timer.stop()
        self.accept()

    # -- internals -------------------------------------------------------------

    def _set_state(self, key: str, state: str) -> None:
        glyph, _name, status = self._rows[key]
        symbol, role = _STATES.get(state, _STATES["pending"])
        glyph.setText(symbol)
        glyph.setProperty("role", role)
        glyph.style().polish(glyph)
        status.setText(_STATUS_TEXT.get(state, ""))
        if state == "failed":
            status.setProperty("role", "error")
            status.style().polish(status)

    def _tick(self) -> None:
        self._seconds += 0.5
        self.elapsed_label.setText(f"{self._seconds:.0f} s")


__all__ = ["ExtractionProgressDialog"]
