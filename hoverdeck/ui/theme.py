"""Sähkökeskus design tokens — the single source of truth (PLAN.md §4.2–4.3, §8).

Industrial switchboard: gunmetal housing, raised backlit keycaps, engraved
label plates, indicator lamps. One accent (signal amber) carries the identity;
live/fault are status lamps, never decoration.

Every color, radius, spacing, font, and duration in ui/ comes from here.
Sizes flow through one SCALE token: call set_scale() and every size token is
recomputed as base * SCALE (hairline seams stay 1px on purpose — machined
seams don't get thicker). Zero hardcoded styling anywhere else.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QFontDatabase

# ---------------------------------------------------------------------------
# Color tokens (hex) — §4.2
# ---------------------------------------------------------------------------
PANEL = "#14171B"         # gunmetal housing; overlay body
KEYCAP = "#1F242B"        # raised key surface (default button fill)
KEYCAP_HOVER = "#262C35"  # key under finger
SEAM = "#2C333D"          # 1px seams/borders between machined parts
SIGNAL = "#F5A623"        # amber indicator lamp; THE accent
LIVE = "#5BD66A"          # green "OK" lamp; success flash
FAULT = "#E05547"         # fault lamp; error flash, destructive actions
INK = "#E8E6E1"           # primary text (warm off-white)
INK_DIM = "#8A919C"       # labels, secondary text
VAULT_TINT = "#3A2430"    # deep ember wash, vault pages ONLY (Phase 3)


def qcolor(token: str, alpha: int = 255) -> QColor:
    """Token hex -> QColor with optional alpha (0-255)."""
    color = QColor(token)
    color.setAlpha(alpha)
    return color


# Machined-surface modelling (factors for QColor.lighter()/darker()).
KEYCAP_TOP_LIGHTER = 114      # top edge catches the light
KEYCAP_BOTTOM_DARKER = 110    # bottom edge falls into shade
KEYCAP_PRESSED_DARKER = 106   # whole cap sinks slightly when pressed
SOCKET_DARKER = 118           # empty slot = recessed socket in the housing
TOP_HIGHLIGHT_ALPHA = 26      # 1px machined glint under a keycap's top edge
LED_GLOW_ALPHA = 70           # soft halo around a lit LED
LED_IDLE_ALPHA = 90           # barely-visible seam dot when the lamp is off
NOTCH_SHADOW_ALPHA = 140      # engraved notch: dark groove...
NOTCH_GLINT_ALPHA = 22        # ...with a light edge below
EDIT_BADGE_LIGHTER = 165      # pencil badge: seam metal, raised just enough to read
PEEK_HOVER_LIGHTER = 115      # peek lamp brightens under the cursor
DRAG_LIFT_OPACITY = 0.7       # dragged key lifts off the panel
DRAG_LIFT_SCALE = 1.05
LIVE_LAMP_BG_ALPHA = 36       # translucent live fill behind "ADD TO DECK"


def keycap_gradient(base_hex: str, pressed: bool) -> tuple[QColor, QColor]:
    """(top, bottom) gradient stops for a keycap face."""
    base = QColor(base_hex)
    if pressed:
        flat = base.darker(KEYCAP_PRESSED_DARKER)
        return flat, flat
    return base.lighter(KEYCAP_TOP_LIGHTER), base.darker(KEYCAP_BOTTOM_DARKER)


# Key tint presets offered in the button editor — existing lamp tokens only,
# so user color stays as disciplined as the rest of the panel.
TINT_PRESETS: list[tuple[str, str]] = [
    ("None", ""),
    ("Amber", SIGNAL),
    ("Green", LIVE),
    ("Red", FAULT),
    ("Steel", SEAM),
]


def tinted_keycap(base_hex: str, tint_hex: str, strength: float = 0.18) -> str:
    """Blend a user-chosen tint into the keycap fill, kept disciplined."""
    base, tint = QColor(base_hex), QColor(tint_hex)
    if not tint.isValid():
        return base_hex
    mixed = QColor(
        round(base.red() + (tint.red() - base.red()) * strength),
        round(base.green() + (tint.green() - base.green()) * strength),
        round(base.blue() + (tint.blue() - base.blue()) * strength),
    )
    return mixed.name()


# ---------------------------------------------------------------------------
# SCALE — §8.B. One float drives every size and font token below.
# ---------------------------------------------------------------------------
SCALE = 1.0
SCALE_MIN = 0.6
SCALE_MAX = 2.0

# Unscaled bases. set_scale() materializes same-named module globals.
_SIZE_BASES: dict[str, float] = {
    # shape & layout — §4.2
    "OVERLAY_RADIUS": 16,
    "GRID_GUTTER": 10,
    "OVERLAY_PADDING": 12,
    "SECTION_SPACING": 8,
    "HANDLE_HEIGHT": 14,
    "HANDLE_RADIUS": 4,
    "HANDLE_NOTCH_WIDTH": 14,
    "HANDLE_NOTCH_GAP": 8,
    "LED_DIAMETER": 5,
    "LED_INSET": 8,
    "PAGE_DOT_DIAMETER": 6,
    "PAGE_DOT_HIT": 16,        # clickable area around a page dot
    "BUTTON_SIZE_DEFAULT": 72,
    # phase 2 widgets — §8
    "EDIT_BADGE_SIZE": 9,
    "EDIT_BADGE_INSET": 8,
    "GRIP_SIZE": 14,
    "GRIP_DOT": 2,
    "PEEK_RADIUS": 26,
    "PIN_KEY_SIZE": 40,        # numpad keycaps (smaller than deck keys)
    "PIN_DOT_DIAMETER": 8,     # PIN fill dots
    "PIN_DOT_GAP": 10,
    "SHAKE_AMPLITUDE": 8,      # wrong-code shake, px at full deflection
    "SWIPE_THRESHOLD": 40,     # horizontal drag distance that flips a page
    "AI_PANEL_WIDTH": 300,
    "BUBBLE_RADIUS": 8,
    "BUBBLE_PADDING": 8,
    "CONTROL_RADIUS": 6,
    "CONTROL_PADDING": 6,
    # type sizes (pt)
    "LABEL_POINT_SIZE": 7,
    "BODY_POINT_SIZE": 10,
    "MONO_POINT_SIZE": 10,
    "TITLE_POINT_SIZE": 10,
}

# Hairlines stay fixed at every scale.
SEAM_WIDTH = 1
FOCUS_RING_WIDTH = 1

HANDLE_NOTCHES = 3
KEY_RADIUS_RATIO = 0.20   # button radius ≈ 20% of button size
ICON_SIZE_RATIO = 0.30    # glyph height relative to button size


def set_scale(scale: float) -> float:
    """Clamp + apply the scale; recomputes every size token in this module.

    Callers must rebuild widgets and re-apply the QSS afterwards.
    """
    global SCALE
    SCALE = min(SCALE_MAX, max(SCALE_MIN, float(scale)))
    g = globals()
    for name, base in _SIZE_BASES.items():
        g[name] = max(1, round(base * SCALE))
    return SCALE


def scaled(px: float) -> int:
    """Scale an arbitrary base size (e.g. settings.button_size)."""
    return max(1, round(px * SCALE))


def key_radius(button_size: int) -> int:
    return round(button_size * KEY_RADIUS_RATIO)


set_scale(1.0)  # materialize the size tokens at import


# ---------------------------------------------------------------------------
# Motion tokens (ms) — §4.3 + §8. Mechanical, restrained. reduce_motion makes
# all state changes instant (consumers must check it before animating).
# ---------------------------------------------------------------------------
KEY_DEPRESS_MS = 80
LED_PULSE_MS = 900
SUCCESS_BLINK_MS = 140    # green lamp full-on...
SUCCESS_FADE_MS = 600     # ...then fades out
PIN_SLIDE_MS = 160        # PIN pad + AI panel slide
PEEK_SLIDE_MS = 200       # overlay tucking to / returning from a screen edge
SHAKE_MS = 300            # wrong-code shake duration
WRONG_CODE_HOLD_MS = 1500  # "Wrong code." stays this long
PIN_FLASH_MS = 350        # dots flash live/fault before clearing
LED_PULSE_FLOOR = 0.30    # pulse dims to this fraction, never fully off

# Vault visual language (§4.5): barely-perceptible ember wash on the housing
# while the vault is unlocked. A bystander sees nothing unusual.
VAULT_WASH_ALPHA = 30


# ---------------------------------------------------------------------------
# Type roles — §4.2. Bundled fonts with sane Qt fallbacks.
# ---------------------------------------------------------------------------
FONT_DISPLAY = "Chakra Petch"   # engraved panel lettering (labels, titles)
FONT_BODY = "IBM Plex Sans"     # dialogs, body, chat
FONT_MONO = "IBM Plex Mono"     # paths, timings, JSON, PIN digits

_FALLBACK_DISPLAY = ["Bahnschrift", "Segoe UI", "DejaVu Sans", "Sans Serif"]
_FALLBACK_BODY = ["Segoe UI", "DejaVu Sans", "Sans Serif"]
_FALLBACK_MONO = ["Consolas", "DejaVu Sans Mono", "Monospace"]

LABEL_LETTERSPACING_PCT = 106   # +0.06em


def load_fonts(fonts_dir: Path) -> list[str]:
    """Register every bundled font; return the family names that loaded.

    Missing files are fine — the role fonts below fall back gracefully.
    Call after QApplication exists.
    """
    loaded: list[str] = []
    if not fonts_dir.is_dir():
        return loaded
    for path in sorted(fonts_dir.glob("*.[ot]tf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    return loaded


def _family(preferred: str, fallbacks: list[str]) -> str:
    available = set(QFontDatabase.families())
    if preferred in available:
        return preferred
    for name in fallbacks:
        if name in available:
            return name
    return fallbacks[-1]


def label_font(point_size: int | None = None) -> QFont:
    """Engraved label-plate lettering: Medium, UPPERCASE, letterspaced."""
    font = QFont(_family(FONT_DISPLAY, _FALLBACK_DISPLAY),
                 point_size or LABEL_POINT_SIZE)
    font.setWeight(QFont.Weight.Medium)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, LABEL_LETTERSPACING_PCT)
    return font


def title_font(point_size: int | None = None) -> QFont:
    """Panel headers ("AI BUILDER"): the label plate, one size up."""
    return label_font(point_size or TITLE_POINT_SIZE)


def glyph_font(pixel_size: int) -> QFont:
    """Keycap icon glyphs (display family, no uppercase/letterspacing)."""
    font = QFont(_family(FONT_DISPLAY, _FALLBACK_DISPLAY))
    font.setPixelSize(pixel_size)
    return font


def body_font(point_size: int | None = None) -> QFont:
    return QFont(_family(FONT_BODY, _FALLBACK_BODY), point_size or BODY_POINT_SIZE)


def mono_font(point_size: int | None = None) -> QFont:
    return QFont(_family(FONT_MONO, _FALLBACK_MONO), point_size or MONO_POINT_SIZE)


# ---------------------------------------------------------------------------
# QSS for the stock widgets (menus, dialogs, inputs). Rebuilt on set_scale().
# Buttons take variants via a dynamic property:
#   btn.setProperty("variant", "primary" | "live" | "danger")
# ---------------------------------------------------------------------------
def app_qss() -> str:
    body = _family(FONT_BODY, _FALLBACK_BODY)
    display = _family(FONT_DISPLAY, _FALLBACK_DISPLAY)
    mono = _family(FONT_MONO, _FALLBACK_MONO)
    live_bg = qcolor(LIVE, LIVE_LAMP_BG_ALPHA)
    return f"""
