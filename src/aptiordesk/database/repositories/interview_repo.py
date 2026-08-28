"""Persistence for interview sessions, questions, answers, and feedback."""

from __future__ import annotations

import json
import sqlite3

from aptiordesk.database.models.interview import (
    AnswerFeedback,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
)
from aptiordesk.database.repositories._util import now_iso


class InterviewRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- sessions ------------------------------------------------------------

    def create_session(self, session: InterviewSession) -> InterviewSession:
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO interview_sessions(job_id, resume_version_id, mode, persona, "
                "stage, status, report_json, started_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    session.job_id,
                    session.resume_version_id,
                    session.mode,
                    session.persona,
                    session.stage,
                    session.status,
                    json.dumps(session.report),
                    ts,
                ),
            )
        session.id = cur.lastrowid
        session.started_at = ts
        return session

    def get_session(self, session_id: int) -> InterviewSession | None:
        row = self._conn.execute(
            "SELECT * FROM interview_sessions WHERE id=?", (session_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self) -> list[InterviewSession]:
        rows = self._conn.execute(
            "SELECT * FROM interview_sessions ORDER BY started_at DESC"
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def list_completed_reports(self) -> list[InterviewSession]:
        rows = self._conn.execute(
            "SELECT * FROM interview_sessions "
            "WHERE status='completed' AND report_json NOT IN ('', '{}') "
            "ORDER BY ended_at DESC, id DESC"
        ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def complete_session(self, session_id: int, report: dict) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE interview_sessions SET status='completed', report_json=?, ended_at=? "
                "WHERE id=?",
                (json.dumps(report), now_iso(), session_id),
            )

    def delete_session(self, session_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM interview_sessions WHERE id=?", (session_id,))

    # -- questions -----------------------------------------------------------

    def add_question(self, question: InterviewQuestion) -> InterviewQuestion:
        with self._conn:
            self._insert_question(question)
        return question

    def add_questions(self, questions: list[InterviewQuestion]) -> list[InterviewQuestion]:
        """Insert a generated set atomically so a bad row leaves no partial set."""
        with self._conn:
            for question in questions:
                self._insert_question(question)
        return questions

    def _insert_question(self, question: InterviewQuestion) -> None:
        cur = self._conn.execute(
            "INSERT INTO questions(session_id, job_id, category, stage, difficulty, "
            "text, key_points_json, why_asked, is_followup, parent_question_id, "
            "sort_order, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                question.session_id,
                question.job_id,
                question.category,
                question.stage,
                question.difficulty,
                question.text,
                json.dumps(question.key_points),
                question.why_asked,
                int(question.is_followup),
                question.parent_question_id,
                question.sort_order,
                now_iso(),
            ),
        )
        question.id = cur.lastrowid

    def list_questions(self, session_id: int) -> list[InterviewQuestion]:
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE session_id=? ORDER BY sort_order, id", (session_id,)
        ).fetchall()
        return [self._row_to_question(r) for r in rows]

    def get_question(self, question_id: int) -> InterviewQuestion | None:
        row = self._conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        return self._row_to_question(row) if row else None

    def list_job_questions(self, job_id: int) -> list[InterviewQuestion]:
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE job_id=? AND session_id IS NULL ORDER BY sort_order, id",
            (job_id,),
        ).fetchall()
        return [self._row_to_question(r) for r in rows]

    # -- answers -------------------------------------------------------------

    def add_answer(self, answer: InterviewAnswer) -> InterviewAnswer:
        next_attempt = self._conn.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM answers WHERE question_id=?",
            (answer.question_id,),
        ).fetchone()[0]
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO answers(question_id, session_id, attempt_no, text, input_mode, "
                "duration_s, words_per_minute, filler_json, in_library, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    answer.question_id,
                    answer.session_id,
                    next_attempt,
                    answer.text,
                    answer.input_mode,
                    answer.duration_s,
                    answer.words_per_minute,
                    json.dumps(answer.filler),
                    int(answer.in_library),
                    ts,
                ),
            )
        answer.id = cur.lastrowid
        answer.attempt_no = next_attempt
        answer.created_at = ts
        return answer

    def list_answers(self, question_id: int) -> list[InterviewAnswer]:
        rows = self._conn.execute(
            "SELECT * FROM answers WHERE question_id=? ORDER BY attempt_no", (question_id,)
        ).fetchall()
        return [self._row_to_answer(r) for r in rows]

    def list_session_answers(self, session_id: int) -> list[InterviewAnswer]:
        rows = self._conn.execute(
            "SELECT * FROM answers WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [self._row_to_answer(r) for r in rows]

    def set_in_library(self, answer_id: int, in_library: bool) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE answers SET in_library=? WHERE id=?", (int(in_library), answer_id)
            )

    def list_library(self) -> list[tuple[InterviewAnswer, str]]:
        """Saved answers with their question text."""
        rows = self._conn.execute(
            "SELECT a.*, q.text AS question_text FROM answers a "
            "JOIN questions q ON q.id = a.question_id "
            "WHERE a.in_library=1 ORDER BY a.created_at DESC"
        ).fetchall()
        return [(self._row_to_answer(r), r["question_text"]) for r in rows]

    # -- feedback ------------------------------------------------------------

    def add_feedback(
        self, answer_id: int, feedback: AnswerFeedback, prompt_id: str, prompt_version: int
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO feedback(answer_id, result_json, prompt_id, prompt_version, "
                "created_at) VALUES(?,?,?,?,?)",
                (
                    answer_id,
                    feedback.model_dump_json(),
                    prompt_id,
                    prompt_version,
                    now_iso(),
                ),
            )

    def get_feedback(self, answer_id: int) -> AnswerFeedback | None:
        row = self._conn.execute(
            "SELECT * FROM feedback WHERE answer_id=? ORDER BY id DESC LIMIT 1", (answer_id,)
        ).fetchone()
        if row is None:
            return None
        return AnswerFeedback.model_validate(json.loads(row["result_json"]))

    # -- mapping -------------------------------------------------------------

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> InterviewSession:
        return InterviewSession(
            id=row["id"],
            job_id=row["job_id"],
            resume_version_id=row["resume_version_id"],
            mode=row["mode"],
            persona=row["persona"],
            stage=row["stage"],
            status=row["status"],
            report=json.loads(row["report_json"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
        )

    @staticmethod
    def _row_to_question(row: sqlite3.Row) -> InterviewQuestion:
        return InterviewQuestion(
            id=row["id"],
            session_id=row["session_id"],
            job_id=row["job_id"],
            category=row["category"],
            stage=row["stage"],
            difficulty=row["difficulty"],
            text=row["text"],
            key_points=json.loads(row["key_points_json"]),
            why_asked=row["why_asked"],
            is_followup=bool(row["is_followup"]),
            parent_question_id=row["parent_question_id"],
            sort_order=row["sort_order"],
        )

    @staticmethod
    def _row_to_answer(row: sqlite3.Row) -> InterviewAnswer:
        return InterviewAnswer(
            id=row["id"],
            question_id=row["question_id"],
            session_id=row["session_id"],
            attempt_no=row["attempt_no"],
            text=row["text"],
            input_mode=row["input_mode"],
            duration_s=row["duration_s"],
            words_per_minute=row["words_per_minute"],
            filler=json.loads(row["filler_json"]),
            in_library=bool(row["in_library"]),
            created_at=row["created_at"],
        )
