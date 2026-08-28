"""Building the candidate profile from an extracted resume.

The behaviour that matters most here is what happens on the *second* import:
duplicates must not accumulate, and corrections the user made by hand must
survive.
"""

from __future__ import annotations

import pytest

from aptiordesk.database.models.extraction import ExtractionReport, FieldNote, Provenance
from aptiordesk.database.models.profile import Education, ProfileItem, Skill, WorkExperience
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.features.profile.import_service import (
    Action,
    ProfileImporter,
    Strategy,
    describe_item,
    identity_key,
)


@pytest.fixture
def content() -> ResumeContent:
    return ResumeContent(
        full_name="Ada Lovelace",
        professional_title="Senior Data Engineer",
        email="ada@example.com",
        phone="+44 20 7946 0958",
        location="London, UK",
        linkedin_url="linkedin.com/in/adalovelace",
        summary="Data engineer with eight years building analytical pipelines.",
        experiences=[
            WorkExperience(
                title="Principal Engineer",
                organization="Analytical Engines Ltd",
                start_date="2021-03",
                highlights=["Rebuilt the ingest pipeline."],
            ),
            WorkExperience(
                title="Data Engineer",
                organization="Analytical Engines Ltd",
                start_date="2018-01",
                end_date="2021-02",
            ),
        ],
        education=[
            Education(
                institution="University of London",
                degree="MSc",
                field_of_study="Mathematics",
                end_date="2017",
            )
        ],
        skills=[Skill(name="Python"), Skill(name="SQL"), Skill(name="Spark")],
    )


def _items(conn, kind=None):
    repo = ProfileRepository(conn)
    return repo.list_items(repo.get_default().id, kind)


# --- first import -------------------------------------------------------------


def test_first_import_populates_an_empty_profile(conn, content):
    importer = ProfileImporter(conn)

    plan = importer.build_plan(content)
    result = importer.apply_plan(plan)

    profile = ProfileRepository(conn).get_default()
    assert profile.display_name == "Ada Lovelace"
    assert profile.contact.email == "ada@example.com"
    assert profile.contact.location == "London, UK"
    assert profile.summary.startswith("Data engineer")
    # The headline title seeds the job-search targets rather than overwriting them.
    assert "Senior Data Engineer" in profile.preferences.target_titles

    assert len(_items(conn, "experience")) == 2
    assert len(_items(conn, "education")) == 1
    assert len(_items(conn, "skill")) == 3
    assert result.added == 6
    assert result.fields_set >= 6


def test_experience_maps_to_the_right_fields(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))

    entries = [i.parsed() for i in _items(conn, "experience")]
    principal = next(e for e in entries if e.title == "Principal Engineer")
    assert principal.organization == "Analytical Engines Ltd"
    assert principal.start_date == "2021-03"
    assert principal.end_date == ""  # current role
    assert principal.highlights == ["Rebuilt the ingest pipeline."]


def test_plan_writes_nothing_until_applied(conn, content):
    importer = ProfileImporter(conn)

    importer.build_plan(content)

    assert _items(conn) == []
    assert ProfileRepository(conn).get_default().display_name == ""


# --- re-import ----------------------------------------------------------------


def test_reimporting_the_same_resume_adds_nothing(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))

    plan = importer.build_plan(content)
    result = importer.apply_plan(plan)

    assert result.added == 0
    assert result.updated == 0
    assert len(_items(conn, "experience")) == 2
    assert len(_items(conn, "skill")) == 3
    assert plan.by_action(Action.SKIP_DUPLICATE)


def test_reimport_adds_only_the_new_role(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))

    updated = content.model_copy(deep=True)
    updated.experiences.insert(
        0,
        WorkExperience(title="Head of Data", organization="Babbage Systems", start_date="2024-06"),
    )
    plan = importer.build_plan(updated)
    result = importer.apply_plan(plan)

    assert result.added == 1
    assert len(_items(conn, "experience")) == 3


def test_a_role_whose_end_date_changed_is_updated_not_duplicated(conn, content):
    """The current role gained an end date — same role, not a new one."""
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))

    updated = content.model_copy(deep=True)
    updated.experiences[0].end_date = "2025-01"
    plan = importer.build_plan(updated)
    importer.apply_plan(plan)

    entries = _items(conn, "experience")
    assert len(entries) == 2  # not 3
    principal = next(e.parsed() for e in entries if e.data.get("title") == "Principal Engineer")
    assert principal.end_date == "2025-01"


# --- protecting the user's own edits ------------------------------------------


def test_a_hand_edited_entry_is_not_overwritten(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))
    repo = ProfileRepository(conn)
    entry = next(
        i for i in _items(conn, "experience") if i.data.get("title") == "Principal Engineer"
    )
    entry.data["highlights"] = ["My own carefully written bullet."]
    repo.update_item(entry)
    repo.mark_user_edited(entry.id)

    changed = content.model_copy(deep=True)
    changed.experiences[0].highlights = ["Rebuilt the ingest pipeline."]
    plan = importer.build_plan(changed)
    importer.apply_plan(plan)

    kept = next(
        i for i in _items(conn, "experience") if i.data.get("title") == "Principal Engineer"
    )
    assert kept.data["highlights"] == ["My own carefully written bullet."]
    conflicts = plan.conflicts()
    assert conflicts and conflicts[0].include is False


