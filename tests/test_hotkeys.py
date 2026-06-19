"""parse_combo: combo string -> (mods, vk), the contract RegisterHotKey relies on."""
from hotkeys import (
    parse_combo, MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT,
)


def test_ctrl_shift_letter():
    mods, vk = parse_combo("ctrl+shift+a")
    assert mods == MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
    assert vk == ord("A")


def test_function_key():
    mods, vk = parse_combo("alt+f4")
    assert mods == MOD_ALT | MOD_NOREPEAT
    assert vk == 0x73  # VK_F4


def test_win_aliases_collapse_to_same_flag():
    for token in ("win", "windows", "super", "meta"):
        mods, vk = parse_combo(f"{token}+d")
        assert mods == MOD_WIN | MOD_NOREPEAT
        assert vk == ord("D")


def test_digit_and_oem_punctuation():
    assert parse_combo("ctrl+1")[1] == ord("1")
    assert parse_combo("ctrl+,")[1] == 0xBC
    assert parse_combo("ctrl+/")[1] == 0xBF


def test_norepeat_always_set():
    mods, _ = parse_combo("ctrl+a")
    assert mods & MOD_NOREPEAT


def test_case_insensitive():
    assert parse_combo("CTRL+SHIFT+A") == parse_combo("ctrl+shift+a")


def test_unknown_token_returns_none():
    assert parse_combo("ctrl+nope") is None


def test_empty_returns_none():
    assert parse_combo("") is None


def test_modifiers_without_key_returns_none():
    assert parse_combo("ctrl+shift") is None
