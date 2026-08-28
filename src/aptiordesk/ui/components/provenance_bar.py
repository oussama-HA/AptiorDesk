"""A stacked bar showing how much of an extraction is verified.

One glance answers the question the review screen exists for: how much of
this was actually read from my document (green), how much did the AI produce
that I need to check (amber), and how much is simply absent (grey). The
numbers are printed in the legend — the bar is proportion, the legend is fact.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from aptiordesk.database.models.extraction import ExtractionReport, Provenance
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE


class _Bar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: list[tuple[int, QColor]] = []
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_segments(self, segments: list[tuple[int, QColor]]) -> None:
        self._segments = [(count, colour) for count, colour in segments if count > 0]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        total = sum(count for count, _ in self._segments)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 5, 5)
        painter.setClipPath(clip)

        if total == 0:
            painter.fillRect(self.rect(), QColor(current().surface_hover))
            return
        x = 0.0
        width = float(self.width())
        for count, colour in self._segments:
            segment = width * count / total
            painter.fillRect(QRectF(x, 0, segment + 1, self.height()), colour)
            x += segment


class ProvenanceBar(QWidget):
    """The bar plus its legend, driven by an ``ExtractionReport``."""

    def __init__(self, report: ExtractionReport, parent=None):
        super().__init__(parent)
        palette = current()
        counts = _counts(report)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["xs"])

        self._bar = _Bar()
        self._bar.set_segments(
            [
                (counts[Provenance.EXTRACTED], QColor(palette.success)),
                (counts[Provenance.INFERRED], QColor(palette.warning)),
                (counts[Provenance.MISSING], QColor(palette.surface_hover)),
            ]
        )
        layout.addWidget(self._bar)

        # Everything here counts *fields*, and says so — the headline above
        # counts items (roles, degrees, skills), and mixing the units without
        # labels would make the numbers look contradictory.
        legend = QHBoxLayout()
        legend.setSpacing(SPACE["md"])
        legend.addWidget(
            _legend_chip(
                palette.success,
                f"{counts[Provenance.EXTRACTED]} fields verified in your document",
            )
        )
        if counts[Provenance.INFERRED]:
            legend.addWidget(
                _legend_chip(
                    palette.warning, f"{counts[Provenance.INFERRED]} fields for you to check"
                )
            )
        legend.addWidget(
            _legend_chip(palette.text_faint, f"{counts[Provenance.MISSING]} fields left empty")
        )
        legend.addStretch(1)
        layout.addLayout(legend)


def _counts(report: ExtractionReport) -> dict[Provenance, int]:
    counts = dict.fromkeys(Provenance, 0)
    for note in report.notes:
        counts[note.provenance] += 1
    return counts


def _legend_chip(colour: str, text: str) -> QLabel:
    chip = QLabel(f"<span style='color:{colour}'>●</span>  {text}")
    chip.setTextFormat(Qt.TextFormat.RichText)
    chip.setProperty("role", "hint")
    return chip


__all__ = ["ProvenanceBar"]
