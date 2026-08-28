"""Build the candidate profile from an extracted resume.

The resume and the profile already share their item models, so mapping is
mechanical. What is not mechanical is deciding what to do when the profile
already has content — which is the normal case on a re-import, and the case
where a careless implementation destroys work the user did by hand.

The rules this module enforces:

* Nothing is written until the user approves a plan. ``build_plan`` computes
  what *would* change; ``apply_plan`` performs only the changes still marked
  ``include``.
* A profile value the user typed or corrected (``user_edited``) is never
  overwritten by an import. It becomes a ``CONFLICT`` the user must resolve
  deliberately.
* Values the AI inferred rather than read from the document are carried in
  flagged, so they arrive in the profile marked for review rather than as
  established fact.
* Duplicates are detected on a per-kind identity key so re-importing an
  updated resume adds the new role instead of a second copy of every old one.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from aptiordesk.ai.prompts.grounding import normalise_for_match
from aptiordesk.database.models.extraction import ExtractionReport, Provenance
from aptiordesk.database.models.profile import Profile, ProfileItem
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.database.repositories.profile_repo import ProfileRepository

log = logging.getLogger(__name__)


class Strategy(StrEnum):
    """What the user chose to do about existing profile content."""

    MERGE = "merge"  # add what is new, keep what is there
    REPLACE = "replace"  # imported resume becomes the profile
    FILL_GAPS = "fill_gaps"  # only populate fields that are currently empty


class Action(StrEnum):
    ADD = "add"
    UPDATE = "update"
    SKIP_DUPLICATE = "skip_duplicate"
    CONFLICT = "conflict"  # differs from something the user edited by hand
    REMOVE = "remove"  # only under REPLACE


#: Which fields identify an item, per kind. Two items agreeing on all of these
#: are the same real-world thing even if their descriptions differ.
IDENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "experience": ("organization", "title", "start_date"),
    "education": ("institution", "degree", "field_of_study"),
    "skill": ("name",),
    "language": ("name",),
    "certification": ("name", "issuer"),
    "project": ("name",),
    "award": ("title", "organization"),
    "publication": ("title", "organization"),
    "volunteer": ("title", "organization"),
}

#: Resume content list fields -> profile item kinds.
LIST_FIELD_TO_KIND: dict[str, str] = {
    "experiences": "experience",
    "education": "education",
    "skills": "skill",
    "projects": "project",
    "certifications": "certification",
    "languages": "language",
    "awards": "award",
    "publications": "publication",
    "volunteer": "volunteer",
}

#: Resume scalar fields -> where they live on the profile.
SCALAR_MAP: dict[str, str] = {
    "full_name": "display_name",
    "summary": "summary",
    "email": "contact.email",
    "phone": "contact.phone",
    "location": "contact.location",
    "linkedin_url": "contact.linkedin_url",
    "github_url": "contact.github_url",
    "portfolio_url": "contact.portfolio_url",
    "professional_title": "preferences.target_titles",
}


@dataclass
class ProposedChange:
    """One reviewable line in the import plan."""

    action: Action
    label: str
    target: str  # profile field path or item kind
    new_value: str = ""
    current_value: str = ""
    provenance: Provenance = Provenance.EXTRACTED
    reason: str = ""
    include: bool = True
    #: Set for item changes; None for scalar field changes.
    item: ProfileItem | None = None
    existing_item_id: int | None = None

    @property
    def needs_attention(self) -> bool:
        return self.action is Action.CONFLICT or self.provenance is Provenance.INFERRED


@dataclass
class ImportPlan:
    strategy: Strategy
    changes: list[ProposedChange] = field(default_factory=list)
    profile_id: int | None = None
    source_resume_version_id: int | None = None

    def by_action(self, action: Action) -> list[ProposedChange]:
        return [c for c in self.changes if c.action is action]

    def included(self) -> list[ProposedChange]:
        return [c for c in self.changes if c.include]

    def conflicts(self) -> list[ProposedChange]:
        return self.by_action(Action.CONFLICT)

    def needs_review(self) -> list[ProposedChange]:
        return [c for c in self.changes if c.needs_attention]

    def summary(self) -> str:
        if not self.changes:
            return "Your profile already matches this resume — nothing to import."
        parts = []
        for action, word in (
            (Action.ADD, "to add"),
            (Action.UPDATE, "to update"),
            (Action.SKIP_DUPLICATE, "already present"),
            (Action.CONFLICT, "needing a decision"),
            (Action.REMOVE, "to remove"),
        ):
            count = len(self.by_action(action))
            if count:
                parts.append(f"{count} {word}")
        return ", ".join(parts) + "."


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    fields_set: int = 0

    def summary(self) -> str:
        bits = []
        if self.fields_set:
            bits.append(f"{self.fields_set} profile field(s) filled in")
        if self.added:
            bits.append(f"{self.added} entry/entries added")
        if self.updated:
            bits.append(f"{self.updated} updated")
        if self.removed:
            bits.append(f"{self.removed} removed")
        if self.skipped:
            bits.append(f"{self.skipped} skipped as duplicates")
        return ("Imported: " + ", ".join(bits) + ".") if bits else "Nothing was changed."


class ProfileImporter:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._repo = ProfileRepository(conn)

    # -- planning ------------------------------------------------------------

    def build_plan(
        self,
        content: ResumeContent,
        report: ExtractionReport | None = None,
        *,
        strategy: Strategy = Strategy.MERGE,
        source_resume_version_id: int | None = None,
    ) -> ImportPlan:
        """Compute what importing `content` would do. Writes nothing."""
        profile = self._repo.get_default()
        existing = self._repo.list_items(profile.id)
        plan = ImportPlan(
            strategy=strategy,
            profile_id=profile.id,
            source_resume_version_id=source_resume_version_id,
        )

        self._plan_scalars(plan, profile, content, report, strategy)
        self._plan_items(plan, profile, content, report, existing, strategy)
        return plan

    def _plan_scalars(
        self,
        plan: ImportPlan,
        profile: Profile,
        content: ResumeContent,
        report: ExtractionReport | None,
        strategy: Strategy,
    ) -> None:
        edited = _edited_fields(profile)
        for resume_field, profile_path in SCALAR_MAP.items():
            new_value = getattr(content, resume_field, "") or ""
            if not new_value.strip():
                continue
            current = _read_path(profile, profile_path)
            provenance = report.provenance_for(resume_field) if report else Provenance.EXTRACTED
            label = _humanise(profile_path)

            if _same(current, new_value):
                continue
            if not current:
                plan.changes.append(
                    ProposedChange(
                        action=Action.ADD,
                        label=label,
                        target=profile_path,
                        new_value=new_value,
                        provenance=provenance,
                        reason="Currently empty in your profile.",
                    )
                )
                continue
            if strategy is Strategy.FILL_GAPS:
                continue
            if profile_path in edited:
                plan.changes.append(
                    ProposedChange(
                        action=Action.CONFLICT,
                        label=label,
                        target=profile_path,
                        new_value=new_value,
                        current_value=str(current),
                        provenance=provenance,
                        include=False,
                        reason=(
                            "You edited this yourself. It will be kept unless you tick this line."
                        ),
                    )
                )
                continue
            plan.changes.append(
                ProposedChange(
                    action=Action.UPDATE,
                    label=label,
                    target=profile_path,
                    new_value=new_value,
                    current_value=str(current),
                    provenance=provenance,
                    include=strategy is Strategy.REPLACE,
                    reason="Differs from what your resume says.",
                )
            )

    def _plan_items(
        self,
        plan: ImportPlan,
        profile: Profile,
        content: ResumeContent,
        report: ExtractionReport | None,
        existing: list[ProfileItem],
        strategy: Strategy,
    ) -> None:
        by_kind: dict[str, list[ProfileItem]] = {}
        for item in existing:
            by_kind.setdefault(item.kind, []).append(item)

        seen_existing: set[int] = set()

        for resume_field, kind in LIST_FIELD_TO_KIND.items():
            entries = getattr(content, resume_field, None) or []
            for index, entry in enumerate(entries):
                data = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
                key = identity_key(kind, data)
                match = _find_match(by_kind.get(kind, []), kind, key)
                provenance = _entry_provenance(report, resume_field, index)
                label = describe_item(kind, data)

                if match is None:
                    plan.changes.append(
                        ProposedChange(
                            action=Action.ADD,
                            label=label,
                            target=kind,
                            new_value=label,
                            provenance=provenance,
                            item=ProfileItem(
                                profile_id=profile.id,
                                kind=kind,
                                data=data,
                                sort_order=index,
                            ),
                        )
                    )
                    continue

                seen_existing.add(match.id)
                if _same_data(match.data, data):
                    plan.changes.append(
                        ProposedChange(
                            action=Action.SKIP_DUPLICATE,
                            label=label,
                            target=kind,
                            provenance=provenance,
                            include=False,
                            existing_item_id=match.id,
                            reason="Already in your profile, unchanged.",
                        )
                    )
                elif match.user_edited and strategy is not Strategy.REPLACE:
                    plan.changes.append(
                        ProposedChange(
                            action=Action.CONFLICT,
                            label=label,
                            target=kind,
                            new_value=_describe_data(data),
                            current_value=_describe_data(match.data),
                            provenance=provenance,
                            include=False,
                            existing_item_id=match.id,
                            item=ProfileItem(
                                profile_id=profile.id,
                                kind=kind,
                                data=data,
                                sort_order=index,
                            ),
                            reason=(
                                "You edited this entry. Your version is kept unless "
                                "you tick this line."
                            ),
                        )
                    )
                elif strategy is Strategy.FILL_GAPS:
                    continue
                else:
                    plan.changes.append(
                        ProposedChange(
                            action=Action.UPDATE,
                            label=label,
                            target=kind,
                            new_value=_describe_data(data),
                            current_value=_describe_data(match.data),
                            provenance=provenance,
                            existing_item_id=match.id,
                            item=ProfileItem(
                                profile_id=profile.id,
                                kind=kind,
                                data=data,
                                sort_order=index,
                                id=match.id,
                            ),
                            reason="This entry has changed since you last imported.",
                        )
                    )

        if strategy is Strategy.REPLACE:
            for item in existing:
                if item.id in seen_existing:
                    continue
                plan.changes.append(
                    ProposedChange(
                        action=Action.REMOVE,
                        label=describe_item(item.kind, item.data),
                        target=item.kind,
                        existing_item_id=item.id,
                        current_value=_describe_data(item.data),
                        reason="Not present in the resume you are importing.",
                        # Even under Replace, deleting the user's own work is
                        # opt-in rather than automatic.
                        include=not item.user_edited,
                    )
                )

    # -- applying ------------------------------------------------------------

    def apply_plan(self, plan: ImportPlan) -> ImportResult:
        """Apply only the included changes. Everything else is left alone."""
        profile = self._repo.get_default()
        result = ImportResult()
        origin = _field_origin(profile)

        for change in plan.changes:
            if not change.include:
                if change.action is Action.SKIP_DUPLICATE:
                    result.skipped += 1
                continue

            if change.item is None and change.action in (
                Action.ADD,
                Action.UPDATE,
                Action.CONFLICT,
            ):
                _write_path(profile, change.target, change.new_value)
                origin[change.target] = str(change.provenance)
                result.fields_set += 1
            elif change.action is Action.REMOVE and change.existing_item_id:
                self._repo.delete_item(change.existing_item_id)
                result.removed += 1
            elif change.item is not None:
                item = change.item
                item.provenance = str(change.provenance)
                item.source_resume_version_id = plan.source_resume_version_id
                item.needs_review = change.provenance is Provenance.INFERRED
                if change.existing_item_id:
                    item.id = change.existing_item_id
                    # An import supersedes the old value, so it is no longer a
                    # hand-edit; the user re-approved it by including this line.
                    item.user_edited = False
                    self._repo.update_item(item)
                    result.updated += 1
                else:
                    self._repo.add_item(item)
                    result.added += 1

        profile.field_origin = origin
        self._repo.save(profile)
        log.info("Profile import applied: %s", result.summary())
        return result


# --- identity and comparison --------------------------------------------------


def identity_key(kind: str, data: dict) -> tuple[str, ...]:
    """The normalised fields that decide whether two entries are the same."""
    fields = IDENTITY_KEYS.get(kind, ("title", "organization"))
    return tuple(normalise_for_match(str(data.get(f, "") or "")) for f in fields)


def _find_match(
    candidates: Iterable[ProfileItem], kind: str, key: tuple[str, ...]
) -> ProfileItem | None:
    non_empty = [part for part in key if part]
    if not non_empty:
        return None
    for item in candidates:
        existing_key = identity_key(kind, item.data)
        if existing_key == key:
            return item
        # A role whose end date changed (or whose title gained "Senior") is the
        # same role: agreeing on every non-empty component is enough.
        shared = [(a, b) for a, b in zip(key, existing_key, strict=False) if a and b]
        if shared and all(a == b for a, b in shared) and len(shared) >= 2:
            return item
    return None


def _same(a: object, b: object) -> bool:
    if isinstance(a, list):
        return any(normalise_for_match(str(x)) == normalise_for_match(str(b)) for x in a)
    return normalise_for_match(str(a or "")) == normalise_for_match(str(b or ""))


def _same_data(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    for key in keys:
        left, right = a.get(key), b.get(key)
        if isinstance(left, list) or isinstance(right, list):
            left_items = [normalise_for_match(str(x)) for x in (left or [])]
            right_items = [normalise_for_match(str(x)) for x in (right or [])]
            if left_items != right_items:
                return False
        elif normalise_for_match(str(left or "")) != normalise_for_match(str(right or "")):
            return False
    return True


def _entry_provenance(report: ExtractionReport | None, resume_field: str, index: int) -> Provenance:
    """An entry is only as trustworthy as its least-grounded field."""
    if report is None:
        return Provenance.EXTRACTED
    prefix = f"{resume_field}.{index}."
    relevant = [n for n in report.notes if n.path.startswith(prefix)]
    if any(n.provenance is Provenance.INFERRED for n in relevant):
        return Provenance.INFERRED
    if any(n.provenance is Provenance.EXTRACTED for n in relevant):
        return Provenance.EXTRACTED
    return Provenance.MISSING


# --- description helpers ------------------------------------------------------


def describe_item(kind: str, data: dict) -> str:
    """A short human label for one entry, used throughout the review UI."""

    def get(*names: str) -> str:
        return next((str(data[n]) for n in names if data.get(n)), "")

    if kind == "experience":
        title, org = get("title"), get("organization")
        # Never str.strip(" at ") here: that strips the *characters* a, t, and
        # space, so "Analyst" would lose its trailing "t".
        who = " at ".join(x for x in (title, org) if x)
        start, end = get("start_date"), get("end_date")
        # "present" only means something once there is a start date; an entry
        # with no dates at all should show none.
        dates = f"{start} – {end or 'present'}" if start else end
        return " · ".join(x for x in (who, dates) if x)
    if kind == "education":
        return " · ".join(
            x
            for x in (
                f"{get('degree')} {get('field_of_study')}".strip(),
                get("institution"),
                get("end_date"),
            )
            if x
        )
    if kind in ("skill", "language", "project", "certification"):
        return get("name") or "(unnamed)"
    return get("title", "name") or "(untitled)"


def _describe_data(data: dict) -> str:
    parts = []
    for key, value in data.items():
        if not value:
            continue
        if isinstance(value, list):
            parts.append(f"{_humanise(key)}: {len(value)} item(s)")
        else:
            parts.append(f"{_humanise(key)}: {value}")
    return "; ".join(parts)


def _humanise(path: str) -> str:
    return path.split(".")[-1].replace("_", " ").replace(" url", " URL").capitalize()


# --- profile field access -----------------------------------------------------


def _read_path(profile: Profile, path: str) -> object:
    target: object = profile
    for part in path.split("."):
        target = getattr(target, part, "")
    return target


def _write_path(profile: Profile, path: str, value: str) -> None:
    parts = path.split(".")
    target: object = profile
    for part in parts[:-1]:
        target = getattr(target, part)
    leaf = parts[-1]
    current = getattr(target, leaf, "")
    if isinstance(current, list):
        # target_titles and friends: append rather than clobber.
        if not any(normalise_for_match(str(x)) == normalise_for_match(value) for x in current):
            setattr(target, leaf, [*current, value])
    else:
        setattr(target, leaf, value)


def _field_origin(profile: Profile) -> dict:
    return dict(getattr(profile, "field_origin", {}) or {})


def _edited_fields(profile: Profile) -> set[str]:
    """Profile paths whose current value the user set by hand."""
    return {path for path, origin in _field_origin(profile).items() if origin in ("manual", "user")}


__all__ = [
    "Action",
    "ImportPlan",
    "ImportResult",
    "ProfileImporter",
    "ProposedChange",
    "Strategy",
    "describe_item",
    "identity_key",
]
