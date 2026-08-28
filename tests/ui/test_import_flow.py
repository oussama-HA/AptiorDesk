"""The import review screens, driven the way a user drives them.

These are the screens standing between a misread resume and a corrupted
profile, so they are exercised against real extraction output rather than
constructed in isolation.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import Qt

from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.documents.pipeline import load_document
from aptiordesk.features.profile.import_service import Action
from aptiordesk.features.resumes.extraction import SECTIONS, ResumeExtractor
from aptiordesk.ui.components.extraction_review import ExtractionReviewDialog
from aptiordesk.ui.components.profile_import_dialog import ProfileImportDialog
from tests.helpers import SectionedProvider, make_minimal_pdf

RESUME = """Ada Lovelace
Senior Data Engineer
ada@example.com | London, UK

EXPERIENCE
Principal Engineer, Analytical Engines Ltd, London
March 2021 - Present
- Rebuilt the ingest pipeline.

SKILLS
Python, SQL
"""

_SECTION_RESPONSES = {
    "contact": {
        "full_name": "Ada Lovelace",
        "professional_title": "Senior Data Engineer",
        "email": "ada@example.com",
        "location": "London, UK",
    },
    "experience": {
        "experiences": [
            {
                "title": "Principal Engineer",
                "organization": "Analytical Engines Ltd",
                "start_date": "2021-03",
                "highlights": ["Rebuilt the ingest pipeline."],
            },
            # Not in the document: must be flagged as inferred.
            {"title": "CTO", "organization": "Cyberdyne Systems", "start_date": "2015-01"},
        ]
    },
    "education": {"education": []},
    "skills": {
        "skills": [{"name": "Python"}, {"name": "SQL"}],
        "certifications": [],
        "languages": [],
    },
    "extras": {"projects": [], "awards": [], "publications": [], "volunteer": []},
}


@pytest.fixture
def extracted(tmp_path):
    path = tmp_path / "ada.pdf"
    path.write_bytes(make_minimal_pdf(RESUME.splitlines()))
    document = load_document(path)
    provider = SectionedProvider(
        {spec.key: json.dumps(_SECTION_RESPONSES[spec.key]) for spec in SECTIONS}
    )
    content, report = ResumeExtractor(provider).extract(document)
    return document, content, report


# --- the extraction review screen ---------------------------------------------


def test_review_dialog_shows_source_text_and_flags(qtbot, extracted):
    document, content, report = extracted
    dialog = ExtractionReviewDialog(content, report, document)
    qtbot.addWidget(dialog)

    titles = _tab_titles(dialog)

    # The flagged tab is named with the count of things to check.
    assert any("Extracted information" in t for t in titles), titles
    assert any("Needs checking (3)" in t for t in titles), titles
    assert any("Text read from the file" in t for t in titles)
    assert any("Problems" in t for t in titles)


def test_review_dialog_returns_user_corrections(qtbot, extracted):
    document, content, report = extracted
    dialog = ExtractionReviewDialog(content, report, document)
    qtbot.addWidget(dialog)

    dialog._editor._fields["full_name"].setText("Ada B. Lovelace")

    assert dialog.content().full_name == "Ada B. Lovelace"
    # Corrections must not disturb the rest of the extraction.
    assert len(dialog.content().experiences) == 2


def test_review_dialog_handles_an_empty_extraction_without_crashing(qtbot, tmp_path):
    """A resume the AI got nothing useful from must still render."""
    from aptiordesk.database.models.extraction import ExtractionReport
    from aptiordesk.database.models.resume import ResumeContent

    path = tmp_path / "thin.txt"
    path.write_text("Ada Lovelace")
    document = load_document(path)
    dialog = ExtractionReviewDialog(ResumeContent(), ExtractionReport(), document)
    qtbot.addWidget(dialog)

    assert dialog.content().is_empty()


# --- the profile import screen ------------------------------------------------


def test_profile_import_dialog_lists_changes_and_applies_them(qtbot, conn, extracted):
    _, content, report = extracted
    dialog = ProfileImportDialog(conn, content, report)
    qtbot.addWidget(dialog)

    assert dialog.tree.topLevelItemCount() > 0
    # Apply the plan directly: _apply() shows a modal confirmation, which has
    # no place in an automated run.
    dialog._importer.apply_plan(dialog._plan)

    repo = ProfileRepository(conn)
    profile = repo.get_default()
    assert profile.display_name == "Ada Lovelace"
    assert profile.contact.email == "ada@example.com"
    assert len(repo.list_items(profile.id, "experience")) == 2


def test_inferred_rows_are_marked_in_the_list(qtbot, conn, extracted):
    _, content, report = extracted
    dialog = ProfileImportDialog(conn, content, report)
    qtbot.addWidget(dialog)

    flagged = [
        dialog.tree.topLevelItem(i).text(1)
        for i in range(dialog.tree.topLevelItemCount())
        if dialog.tree.topLevelItem(i).text(1).startswith("⚠")
    ]
    assert any("Cyberdyne" in text for text in flagged), flagged


def test_unticking_a_row_excludes_it(qtbot, conn, extracted):
    _, content, report = extracted
    dialog = ProfileImportDialog(conn, content, report)
    qtbot.addWidget(dialog)
    before = len(dialog._plan.included())

    dialog.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)

    assert len(dialog._plan.included()) == before - 1


def test_select_none_then_apply_changes_nothing(qtbot, conn, extracted):
    _, content, report = extracted
    dialog = ProfileImportDialog(conn, content, report)
    qtbot.addWidget(dialog)

    dialog._set_all(False)
    dialog._importer.apply_plan(dialog._plan)

    repo = ProfileRepository(conn)
    profile = repo.get_default()
    assert profile.display_name == ""
    assert repo.list_items(profile.id) == []


def test_switching_strategy_rebuilds_the_plan(qtbot, conn, extracted):
    from aptiordesk.features.profile.import_service import Strategy

    _, content, report = extracted
    dialog = ProfileImportDialog(conn, content, report)
    qtbot.addWidget(dialog)
    dialog._importer.apply_plan(dialog._plan)  # first import

    index = next(
        i
        for i in range(dialog.strategy_box.count())
        if Strategy(dialog.strategy_box.itemData(i)) is Strategy.REPLACE
    )
    dialog.strategy_box.setCurrentIndex(index)

    assert dialog._plan.strategy is Strategy.REPLACE
    # Second pass over the same content: everything is now a duplicate.
    assert dialog._plan.by_action(Action.SKIP_DUPLICATE)


def _tab_titles(dialog) -> list[str]:
    from PySide6.QtWidgets import QTabWidget

    tabs = dialog.findChild(QTabWidget)
    return [tabs.tabText(i) for i in range(tabs.count())]
