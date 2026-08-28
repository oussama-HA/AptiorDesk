"""Hero-style current-versus-tailored Job Fit Ratio presentation."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.database.models.job import FitFactor, JobFitComparison, JobFitRatio
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE


class FitScoreRing(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._score = 0
        self.setFixedSize(104, 104)
        self.setAccessibleName("Job Fit Ratio")

    def set_score(self, score: int) -> None:
        self._score = max(0, min(100, int(score)))
        self.setAccessibleDescription(f"{self._score} percent")
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        palette = current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(10, 10, self.width() - 20, self.height() - 20)
        pen = QPen(QColor(palette.border_strong), 8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -360 * 16)
        pen.setColor(QColor(palette.accent))
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, round(-360 * 16 * self._score / 100))

        painter.setPen(QColor(palette.text))
        font = QFont(self.font())
        font.setPointSize(21)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self._score))
        painter.setPen(QColor(palette.text_faint))
        small = QFont(self.font())
        small.setPointSize(7)
        small.setWeight(QFont.Weight.DemiBold)
        painter.setFont(small)
        painter.drawText(
            QRectF(rect.left(), rect.center().y() + 19, rect.width(), 13),
            Qt.AlignmentFlag.AlignHCenter,
            "%",
        )


class _ScoreBlock(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setProperty("role", "layoutOnly")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])
        self.ring = FitScoreRing()
        layout.addWidget(self.ring)
        copy = QVBoxLayout()
        copy.setSpacing(SPACE["xs"])
        self.title = QLabel(title)
        self.title.setProperty("role", "fieldLabel")
        copy.addWidget(self.title)
        self.score = QLabel("0% fit")
        self.score.setProperty("role", "sectionTitle")
        copy.addWidget(self.score)
        self.caption = QLabel("")
        self.caption.setProperty("role", "caption")
        self.caption.setWordWrap(True)
        copy.addWidget(self.caption)
        copy.addStretch(1)
        layout.addLayout(copy, 1)

    def set_ratio(self, ratio: JobFitRatio | None, empty_text: str = "") -> None:
        score = ratio.score if ratio is not None else 0
        self.ring.set_score(score)
        self.score.setText(f"{score}% fit" if ratio is not None else "Not available")
        if ratio is None:
            self.caption.setText(empty_text)
            self.setEnabled(False)
            return
        self.setEnabled(True)
        applicable = sum(factor.total_count > 0 for factor in ratio.factors)
        penalty = (
            f" · {ratio.critical_penalty}-point critical-gap penalty"
            if ratio.critical_penalty
            else ""
        )
        self.caption.setText(f"{applicable} measurable factors{penalty}")


class _FactorRow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "layoutOnly")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])
        self.label = QLabel()
        self.label.setProperty("role", "caption")
        self.label.setMinimumWidth(150)
        layout.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar, 1)
        self.value = QLabel()
        self.value.setProperty("role", "fieldLabel")
        self.value.setMinimumWidth(76)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.value)

    def set_factors(self, current_factor: FitFactor, tailored_factor: FitFactor | None) -> None:
        self.label.setText(current_factor.label)
        display_score = (
            tailored_factor.score if tailored_factor is not None else current_factor.score
        )
        self.bar.setValue(display_score)
        if tailored_factor is None:
            self.value.setText(f"{current_factor.score}%")
        else:
            delta = tailored_factor.score - current_factor.score
            sign = "+" if delta > 0 else ""
            self.value.setText(f"{current_factor.score} → {tailored_factor.score} ({sign}{delta})")


class JobFitRatioCard(QFrame):
    """Reusable comparison card for Jobs and Resume tailoring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "section")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        outer.setSpacing(SPACE["md"])

        header = QHBoxLayout()
        heading = QVBoxLayout()
        eyebrow = QLabel("JOB FIT RATIO")
        eyebrow.setProperty("role", "eyebrow")
        heading.addWidget(eyebrow)
        title = QLabel("Resume-to-role comparison")
        title.setProperty("role", "sectionTitle")
        heading.addWidget(title)
        header.addLayout(heading)
        header.addStretch(1)
        self.improvement = QLabel("TAILOR TO COMPARE")
        self.improvement.setProperty("role", "badge")
        self.improvement.setProperty("tone", "accent")
        header.addWidget(self.improvement)
        outer.addLayout(header)

        scores = QHBoxLayout()
        scores.setSpacing(SPACE["xl"])
        self.current = _ScoreBlock("CURRENT RESUME")
        scores.addWidget(self.current, 1)
        arrow = QLabel("→")
        arrow.setProperty("role", "metric")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scores.addWidget(arrow)
        self.tailored = _ScoreBlock("TAILORED RESUME")
        scores.addWidget(self.tailored, 1)
        outer.addLayout(scores)

        self.factor_container = QWidget()
        self.factor_container.setProperty("role", "layoutOnly")
        self.factor_layout = QVBoxLayout(self.factor_container)
        self.factor_layout.setContentsMargins(0, 0, 0, 0)
        self.factor_layout.setSpacing(SPACE["xs"])
        self.factor_rows = [_FactorRow() for _ in range(4)]
        for row in self.factor_rows:
            self.factor_layout.addWidget(row)
        outer.addWidget(self.factor_container)

        self.detail = QLabel()
        self.detail.setProperty("role", "caption")
        self.detail.setWordWrap(True)
        outer.addWidget(self.detail)

    def set_comparison(self, comparison: JobFitComparison | None) -> None:
        if comparison is None:
            self.current.set_ratio(None, "Choose a saved job and resume version.")
            self.tailored.set_ratio(None, "Create a tailored version to compare.")
            self.improvement.setText("NO COMPARISON")
            self.factor_container.hide()
            self.detail.setText(
                "The ratio uses measurable requirements and never asks the AI to invent a score."
            )
            return

        self.current.set_ratio(comparison.current)
        self.tailored.set_ratio(
            comparison.tailored,
            "Apply accepted tailoring changes to create the comparison.",
        )
        if comparison.improvement is None:
            self.improvement.setText("TAILOR TO COMPARE")
        else:
            sign = "+" if comparison.improvement > 0 else ""
            self.improvement.setText(f"{sign}{comparison.improvement}% IMPROVEMENT")

        applicable = [factor for factor in comparison.current.factors if factor.total_count > 0]
        applicable.sort(key=lambda factor: factor.weight, reverse=True)
        tailored_by_key = (
            {factor.key: factor for factor in comparison.tailored.factors}
            if comparison.tailored is not None
            else {}
        )
        for index, row in enumerate(self.factor_rows):
            if index >= len(applicable):
                row.hide()
                continue
            factor = applicable[index]
            row.set_factors(factor, tailored_by_key.get(factor.key))
            row.show()
        self.factor_container.setVisible(bool(applicable))

        missing = comparison.current.missing_critical
        if missing:
            self.detail.setText("Critical gaps affecting the score: " + "; ".join(missing[:3]))
            self.detail.setProperty("role", "warning")
        else:
            self.detail.setText(
                "Weights are normalized across explicit requirements. Open Job fit for "
                "the complete evidence and methodology."
            )
            self.detail.setProperty("role", "caption")
        self.detail.style().unpolish(self.detail)
        self.detail.style().polish(self.detail)


__all__ = ["FitScoreRing", "JobFitRatioCard"]