* {{
    font-family: "{body}";
    font-size: {BODY_POINT_SIZE}pt;
    color: {INK};
}}
QMenu {{
    background-color: {PANEL};
    border: {SEAM_WIDTH}px solid {SEAM};
    padding: {CONTROL_PADDING}px;
}}
QMenu::item {{
    padding: {CONTROL_PADDING}px {CONTROL_PADDING * 3}px;
    border-radius: {CONTROL_RADIUS - 2}px;
}}
QMenu::item:selected {{ background-color: {KEYCAP_HOVER}; }}
QMenu::item:disabled {{ color: {INK_DIM}; }}
QMenu::separator {{
    height: {SEAM_WIDTH}px;
    background: {SEAM};
    margin: {CONTROL_PADDING - 2}px {CONTROL_PADDING}px;
}}
QToolTip {{
    background-color: {PANEL};
    color: {INK};
    border: {SEAM_WIDTH}px solid {SEAM};
    padding: {CONTROL_PADDING - 2}px {CONTROL_PADDING}px;
}}
QDialog {{ background-color: {PANEL}; }}
QLabel {{ background: transparent; }}
QLabel[role="dim"] {{ color: {INK_DIM}; }}
QLabel[role="fault"] {{ color: {FAULT}; }}
QLabel[role="live"] {{ color: {LIVE}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: {KEYCAP};
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS}px;
    padding: {CONTROL_PADDING - 1}px {CONTROL_PADDING}px;
    selection-background-color: {SEAM};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QComboBox:focus {{ border-color: {SIGNAL}; }}
QLineEdit[role="mono"], QPlainTextEdit[role="mono"] {{ font-family: "{mono}"; }}
QComboBox::drop-down {{ border: none; width: {CONTROL_PADDING * 3}px; }}
QComboBox QAbstractItemView {{
    background-color: {PANEL};
    border: {SEAM_WIDTH}px solid {SEAM};
    selection-background-color: {KEYCAP_HOVER};
}}
QPushButton {{
    background-color: {KEYCAP};
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS}px;
    padding: {CONTROL_PADDING}px {CONTROL_PADDING * 3}px;
}}
QPushButton:hover {{ background-color: {KEYCAP_HOVER}; }}
QPushButton:pressed {{ background-color: {PANEL}; }}
QPushButton:disabled {{ color: {INK_DIM}; border-color: {SEAM}; }}
QPushButton[variant="primary"] {{ border-color: {SIGNAL}; color: {SIGNAL}; }}
QPushButton[variant="live"] {{
    border-color: {LIVE};
    color: {LIVE};
    background-color: {live_bg.name(QColor.NameFormat.HexArgb)};
    font-family: "{display}";
    font-weight: 500;
    letter-spacing: 1px;
}}
QPushButton[variant="danger"] {{ border-color: {FAULT}; color: {FAULT}; }}
QPushButton[variant="glyph"] {{ padding: 0; }}
QCheckBox::indicator {{
    width: {CONTROL_PADDING * 2}px;
    height: {CONTROL_PADDING * 2}px;
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS - 3}px;
    background: {KEYCAP};
}}
QCheckBox::indicator:checked {{ background: {SIGNAL}; border-color: {SIGNAL}; }}
QTabWidget::pane {{
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS}px;
    top: -{SEAM_WIDTH}px;
}}
QTabBar::tab {{
    background: {PANEL};
    color: {INK_DIM};
    border: {SEAM_WIDTH}px solid {SEAM};
    border-bottom: none;
    border-top-left-radius: {CONTROL_RADIUS}px;
    border-top-right-radius: {CONTROL_RADIUS}px;
    padding: {CONTROL_PADDING - 1}px {CONTROL_PADDING * 3}px;
    margin-right: {SEAM_WIDTH * 2}px;
}}
QTabBar::tab:selected {{ background: {KEYCAP}; color: {INK}; }}
QListWidget {{
    background-color: {KEYCAP};
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS}px;
}}
QTableWidget {{
    background-color: {KEYCAP};
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS}px;
    gridline-color: {SEAM};
}}
QTableWidget::item {{ padding: {CONTROL_PADDING - 2}px; }}
QTableWidget::item:selected {{ background: {KEYCAP_HOVER}; color: {INK}; }}
QHeaderView::section {{
    background-color: {PANEL};
    color: {INK_DIM};
    border: none;
    border-bottom: {SEAM_WIDTH}px solid {SEAM};
    padding: {CONTROL_PADDING - 2}px {CONTROL_PADDING}px;
}}
QTableCornerButton::section {{ background-color: {PANEL}; border: none; }}
QListWidget::item {{ padding: {CONTROL_PADDING - 2}px; }}
QListWidget::item:selected {{ background: {KEYCAP_HOVER}; color: {INK}; }}
QSlider::groove:horizontal {{
    height: {SEAM_WIDTH * 2}px;
    background: {SEAM};
    border-radius: {SEAM_WIDTH}px;
}}
QSlider::handle:horizontal {{
    background: {SIGNAL};
    width: {CONTROL_PADDING * 2}px;
    height: {CONTROL_PADDING * 2}px;
    margin: -{CONTROL_PADDING - 1}px 0;
    border-radius: {CONTROL_PADDING}px;
}}
QToolButton {{
    background-color: {KEYCAP};
    border: {SEAM_WIDTH}px solid {SEAM};
    border-radius: {CONTROL_RADIUS}px;
    padding: {CONTROL_PADDING - 2}px {CONTROL_PADDING}px;
}}
QToolButton:hover {{ background-color: {KEYCAP_HOVER}; }}
QToolButton:pressed {{ background-color: {PANEL}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: {CONTROL_PADDING + 2}px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {SEAM};
    border-radius: {(CONTROL_PADDING + 2) // 2}px;
    min-height: {CONTROL_PADDING * 4}px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""
