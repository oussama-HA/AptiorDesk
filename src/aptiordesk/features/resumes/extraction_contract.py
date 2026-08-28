"""Strict, lossless boundary models for resume extraction.

AI providers do not always honour the exact field names in a JSON example.
That is expected at the transport boundary, but it must not leak into the
domain model.  Pydantic's default ``extra='ignore'`` is useful for long-lived
stored profile data; it is dangerous for model output because an object such
as ``{"job_title": "Engineer", "company": "Acme"}`` validates as a wholly
empty ``WorkExperience``.

These extraction-only models keep the persisted domain schema permissive for
forward compatibility while making the AI boundary strict.  Common,
unambiguous aliases are translated to the canonical fields.  Anything else is
rejected so ``AIProvider.structured`` can ask the model to repair its response
instead of silently deleting the candidate's information.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ConfigDict, model_validator

from aptiordesk.database.models.profile import (
    Certification,
    Education,
    Language,
    Project,
    SimpleEntry,
    Skill,
    WorkExperience,
)

_KEY_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")
_RANGE_SEPARATOR = re.compile(r"\s+(?:-|to)\s+|\s*[–—]\s*", re.IGNORECASE)
_CURRENT = {"current", "currently", "now", "ongoing", "present"}


def _key(value: object) -> str:
    text = _KEY_BOUNDARY.sub("_", str(value).strip())
    return _NON_WORD.sub("_", text).strip("_").lower()


def _empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_value(target: dict[str, Any], key: str, value: Any) -> None:
    """Merge aliases without choosing arbitrarily between conflicting data."""
    if key not in target or _empty(target[key]):
        target[key] = value
        return
    if _empty(value) or target[key] == value:
        return
    if isinstance(target[key], list) and isinstance(value, list):
        target[key] = [*target[key], *value]
        return
    raise ValueError(f"conflicting values were returned for {key!r}")


def _normalise_mapping(value: object, aliases: Mapping[str, str]) -> object:
    if not isinstance(value, Mapping):
        return value
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        normalised = _key(raw_key)
        _merge_value(result, aliases.get(normalised, normalised), raw_value)
    return result


def _normalise_list(value: object, item_type: type) -> object:
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    return [item_type.normalise(item) for item in value]


def _normalise_named_list(value: object, item_type: type, name_key: str = "name") -> object:
    """Accept a model's common shorthand of returning a list of strings."""
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    return [
        {name_key: item} if isinstance(item, str) else item_type.normalise(item) for item in value
    ]


