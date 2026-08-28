"""Prominent, truthful progress feedback for user-initiated background work."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from aptiordesk.ui.theme.tokens import SPACE


class TaskProgressDialog(QDialog):
    """Show real progress when totals exist and label unknown work honestly."""

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setObjectName("taskProgressDialog")
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(440)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])

        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "pageTitle")
        layout.addWidget(self.title_label)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("taskProgressDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("taskProgressBar")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Indeterminate")
        layout.addWidget(self.progress)

        footer = QHBoxLayout()
        self.activity_label = QLabel("Indeterminate")
        self.activity_label.setProperty("role", "accent")
        footer.addWidget(self.activity_label)
        footer.addStretch(1)
        self.elapsed_label = QLabel("0 s")
        self.elapsed_label.setProperty("role", "hint")
        footer.addWidget(self.elapsed_label)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        self.close_button.hide()
        footer.addWidget(self.close_button)
        layout.addLayout(footer)

        self._ticks = 0
        self._measured = False
        self._last_completed = 0
        self._last_measurement_seconds = 0.0
        self._bytes_per_second = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def report(self, update: object) -> None:
        """Display a worker's current step and any real byte totals it supplies."""
        if isinstance(update, str):
            detail = update.strip().splitlines()[-1] if update.strip() else ""
            self._measured = False
            self.progress.setRange(0, 0)
            self.progress.setFormat("Indeterminate")
        else:
            status = getattr(update, "status", "")
            completed = getattr(update, "completed", None)
            total = getattr(update, "total", None)
            detail = str(status or update)
            if completed is not None and total:
                completed = int(completed)
                total = int(total)
                percent = min(100, max(0, round(completed / total * 100)))
                self.progress.setRange(0, 100)
                self.progress.setValue(percent)
                self.progress.setFormat(f"{percent}%")
                self._measured = True
                elapsed = self._ticks / 2
                interval = elapsed - self._last_measurement_seconds
                delta = completed - self._last_completed
                if interval > 0 and delta > 0:
                    current_rate = delta / interval
                    self._bytes_per_second = (
                        current_rate
                        if self._bytes_per_second <= 0
                        else self._bytes_per_second * 0.7 + current_rate * 0.3
                    )
                self._last_completed = completed
                self._last_measurement_seconds = elapsed
                detail += f" · {_format_size(completed)} of {_format_size(total)}"
                if self._bytes_per_second > 0 and completed < total:
                    remaining = (total - completed) / self._bytes_per_second
                    detail += f" · about {_format_duration(remaining)} remaining"
                self.activity_label.setText(f"{percent}% complete")
        if detail:
            self.detail_label.setText(detail[:360])

    def succeed(self, _result: object = None) -> None:
        self._timer.stop()
        if self._measured:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress.setFormat("100%")
        self.activity_label.setText("Complete")
        self.activity_label.setProperty("role", "success")
        _refresh_style(self.activity_label)
        QTimer.singleShot(650, self.close)

    def fail(self, exc: object) -> None:
        self._timer.stop()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Failed")
        self.activity_label.setText("Failed")
        self.activity_label.setProperty("role", "error")
        _refresh_style(self.activity_label)
        message = getattr(exc, "user_message", str(exc))
        self.detail_label.setText(str(message)[:360])
        self.close_button.show()

    def _tick(self) -> None:
        self._ticks += 1
        seconds = self._ticks / 2
        self.elapsed_label.setText(f"{seconds:.0f} s")
        if not self._measured:
            self.activity_label.setText("Indeterminate" + "." * ((self._ticks % 3) + 1))


def _refresh_style(widget: QLabel) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _format_size(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1000 or unit == "TB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1000
    return f"{amount:.1f} TB"


def _format_duration(seconds: float) -> str:
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds} sec"
    minutes = (seconds + 30) // 60
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes / 60:.1f} hr"


__all__ = ["TaskProgressDialog"]
