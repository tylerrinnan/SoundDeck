"""
hotkeys.py — Win32 RegisterHotKey wrapper.

Uses kernel-managed global hotkeys via WM_HOTKEY. Survives sleep/lock and
the LL-hook timeouts (LowLevelHooksTimeout) that drop `keyboard` library
hooks after long idle.

Messages post to the thread message queue of the registering thread.
Register from the Qt UI thread so WM_HOTKEY arrives via the app's
QAbstractNativeEventFilter as `windows_generic_MSG`.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Dict, Optional, Tuple

WM_HOTKEY    = 0x0312
MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002
MOD_SHIFT    = 0x0004
MOD_WIN      = 0x0008
MOD_NOREPEAT = 0x4000

_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes   = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype    = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype  = wintypes.BOOL

_MOD_FLAGS: Dict[str, int] = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN,
}

# Named keys → VK code. Mirrors widgets._KEY_MAP so HotkeyDialog combos parse.
_VK: Dict[str, int] = {
    **{f"f{i}": 0x70 + (i - 1) for i in range(1, 25)},
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "backspace": 0x08, "escape": 0x1B, "esc": 0x1B,
    "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23,
    "page up": 0x21, "pageup": 0x21,
    "page down": 0x22, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "print screen": 0x2C, "printscreen": 0x2C,
    "scroll lock": 0x91, "scrolllock": 0x91,
    "pause": 0x13, "caps lock": 0x14, "capslock": 0x14,
    "num lock": 0x90, "numlock": 0x90,
    # OEM punctuation (US layout)
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}


def parse_combo(combo: str) -> Optional[Tuple[int, int]]:
    """Parse `ctrl+shift+a` into (mods, vk). Returns None on unknown token."""
    if not combo:
        return None
    mods = 0
    vk: Optional[int] = None
    for raw in combo.lower().split("+"):
        part = raw.strip()
        if not part:
            continue
        if part in _MOD_FLAGS:
            mods |= _MOD_FLAGS[part]
            continue
        if part in _VK:
            vk = _VK[part]
            continue
        if len(part) == 1:
            ch = part.upper()
            if ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
                vk = ord(ch)
                continue
        return None
    if vk is None:
        return None
    return mods | MOD_NOREPEAT, vk


class HotkeyManager:
    """Track registered IDs so re-registration (after rebind or resume) is clean.

    All public methods must run on the same thread (typically Qt's UI thread)
    so WM_HOTKEY messages post to the queue that the native event filter pumps.
    """

    def __init__(self) -> None:
        self._next_id = 1
        # id -> (combo, mods, vk, callback)
        self._registered: Dict[int, Tuple[str, int, int, Callable[[], None]]] = {}

    def register(self, combo: str, callback: Callable[[], None]) -> Optional[int]:
        parsed = parse_combo(combo)
        if parsed is None:
            print(f"[hotkeys] cannot parse {combo!r}")
            return None
        mods, vk = parsed
        hk_id = self._next_id
        self._next_id += 1
        if not _user32.RegisterHotKey(None, hk_id, mods, vk):
            err = ctypes.get_last_error()
            print(f"[hotkeys] RegisterHotKey({combo!r}) failed (err={err})")
            return None
        self._registered[hk_id] = (combo, mods, vk, callback)
        print(f"[hotkeys] registered {combo.upper()} -> id={hk_id}")
        return hk_id

    def unregister_all(self) -> None:
        for hk_id in list(self._registered.keys()):
            try:
                _user32.UnregisterHotKey(None, hk_id)
            except Exception as e:
                print(f"[hotkeys] UnregisterHotKey({hk_id}) error: {e}")
        self._registered.clear()
        self._next_id = 1

    def reregister_all(self) -> None:
        """After sleep/lock, drop+re-add so Windows refreshes ownership tables."""
        items = [(combo, cb) for combo, _m, _v, cb in self._registered.values()]
        self.unregister_all()
        for combo, cb in items:
            self.register(combo, cb)

    def has(self, combo: str) -> bool:
        target = combo.lower()
        return any(entry[0].lower() == target for entry in self._registered.values())

    def dispatch(self, hk_id: int) -> bool:
        entry = self._registered.get(hk_id)
        if entry is None:
            return False
        _combo, _mods, _vk, callback = entry
        try:
            callback()
        except Exception as e:
            print(f"[hotkeys] callback for id={hk_id} raised: {e}")
        return True
