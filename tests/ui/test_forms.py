"""Layout primitives: the grid, section cards, entry rows, and chip flow."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QSizePolicy

from aptiordesk.ui.components.forms import ChipFlow, EntryRow, FieldGrid, SectionCard


def test_field_grid_places_pairs_side_by_side(qtbot):
    grid = FieldGrid(columns=2)
    qtbot.addWidget(grid)

    first = grid.add("Email", QLineEdit())
    second = grid.add("Phone", QLineEdit())

    layout = grid.layout()
    assert layout.getItemPosition(layout.indexOf(first))[:2] == (0, 0)
    assert layout.getItemPosition(layout.indexOf(second))[:2] == (0, 1)


def test_field_grid_top_aligns_fields_when_only_one_has_helper_text(qtbot):
    from PySide6.QtWidgets import QApplication

    from aptiordesk.ui.components.dropdown import Dropdown
    from aptiordesk.ui.theme import apply_theme

    app = QApplication.instance()
    previous_stylesheet = app.styleSheet()
    apply_theme("dark", app)
    grid = FieldGrid(columns=2)
    qtbot.addWidget(grid)
    location = QLineEdit()
    work_mode = Dropdown()
    work_mode.addItems(["Remote", "Hybrid", "On-site"])
    grid.add("Preferred locations", location, "Comma-separated")
    grid.add("Work mode", work_mode)
    grid.resize(800, 150)
    grid.show()
    qtbot.wait(1)

    location_top = location.mapTo(grid, location.rect().topLeft()).y()
    work_mode_top = work_mode.mapTo(grid, work_mode.rect().topLeft()).y()
    assert location_top == work_mode_top
    assert location.height() == work_mode.height()
    app.setStyleSheet(previous_stylesheet)


def test_field_grid_spans_a_full_width_field_and_resets_the_row(qtbot):
    grid = FieldGrid(columns=2)
    qtbot.addWidget(grid)

    grid.add("Email", QLineEdit())
    spanning = grid.add("Summary", QLineEdit(), span=True)
    after = grid.add("Phone", QLineEdit())

    layout = grid.layout()
    row, column, _, column_span = layout.getItemPosition(layout.indexOf(spanning))
    assert column == 0
    assert column_span == 2
    # The next field starts a fresh row rather than sitting beside the span.
    assert layout.getItemPosition(layout.indexOf(after))[0] > row


def test_field_labels_keep_readable_case_and_carry_the_label_role(qtbot):
    grid = FieldGrid()
    qtbot.addWidget(grid)

    cell = grid.add("Full name", QLineEdit(), hint="As it appears on your CV")

    labels = cell.findChildren(QLabel)
    assert labels[0].text() == "Full name"
    assert labels[0].property("role") == "fieldLabel"
    assert labels[1].text() == "As it appears on your CV"


def test_grid_cells_do_not_paint_over_their_card(qtbot):
    """Regression: plain container QWidgets painted the canvas colour on top
    of the card, drawing a dark strip behind every label."""
    grid = FieldGrid()
    qtbot.addWidget(grid)
    cell = grid.add("Email", QLineEdit())

    assert grid.property("role") == "layoutOnly"
    assert cell.property("role") == "layoutOnly"


def test_section_card_shows_title_description_and_actions(qtbot):
    card = SectionCard("Basics", "Your contact details", icon="user")
    qtbot.addWidget(card)
    clicks = []

    card.add_action("Import", lambda: clicks.append(1), accent=True)

    assert card.title_label.text() == "Basics"
    assert card.description_label.text() == "Your contact details"
    assert card.description_label.isVisibleTo(card)
    assert card.actions.count() == 1
    assert card.title_label.parentWidget() is not None
    assert card.description_label.parentWidget() is not None
    assert not card.title_label.isWindow()
    assert not card.description_label.isWindow()


def test_section_card_hides_an_empty_description(qtbot):
    card = SectionCard("Basics")
    qtbot.addWidget(card)

    assert not card.description_label.isVisibleTo(card)


def test_entry_row_renders_its_parts(qtbot):
    row = EntryRow(
        title="Principal Engineer",
        subtitle="Analytical Engines Ltd",
        meta="2021-03 – present · London",
        details=["Rebuilt the ingest pipeline.", "Led five engineers."],
    )
    qtbot.addWidget(row)

    text = " ".join(label.text() for label in row.findChildren(QLabel))
    assert "Principal Engineer" in text
    assert "Analytical Engines Ltd" in text
    assert "2021-03 – present · London" in text
    assert "Rebuilt the ingest pipeline." in text
    assert row.property("flagged") == "false"


def test_entry_row_marks_a_flagged_entry(qtbot):
    row = EntryRow(title="Chief Architect", subtitle="Cyberdyne", flagged=True)
    qtbot.addWidget(row)

    assert row.property("flagged") == "true"
    assert "Check this" in " ".join(label.text() for label in row.findChildren(QLabel))


def test_entry_row_truncates_a_long_detail_list_with_a_count(qtbot):
    row = EntryRow(title="Role", details=[f"Bullet {i}" for i in range(9)])
    qtbot.addWidget(row)

    text = " ".join(label.text() for label in row.findChildren(QLabel))
    assert "+ 5 more" in text


def test_entry_row_actions_fire(qtbot):
    row = EntryRow(title="Role")
    qtbot.addWidget(row)
    fired = []

    button = row.add_action("edit", "Edit", lambda: fired.append("edit"))
    button.click()

    assert fired == ["edit"]


def test_chip_flow_replaces_its_items_rather_than_appending(qtbot):
    flow = ChipFlow()
    qtbot.addWidget(flow)

    flow.set_items(["Python", "SQL", "Spark"])
    assert len(flow.findChildren(QLabel)) == 3

    flow.set_items(["Go"])
    remaining = [label.text() for label in flow.findChildren(QLabel) if label.text()]
    assert remaining == ["Go"]


def test_chip_flow_wraps_within_its_width(qtbot):
    flow = ChipFlow()
    qtbot.addWidget(flow)
    flow.set_items([f"skill-{i}" for i in range(12)])

    narrow = flow.layout().heightForWidth(200)
    wide = flow.layout().heightForWidth(1200)

    assert narrow > wide


def test_profile_background_tabs_are_content_sized_and_top_aligned(qtbot, conn):
    from aptiordesk.features.profile.page import ProfilePage

    page = ProfilePage(conn)
    qtbot.addWidget(page)
    page.resize(1100, 900)
    page.show()
    qtbot.waitUntil(lambda: page.tabs.height() > 0)

    assert page.background_card.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert page.tabs.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert page.tabs.height() < 220

    current = page.tabs.currentWidget()
    layout = current.layout()
    assert layout.alignment() & Qt.AlignmentFlag.AlignTop
    empty = page._item_empties["experience"]
    margins = empty.contentsMargins()
    assert margins.top() <= 8 and margins.bottom() <= 8
    add_button = next(
        button for button in current.findChildren(QPushButton) if button.text() == "Add experience"
    )
    assert add_button.y() < empty.y()


def test_profile_background_grows_to_rows_without_filling_the_viewport(qtbot, conn):
    from aptiordesk.database.models.profile import ProfileItem
    from aptiordesk.database.repositories.profile_repo import ProfileRepository
    from aptiordesk.features.profile.page import ProfilePage

    repo = ProfileRepository(conn)
    profile = repo.get_default()
    for index in range(2):
        repo.add_item(
            ProfileItem(
                profile_id=profile.id,
                kind="experience",
                data={
                    "title": f"Product designer {index + 1}",
                    "organization": "Northstar",
                    "start_date": "2022",
                    "end_date": "2024",
                    "highlights": ["Designed accessible customer workflows."],
                },
            )
        )

    page = ProfilePage(conn)
    qtbot.addWidget(page)
    page.resize(1100, 900)
    page.show()
    qtbot.waitUntil(lambda: page._item_lists["experience"].count() == 2)
    page._sync_background_height()

    rows_height = page._item_lists["experience"].height()
    assert rows_height > 0
    assert page.tabs.height() > rows_height
    assert page.tabs.height() < 500


def test_shared_dropdown_has_bounded_readable_popup_and_full_label_tooltips(qtbot):
    from aptiordesk.ui.components.dropdown import Dropdown
    from aptiordesk.ui.theme.tokens import CONTROL_HEIGHT

    combo = Dropdown()
    qtbot.addWidget(combo)
    combo.resize(180, CONTROL_HEIGHT)
    for index in range(16):
        combo.addItem(f"Option {index + 1} with a deliberately long descriptive label")
    combo.show()
    combo.showPopup()

    # QSS borders are included in the effective outer minimum on styled apps.
    assert combo.minimumHeight() >= CONTROL_HEIGHT
    assert combo.maxVisibleItems() == 10
    assert combo.view().minimumWidth() >= combo.width()
    assert combo.view().verticalScrollMode() == combo.view().ScrollMode.ScrollPerPixel
    assert combo.view().textElideMode() == Qt.TextElideMode.ElideRight
    assert combo.itemData(0, Qt.ItemDataRole.ToolTipRole) == combo.itemText(0)
    assert "Escape" in combo.accessibleDescription()
    combo.hidePopup()


def test_editable_shared_dropdown_uses_contains_completion(qtbot):
    from PySide6.QtWidgets import QCompleter

    from aptiordesk.ui.components.dropdown import Dropdown

    combo = Dropdown()
    qtbot.addWidget(combo)
    combo.setEditable(True)
    combo.addItems(["Claude Sonnet", "Gemini Flash", "Local Gemma"])

    assert combo.lineEdit().isClearButtonEnabled()
    assert combo.completer().filterMode() == Qt.MatchFlag.MatchContains
    assert combo.completer().completionMode() == QCompleter.CompletionMode.PopupCompletion
