"""
tray.py — System tray icon for SoundDeck.
"""

from __future__ import annotations

import os
import threading
import winreg
from typing import TYPE_CHECKING, Callable

import pystray

from make_icon import make_icon as _make_icon

if TYPE_CHECKING:
    from audio import AudioManager

STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME    = "SoundDeck"


def _is_in_startup() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def _set_startup(enabled: bool, exe_path: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY,
                            0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception as e:
        print(f"[tray] startup registry error: {e}")


class TrayManager:
    def __init__(
        self,
        audio:            "AudioManager",
        show_overlay_fn:  Callable[[], None],
        quit_fn:          Callable[[], None],
        exe_path: str     = "",
        change_hotkey_fn: Callable[[], None] | None = None,
    ) -> None:
        self._audio            = audio
        self._show_overlay     = show_overlay_fn
        self._quit             = quit_fn
        self._exe_path         = exe_path
        self._change_hotkey_fn = change_hotkey_fn
        self._icon: "pystray.Icon | None" = None  # type: ignore[reportInvalidTypeForm]  # pystray: no stubs
        self._cached_tooltip: str = "SoundDeck"

    def start(self) -> None:
        icon = pystray.Icon(
            name  = APP_NAME,
            icon  = _make_icon(),
            title = self._build_tooltip(),
            menu  = self._build_menu(),
        )
        self._icon = icon
        threading.Thread(target=icon.run, daemon=True).start()

    def update_tooltip(self, device_name: str | None = None) -> None:
        """Update tray tooltip. Pass device_name to avoid a COM round-trip."""
        if device_name:
            self._cached_tooltip = f"SoundDeck  —  {device_name}"
        else:
            self._cached_tooltip = self._build_tooltip()
        if self._icon:
            self._icon.title = self._cached_tooltip

    def _build_tooltip(self) -> str:
        try:
            dev_id = self._audio.get_default_output_id()
            if dev_id:
                for d in self._audio.get_playback_devices():
                    if d.id == dev_id:
                        return f"SoundDeck  —  {d.short_name(30)}"
        except Exception:
            pass
        return "SoundDeck"

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def _build_menu(self) -> pystray.Menu:
        items = [
            pystray.MenuItem(
                "🎛️  Open SoundDeck",
                lambda icon, item: self._show_overlay(),
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_startup,
                checked=lambda item: _is_in_startup(),
            ),
        ]
        if self._change_hotkey_fn is not None:
            items.append(pystray.MenuItem(
                "⌨️  Change Hotkey",
                lambda icon, item: self._change_hotkey_fn(),  # type: ignore[misc]
            ))
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Exit", self._on_exit)]
        return pystray.Menu(*items)

    def _toggle_startup(self, icon, item) -> None:
        _set_startup(not _is_in_startup(), self._exe_path)

    def _on_exit(self, icon, item) -> None:
        """Hard exit — guaranteed to work from any thread."""
        try:
            self.stop()
        except Exception:
            pass
        os._exit(0)
