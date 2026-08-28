"""Dark-mode design tokens and stylesheet generation.

One palette, one spacing/radius/type scale, and a single QSS
template built from them — so colours are defined once rather than scattered
through widget code. No external theming dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from aptiordesk.ui.theme.shared import number, token


@dataclass(frozen=True)
class Palette:
    name: str
    # surfaces, back to front
    canvas: str  # window background
    sidebar: str
    surface: str  # panels, lists, inputs
    surface_raised: str  # cards sitting on a panel
    surface_hover: str
    # lines
    border: str
    border_strong: str
    # text
    text: str
    text_muted: str
    text_faint: str
    # accent + semantics
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_soft: str  # tinted background for subtle accent fills
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    # misc
    selection: str
    shadow: str


# Surfaces step up in luminance as they come forward (canvas → surface →
# raised). The earlier palette kept them within a few points of each other, so
# cards did not read as cards; the gaps here are wide enough to see.
DARK = Palette(
    name="dark",
    canvas=token("canvas"),
    sidebar=token("sidebar"),
    surface=token("surface"),
    surface_raised=token("surface-raised"),
    surface_hover=token("surface-hover"),
    border=token("border"),
    border_strong=token("border-strong"),
    text=token("text"),
    text_muted=token("text-muted"),
    text_faint=token("text-faint"),
    accent=token("accent"),
    accent_hover=token("accent-hover"),
    accent_pressed=token("accent-pressed"),
    accent_text=token("accent-text"),
    accent_soft=token("accent-soft"),
    success=token("success"),
    success_soft=token("success-soft"),
    warning=token("warning"),
    warning_soft=token("warning-soft"),
    danger=token("danger"),
    danger_soft=token("danger-soft"),
    selection=token("selection"),
    shadow=token("shadow-color"),
)

THEMES = {"dark": DARK}
DEFAULT_THEME = "dark"

# Spacing scale (px) — use these rather than arbitrary numbers.
SPACE = {
    name: int(number(f"space-{name}")) for name in ("xs", "sm", "md", "lg", "xl", "2xl", "3xl")
}
RADIUS = {name: int(number(f"radius-{name}")) for name in ("sm", "md", "lg", "xl", "pill")}
CONTROL_HEIGHT = int(number("control-height"))

#: Type scale in points. Kept small and explicit: a form reads as designed
#: mostly because its labels are visibly a different rank from its values, and
#: that only happens if the sizes are chosen rather than left at the default.
TYPE = {
    name: number(f"font-{name}")
    for name in ("display", "title", "heading", "body", "label", "caption", "metric")
}

FONT_STACK = token("font-family")
MONO_STACK = '"Cascadia Code", "JetBrains Mono", "SF Mono", Consolas, monospace'


def build_stylesheet(palette: Palette, chevron_path: str = "") -> str:
    """Render the full application stylesheet for a palette.

    `chevron_path` is an optional PNG for combo-box arrows; without it Qt
    draws its own native arrow, which is fine but less consistent.
    """
    p = palette
    arrow = (
        f"image: url({chevron_path}); width: 10px; height: 10px;"
        if chevron_path
        else "width: 10px; height: 10px;"
    )
    return _TEMPLATE.format(
        p=p,
        font=FONT_STACK,
        mono=MONO_STACK,
        r_sm=RADIUS["sm"],
        r_md=RADIUS["md"],
        r_lg=RADIUS["lg"],
        r_pill=RADIUS["pill"],
        t_display=TYPE["display"],
        t_title=TYPE["title"],
        t_heading=TYPE["heading"],
        t_body=TYPE["body"],
        t_label=TYPE["label"],
        t_caption=TYPE["caption"],
        t_metric=TYPE["metric"],
        control_height=CONTROL_HEIGHT,
        spin_control_height=CONTROL_HEIGHT - 3,
        arrow=arrow,
    )


# NOTE: Qt Style Sheets support a subset of CSS — no box-shadow, no
# transitions, no flexbox. Depth comes from layered surfaces and borders;
# drop shadows are applied in code with QGraphicsDropShadowEffect.
_TEMPLATE = """
/* ---------------------------------------------------------------- base */
QWidget {{
    background-color: {p.canvas};
    color: {p.text};
    font-family: {font};
    font-size: {t_body}pt;
}}
QMainWindow, QDialog {{ background-color: {p.canvas}; }}
QFrame#appShell {{
    background-color: {p.canvas};
    border: none;
}}
QWidget#shellContent {{ background-color: {p.canvas}; }}
/* Labels and other passive widgets must not paint the canvas colour on top
   of whatever surface they sit on (cards, tiles, the sidebar). */
