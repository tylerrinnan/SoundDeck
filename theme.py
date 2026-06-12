"""
theme.py — Palette dataclass, theme catalogue, and QSS builders.
"""

from __future__ import annotations
from dataclasses import dataclass


def hex_to_rgb(h: str) -> str:
    """Convert '#RRGGBB' to 'R,G,B' for use in rgba() CSS values."""
    h = h.lstrip('#')
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"


# ── Status / semantic ────────────────────────────────────────────────────────
HDR_ON   = "#00d4a8"  # universal "good/active" green; readable on dark + light
GSYNC_ON = "#76b900"  # NVIDIA green


@dataclass(frozen=True)
class Palette:
    name:       str
    group:      str   # "Saturated" | "Pastel" | "Neutral" | "Community"
    mode:       str   # "dark" | "light"
    bg:         str   # outer card base bg hex
    surface:    str   # section card surface hex
    text_pri:   str
    text_sec:   str
    text_tert:  str   # section labels / faint
    accent:     str
    accent_dim: str

    @property
    def is_light(self) -> bool: return self.mode == "light"
    @property
    def bg_rgb(self) -> str:      return hex_to_rgb(self.bg)
    @property
    def surface_rgb(self) -> str: return hex_to_rgb(self.surface)
    @property
    def accent_rgb(self) -> str:  return hex_to_rgb(self.accent)

    @property
    def hairline(self) -> str:
        return "rgba(0,0,0,0.07)" if self.is_light else "rgba(255,255,255,0.06)"

    @property
    def hairline_strong(self) -> str:
        return "rgba(0,0,0,0.14)" if self.is_light else "rgba(255,255,255,0.10)"

    @property
    def slider_track(self) -> str:
        return "rgba(0,0,0,0.10)" if self.is_light else "rgba(255,255,255,0.08)"

    @property
    def accent_text(self) -> str:
        # accent variant guaranteed to read as text on the theme's bg
        return self.accent_dim if self.is_light else self.accent

    @property
    def slider_knob(self) -> str:
        return "#ffffff"


_THEMES_LIST: list[Palette] = [
    # ── Saturated (existing) ──────────────────────────────────────────────────
    Palette("Violet",  "Saturated", "dark",
            bg="#0a0a10", surface="#16161f",
            text_pri="#e8e7f5", text_sec="#8a88a8", text_tert="#6e6c9a",
            accent="#7c5cf5", accent_dim="#4a3599"),
    Palette("Blue",    "Saturated", "dark",
            bg="#0a0c16", surface="#161827",
            text_pri="#e0e8f5", text_sec="#7e8ba5", text_tert="#5a7eaf",
            accent="#4a9eff", accent_dim="#1a5fcc"),
    Palette("Cyan",    "Saturated", "dark",
            bg="#0a0e11", surface="#152024",
            text_pri="#dfeff0", text_sec="#7a9a9a", text_tert="#5a8e8a",
            accent="#00c4d4", accent_dim="#00707d"),
    Palette("Green",   "Saturated", "dark",
            bg="#0a0f0a", surface="#152115",
            text_pri="#deefe2", text_sec="#789a82", text_tert="#5a8062",
            accent="#00c875", accent_dim="#007a44"),
    Palette("Pink",    "Saturated", "dark",
            bg="#0e0a11", surface="#1f1626",
            text_pri="#f0e0f0", text_sec="#9c789a", text_tert="#a558b8",
            accent="#e040fb", accent_dim="#8b009e"),
    Palette("OLED",    "Saturated", "dark",
            bg="#000000", surface="#0a0a0f",
            text_pri="#e6e5f3", text_sec="#7a789a", text_tert="#5a58a0",
            accent="#e0dff0", accent_dim="#7a789a"),

    # ── Community / dark ──────────────────────────────────────────────────────
    Palette("Nord",                    "Community", "dark",
            bg="#2e3440", surface="#3b4252",
            text_pri="#eceff4", text_sec="#d8dee9", text_tert="#a3b3c5",
            accent="#88c0d0", accent_dim="#5e81ac"),
    Palette("Tokyo Night",             "Community", "dark",
            bg="#1a1b26", surface="#24283b",
            text_pri="#c0caf5", text_sec="#9aa5ce", text_tert="#7681a8",
            accent="#7aa2f7", accent_dim="#3d59a1"),
    Palette("Catppuccin Mocha",        "Community", "dark",
            bg="#1e1e2e", surface="#313244",
            text_pri="#cdd6f4", text_sec="#a6adc8", text_tert="#7f849c",
            accent="#cba6f7", accent_dim="#7d5ba6"),
    Palette("Catppuccin Macchiato",    "Community", "dark",
            bg="#24273a", surface="#363a4f",
            text_pri="#cad3f5", text_sec="#a5adcb", text_tert="#7b819b",
            accent="#c6a0f6", accent_dim="#7d5ba6"),
    Palette("Catppuccin Frappé",       "Community", "dark",
            bg="#303446", surface="#414559",
            text_pri="#c6d0f5", text_sec="#a5adce", text_tert="#838ba7",
            accent="#ca9ee6", accent_dim="#7d5ba6"),

    # ── Neutral / dark ────────────────────────────────────────────────────────
    Palette("Graphite", "Neutral", "dark",
            bg="#18181b", surface="#27272a",
            text_pri="#fafafa", text_sec="#a1a1aa", text_tert="#71717a",
            accent="#fafafa", accent_dim="#a1a1aa"),

    # ── Pastel / light ────────────────────────────────────────────────────────
    Palette("Sakura",   "Pastel", "light",
            bg="#fdf6f8", surface="#f9e8ee",
            text_pri="#3a2630", text_sec="#7a5e68", text_tert="#a98494",
            accent="#e88aae", accent_dim="#c25c84"),
    Palette("Lavender", "Pastel", "light",
            bg="#f7f5ff", surface="#ece8fa",
            text_pri="#2b2740", text_sec="#6a6a90", text_tert="#9a98c0",
            accent="#9b8af0", accent_dim="#6e58c8"),
    Palette("Mint",     "Pastel", "light",
            bg="#f3fbf7", surface="#dff5ea",
            text_pri="#1f3a30", text_sec="#557066", text_tert="#7e9a90",
            accent="#5fc09a", accent_dim="#3a8a6e"),
    Palette("Peach",    "Pastel", "light",
            bg="#fef6f1", surface="#fbe5d6",
            text_pri="#3a2820", text_sec="#7a5c50", text_tert="#a08070",
            accent="#f49b6f", accent_dim="#c46c3e"),
    Palette("Sage",     "Pastel", "light",
            bg="#f7f8f1", surface="#e8ebe0",
            text_pri="#2c2f24", text_sec="#5e6452", text_tert="#88907a",
            accent="#7a9a72", accent_dim="#56784f"),

    # ── Neutral / light ───────────────────────────────────────────────────────
    Palette("Paper",    "Neutral", "light",
            bg="#fbf8f0", surface="#f0ebdf",
            text_pri="#2c2820", text_sec="#605c50", text_tert="#94907e",
            accent="#3a3a3a", accent_dim="#1a1a1a"),

    # ── Community / light ─────────────────────────────────────────────────────
    Palette("Catppuccin Latte", "Community", "light",
            bg="#eff1f5", surface="#e6e9ef",
            text_pri="#4c4f69", text_sec="#6c6f85", text_tert="#9ca0b0",
            accent="#8839ef", accent_dim="#5b21b6"),
]

