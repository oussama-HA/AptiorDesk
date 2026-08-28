"""Interview preparation, mock session, and feedback models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

PERSONAS: dict[str, str] = {
    "friendly_recruiter": "Warm and encouraging. Keeps things moving, asks for "
    "clarity gently, focuses on motivation and fit.",
    "skeptical_hiring_manager": "Probing and evidence-driven. Challenges vague "
    "claims, asks 'what exactly did you do' and 'how do you know it worked'.",
    "technical_interviewer": "Depth-focused. Follows up on technical decisions, "
    "trade-offs, and failure modes.",
    "executive": "Strategic and brief. Cares about scope, business impact, and "
    "judgement under constraint.",
    "stress": "Terse and pressing. Interrupts padding, demands specifics. Never "
    "rude or personal — only demanding.",
    "coaching": "Supportive teacher. Asks the question, then helps the candidate "
    "find a stronger version of their own answer.",
}

STAGES: dict[str, str] = {
    "recruiter_screen": "Recruiter screen — motivation, basics, logistics, salary.",
    "hiring_manager": "Hiring manager — ownership, judgement, working style.",
    "behavioral": "Behavioral — past situations, STAR-style evidence.",
    "technical": "Technical — depth in the role's core skills.",
    "case_study": "Case or take-home discussion — structured problem solving.",
    "portfolio_review": "Portfolio or past-work walkthrough.",
    "leadership": "Leadership — influence, conflict, growing people.",
    "culture_fit": "Culture and values alignment.",
    "salary_negotiation": "Compensation discussion.",
    "final_panel": "Final panel — mixed, senior stakeholders.",
}

CATEGORIES = [
    "behavioral",
    "technical",
    "situational",
    "motivation",
    "career_narrative",
    "role_specific",
    "questions_to_ask",
]


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_id: int | None = None
    job_id: int | None = None
    text: str = ""
    category: str = "behavioral"
    stage: str = ""
    difficulty: str = "medium"
    key_points: list[str] = Field(default_factory=list)
    why_asked: str = ""
    is_followup: bool = False
    parent_question_id: int | None = None
    sort_order: int = 0


class InterviewQuestionDraft(BaseModel):
    """AI-facing question shape with no persistence-controlled identifiers."""

    model_config = ConfigDict(extra="ignore")

    text: str = ""
    category: str = "behavioral"
    difficulty: str = "medium"
    key_points: list[str] = Field(default_factory=list)
    why_asked: str = ""


class QuestionList(BaseModel):
    """AI output schema for question generation."""

    model_config = ConfigDict(extra="ignore")

    questions: list[InterviewQuestionDraft] = Field(default_factory=list)


class InterviewAnswer(BaseModel):
    id: int | None = None
    question_id: int
    session_id: int | None = None
    attempt_no: int = 1
    text: str = ""
    input_mode: str = "typed"  # typed | voice
    duration_s: float | None = None
    words_per_minute: float | None = None
    filler: dict = Field(default_factory=dict)
    in_library: bool = False
    created_at: str = ""


class FeedbackScores(BaseModel):
    """1-5 per dimension. Absent dimensions mean 'not applicable here'."""

    model_config = ConfigDict(extra="ignore")

    relevance: int | None = None
    clarity: int | None = None
    structure: int | None = None
    specificity: int | None = None
    evidence: int | None = None
    conciseness: int | None = None
    technical_accuracy: int | None = None


class AnswerFeedback(BaseModel):
    """AI output schema for answer feedback."""

    model_config = ConfigDict(extra="ignore")

    scores: FeedbackScores = Field(default_factory=FeedbackScores)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    star_assessment: str = ""
    missing_specifics: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    stronger_version: str = ""
    summary: str = ""


class FollowUpDecision(BaseModel):
    """Whether the interviewer should probe further before moving on."""

    model_config = ConfigDict(extra="ignore")

    ask_followup: bool = False
    followup_question: str = ""
    reason: str = ""


class InterviewSession(BaseModel):
    id: int | None = None
    job_id: int | None = None
    resume_version_id: int | None = None
    mode: str = "mock"
    persona: str = "friendly_recruiter"
    stage: str = "recruiter_screen"
    status: str = "active"
    report: dict = Field(default_factory=dict)
    started_at: str = ""
    ended_at: str | None = None


class SessionReport(BaseModel):
    """AI output schema for the end-of-session report."""

    model_config = ConfigDict(extra="ignore")

    overall_summary: str = ""
    strongest_answers: list[str] = Field(default_factory=list)
    weakest_answers: list[str] = Field(default_factory=list)
    recurring_patterns: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