QLabel, QCheckBox, QRadioButton, QSplitter, QStackedWidget,
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
/* Plain QWidgets used purely to hold a layout would otherwise paint the
   canvas colour over whatever surface they sit on, which shows up as a dark
   strip behind every field label inside a card. */
QWidget[role="layoutOnly"] {{ background: transparent; }}
QToolTip {{
    background-color: {p.surface_raised};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r_sm}px;
    padding: 6px 8px;
}}

/* ------------------------------------------------------------- sidebar */
QWidget#sidebar {{
    background-color: {p.sidebar};
    border-right: 1px solid {p.border};
}}
QWidget#brandRow {{ background: transparent; }}
QLabel#brandMark {{
    background: transparent;
    border: none;
    padding: 0;
}}
QLabel#wordmark {{
    color: {p.text};
    font-size: 13.5pt;
    font-weight: 650;
    padding: 0;
}}
QLabel#wordmarkSub {{
    color: {p.text_faint};
    font-size: 7.5pt;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}
QLabel#navSection {{
    color: {p.text_faint};
    font-size: 7.5pt;
    font-weight: 650;
    letter-spacing: 1.2px;
    padding: 0 22px;
}}
QListWidget#navList {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 0px;
}}
QListWidget#navList::item {{
    color: {p.text_muted};
    padding: 9px 12px;
    margin: 2px 10px;
    border: none;
    border-left: 2px solid transparent;
    border-radius: {r_sm}px;
    font-size: 9.5pt;
}}
QListWidget#navList::item:hover {{
    background-color: {p.surface_hover};
    color: {p.text};
}}
QListWidget#navList::item:selected {{
    background-color: {p.surface_raised};
    color: {p.text};
    border-left: 2px solid {p.accent};
    font-weight: 600;
}}

QWidget#sidebarFooter {{ background-color: transparent; }}
QLabel#providerStatus {{ color: {p.text_muted}; font-size: 9pt; }}
QLabel#sidebarCredits {{
    color: {p.text_faint};
    font-size: 8pt;
    padding: 2px 0;
}}
QFrame#providerCard {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
}}
/* -------------------------------------------------------- workspace bar */
QWidget#workspaceBar {{
    background-color: {p.canvas};
    border-bottom: 1px solid {p.border};
}}
QLabel#workspaceContext {{
    color: {p.text_muted};
    font-size: 10pt;
    font-weight: 600;
}}
QPushButton#toolbarButton {{
    background-color: transparent;
    color: {p.text_muted};
    border: 1px solid {p.border};
    padding: 7px 11px;
    min-height: 18px;
    font-size: 9.25pt;
}}
QPushButton#toolbarButton:hover {{
    color: {p.text};
    background-color: {p.surface_hover};
    border-color: {p.border_strong};
}}
/* --------------------------------------------------------------- pages */
QWidget#pageBody {{ background-color: {p.canvas}; }}
QWidget[role="pane"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
}}
QLabel[role="eyebrow"] {{
    color: {p.accent};
    font-size: 7.5pt;
    font-weight: 700;
    letter-spacing: 1.4px;
}}
QLabel[role="pageTitle"] {{
    font-size: {t_title}pt;
    font-weight: 700;
    color: {p.text};
}}
QLabel[role="display"] {{
    font-size: {t_display}pt;
    font-weight: 700;
    color: {p.text};
}}
QLabel[role="sectionTitle"] {{
    font-size: {t_heading}pt;
    font-weight: 650;
    color: {p.text};
}}
QLabel[role="paneTitle"] {{
    color: {p.text};
    font-size: {t_heading}pt;
    font-weight: 650;
}}
/* The rank that makes a form look designed: small, spaced, quiet, so the
   value beside it is unmistakably the content. */
