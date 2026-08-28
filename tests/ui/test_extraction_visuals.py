"""The three visualisations added to the resume-import flow.

Each exists to answer one question without ambiguity, so the tests check that
the numbers shown are the real ones and that the wording never overstates what
the app actually knows.
"""

from __future__ import annotations

import pytest

from aptiordesk.database.models.extraction import (
    ExtractionReport,
    FieldNote,
    Provenance,
    SectionOutcome,
)
from aptiordesk.database.models.profile import ProfileItem
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.features.resumes.extraction import SECTIONS, SectionProgress
from aptiordesk.ui.components.extraction_progress import ExtractionProgressDialog
from aptiordesk.ui.components.profile_strength import ProfileStrengthCard
from aptiordesk.ui.components.provenance_bar import ProvenanceBar


def _report(extracted=8, inferred=2, missing=5) -> ExtractionReport:
    notes = (
        [FieldNote(path=f"e{i}", provenance=Provenance.EXTRACTED) for i in range(extracted)]
        + [FieldNote(path=f"i{i}", provenance=Provenance.INFERRED) for i in range(inferred)]
        + [FieldNote(path=f"m{i}", provenance=Provenance.MISSING) for i in range(missing)]
    )
    return ExtractionReport(
        notes=notes,
        sections=[SectionOutcome(name=s.label, ok=True, item_count=2) for s in SECTIONS],
    )


# --- progress dialog ----------------------------------------------------------


def test_progress_dialog_lists_every_section_as_pending(qtbot):
    dialog = ExtractionProgressDialog("ada.pdf", 1200, "llama3.2:3b")
    qtbot.addWidget(dialog)

    assert set(dialog._rows) == {spec.key for spec in SECTIONS}
    assert dialog.bar.value() == 0
    assert dialog.bar.maximum() == len(SECTIONS)


def test_progress_dialog_advances_only_on_completion(qtbot):
    """A section starting is not progress; a section finishing is."""
    dialog = ExtractionProgressDialog("ada.pdf", 1200)
    qtbot.addWidget(dialog)

    dialog.handle_event(SectionProgress("contact", "contact", "running", 0, 5))
    assert dialog.bar.value() == 0

    dialog.handle_event(SectionProgress("contact", "contact", "done", 1, 5))
    assert dialog.bar.value() == 1


def test_progress_dialog_marks_a_failed_section_without_hiding_it(qtbot):
    dialog = ExtractionProgressDialog("ada.pdf", 1200)
    qtbot.addWidget(dialog)

    dialog.handle_event(SectionProgress("skills", "skills", "failed", 1, 5))

    _glyph, _name, status = dialog._rows["skills"]
    assert "failed" in status.text()
    # The rest is still usable, and the wording says so rather than alarming.
    assert "review" in status.text()
    assert dialog.bar.value() == 1


def test_progress_dialog_tolerates_an_unknown_section_key(qtbot):
    dialog = ExtractionProgressDialog("ada.pdf", 1200)
    qtbot.addWidget(dialog)

    dialog.handle_event(SectionProgress("nonexistent", "?", "done", 1, 5))  # must not raise

    assert dialog.bar.value() == 0


def test_progress_dialog_stops_its_clock_when_finished(qtbot):
    dialog = ExtractionProgressDialog("ada.pdf", 1200)
    qtbot.addWidget(dialog)

    dialog.finish()

    assert not dialog._timer.isActive()


# --- provenance bar -----------------------------------------------------------


def test_provenance_bar_counts_fields_and_labels_them_as_fields(qtbot):
    """The header counts items, the bar counts fields. Both must say which,
    or the two numbers look like a contradiction."""
    bar = ProvenanceBar(_report(extracted=8, inferred=2, missing=5))
    qtbot.addWidget(bar)

    text = _label_text(bar)

    assert "8 fields verified in your document" in text
    assert "2 fields for you to check" in text
    assert "5 fields left empty" in text


