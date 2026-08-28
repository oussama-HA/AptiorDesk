"""Generic background worker for anything that must not block the UI thread
(AI calls, network, file parsing, package installs).

Widgets may only be touched on the UI thread, so results and progress come
back as signals. Never call a widget method from inside the worker function.

Usage::

    worker = Worker(lambda: provider.health_check(), parent=self)
    worker.result.connect(self.on_ok)
    worker.error.connect(self.on_error)
    worker.start()

For long jobs that report as they go, accept a single argument — the worker
passes a callback that emits `progress` on the UI thread::

    def run(report):
        for chunk in download():
            report(chunk)
        return "done"

    worker = Worker(run, parent=self)
    worker.progress.connect(self.on_progress)
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget


class Worker(QThread):
    result = Signal(object)
    error = Signal(object)
    progress = Signal(object)

    def __init__(self, fn: Callable[..., Any], parent=None):
        super().__init__(parent)
        self._fn = fn
        self._wants_progress = _accepts_one_argument(fn)
        # keep the worker alive until it finishes even if the caller drops it
        self.finished.connect(self.deleteLater)
        self._progress_dialog = None

    def show_progress(self, title: str, detail: str) -> Worker:
        """Attach the standard visible activity window to this worker.

        Pages with a richer domain-specific progress view (resume extraction,
        model downloads) do not call this method. Keeping the opt-in beside the
        worker construction makes task copy specific and testable.
        """
        if QApplication.instance() is None or not isinstance(self.parent(), QWidget):
            return self
        from aptiordesk.ui.components.task_progress import TaskProgressDialog

        dialog = TaskProgressDialog(title, detail, self.parent())
        self._progress_dialog = dialog
        self.progress.connect(dialog.report)
        self.result.connect(dialog.succeed)
        self.error.connect(dialog.fail)
        dialog.show()
        dialog.raise_()
        return self

    def run(self) -> None:
        try:
            if self._wants_progress:
                self.result.emit(self._fn(self.progress.emit))
            else:
                self.result.emit(self._fn())
        except Exception as exc:  # delivered to the UI as a value, not raised
            self.error.emit(exc)


def _accepts_one_argument(fn: Callable[..., Any]) -> bool:
    """True if `fn` takes exactly one required positional parameter, which we
    treat as a request for the progress callback."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    return len(required) == 1