THEMES: dict[str, Palette] = {p.name: p for p in _THEMES_LIST}

# Ordering for the SettingsDialog grouped dropdown
THEME_GROUPS: list[tuple[str, list[str]]] = [
    ("Saturated", [p.name for p in _THEMES_LIST if p.group == "Saturated"]),
    ("Pastel",    [p.name for p in _THEMES_LIST if p.group == "Pastel"]),
    ("Neutral",   [p.name for p in _THEMES_LIST if p.group == "Neutral"]),
    ("Community", [p.name for p in _THEMES_LIST if p.group == "Community"]),
]

SIZE_OPTIONS  = {"Compact": 310, "Normal": 370, "Wide": 440}
POSITION_OPTS = ["Center", "Top Center", "Top Right", "Bottom Right", "Bottom Left"]


def get_palette(name: str) -> Palette:
    return THEMES.get(name, THEMES["Violet"])


# ═══════════════════════════════════════════════════════════════════════════════
#  QSS builders
# ═══════════════════════════════════════════════════════════════════════════════
def build_overlay_qss(p: Palette) -> str:
    ar = p.accent_rgb
    sr = p.surface_rgb
    return f"""
QWidget {{
    font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
    color: {p.text_pri};
    background: transparent;
}}
QFrame#section_card {{
    background: rgba({sr},0.55);
    border: 1px solid {p.hairline};
    border-radius: 10px;
}}
QLabel#section_label {{
    color: {p.text_tert};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
QLabel#title_label {{
    color: {p.text_pri};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QLabel#mono_label {{
    color: {p.text_sec};
    font-size: 11px;
    font-variant-numeric: tabular-nums;
}}
QLabel#subtle_label {{
    color: {p.text_sec};
    font-size: 11px;
}}
QLabel#vol_pct {{
    color: {p.text_sec};
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    min-width: 30px;
}}
QPushButton#dev_row {{
    background: transparent;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 0 10px;
    font-size: 12px;
    color: {p.text_sec};
    min-height: 30px;
}}
QPushButton#dev_row:hover {{
    background: rgba({ar},0.10);
    color: {p.text_pri};
}}
QPushButton#dev_row[active="true"] {{
    background: rgba({ar},0.16);
    color: {p.accent_text};
    font-weight: 600;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {p.slider_track};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                 stop:0 {p.accent_dim}, stop:1 {p.accent});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px;
    background: {p.slider_knob};
    border-radius: 7px;
    margin: -5px 0;
    border: 2px solid {p.accent};
}}
QSlider::handle:horizontal:hover {{ background: {p.accent}; }}

QSlider::groove:vertical {{
    width: 4px;
    background: {p.slider_track};
    border-radius: 2px;
}}
QSlider::sub-page:vertical {{
    background: {p.slider_track};
    border-radius: 2px;
}}
QSlider::add-page:vertical {{
    background: qlineargradient(x1:0,y1:1,x2:0,y2:0,
                 stop:0 {p.accent_dim}, stop:1 {p.accent});
    border-radius: 2px;
}}
QSlider::handle:vertical {{
    width: 14px; height: 14px;
    background: {p.slider_knob};
    border-radius: 7px;
    margin: 0 -5px;
    border: 2px solid {p.accent};
}}
QSlider::handle:vertical:hover {{ background: {p.accent}; }}

QPushButton#profile_pill {{
    background: rgba({sr},0.7);
    border: 1px solid {p.hairline};
    border-radius: 14px;
    padding: 4px 12px;
    font-size: 11px;
    color: {p.text_pri};
}}
QPushButton#profile_pill:hover {{ border: 1px solid rgba({ar},0.45); }}
QPushButton#profile_pill[active="true"] {{
    background: rgba({ar},0.18);
    border: 1px solid {p.accent};
    color: {p.accent_text};
    font-weight: 600;
}}
QPushButton#add_profile_btn {{
    background: transparent;
    border: 1px dashed rgba({ar},0.40);
    border-radius: 14px;
    padding: 4px 10px;
    font-size: 13px;
    color: {p.accent_text};
}}
QPushButton#add_profile_btn:hover {{
    border: 1px dashed {p.accent};
    color: {p.accent};
    background: rgba({ar},0.08);
}}

QComboBox#rate_combo {{
    background: rgba({sr},0.7);
    border: 1px solid {p.hairline};
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    min-width: 76px;
    color: {p.text_pri};
    selection-background-color: rgba({ar},0.25);
}}
QComboBox#rate_combo:hover {{ border: 1px solid rgba({ar},0.45); }}
QComboBox#rate_combo::drop-down {{ border: none; width: 20px; }}
QComboBox#rate_combo::down-arrow {{
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_sec};
}}
QComboBox#rate_combo QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.hairline};
    border-radius: 6px;
    color: {p.text_pri};
    selection-background-color: rgba({ar},0.25);
    outline: none; padding: 2px;
}}

QPushButton#close_btn, QPushButton#mute_btn, QPushButton#mixer_toggle {{
    background: transparent; border: none;
    color: {p.text_sec}; font-size: 13px; padding: 0;
    border-radius: 4px;
}}
QPushButton#close_btn:hover,
QPushButton#mute_btn:hover,
QPushButton#mixer_toggle:hover {{ color: {p.text_pri}; }}

QPushButton#mute_btn[muted="true"] {{ color: {p.accent_text}; }}

QProgressBar#peak_meter {{
    max-height: 3px;
    background: {p.slider_track};
    border: none;
    border-radius: 1px;
}}
QProgressBar#peak_meter::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                 stop:0 {p.accent_dim}, stop:1 {p.accent});
    border-radius: 1px;
}}
"""


