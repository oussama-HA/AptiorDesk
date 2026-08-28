"""Render the first-run AI-provider step for native visual QA."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from aptiordesk.app.onboarding import AIStep, OnboardingWizard
from aptiordesk.core.environment import OllamaStatus
from aptiordesk.database.db import connect, migrate
from aptiordesk.ui.theme import apply_theme


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate_onboarding.py OUTPUT.png")
    output = Path(sys.argv[1]).resolve()
    app = QApplication(sys.argv[:1])
    apply_theme("dark", app)
    connection = connect(":memory:")
    migrate(connection)

    # Visual validation must be deterministic and must not probe or modify the
    # developer's real Ollama installation.
    AIStep.on_enter = lambda _self: None
    wizard = OnboardingWizard(connection)
    wizard.resize(1040, 920)
    wizard._show_step(2)
    step = wizard.steps[2]
    step._show_status(
        OllamaStatus(
            installed=True,
            running=True,
            version="0.30.10",
            models=["gemma4:e4b"],
        )
    )
    wizard.show()
    result = {"code": 2}

    def capture() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        image = wizard.grab()
        if not image.isNull() and image.save(str(output)):
            print(f"Saved onboarding validation to {output}")
            result["code"] = 0
        wizard.accept()
        connection.close()
        app.quit()

    QTimer.singleShot(500, capture)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