QLabel[role="fieldLabel"] {{
    color: {p.text_muted};
    font-size: {t_label}pt;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
QLabel[role="value"] {{ color: {p.text}; font-size: {t_body}pt; }}
QLabel[role="hint"] {{ color: {p.text_muted}; font-size: {t_body}pt; }}
QLabel[role="caption"] {{ color: {p.text_faint}; font-size: {t_caption}pt; }}
QLabel[role="error"] {{ color: {p.danger}; }}
QLabel[role="success"] {{ color: {p.success}; }}
QLabel[role="warning"] {{ color: {p.warning}; }}
QLabel[role="accent"] {{ color: {p.accent}; }}
QLabel[role="metric"] {{
    font-size: {t_metric}pt;
    font-weight: 700;
    color: {p.text};
}}
QLabel[role="listTitle"] {{ color: {p.text}; font-size: {t_body}pt; font-weight: 650; }}
QLabel[role="listMeta"] {{ color: {p.text_muted}; font-size: {t_caption}pt; }}

/* ------------------------------------------------------- section cards */
/* A titled panel whose heading sits inside it, rather than floating on the
   border as QGroupBox does by default. */
QFrame[role="section"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
}}
QWidget#sectionHeader {{ background: transparent; }}
QFrame[role="divider"] {{
    background-color: {p.border};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QFrame[role="entryRow"] {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
}}
QFrame[role="entryRow"]:hover {{
    background-color: {p.surface_hover};
    border-color: {p.border_strong};
}}
QFrame[role="entryRow"][flagged="true"] {{ border-color: {p.warning}; }}
QFrame[role="emptyState"] {{
    background-color: {p.surface_raised};
    border: 1px dashed {p.border_strong};
    border-radius: {r_lg}px;
}}
QFrame[role="actionBar"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
}}

/* --------------------------------------------------------------- cards */
QFrame[role="card"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
}}
QFrame[role="card"]:hover {{ border-color: {p.border_strong}; }}
QFrame[role="card"][selectable="true"] {{ border-width: 2px; }}
QFrame[role="card"][selectable="true"]:hover {{
    background-color: {p.surface_hover};
    border-color: {p.accent};
}}
QFrame[role="card"][selectable="true"][selected="true"] {{
    background-color: {p.accent_soft};
    border-color: {p.accent};
}}
QFrame[role="card"][providerChoice="true"][selected="true"] {{
    background-color: {p.surface_raised};
    border-color: {p.border_strong};
}}
QFrame[role="card"][providerChoice="true"] {{
    border: 1px solid {p.border_strong};
}}
QFrame[role="card"][providerChoice="true"]:hover {{
    background-color: {p.surface_hover};
    border-color: {p.border_strong};
}}
QLabel[role="selectionCheck"] {{
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    padding: 0;
    color: {p.accent_text};
    background-color: {p.accent};
    border-radius: 10px;
    font-size: 8pt;
    font-weight: 800;
}}
QLabel[role="providerCost"] {{
    padding: 2px 7px;
    border-radius: {r_pill}px;
    color: {p.text_muted};
    background-color: {p.surface_hover};
    font-size: 7pt;
    font-weight: 700;
}}
QLabel[role="providerCost"][tone="success"] {{
    color: {p.success};
    background-color: {p.success_soft};
}}
QLabel[role="providerCost"][tone="warning"] {{
    color: {p.warning};
    background-color: {p.warning_soft};
}}
QFrame[role="tile"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
}}
QLabel[role="tileValue"] {{
    font-size: {t_metric}pt;
    font-weight: 700;
    color: {p.text};
}}
QLabel[role="tileLabel"] {{
    color: {p.text_muted};
    font-size: 8.5pt;
}}
QFrame[role="focus"] {{
    background-color: {p.accent_soft};
    border: 1px solid {p.accent};
    border-radius: {r_lg}px;
}}
QLabel[role="focusTitle"] {{
    color: {p.text};
    font-size: 13pt;
    font-weight: 650;
}}

