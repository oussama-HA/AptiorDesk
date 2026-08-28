"""Render a real AptiorDesk mock-interview room for native visual QA."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtWidgets import QApplication

from aptiordesk.database.db import connect, migrate
from aptiordesk.database.models.interview import InterviewQuestion
from aptiordesk.database.repositories.interview_repo import InterviewRepository
from aptiordesk.features.interviews.page import InterviewPage
from aptiordesk.features.interviews.service import InterviewService
from aptiordesk.ui.theme import apply_theme


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit(
            "Usage: validate_interview_room.py OUTPUT.png [open|tight|tight_o|wide]"
        )
    output = Path(sys.argv[1]).resolve()
    requested_viseme = sys.argv[2] if len(sys.argv) == 3 else None
    app = QApplication(sys.argv[:1])
    apply_theme("dark", app)
    connection = connect(":memory:")
    migrate(connection)
    service = InterviewService(connection)
    session = service.start_session(
        None,
        None,
        persona="friendly_recruiter",
        stage="behavioral",
        feedback_mode="realistic",
    )
    InterviewRepository(connection).add_question(
        InterviewQuestion(
            session_id=session.id,
            text=(
                "We require proficiency across multiple tools: Premiere Pro for video, "
                "After Effects for motion, Photoshop/Illustrator for static, and Figma "
                "for brand systems. Which of these disciplines do you feel is your most "
                "underdeveloped area relative to the job requirements, and how would "
                "you plan to rapidly close that gap?"
            ),
            category="behavioral",
            stage="behavioral",
            sort_order=0,
        )
    )
    page = InterviewPage(connection)
    page.resize(
        int(os.environ.get("APTIORDESK_QA_WIDTH", "1600")),
        int(os.environ.get("APTIORDESK_QA_HEIGHT", "900")),
    )
    page.show()
    page._on_session_started(session.id)
    elapsed = QElapsedTimer()
    elapsed.start()
    result = {"code": 2, "posed": False}

    def capture_when_ready() -> None:
        mock = page.mock_tab
        if (
            mock.environment_ready
            and mock.initial_audio_ready
            and mock.avatar_stage.is_ready
        ):
            if requested_viseme and not result["posed"]:
                result["posed"] = True
                mock._speech.stop()
                mock.avatar_stage.set_viseme(requested_viseme, 0.72)
                QTimer.singleShot(450, capture_when_ready)
                return
            output.parent.mkdir(parents=True, exist_ok=True)
            image = page.grab()
            if not image.isNull() and image.save(str(output)):
                print(f"Saved interview room to {output}")
                result["code"] = 0
            mock._speech.stop()
            speech_worker = mock._speech._worker
            if speech_worker is not None and speech_worker.isRunning():
                speech_worker.wait(15_000)
            for preload_worker in tuple(mock._speech._preload_workers.values()):
                if preload_worker.isRunning():
                    preload_worker.wait(15_000)
            mock._avatar.shutdown()
            connection.close()
            app.quit()
            return
        if elapsed.elapsed() >= 90_000:
            print(f"Interview room did not become ready: {mock._environment_error}")
            mock._avatar.shutdown()
            connection.close()
            app.quit()
            return
        QTimer.singleShot(250, capture_when_ready)

    QTimer.singleShot(250, capture_when_ready)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
