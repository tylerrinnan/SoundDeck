"""Palette catalogue integrity + the hex_to_rgb helper used across QSS builders."""
from theme import (
    hex_to_rgb, get_palette, THEMES, THEME_GROUPS,
    build_overlay_qss, build_card_style, build_menu_qss,
    hdr_pill_style, gsync_pill_style, HDR_ON, GSYNC_ON,
)


def test_hex_to_rgb():
    assert hex_to_rgb("#7c5cf5") == "124,92,245"
    assert hex_to_rgb("7c5cf5") == "124,92,245"   # leading '#' optional
    assert hex_to_rgb("#000000") == "0,0,0"
    assert hex_to_rgb("#ffffff") == "255,255,255"


def test_get_palette_known_and_fallback():
    assert get_palette("Violet").name == "Violet"
    assert get_palette("no-such-theme").name == "Violet"   # safe default


def test_theme_groups_cover_every_theme_exactly_once():
    grouped = [name for _group, names in THEME_GROUPS for name in names]
    assert set(grouped) == set(THEMES)
    assert len(grouped) == len(THEMES)   # none missing, none duplicated


def test_palette_rgb_props_match_hex():
    v = get_palette("Violet")
    assert v.is_light is False
    assert v.bg_rgb == hex_to_rgb(v.bg)
    assert v.surface_rgb == hex_to_rgb(v.surface)
    assert v.accent_rgb == hex_to_rgb(v.accent)


def test_light_palette_flag():
    assert get_palette("Sakura").is_light is True


def test_dark_palette_surface_props():
    v = get_palette("Violet")  # dark
    assert v.hairline == "rgba(255,255,255,0.06)"
    assert v.hairline_strong == "rgba(255,255,255,0.10)"
    assert v.slider_track == "rgba(255,255,255,0.08)"
    assert v.slider_knob == "#ffffff"
    assert v.accent_text == v.accent          # dark themes use the full accent


def test_light_palette_surface_props():
    s = get_palette("Sakura")  # light
    assert s.hairline == "rgba(0,0,0,0.07)"
    assert s.hairline_strong == "rgba(0,0,0,0.14)"
    assert s.slider_track == "rgba(0,0,0,0.10)"
    assert s.accent_text == s.accent_dim       # light themes dim the accent for legibility


def test_build_overlay_qss_embeds_palette_colors():
    p = get_palette("Violet")
    qss = build_overlay_qss(p)
    assert "QWidget" in qss
    assert p.text_pri in qss
    assert p.accent_rgb in qss


def test_build_card_style_alpha_scales_with_opacity():
    p = get_palette("Violet")
    assert f"rgba({p.bg_rgb},255)" in build_card_style(p, 100)
    assert f"rgba({p.bg_rgb},127)" in build_card_style(p, 50)   # int(50/100*255)


def test_build_menu_qss_embeds_surface():
    p = get_palette("Nord")
    qss = build_menu_qss(p)
    assert "QMenu" in qss
    assert p.surface in qss


def test_hdr_pill_style_differs_on_off():
    p = get_palette("Violet")
    on, off = hdr_pill_style(p, True), hdr_pill_style(p, False)
    assert HDR_ON in on
    assert "transparent" in off
    assert on != off


def test_gsync_pill_style_differs_on_off():
    p = get_palette("Violet")
    on, off = gsync_pill_style(p, True), gsync_pill_style(p, False)
    assert GSYNC_ON in on
    assert "transparent" in off
    assert on != off