/* badges (QLabel with role=badge + tone property) */
QLabel[role="badge"] {{
    border-radius: {r_pill}px;
    padding: 3px 10px;
    font-size: {t_label}pt;
    font-weight: 600;
    background-color: {p.surface_hover};
    color: {p.text_muted};
}}
/* Skill/keyword chips: same pill, sized for a wrapped flow of many. */
QLabel[role="chip"] {{
    border-radius: {r_pill}px;
    padding: 4px 12px;
    font-size: {t_body}pt;
    background-color: {p.surface_hover};
    border: 1px solid {p.border};
    color: {p.text};
}}
QLabel[role="badge"][tone="accent"] {{ background-color: {p.accent_soft}; color: {p.accent}; }}
QLabel[role="badge"][tone="success"] {{ background-color: {p.success_soft}; color: {p.success}; }}
QLabel[role="badge"][tone="warning"] {{ background-color: {p.warning_soft}; color: {p.warning}; }}
QLabel[role="badge"][tone="danger"] {{ background-color: {p.danger_soft}; color: {p.danger}; }}

/* ------------------------------------------------------------- inputs */
/* Inputs sit on the raised surface so they read as fields inside a card
   rather than holes cut through it. */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border};
    border-radius: {r_sm}px;
    padding: 9px 12px;
    color: {p.text};
    selection-background-color: {p.selection};
    selection-color: {p.text};
    font-size: {t_body}pt;
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {p.border_strong};
    background-color: {p.surface_hover};
}}
/* Focus compensates its padding for the thicker border, so the field does not
   jump by a pixel when focused. */
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 2px solid {p.accent};
    padding: 7px 11px;
    background-color: {p.surface_raised};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{
    background-color: {p.canvas};
    color: {p.text_faint};
}}
QPlainTextEdit, QTextEdit {{ padding: 12px; }}

/* Every single-line field uses the same outer rhythm. Previously line edits
   and spin boxes were shorter than dropdowns, which made paired form rows look
   vertically offset even when their layout cells were aligned. */
QLineEdit {{
    min-height: {control_height}px;
    padding: 0 12px;
}}
QSpinBox, QDoubleSpinBox {{
    min-height: {spin_control_height}px;
    padding: 0 12px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    padding: 0 11px;
}}

/* Dropdown owns its full control height, keeps the arrow clear of long text,
   and uses a native top-level Qt popup so dialogs/panels cannot clip it. */
QComboBox {{
    min-height: {control_height}px;
    padding: 0 36px 0 12px;
}}
QComboBox:focus {{ padding: 0 35px 0 11px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border: none;
    border-left: 1px solid {p.border};
    width: 32px;
}}
QComboBox:hover::drop-down {{ border-left-color: {p.border_strong}; }}
QComboBox::down-arrow {{ {arrow} margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border_strong};
    border-radius: {r_sm}px;
    padding: 6px;
    outline: none;
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
}}
QComboBox QAbstractItemView::item {{
    min-height: {control_height}px;
    padding: 0 12px;
    margin: 2px 0;
    border-radius: {r_sm}px;
    color: {p.text};
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {p.surface_hover};
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
    border-left: 3px solid {p.accent};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}

QCheckBox, QRadioButton {{ spacing: 8px; color: {p.text}; padding: 3px 0; }}
/* Qt applies border-radius to the OUTER box, and width/height set the inner
   content box — so a circle needs radius == (width + 2 * border) / 2, and the
   checked state must shrink its content box to keep the same outer size. */
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.border_strong};
    border-radius: 4px;
    background-color: {p.surface};
}}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {p.border_strong};
    border-radius: 8px;
    background-color: {p.surface};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border-color: {p.accent};
}}
QRadioButton::indicator:checked {{
    width: 8px; height: 8px;
    border: 4px solid {p.accent};
    border-radius: 8px;
    background-color: {p.surface};
}}

