"""Deterministic, explainable Job Fit Ratio scoring.

The AI provider never chooses this number.  The scorer compares structured job
requirements with one immutable resume version and, when available, the user's
explicit profile preferences.  Factors without measurable job requirements are
excluded and the remaining weights are normalized to 100.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from aptiordesk.database.models.job import FitFactor, Job, JobExtraction, JobFitRatio
from aptiordesk.database.models.profile import Profile
from aptiordesk.database.models.resume import ResumeContent, ResumeVersion
from aptiordesk.documents.render import resume_to_markdown

SCORING_VERSION = "1.0"

_WEIGHTS = {
    "required_skills": 20,
    "preferred_skills": 7,
    "relevant_experience": 15,
    "seniority": 8,
    "responsibilities": 12,
    "industry": 5,
    "education": 8,
    "keywords": 10,
    "location_mode": 8,
    "authorization": 7,
}

_LABELS = {
    "required_skills": "Required skills",
    "preferred_skills": "Preferred skills",
    "relevant_experience": "Relevant experience",
    "seniority": "Seniority alignment",
    "responsibilities": "Responsibilities alignment",
    "industry": "Industry relevance",
    "education": "Education and certifications",
    "keywords": "Important keyword coverage",
    "location_mode": "Location and work mode",
    "authorization": "Work authorization",
}

_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "based",
    "been",
    "being",
    "but",
    "candidate",
    "company",
    "from",
    "have",
    "into",
    "job",
    "more",
    "our",
    "role",
    "that",
    "the",
    "their",
    "they",
    "this",
    "through",
    "using",
    "what",
    "when",
    "where",
    "which",
    "will",
    "with",
    "work",
    "years",
    "you",
    "your",
}

_TOKEN_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "nodejs": "node",
    "reactjs": "react",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "aws": "amazonwebservices",
    "gcp": "googlecloud",
    "ux": "userexperience",
    "ui": "userinterface",
    "pm": "productmanagement",
}

_SKILL_VOCABULARY = {
    "adobe after effects",
    "adobe illustrator",
    "adobe photoshop",
    "agile",
    "amazon web services",
    "analytics",
    "angular",
    "aws",
    "azure",
    "c++",
    "canva",
    "ci/cd",
    "content strategy",
    "css",
    "data analysis",
    "design systems",
    "docker",
    "excel",
    "figma",
    "git",
    "google analytics",
    "graphic design",
    "html",
    "illustrator",
    "java",
    "javascript",
    "jira",
    "kubernetes",
    "machine learning",
    "motion design",
    "node.js",
    "photoshop",
    "power bi",
    "premiere pro",
    "product design",
    "product management",
    "project management",
    "prototyping",
    "python",
    "react",
    "research",
    "salesforce",
    "seo",
    "sql",
    "tableau",
    "typescript",
    "user research",
    "video editing",
}

_INDUSTRIES = {
    "advertising",
    "automotive",
    "banking",
    "cybersecurity",
    "education",
    "energy",
    "entertainment",
    "finance",
    "fintech",
    "government",
    "healthcare",
    "hospitality",
    "insurance",
    "legal",
    "manufacturing",
    "marketing",
    "media",
    "nonprofit",
    "pharmaceutical",
    "real estate",
    "retail",
    "saas",
    "telecommunications",
    "technology",
    "travel",
}

_DEGREE_MARKERS = (
    "bachelor",
    "bsc",
    "ba ",
    "master",
    "msc",
    "mba",
    "phd",
    "degree",
    "diploma",
    "certification",
    "certified",
    "license",
)

_SENIORITY = {
    "internship": 0,
    "intern": 0,
    "entry": 1,
    "junior": 1,
    "associate": 1,
    "mid": 2,
    "intermediate": 2,
    "senior": 3,
    "sr": 3,
    "lead": 4,
    "principal": 4,
    "staff": 4,
    "manager": 4,
    "director": 5,
    "head": 5,
    "executive": 6,
    "vp": 6,
    "chief": 6,
}


def calculate_job_fit_ratio(
    job: Job,
    resume_version: ResumeVersion,
    *,
    extraction: JobExtraction | None = None,
    profile: Profile | None = None,
) -> JobFitRatio:
    """Score one immutable resume version against one saved job snapshot."""
    extraction = extraction or JobExtraction()
    content = resume_version.content
    resume_text = resume_to_markdown(content)
    job_text = job.raw_description

    required_skills = _unique(
        [
            *job.skills,
            *extraction.technical_skills,
            *extraction.tools_and_platforms,
            *_skills_in_text(job_text),
        ]
    )
    preferred_skills = _unique(
        [
            term
            for qualification in extraction.preferred_qualifications
            for term in _skills_in_text(qualification)
        ]
    )
    required_skills = [
        term
        for term in required_skills
        if term.casefold() not in {p.casefold() for p in preferred_skills}
    ]

    responsibilities = _unique(extraction.responsibilities or _responsibility_phrases(job_text))[
        :12
    ]
    experience_terms = _unique(
        [
            job.title,
            extraction.experience_requirements,
            *responsibilities,
        ]
    )
    education_requirements = _unique(
        [
            *extraction.education_requirements,
            *(
                item
                for item in extraction.required_qualifications
                if _contains_any(item, _DEGREE_MARKERS)
            ),
        ]
    )
    keywords = _unique(
        [*extraction.keywords, *required_skills, *_top_keywords(job.title + "\n" + job_text)]
    )[:20]

    factors: list[FitFactor] = []
    factors.append(
        _term_factor(
            "required_skills",
            required_skills,
            _resume_skill_text(content),
            "Direct and equivalent skill names found in the resume.",
        )
    )
    factors.append(
        _term_factor(
            "preferred_skills",
            preferred_skills,
            _resume_skill_text(content),
            "Preferred capabilities are scored separately from required skills.",
        )
    )
    factors.append(
        _term_factor(
            "relevant_experience",
            experience_terms,
            _experience_text(content),
            "Role, project, and achievement language compared with the target work.",
        )
    )
    factors.append(_seniority_factor(job, extraction, content))
    factors.append(
        _term_factor(
            "responsibilities",
            responsibilities,
            _experience_text(content),
            "Posting responsibilities compared with experience and project evidence.",
        )
    )
    factors.append(_industry_factor(job_text, extraction, resume_text, profile))
    factors.append(
        _term_factor(
            "education",
            education_requirements,
            _education_text(content),
            "Explicit degree and certification requirements only.",
        )
    )
    factors.append(
        _term_factor(
            "keywords",
            keywords,
            resume_text,
            "Important posting terms that already appear naturally in the resume.",
        )
    )
    factors.append(_location_mode_factor(job, extraction, content, profile))
    factors.append(_authorization_factor(job_text, extraction, profile))

    applicable = [factor for factor in factors if factor.total_count > 0]
    applicable_weight = sum(factor.weight for factor in applicable)
    base_score = (
        round(sum(factor.score * factor.weight for factor in applicable) / applicable_weight)
        if applicable_weight
        else 0
    )

    missing_critical = _critical_missing(
        extraction,
        required_skills,
        _resume_skill_text(content),
        resume_text,
    )
    critical_penalty = min(20, len(missing_critical) * 4)
    score = max(0, min(100, base_score - critical_penalty))
    return JobFitRatio(
        job_id=job.id,
        resume_version_id=resume_version.id,
        score=score,
        base_score=base_score,
        critical_penalty=critical_penalty,
        factors=factors,
        missing_critical=missing_critical,
        methodology=(
            "AptiorDesk scoring method 1.0 uses deterministic text and structured-field "
            "matching. Only factors with explicit job requirements are counted; their "
            "weights are normalized to 100. Explicit missing must-have qualifications "
            "apply a visible penalty of up to 20 points. The ratio is not an ATS score "
            "or a prediction of a hiring decision."
        ),
    )


def _term_factor(key: str, terms: list[str], candidate_text: str, explanation: str) -> FitFactor:
    terms = _unique(term for term in terms if _tokens(term))
    matched: list[str] = []
    missing: list[str] = []
    scores: list[int] = []
    for term in terms:
        score = _phrase_score(term, candidate_text)
        scores.append(score)
        (matched if score >= 60 else missing).append(term)
    return FitFactor(
        key=key,
        label=_LABELS[key],
        weight=_WEIGHTS[key],
        score=round(sum(scores) / len(scores)) if scores else 0,
        matched_count=len(matched),
        total_count=len(terms),
        matched=matched[:8],
        missing=missing[:8],
        explanation=explanation if terms else "No explicit requirement was found; excluded.",
    )


def _seniority_factor(job: Job, extraction: JobExtraction, content: ResumeContent) -> FitFactor:
    target = _seniority_rank(" ".join((job.experience_level, extraction.seniority, job.title)))
    candidate_ranks = [
        rank for exp in content.experiences if (rank := _seniority_rank(exp.title)) is not None
    ]
    candidate = max(candidate_ranks) if candidate_ranks else None
    if target is None:
        return _single_factor("seniority", 0, False, "No explicit seniority requirement found.")
    if candidate is None:
        return _single_factor(
            "seniority",
            0,
            True,
            "The job states a seniority level, but no experience title is available.",
        )
    difference = candidate - target
    if difference in (0, 1):
        score = 100
    elif difference == -1:
        score = 72
    elif difference <= -2:
        score = 32
    else:
        score = 88
    return _single_factor(
        "seniority",
        score,
        True,
        f"Target level {target}; strongest resume-title level {candidate}.",
    )


def _industry_factor(
    job_text: str,
    extraction: JobExtraction,
    resume_text: str,
    profile: Profile | None,
) -> FitFactor:
    job_industries = {
        industry
        for industry in _INDUSTRIES
        if industry in _normalised(job_text + " " + " ".join(extraction.keywords))
    }
    if not job_industries:
        return _single_factor("industry", 0, False, "No clear industry signal found.")
    candidate_blob = resume_text
    if profile is not None:
        candidate_blob += " " + " ".join(profile.preferences.target_industries)
    matched = [term for term in sorted(job_industries) if _phrase_score(term, candidate_blob) >= 60]
    score = round(len(matched) / len(job_industries) * 100)
    return FitFactor(
        key="industry",
        label=_LABELS["industry"],
        weight=_WEIGHTS["industry"],
        score=score,
        matched_count=len(matched),
        total_count=len(job_industries),
        matched=matched,
        missing=sorted(job_industries - set(matched)),
        explanation="Explicit industry terms compared with resume and profile preferences.",
    )


def _location_mode_factor(
    job: Job,
    extraction: JobExtraction,
    content: ResumeContent,
    profile: Profile | None,
) -> FitFactor:
    mode = (job.remote_type or "").casefold()
    location = (job.location or extraction.location or "").strip()
    if mode == "unknown" and not location:
        return _single_factor(
            "location_mode", 0, False, "No location or work-mode requirement found."
        )
    preferences = profile.preferences if profile is not None else None
    preferred_mode = (preferences.work_mode if preferences else "").casefold()
    preferred_locations = preferences.preferred_locations if preferences else []
    candidate_location = content.location
    checks: list[int] = []
    notes: list[str] = []
    if mode != "unknown":
        if not preferred_mode:
            checks.append(70)
            notes.append("work-mode preference not specified")
        elif (
            preferred_mode in ("flexible", mode) or mode == "remote" and preferred_mode == "hybrid"
        ):
            checks.append(100)
            notes.append(f"{mode} matches preference")
        else:
            checks.append(25)
            notes.append(f"{mode} differs from {preferred_mode}")
    if location and mode != "remote":
        location_blob = " ".join([candidate_location, *preferred_locations])
        location_score = _phrase_score(location, location_blob)
        checks.append(max(20, location_score))
        notes.append("location compared with resume and preferred locations")
    return _single_factor(
        "location_mode",
        round(sum(checks) / len(checks)) if checks else 0,
        bool(checks),
        "; ".join(notes).capitalize() + ".",
    )


def _authorization_factor(
    job_text: str, extraction: JobExtraction, profile: Profile | None
) -> FitFactor:
    requirement = extraction.work_authorization.strip()
    if not requirement:
        match = re.search(
            r"(?i)(?:must be )?(?:legally )?authorized to work[^.\n]*|"
            r"(?:no|without) (?:visa )?sponsorship[^.\n]*|"
            r"(?:visa )?sponsorship (?:is )?(?:not )?available[^.\n]*",
            job_text,
        )
        requirement = match.group(0) if match else ""
    if not requirement:
        return _single_factor("authorization", 0, False, "No work-authorization requirement found.")
    if profile is None or profile.work_auth.needs_sponsorship is None:
        return _single_factor(
            "authorization",
            50,
            True,
            "The job has an authorization requirement; profile status is not confirmed.",
        )
    denies_sponsorship = bool(
        re.search(r"(?i)\b(no|not|without|unable)\b.{0,22}\bsponsor", requirement)
    )
    if denies_sponsorship and profile.work_auth.needs_sponsorship:
        score = 0
        explanation = (
            "The job does not offer sponsorship and the profile says sponsorship is needed."
        )
    else:
        score = 100
        explanation = "The saved work-authorization profile is compatible with the posting."
    return _single_factor("authorization", score, True, explanation)


def _single_factor(key: str, score: int, applicable: bool, explanation: str) -> FitFactor:
    return FitFactor(
        key=key,
        label=_LABELS[key],
        weight=_WEIGHTS[key],
        score=score,
        matched_count=int(applicable and score >= 60),
        total_count=int(applicable),
        matched=[explanation] if applicable and score >= 60 else [],
        missing=[explanation] if applicable and score < 60 else [],
        explanation=explanation,
    )


def _critical_missing(
    extraction: JobExtraction,
    required_skills: list[str],
    skill_text: str,
    resume_text: str,
) -> list[str]:
    missing: list[str] = []
    for skill in required_skills:
        if _phrase_score(skill, skill_text) < 45:
            missing.append(skill)
    for requirement in extraction.required_qualifications:
        if (
            re.search(r"(?i)\b(must|required|minimum|mandatory)\b", requirement)
            and _phrase_score(requirement, resume_text) < 35
        ):
            missing.append(requirement)
    return _unique(missing)[:5]


def _resume_skill_text(content: ResumeContent) -> str:
    return "\n".join(
        [
            *(skill.name for skill in content.skills),
            content.summary,
            _experience_text(content),
            *(
                project.description + " " + " ".join(project.highlights)
                for project in content.projects
            ),
        ]
    )


def _experience_text(content: ResumeContent) -> str:
    return "\n".join(
        " ".join(
            [
                exp.title,
                exp.organization,
                exp.description,
                *exp.highlights,
            ]
        )
        for exp in content.experiences
    )


def _education_text(content: ResumeContent) -> str:
    return "\n".join(
        [
            *(
                " ".join((item.degree, item.field_of_study, item.institution, item.details))
                for item in content.education
            ),
            *(" ".join((item.name, item.issuer)) for item in content.certifications),
        ]
    )


def _skills_in_text(text: str) -> list[str]:
    normalised = _normalised(text)
    return sorted(skill for skill in _SKILL_VOCABULARY if _normalised(skill) in normalised)


def _responsibility_phrases(text: str) -> list[str]:
    phrases = []
    for line in text.splitlines():
        cleaned = re.sub(r"^[\s•*+\-\d.)]+", "", line).strip()
        if 18 <= len(cleaned) <= 220 and re.match(
            r"(?i)^(lead|manage|design|build|create|develop|deliver|own|drive|"
            r"collaborate|support|analyze|produce|maintain|coordinate|write|plan)",
            cleaned,
        ):
            phrases.append(cleaned)
    return _unique(phrases)[:12]


def _top_keywords(text: str) -> list[str]:
    words = [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", text.casefold())
        if token not in _STOPWORDS and not token.isdigit()
    ]
    return [word for word, _count in Counter(words).most_common(18)]


def _phrase_score(phrase: str, candidate_text: str) -> int:
    phrase_normal = _normalised(phrase)
    candidate_normal = _normalised(candidate_text)
    if not phrase_normal or not candidate_normal:
        return 0
    if phrase_normal in candidate_normal:
        return 100
    phrase_tokens = _tokens(phrase)
    candidate_tokens = _tokens(candidate_text)
    if not phrase_tokens:
        return 0
    overlap = len(phrase_tokens & candidate_tokens) / len(phrase_tokens)
    if len(phrase_tokens) == 1:
        return 100 if overlap == 1 else 0
    return round(overlap * 100)


def _tokens(text: str) -> set[str]:
    output: set[str] = set()
    for token in re.findall(r"[a-z0-9+#]+", text.casefold()):
        if token in _STOPWORDS or len(token) <= 1:
            continue
        output.add(_TOKEN_ALIASES.get(token, token.rstrip("s") if len(token) > 4 else token))
    return output


def _normalised(text: str) -> str:
    return " ".join(sorted(_tokens(text)))


def _seniority_rank(text: str) -> int | None:
    tokens = re.findall(r"[a-z]+", text.casefold())
    ranks = [_SENIORITY[token] for token in tokens if token in _SENIORITY]
    return max(ranks) if ranks else None


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in markers)


def _unique(items: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = " ".join(str(item or "").split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


__all__ = ["SCORING_VERSION", "calculate_job_fit_ratio"]