def test_provenance_bar_hides_the_check_chip_when_nothing_needs_checking(qtbot):
    bar = ProvenanceBar(_report(extracted=10, inferred=0, missing=3))
    qtbot.addWidget(bar)

    assert "for you to check" not in _label_text(bar)


def test_provenance_bar_renders_with_no_notes_at_all(qtbot):
    """An extraction that produced nothing must not divide by zero."""
    bar = ProvenanceBar(ExtractionReport())
    qtbot.addWidget(bar)
    bar.resize(300, 40)
    bar.grab()  # forces a paint


# --- profile strength card ----------------------------------------------------


def test_strength_card_is_zero_and_offers_the_import_when_empty(qtbot, conn):
    card = ProfileStrengthCard(conn)
    qtbot.addWidget(card)

    assert card.bar.value() == 0
    assert card.percent_label.text() == "0%"
    assert "empty" in card.title_label.text()
    assert card.import_button.isVisibleTo(card)


def test_strength_card_reflects_real_counts(qtbot, conn):
    repo = ProfileRepository(conn)
    profile = repo.get_default()
    profile.display_name = "Ada Lovelace"
    profile.summary = "Engineer."
    profile.contact.email = "ada@example.com"
    profile.contact.location = "London"
    repo.save(profile)
    for _ in range(3):
        repo.add_item(
            ProfileItem(profile_id=profile.id, kind="experience", data={"title": "Engineer"})
        )
    repo.add_item(ProfileItem(profile_id=profile.id, kind="skill", data={"name": "Python"}))

    card = ProfileStrengthCard(conn)
    qtbot.addWidget(card)

    chips = _chip_texts(card)
    assert "Experience · 3" in chips
    assert "Skills · 1" in chips
    assert "Contact · 2/3" in chips
    assert "No education" in chips
    assert card.bar.value() > 0
    # The import prompt steps aside once the profile is substantially filled.
    assert not card.import_button.isVisibleTo(card)


def test_strength_card_surfaces_entries_awaiting_confirmation(qtbot, conn):
    repo = ProfileRepository(conn)
    profile = repo.get_default()
    repo.add_item(
        ProfileItem(
            profile_id=profile.id,
            kind="experience",
            data={"title": "CTO", "organization": "Cyberdyne"},
            provenance="inferred",
            needs_review=True,
        )
    )

    card = ProfileStrengthCard(conn)
    qtbot.addWidget(card)

    assert "1 to confirm" in _chip_texts(card)
    assert "could not be verified" in card.hint.text()


def test_strength_card_refresh_does_not_stack_duplicate_chips(qtbot, conn):
    """Regression class: rebuilding a row layout twice previously left both."""
    card = ProfileStrengthCard(conn)
    qtbot.addWidget(card)
    before = len(_chip_texts(card))

    card.refresh()
    card.refresh()

    assert len(_chip_texts(card)) == before


def test_strength_card_never_claims_quality_only_presence(qtbot, conn):
    """No 'strong'/'weak' scoring — the app cannot judge whether a role is
    good, and pretending to is what makes users distrust the screen."""
    repo = ProfileRepository(conn)
    profile = repo.get_default()
    profile.display_name = "Ada"
    repo.save(profile)
    card = ProfileStrengthCard(conn)
    qtbot.addWidget(card)

    words = (card.title_label.text() + " " + card.hint.text()).lower()
    for judgement in ("weak", "strong", "poor", "excellent", "score", "rating"):
        assert judgement not in words


def _label_text(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return " ".join(label.text() for label in widget.findChildren(QLabel))


def _chip_texts(card: ProfileStrengthCard) -> list[str]:
    texts = []
    for index in range(card.chips.count()):
        widget = card.chips.itemAt(index).widget()
        if widget is not None and hasattr(widget, "text"):
            texts.append(widget.text())
    return texts


@pytest.mark.parametrize("percent", [0, 30, 60, 90])
def test_strength_titles_are_plain_language(percent):
    from aptiordesk.ui.components.profile_strength import _title_for

    title = _title_for(percent, "Ada Lovelace")
    assert title
    assert "%" not in title  # the number lives next to the bar, not in the title