/* ------------------------------------------------------------ buttons */
QPushButton {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border_strong};
    border-radius: {r_sm}px;
    padding: 8px 15px;
    min-height: 20px;
    color: {p.text};
    font-weight: 600;
}}
QPushButton[size="sm"] {{ padding: 6px 11px; font-size: {t_label}pt; min-height: 16px; }}
QPushButton:hover {{ background-color: {p.surface_hover}; border-color: {p.text_faint}; }}
QPushButton:pressed {{ background-color: {p.border}; }}
QPushButton:disabled {{
    background-color: {p.canvas};
    color: {p.text_faint};
    border-color: {p.border};
}}
QPushButton[accent="true"] {{
    background-color: {p.accent};
    border-color: {p.accent};
    color: {p.accent_text};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton[accent="true"]:pressed {{ background-color: {p.accent_pressed}; }}
QPushButton[accent="true"]:disabled {{
    background-color: {p.border};
    border-color: {p.border};
    color: {p.text_faint};
}}
QPushButton[variant="danger"] {{ color: {p.danger}; border-color: {p.border_strong}; }}
QPushButton[variant="danger"]:hover {{
    background-color: {p.danger_soft};
    border-color: {p.danger};
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border-color: transparent;
    color: {p.text_muted};
}}
QPushButton[variant="ghost"]:hover {{ background-color: {p.surface_hover}; color: {p.text}; }}

/* -------------------------------------------------------------- lists */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
    outline: none;
    padding: 6px;
}}
/* A list used purely as a container for widget rows should not draw its own
   frame on top of theirs. */
QListWidget[role="bare"] {{ background: transparent; border: none; padding: 0; }}
QListWidget[role="bare"]::item {{ padding: 0; margin: 0 0 8px 0; }}
QListWidget[role="bare"]::item:hover,
QListWidget[role="bare"]::item:selected {{ background: transparent; }}
QListWidget::item, QTreeWidget::item {{
    padding: 11px 12px;
    margin: 1px 0;
    border-radius: {r_sm}px;
    color: {p.text};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background-color: {p.surface_hover}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {p.accent_soft};
    color: {p.text};
}}
/* Widget-backed captured-job rows need zero item padding. Global list padding
   otherwise shrinks the child geometry and clips the bottom of the selection. */
QListWidget#contentList::item {{
    padding: 0;
    margin: 0;
    border: 1px solid transparent;
    border-radius: {r_md}px;
}}
QListWidget#contentList::item:hover {{
    background-color: {p.surface_hover};
    border-color: {p.border};
}}
QListWidget#contentList::item:selected {{
    background-color: {p.accent_soft};
    border-color: {p.accent};
    color: {p.text};
}}
QListWidget#contentList:focus::item:selected {{
    border: 2px solid {p.accent};
}}

QTableWidget {{ gridline-color: {p.border}; }}
QTableWidget::item {{ padding: 8px; }}
QTableWidget::item:selected {{ background-color: {p.accent_soft}; color: {p.text}; }}
QHeaderView::section {{
    background-color: {p.surface_raised};
    color: {p.text_muted};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 10px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {p.canvas}; border: none; }}

/* --------------------------------------------------------------- tabs */
/* Underline tabs: the boxed style drew three borders around every panel and
   made nested tabs (page > section) unreadable. */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {p.border};
    top: -1px;
    background: transparent;
}}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: 11px 3px;
    margin-right: 22px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: {t_body}pt;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:disabled {{
    color: {p.text_faint};
    background: transparent;
    font-weight: 400;
    border-bottom-color: transparent;
}}
QTabBar::tab:selected {{
    color: {p.text};
    font-weight: 600;
    border-bottom: 2px solid {p.accent};
}}

/* ------------------------------------------------------------ grouping */
QGroupBox {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
    margin-top: 14px;
    padding: 22px 18px 18px 18px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 0 6px;
    color: {p.text_muted};
    font-size: {t_label}pt;
    font-weight: 600;
    letter-spacing: 0.6px;
}}

/* ------------------------------------------------------------- viewers */
QTextBrowser {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
    padding: 16px 18px;
}}

/* ------------------------------------------------------------ chrome */
QSplitter::handle {{ background-color: transparent; }}
QSplitter::handle:horizontal {{ width: 16px; }}
QSplitter::handle:vertical {{ height: 16px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{
    background-color: {p.sidebar};
    color: {p.text_faint};
    border-top: 1px solid {p.border};
    font-size: 8pt;
}}
QStatusBar::item {{ border: none; }}

QProgressBar {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_sm}px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {p.accent}; border-radius: {r_sm}px; }}

QMenu {{
    background-color: {p.surface_raised};
    border: 1px solid {p.border_strong};
    border-radius: {r_sm}px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {p.accent}; color: {p.accent_text}; }}
"""