def _normalise_bullets(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        lines = [line.strip().lstrip("-•* ") for line in value.splitlines() if line.strip()]
        return lines or [value]
    return value


def _apply_date_range(data: object) -> object:
    if not isinstance(data, dict):
        return data
    date_range = data.pop("__date_range", None)
    if _empty(date_range):
        return data
    if not isinstance(date_range, str):
        raise ValueError("date range must be text")
    parts = _RANGE_SEPARATOR.split(date_range.strip(), maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError("date range must contain both a start and an end")
    start, end = (part.strip() for part in parts)
    if _key(end) in _CURRENT:
        end = ""
    _merge_value(data, "start_date", start)
    _merge_value(data, "end_date", end)
    return data


_DATE_ALIASES = {
    "start": "start_date",
    "from": "start_date",
    "date_from": "start_date",
    "started": "start_date",
    "end": "end_date",
    "to": "end_date",
    "date_to": "end_date",
    "ended": "end_date",
    "dates": "__date_range",
    "date_range": "__date_range",
    "employment_dates": "__date_range",
    "period": "__date_range",
    "tenure": "__date_range",
}


class ExtractedWorkExperience(WorkExperience):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        data = _normalise_mapping(
            value,
            {
                **_DATE_ALIASES,
                "job_title": "title",
                "position": "title",
                "position_title": "title",
                "role": "title",
                "role_title": "title",
                "company": "organization",
                "company_name": "organization",
                "employer": "organization",
                "employer_name": "organization",
                "organisation": "organization",
                "job_location": "location",
                "work_location": "location",
                "job_description": "description",
                "role_description": "description",
                "summary": "description",
                "achievements": "highlights",
                "accomplishments": "highlights",
                "bullets": "highlights",
                "key_achievements": "highlights",
            },
        )
        data = _apply_date_range(data)
        if isinstance(data, dict):
            if "responsibilities" in data:
                responsibilities = data.pop("responsibilities")
                target = "highlights" if isinstance(responsibilities, list) else "description"
                _merge_value(data, target, responsibilities)
            if "duties" in data:
                duties = data.pop("duties")
                target = "highlights" if isinstance(duties, list) else "description"
                _merge_value(data, target, duties)
            if "highlights" in data:
                data["highlights"] = _normalise_bullets(data["highlights"])
            if _key(data.get("end_date", "")) in _CURRENT:
                data["end_date"] = ""
        return data

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


class ExtractedEducation(Education):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        data = _normalise_mapping(
            value,
            {
                **_DATE_ALIASES,
                "school": "institution",
                "school_name": "institution",
                "university": "institution",
                "university_name": "institution",
                "college": "institution",
                "qualification": "degree",
                "degree_name": "degree",
                "field": "field_of_study",
                "major": "field_of_study",
                "subject": "field_of_study",
                "specialization": "field_of_study",
                "specialisation": "field_of_study",
                "graduation_date": "end_date",
                "graduation_year": "end_date",
                "year": "end_date",
                "description": "details",
                "honors": "details",
                "honours": "details",
            },
        )
        return _apply_date_range(data)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


class ExtractedSkill(Skill):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        return _normalise_mapping(
            value,
            {
                "skill": "name",
                "technology": "name",
                "tool": "name",
                "proficiency": "level",
                "rating": "level",
                "group": "category",
                "type": "category",
            },
        )

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


class ExtractedCertification(Certification):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        return _normalise_mapping(
            value,
            {
                "title": "name",
                "certification": "name",
                "authority": "issuer",
                "organization": "issuer",
                "organisation": "issuer",
                "provider": "issuer",
                "issue_date": "date",
                "issued": "date",
                "credential_url": "url",
                "link": "url",
            },
        )

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


class ExtractedLanguage(Language):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        return _normalise_mapping(
            value,
            {"language": "name", "level": "proficiency", "fluency": "proficiency"},
        )

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


class ExtractedProject(Project):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        data = _normalise_mapping(
            value,
            {
                "title": "name",
                "project_name": "name",
                "link": "url",
                "project_url": "url",
                "summary": "description",
                "achievements": "highlights",
                "bullets": "highlights",
            },
        )
        if isinstance(data, dict) and "highlights" in data:
            data["highlights"] = _normalise_bullets(data["highlights"])
        return data

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


class ExtractedSimpleEntry(SimpleEntry):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @classmethod
    def normalise(cls, value: object) -> object:
        return _normalise_mapping(
            value,
            {
                "name": "title",
                "company": "organization",
                "organisation": "organization",
                "issuer": "organization",
                "summary": "description",
            },
        )

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return cls.normalise(value)


def normalise_contact(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    # Models often wrap the contact block even when asked for a flat object.
    flattened: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if _key(raw_key) in {"contact", "contact_details", "contact_info", "personal_info"}:
            if not isinstance(raw_value, Mapping):
                raise ValueError("contact details must be an object")
            for nested_key, nested_value in raw_value.items():
                _merge_value(flattened, str(nested_key), nested_value)
        else:
            _merge_value(flattened, str(raw_key), raw_value)
    return _normalise_mapping(
        flattened,
        {
            "name": "full_name",
            "candidate_name": "full_name",
            "headline": "professional_title",
            "job_title": "professional_title",
            "title": "professional_title",
            "professional_summary": "summary",
            "profile": "summary",
            "objective": "summary",
            "email_address": "email",
            "phone_number": "phone",
            "telephone": "phone",
            "address": "location",
            "linkedin": "linkedin_url",
            "linkedin_profile": "linkedin_url",
            "github": "github_url",
            "github_profile": "github_url",
            "portfolio": "portfolio_url",
            "website": "portfolio_url",
        },
    )


def normalise_section(
    value: object,
    *,
    primary_field: str,
    aliases: Mapping[str, str],
    list_fields: Mapping[str, tuple[type, bool]],
) -> object:
    """Normalise one section envelope and each of its list entries."""
    if isinstance(value, list):
        value = {primary_field: value}
    data = _normalise_mapping(value, aliases)
    if not isinstance(data, dict):
        return data
    for field, (item_type, accepts_strings) in list_fields.items():
        if field not in data:
            continue
        if accepts_strings:
            data[field] = _normalise_named_list(data[field], item_type)
        else:
            data[field] = _normalise_list(data[field], item_type)
    return data


__all__ = [
    "ExtractedCertification",
    "ExtractedEducation",
    "ExtractedLanguage",
    "ExtractedProject",
    "ExtractedSimpleEntry",
    "ExtractedSkill",
    "ExtractedWorkExperience",
    "normalise_contact",
    "normalise_section",
]