def test_a_conflict_is_applied_once_the_user_ticks_it(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))
    repo = ProfileRepository(conn)
    entry = next(
        i for i in _items(conn, "experience") if i.data.get("title") == "Principal Engineer"
    )
    entry.data["highlights"] = ["Mine."]
    repo.update_item(entry)
    repo.mark_user_edited(entry.id)

    changed = content.model_copy(deep=True)
    changed.experiences[0].highlights = ["Rebuilt the ingest pipeline."]
    plan = importer.build_plan(changed)
    for conflict in plan.conflicts():
        conflict.include = True  # the user approves the replacement
    importer.apply_plan(plan)

    kept = next(
        i for i in _items(conn, "experience") if i.data.get("title") == "Principal Engineer"
    )
    assert kept.data["highlights"] == ["Rebuilt the ingest pipeline."]
    assert kept.user_edited is False  # superseded by an approved import


def test_a_manually_typed_profile_field_becomes_a_conflict(conn, content):
    repo = ProfileRepository(conn)
    profile = repo.get_default()
    profile.summary = "A summary I wrote myself."
    profile.field_origin = {"summary": "manual"}
    repo.save(profile)

    plan = ProfileImporter(conn).build_plan(content)
    ProfileImporter(conn).apply_plan(plan)

    assert repo.get_default().summary == "A summary I wrote myself."
    assert any(c.target == "summary" for c in plan.conflicts())


# --- strategies ---------------------------------------------------------------


def test_fill_gaps_only_touches_empty_fields(conn, content):
    repo = ProfileRepository(conn)
    profile = repo.get_default()
    profile.summary = "Existing summary."
    repo.save(profile)

    importer = ProfileImporter(conn)
    plan = importer.build_plan(content, strategy=Strategy.FILL_GAPS)
    importer.apply_plan(plan)

    profile = repo.get_default()
    assert profile.summary == "Existing summary."  # untouched
    assert profile.display_name == "Ada Lovelace"  # was empty, so filled


def test_replace_removes_entries_absent_from_the_resume(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))
    repo = ProfileRepository(conn)
    repo.add_item(
        ProfileItem(profile_id=repo.get_default().id, kind="skill", data={"name": "COBOL"})
    )

    plan = importer.build_plan(content, strategy=Strategy.REPLACE)
    result = importer.apply_plan(plan)

    names = {i.data.get("name") for i in _items(conn, "skill")}
    assert "COBOL" not in names
    assert result.removed == 1


def test_replace_still_protects_hand_edited_entries_by_default(conn, content):
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content))
    repo = ProfileRepository(conn)
    extra = repo.add_item(
        ProfileItem(profile_id=repo.get_default().id, kind="skill", data={"name": "COBOL"})
    )
    repo.mark_user_edited(extra.id)

    plan = importer.build_plan(content, strategy=Strategy.REPLACE)
    removal = next(c for c in plan.by_action(Action.REMOVE) if c.existing_item_id == extra.id)

    assert removal.include is False  # deleting the user's own work is opt-in
    importer.apply_plan(plan)
    assert "COBOL" in {i.data.get("name") for i in _items(conn, "skill")}


# --- provenance carried through -----------------------------------------------


def test_inferred_entries_arrive_flagged_for_review(conn, content):
    report = ExtractionReport(
        notes=[
            FieldNote(path="experiences.0.organization", provenance=Provenance.INFERRED),
            FieldNote(path="experiences.1.organization", provenance=Provenance.EXTRACTED),
        ]
    )
    importer = ProfileImporter(conn)

    plan = importer.build_plan(content, report)
    importer.apply_plan(plan)

    entries = {i.data.get("title"): i for i in _items(conn, "experience")}
    assert entries["Principal Engineer"].needs_review is True
    assert entries["Principal Engineer"].provenance == "inferred"
    assert entries["Data Engineer"].needs_review is False


def test_source_resume_version_is_recorded(conn, content):
    """Items remember which resume version they came from, so the profile can
    show provenance and a re-import can reason about supersession."""
    from aptiordesk.features.resumes.service import ResumeService

    _, version = ResumeService(conn).create_manual("Ada CV", content)
    importer = ProfileImporter(conn)

    plan = importer.build_plan(content, source_resume_version_id=version.id)
    importer.apply_plan(plan)

    assert all(i.source_resume_version_id == version.id for i in _items(conn, "experience"))


# --- identity and labels ------------------------------------------------------


def test_identity_key_ignores_punctuation_and_case():
    a = identity_key(
        "experience",
        {
            "organization": "Analytical Engines, Ltd.",
            "title": "Principal Engineer",
            "start_date": "2021-03",
        },
    )
    b = identity_key(
        "experience",
        {
            "organization": "analytical engines ltd",
            "title": "PRINCIPAL ENGINEER",
            "start_date": "2021-03",
        },
    )
    assert a == b


def test_describe_item_reads_naturally():
    label = describe_item(
        "experience",
        {
            "title": "Principal Engineer",
            "organization": "Analytical Engines Ltd",
            "start_date": "2021-03",
        },
    )
    assert "Principal Engineer" in label
    assert "Analytical Engines Ltd" in label

    assert describe_item("skill", {"name": "Python"}) == "Python"
    assert describe_item("award", {"title": "Turing Prize"}) == "Turing Prize"


def test_plan_summary_is_human_readable(conn, content):
    plan = ProfileImporter(conn).build_plan(content)
    assert "to add" in plan.summary()


def test_describe_item_does_not_truncate_titles_ending_in_stripped_chars():
    """Regression: `.strip(" at ")` removed trailing a/t characters."""
    assert describe_item("experience", {"title": "Analyst"}).startswith("Analyst")
    assert describe_item("experience", {"organization": "Meta"}) == "Meta"
    assert describe_item("experience", {"title": "Data"}) == "Data"
