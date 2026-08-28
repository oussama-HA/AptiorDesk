"""Interview preparation and mock interview logic."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from aptiordesk.ai.base import AIProvider, ChatMessage, Role
from aptiordesk.ai.prompts.engine import get_template
from aptiordesk.ai.prompts.guards import FABRICATION_RULES, UNTRUSTED_PREAMBLE, wrap_untrusted
from aptiordesk.database.models.interview import (
    PERSONAS,
    STAGES,
    AnswerFeedback,
    FollowUpDecision,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    QuestionList,
    SessionReport,
)
from aptiordesk.database.models.job import Job
from aptiordesk.database.models.resume import ResumeVersion
from aptiordesk.database.repositories.interview_repo import InterviewRepository
from aptiordesk.documents.render import resume_to_markdown
from aptiordesk.features.interviews.voice.analysis import analyze_delivery

log = logging.getLogger(__name__)

MAX_FOLLOWUPS_PER_QUESTION = 2


@dataclass(frozen=True)
class GeneratedQuestions:
    """AI output that contains no database connection and can cross threads."""

    questions: list[InterviewQuestion]


@dataclass(frozen=True)
class ReportContext:
    """Frozen session transcript prepared on the SQLite-owner thread."""

    session_id: int
    stage: str
    persona: str
    transcript: str


class InterviewService:
    def __init__(self, conn: sqlite3.Connection):
        self._repo = InterviewRepository(conn)

    # -- question generation -------------------------------------------------

    def generate_questions(
        self,
        provider: AIProvider,
        job: Job | None,
        resume_version: ResumeVersion | None,
        *,
        stage: str,
        count: int = 8,
        difficulty: str = "mixed",
        categories: list[str] | None = None,
        session: InterviewSession | None = None,
    ) -> list[InterviewQuestion]:
        generated = self.generate_questions_ai(
            provider,
            job,
            resume_version,
            stage=stage,
            count=count,
            difficulty=difficulty,
            categories=categories,
            session=session,
        )
        return self.persist_questions(generated)

    def generate_questions_ai(
        self,
        provider: AIProvider,
        job: Job | None,
        resume_version: ResumeVersion | None,
        *,
        stage: str,
        count: int = 8,
        difficulty: str = "mixed",
        categories: list[str] | None = None,
        session: InterviewSession | None = None,
    ) -> GeneratedQuestions:
        """Generate question objects without reading or writing SQLite."""
        if stage not in STAGES:
            raise ValueError(f"Unknown interview stage: {stage}")
        template = get_template("interview_questions")
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            fabrication_rules=FABRICATION_RULES,
            stage_name=stage,
            stage_description=STAGES[stage],
            count=str(count),
            difficulty=difficulty,
            categories=", ".join(categories or ["behavioral", "technical", "motivation"]),
            jd_block=wrap_untrusted(
                job.raw_description if job else "(no job description provided)",
                "JOB DESCRIPTION",
            ),
            resume_block=wrap_untrusted(
                resume_to_markdown(resume_version.content) if resume_version else "(no resume)",
                "RESUME",
            ),
        )
        result = provider.structured(
            [ChatMessage(Role.USER, prompt)], QuestionList, temperature=0.7
        )
        prepared: list[InterviewQuestion] = []
        for index, draft in enumerate(result.questions):
            if not draft.text.strip():
                continue
            prepared.append(
                InterviewQuestion(
                    session_id=session.id if session else None,
                    job_id=job.id if job else None,
                    text=draft.text.strip(),
                    category=draft.category,
                    stage=stage,
                    difficulty=draft.difficulty,
                    key_points=draft.key_points,
                    why_asked=draft.why_asked,
                    is_followup=False,
                    parent_question_id=None,
                    sort_order=index,
                )
            )
        return GeneratedQuestions(prepared)

    def persist_questions(self, generated: GeneratedQuestions) -> list[InterviewQuestion]:
        """Persist generated questions on the connection-owner thread."""
        return self._repo.add_questions(generated.questions)

    def discard_session(self, session_id: int) -> None:
        """Remove an empty setup session after question preparation fails."""
        self._repo.delete_session(session_id)

    # -- mock session --------------------------------------------------------

    def start_session(
        self,
        job: Job | None,
        resume_version: ResumeVersion | None,
        *,
        persona: str,
        stage: str,
        feedback_mode: str = "coaching",
    ) -> InterviewSession:
        if persona not in PERSONAS:
            raise ValueError(f"Unknown persona: {persona}")
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")
        if feedback_mode not in {"coaching", "realistic", "practice"}:
            raise ValueError(f"Unknown interview feedback mode: {feedback_mode}")
        return self._repo.create_session(
            InterviewSession(
                job_id=job.id if job else None,
                resume_version_id=resume_version.id if resume_version else None,
                mode="mock",
                persona=persona,
                stage=stage,
                report={"feedback_mode": feedback_mode},
            )
        )

    def record_answer(
        self,
        question: InterviewQuestion,
        text: str,
        *,
        session: InterviewSession | None = None,
        input_mode: str = "typed",
        duration_s: float | None = None,
    ) -> InterviewAnswer:
        """Store an answer, with delivery stats for spoken ones."""
        stats = analyze_delivery(text, duration_s) if duration_s else None
        return self._repo.add_answer(
            InterviewAnswer(
                question_id=question.id,
                session_id=session.id if session else None,
                text=text,
                input_mode=input_mode,
                duration_s=duration_s,
                words_per_minute=stats.words_per_minute if stats else None,
                filler=stats.as_dict() if stats else {},
            )
        )

    def decide_followup(
        self,
        provider: AIProvider,
        session: InterviewSession,
        question: InterviewQuestion,
        answer: InterviewAnswer,
        followup_count: int,
    ) -> FollowUpDecision:
        """Ask the model whether this persona would probe further.

        Feedback is deliberately NOT produced here — a real interviewer does
        not critique mid-interview.
        """
        if followup_count >= MAX_FOLLOWUPS_PER_QUESTION:
            return FollowUpDecision(ask_followup=False, reason="Follow-up limit reached.")
        template = get_template("interview_followup")
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            persona_name=session.persona,
            persona_description=PERSONAS[session.persona],
            question=question.text,
            followup_count=str(followup_count),
            answer_block=wrap_untrusted(answer.text, "CANDIDATE ANSWER"),
        )
        decision = provider.structured(
            [ChatMessage(Role.USER, prompt)], FollowUpDecision, temperature=0.5
        )
        if decision.ask_followup and not decision.followup_question.strip():
            decision.ask_followup = False
        return decision

    def add_followup(
        self, session: InterviewSession, parent: InterviewQuestion, text: str
    ) -> InterviewQuestion:
        return self._repo.add_question(
            InterviewQuestion(
                session_id=session.id,
                job_id=session.job_id,
                text=text,
                category=parent.category,
                stage=parent.stage,
                difficulty=parent.difficulty,
                is_followup=True,
                parent_question_id=parent.id,
                sort_order=parent.sort_order,
            )
        )

    # -- feedback ------------------------------------------------------------

    def feedback_for(
        self,
        provider: AIProvider,
        question: InterviewQuestion,
        answer: InterviewAnswer,
        resume_version: ResumeVersion | None = None,
    ) -> AnswerFeedback:
        feedback = self.generate_feedback(provider, question, answer, resume_version)
        self.persist_feedback(answer, feedback)
        return feedback

    def generate_feedback(
        self,
        provider: AIProvider,
        question: InterviewQuestion,
        answer: InterviewAnswer,
        resume_version: ResumeVersion | None = None,
    ) -> AnswerFeedback:
        """Generate feedback without touching the repository."""
        template = get_template("answer_feedback")
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            fabrication_rules=FABRICATION_RULES,
            category=question.category,
            difficulty=question.difficulty,
            question=question.text,
            key_points="; ".join(question.key_points) or "(none recorded)",
            answer_block=wrap_untrusted(answer.text, "CANDIDATE ANSWER"),
            resume_block=wrap_untrusted(
                resume_to_markdown(resume_version.content) if resume_version else "(no resume)",
                "RESUME",
            ),
        )
        return provider.structured(
            [ChatMessage(Role.USER, prompt)], AnswerFeedback, temperature=0.3
        )

    def persist_feedback(self, answer: InterviewAnswer, feedback: AnswerFeedback) -> None:
        template = get_template("answer_feedback")
        self._repo.add_feedback(answer.id, feedback, template.id, template.version)

    # -- report --------------------------------------------------------------

    def build_report(self, provider: AIProvider, session: InterviewSession) -> SessionReport:
        context = self.report_context(session)
        report = self.generate_report(provider, context)
        self.persist_report(context, report)
        return report

    def report_context(self, session: InterviewSession) -> ReportContext:
        """Read the transcript while still on the SQLite connection's thread."""
        questions = {q.id: q for q in self._repo.list_questions(session.id)}
        answers = self._repo.list_session_answers(session.id)
        if not answers:
            raise ValueError("This session has no answers yet.")
        lines: list[str] = []
        for answer in answers:
            question = questions.get(answer.question_id)
            if question is None:
                continue
            lines.append(f"Q ({question.category}): {question.text}")
            lines.append(f"A: {answer.text}")
            if answer.words_per_minute:
                lines.append(f"[delivery: {answer.words_per_minute:.0f} wpm]")
            lines.append("")
        return ReportContext(
            session_id=session.id,
            stage=session.stage,
            persona=session.persona,
            transcript="\n".join(lines),
        )

    def generate_report(self, provider: AIProvider, context: ReportContext) -> SessionReport:
        """Generate a report from frozen input without accessing SQLite."""
        template = get_template("session_report")
        prompt = template.render(
            untrusted_preamble=UNTRUSTED_PREAMBLE,
            stage_name=context.stage,
            persona_name=context.persona,
            transcript_block=wrap_untrusted(context.transcript, "INTERVIEW TRANSCRIPT"),
        )
        return provider.structured([ChatMessage(Role.USER, prompt)], SessionReport, temperature=0.4)

    def persist_report(self, context: ReportContext, report: SessionReport) -> None:
        self._repo.complete_session(context.session_id, report.model_dump())

    # -- answer library ------------------------------------------------------

    def save_to_library(self, answer: InterviewAnswer) -> None:
        self._repo.set_in_library(answer.id, True)

    def remove_from_library(self, answer: InterviewAnswer) -> None:
        self._repo.set_in_library(answer.id, False)

    def library(self) -> list[tuple[InterviewAnswer, str]]:
        return self._repo.list_library()


__all__ = [
    "GeneratedQuestions",
    "InterviewService",
    "MAX_FOLLOWUPS_PER_QUESTION",
    "ReportContext",
]