def build_card_style(p: Palette, opacity_pct: int) -> str:
    """QSS for the outer overlay card (window-level frame)."""
    alpha = int(opacity_pct / 100 * 255)
    return (
        f"#card {{ background: rgba({p.bg_rgb},{alpha}); "
        f"border: 1px solid {p.hairline_strong}; "
        f"border-radius: 14px; }}"
    )


def build_menu_qss(p: Palette) -> str:
    ar = p.accent_rgb
    return f"""
QMenu {{
    background: {p.surface};
    border: 1px solid rgba({ar},0.3);
    border-radius: 8px;
    color: {p.text_pri};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba({ar},0.2); }}
QMenu::separator {{
    height: 1px;
    background: {p.hairline};
    margin: 4px 6px;
}}
"""


def hdr_pill_style(p: Palette, on: bool) -> str:
    if on:
        return (f"QPushButton{{background:rgba(0,212,168,0.14);"
                f"border:1px solid {HDR_ON};border-radius:8px;"
                f"padding:0 10px;font-size:10px;font-weight:700;color:{HDR_ON};}}")
    return (f"QPushButton{{background:transparent;"
            f"border:1px solid {p.hairline_strong};border-radius:8px;"
            f"padding:0 10px;font-size:10px;color:{p.text_sec};}}")


def gsync_pill_style(p: Palette, on: bool) -> str:
    if on:
        return (f"QPushButton{{background:rgba(118,185,0,0.14);"
                f"border:1px solid {GSYNC_ON};border-radius:8px;"
                f"padding:0 10px;font-size:10px;font-weight:700;color:{GSYNC_ON};}}")
    return (f"QPushButton{{background:transparent;"
            f"border:1px solid {p.hairline_strong};border-radius:8px;"
            f"padding:0 10px;font-size:10px;color:{p.text_sec};}}")
