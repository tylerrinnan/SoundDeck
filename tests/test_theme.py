"""Palette catalogue integrity + the hex_to_rgb helper used across QSS builders."""
from theme import hex_to_rgb, get_palette, THEMES, THEME_GROUPS


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
