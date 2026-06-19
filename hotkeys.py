"""
hotkeys.py — Win32 RegisterHotKey wrapper.

Uses kernel-managed global hotkeys via WM_HOTKEY. Survives sleep/lock and
the LL-hook timeouts (LowLevelHooksTimeout) that drop `keyboard` library
hooks after long idle.

Messages post to the thread message queue of the registering thread.
Register from the Qt UI thread so WM_HOTKEY arrives via the app's
QAbstractNativeEventFilter as `windows_generic_MSG`.

Durability model
----------------
`HotkeyManager` keeps two separate maps:

  * `_desired`  combo -> binding   — the durable INTENT (main hotkey + every
                                     profile hotkey), re-derived from settings
                                     and profiles. This is the source of truth.
  * `_live`     id    -> binding   — what is currently registered with Windows.

`reconcile()` registers any desired combo that is not currently live and
returns the combos that still failed, so the caller can retry. Because the
intent is never thrown away on a failed `RegisterHotKey`, a transient failure
(combo briefly owned by the shell/another app right after resume or boot)
self-heals on the next reconcile instead of being lost until the app restarts.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from log import log

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


def _win_register(hk_id: int, mods: int, vk: int) -> bool:
    return bool(_user32.RegisterHotKey(None, hk_id, mods, vk))


def _win_unregister(hk_id: int) -> None:
    _user32.UnregisterHotKey(None, hk_id)


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


# combo, mods, vk, callback
_Binding = Tuple[str, int, int, Callable[[], None]]


class HotkeyManager:
    """Own the desired hotkey set and reconcile it against Windows.

    All public methods must run on the same thread (typically Qt's UI thread)
    so WM_HOTKEY messages post to the queue that the native event filter pumps.

    `register_fn` / `unregister_fn` are injectable so the reconcile logic can be
    unit-tested without touching real Win32 (tests pass fakes).
    """

    def __init__(
        self,
        register_fn:   Optional[Callable[[int, int, int], bool]] = None,
        unregister_fn: Optional[Callable[[int], None]]           = None,
    ) -> None:
        self._do_register   = register_fn   if register_fn   is not None else _win_register
        self._do_unregister = unregister_fn if unregister_fn is not None else _win_unregister
        self._next_id = 1
        # Durable intent, keyed by normalized combo.
        self._desired: Dict[str, _Binding] = {}
        # Live OS registrations, keyed by hotkey id.
        self._live: Dict[int, _Binding] = {}
        # Combos currently failing — tracked only to avoid re-logging each retry.
        self._known_failed: Set[str] = set()

    # ── Desired set ───────────────────────────────────────────────────────────
    def set_bindings(self, bindings: Iterable[Tuple[str, Callable[[], None]]]) -> List[str]:
        """Replace the entire desired set and reconcile with the OS.

        Source of truth = settings + profiles; safe to call repeatedly. Returns
        the combos that failed to register (caller may schedule a retry)."""
        desired: Dict[str, _Binding] = {}
        for combo, callback in bindings:
            if not combo:
                continue
            parsed = parse_combo(combo)
            if parsed is None:
                log(f"[hotkeys] cannot parse {combo!r} — skipped")
                continue
            mods, vk = parsed
            desired[combo.lower()] = (combo, mods, vk, callback)
        self._desired = desired
        self._known_failed.clear()
        self._unregister_all_live()
        return self.reconcile()

    def clear(self) -> None:
        """Drop all desired bindings and unregister everything live."""
        self._unregister_all_live()
        self._desired.clear()
        self._known_failed.clear()
        self._next_id = 1

    # ── Reconcile ─────────────────────────────────────────────────────────────
    def reconcile(self) -> List[str]:
        """Register every desired combo not currently live. Idempotent and cheap
        when everything is already registered. Returns the combos still failing."""
        live_keys = {combo.lower() for combo, _m, _v, _cb in self._live.values()}
        failed: List[str] = []
        for key, (combo, mods, vk, callback) in self._desired.items():
            if key in live_keys:
                continue
            hk_id = self._next_id
            if self._do_register(hk_id, mods, vk):
                self._live[hk_id] = (combo, mods, vk, callback)
                self._next_id += 1
                log(f"[hotkeys] registered {combo.upper()} -> id={hk_id}")
            else:
                failed.append(combo)
        self._log_failures(failed)
        return failed

    def reregister_all(self) -> List[str]:
        """Resume/lock path: drop live regs and re-assert the full DESIRED set.

        Crucially re-derives from the desired intent, not the live cache, so a
        combo that previously failed can still recover."""
        self._unregister_all_live()
        self._known_failed.clear()
        return self.reconcile()

    def pending(self) -> List[str]:
        """Desired combos that are not currently live (failed or never tried)."""
        live_keys = {combo.lower() for combo, _m, _v, _cb in self._live.values()}
        return [combo for key, (combo, _m, _v, _cb) in self._desired.items()
                if key not in live_keys]

    # ── Queries ───────────────────────────────────────────────────────────────
    def has(self, combo: str) -> bool:
        """True if `combo` is currently registered with Windows (live)."""
        target = combo.lower()
        return any(c.lower() == target for c, _m, _v, _cb in self._live.values())

    def dispatch(self, hk_id: int) -> bool:
        entry = self._live.get(hk_id)
        if entry is None:
            return False
        _combo, _mods, _vk, callback = entry
        try:
            callback()
        except Exception as e:
            log(f"[hotkeys] callback for id={hk_id} raised: {e}")
        return True

    # ── Internals ─────────────────────────────────────────────────────────────
    def _unregister_all_live(self) -> None:
        for hk_id in list(self._live.keys()):
            try:
                self._do_unregister(hk_id)
            except Exception as e:
                log(f"[hotkeys] UnregisterHotKey({hk_id}) error: {e}")
        self._live.clear()

    def _log_failures(self, failed: List[str]) -> None:
        """Log only on change so a chronically-stolen combo doesn't spam the log
        on every periodic reconcile."""
        now = {c.lower() for c in failed}
        newly = now - self._known_failed
        if newly:
            label = ", ".join(c.upper() for c in failed)
            log(f"[hotkeys] could not register (will retry): {label}")
        self._known_failed = now
