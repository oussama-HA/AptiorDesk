"""Theme tokens, stylesheet generation, and the icon set."""

import re

from aptiordesk.ui.theme import apply_theme, current, stylesheet
from aptiordesk.ui.theme import icons as icon_set
from aptiordesk.ui.theme.tokens import DARK, THEMES, build_stylesheet


class TestPalettes:
    def test_dark_theme_defines_every_token(self):
        for field, value in vars(DARK).items():
            assert value, f"{DARK.name}.{field} is empty"

    def test_only_dark_theme_is_registered(self):
        assert THEMES == {"dark": DARK}

    def test_colours_are_valid_css(self):
        pattern = re.compile(r"^(#[0-9a-fA-F]{6}|rgba\([\d\s,]+\))$")
        for field, value in vars(DARK).items():
            if field == "name":
                continue
            assert pattern.match(value), f"{DARK.name}.{field} = {value!r}"


class TestStylesheet:
    def test_builds_without_unsubstituted_placeholders(self):
        css = build_stylesheet(DARK)
        assert "{" not in css.replace("{{", "").replace("}}", "").split("QWidget")[0]
        assert "{p." not in css
        assert DARK.canvas in css

    def test_covers_the_widgets_the_app_uses(self):
        css = build_stylesheet(DARK)
        for selector in (
            "QPushButton",
            "QLineEdit",
            "QComboBox",
            "QTabBar::tab",
            "QGroupBox",
            "QTableWidget",
            "QScrollBar:vertical",
            "QListWidget#navList",
            'QFrame[role="card"]',
            'QLabel[role="pageTitle"]',
        ):
            assert selector in css, f"{selector} is unstyled"

    def test_labels_do_not_paint_over_surfaces(self):
        """A QLabel inheriting the canvas colour draws a visible block inside
        cards and the sidebar."""
        css = build_stylesheet(DARK)
        assert "QLabel, QCheckBox" in css
        assert "background: transparent" in css

    def test_removed_local_badge_has_no_stylesheet_rule(self):
        assert "localBadge" not in build_stylesheet(DARK)


class TestThemeSwitching:
    def test_unsupported_light_request_stays_dark(self, qapp):
        apply_theme("light", qapp)
        assert current().name == "dark"
        assert DARK.canvas in qapp.styleSheet()

    def test_unknown_theme_falls_back_to_default(self, qapp):
        apply_theme("hologram", qapp)
        assert current().name == "dark"

    def test_stylesheet_matches_current_theme(self, qapp):
        apply_theme("light", qapp)
        css = stylesheet()
        assert DARK.canvas in css

    def test_combo_arrow_uses_a_real_image(self, qapp):
        """Qt renders the CSS border-triangle trick as a square, so the arrow
        must come from a cached PNG."""
        apply_theme("dark", qapp)
        css = stylesheet()
        assert "QComboBox::down-arrow" in css
        assert "chevron-dark.png" in css

    def test_saved_light_preference_is_migrated(self, conn):
        from aptiordesk.app import _enforce_dark_theme_setting
        from aptiordesk.database.repositories.settings_repo import SettingsRepository
        from aptiordesk.ui.theme import SETTING_KEY

        settings = SettingsRepository(conn)
        settings.set(SETTING_KEY, "light")
        assert _enforce_dark_theme_setting(settings) == "dark"
        assert settings.get(SETTING_KEY) == "dark"


class TestIcons:
    def test_every_nav_item_has_an_icon(self):
        from aptiordesk.app.main_window import _NAV_ICONS

        for label, name in _NAV_ICONS.items():
            assert name in icon_set.available(), f"{label} references missing icon {name}"

    def test_renders_a_non_empty_pixmap(self, qapp):
        pixmap = icon_set.pixmap("home", "#ffffff", 18)
        assert not pixmap.isNull()
        assert pixmap.size().width() == 18

    def test_unknown_icon_is_empty_not_an_error(self, qapp):
        """A missing glyph must never take a page down."""
        assert icon_set.icon("does-not-exist", "#fff").isNull()
        assert icon_set.pixmap("does-not-exist", "#fff").isNull()

    def test_multi_segment_paths_render(self, qapp):
        """Icons store several sub-paths in one string; the splitter must not
        corrupt them."""
        pixmap = icon_set.pixmap("settings", "#ffffff", 24)
        assert not pixmap.isNull()

    def test_removed_theme_icons_are_not_kept_as_dead_assets(self):
        assert "sun" not in icon_set.available()
        assert "moon" not in icon_set.available()


# --- design tokens ------------------------------------------------------------


def test_every_palette_colour_is_a_valid_css_colour():
    """A typo in a hex value fails silently in QSS — the rule is just dropped,
    so the widget keeps whatever it inherited and the bug is invisible."""
    import re
    from dataclasses import fields

    from aptiordesk.ui.theme.tokens import THEMES

    valid = re.compile(r"^(#[0-9a-fA-F]{6}|rgba?\([\d\s,.]+\))$")
    for palette in THEMES.values():
        for field in fields(palette):
            if field.name == "name":
                continue
            value = getattr(palette, field.name)
            assert valid.match(value), f"{palette.name}.{field.name} = {value!r}"


def test_surfaces_are_visibly_distinct_from_the_canvas():
    """Cards only read as cards if their surface differs from the background."""
    from aptiordesk.ui.theme.tokens import THEMES

    def luminance(hex_colour: str) -> int:
        r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
        return (r * 299 + g * 587 + b * 114) // 1000

    for palette in THEMES.values():
        gap = abs(luminance(palette.surface) - luminance(palette.canvas))
        assert gap >= 5, f"{palette.name}: surface and canvas differ by only {gap}"


def test_stylesheet_defines_the_roles_the_widgets_set():
    """Every role= a widget sets must exist in the stylesheet, or it silently
    renders unstyled."""
    from aptiordesk.ui.theme.tokens import DARK, build_stylesheet

    css = build_stylesheet(DARK)
    for role in (
        "pageTitle",
        "sectionTitle",
        "fieldLabel",
        "hint",
        "caption",
        "badge",
        "chip",
        "card",
        "section",
        "entryRow",
        "layoutOnly",
        "metric",
        "value",
        "error",
        "success",
        "warning",
        "accent",
        "divider",
        "bare",
        "eyebrow",
        "focus",
        "focusTitle",
        "pane",
        "paneTitle",
        "listTitle",
        "listMeta",
        "emptyState",
        "actionBar",
    ):
        assert f'"{role}"' in css, f"role {role!r} is set by a widget but not styled"


def test_type_scale_ranks_are_ordered():
    from aptiordesk.ui.theme.tokens import TYPE

    assert TYPE["display"] > TYPE["title"] > TYPE["heading"] > TYPE["body"]
    assert TYPE["body"] > TYPE["label"]
    assert TYPE["body"] >= 10.5
    assert TYPE["label"] >= 9
