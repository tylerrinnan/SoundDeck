"""
main.py — SoundDeck entry point.
"""

import sys
import os
import ctypes
from ctypes import wintypes

os.environ.setdefault("PYSTRAY_BACKEND", "win32")

from PyQt6.QtCore    import QTimer, pyqtSignal, QObject, QAbstractNativeEventFilter
from PyQt6.QtWidgets import QApplication, QMessageBox

from audio    import AudioManager
from hdr      import HDRManager
from profiles import ProfileManager
from display  import DisplayManager
from mixer    import MixerManager
from settings import SettingsManager
from gsync    import GSyncManager
from overlay  import OverlayWindow
from tray     import TrayManager
from caps     import build_default_registry
from hotkeys  import HotkeyManager, WM_HOTKEY

MUTEX_NAME = "SoundDeck_SingleInstance_Mutex"

# Win32 message constants for resume/unlock detection.
_WM_POWERBROADCAST       = 0x0218
_WM_WTSSESSION_CHANGE    = 0x02B1
_PBT_APMRESUMESUSPEND    = 0x0007
_PBT_APMRESUMEAUTOMATIC  = 0x0012
_WTS_SESSION_UNLOCK      = 0x8
_NOTIFY_FOR_THIS_SESSION = 0


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam",  wintypes.WPARAM),
        ("lParam",  wintypes.LPARAM),
        ("time",    wintypes.DWORD),
        ("pt_x",    wintypes.LONG),
        ("pt_y",    wintypes.LONG),
    ]


def _ensure_single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != 183


class _Bridge(QObject):
    toggle_overlay = pyqtSignal()
    apply_profile  = pyqtSignal(str)


class _NativeFilter(QAbstractNativeEventFilter):
    """Pumps WM_HOTKEY into the HotkeyManager and detects resume/unlock so
    we can re-register hotkeys + invalidate stale COM proxies. Windows can
    silently kill cached MMDevice pointers across suspend transitions."""

    def __init__(self, hotkeys: HotkeyManager, on_resume) -> None:
        super().__init__()
        self._hotkeys   = hotkeys
        self._on_resume = on_resume

    def nativeEventFilter(self, eventType, message):  # type: ignore[override]
        if eventType != b"windows_generic_MSG":
            return False, 0
        msg = _MSG.from_address(int(message))
        if msg.message == WM_HOTKEY:
            self._hotkeys.dispatch(int(msg.wParam))
            return True, 0
        if msg.message == _WM_POWERBROADCAST and msg.wParam in (
            _PBT_APMRESUMESUSPEND, _PBT_APMRESUMEAUTOMATIC):
            self._on_resume()
        elif msg.message == _WM_WTSSESSION_CHANGE and msg.wParam == _WTS_SESSION_UNLOCK:
            self._on_resume()
        return False, 0


def main() -> None:
    if not _ensure_single_instance():
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    settings = SettingsManager()
    audio    = AudioManager()
    hdr      = HDRManager()
    profiles = ProfileManager()
    display  = DisplayManager()
    mixer    = MixerManager()
    gsync    = GSyncManager()
    caps_registry = build_default_registry(audio=audio, display=display, hdr=hdr, gsync=gsync)

    bridge = _Bridge()
    _emit = bridge.toggle_overlay.emit
    _emit_profile = bridge.apply_profile.emit

    hotkeys = HotkeyManager()

    def _register_all_hotkeys() -> None:
        hotkeys.unregister_all()
        main_combo = settings.get("hotkey")
        if not hotkeys.register(main_combo, _emit):
            print(f"[main] main hotkey {main_combo!r} could not be registered")
        for profile in profiles.get_profiles():
            if not profile.hotkey:
                continue
            name = profile.name
            hotkeys.register(profile.hotkey, lambda n=name: _emit_profile(n))

    def rebind_hotkey(new_combo: str) -> None:
        old = settings.get("hotkey")
        settings.set("hotkey", new_combo)
        _register_all_hotkeys()
        if not hotkeys.has(new_combo):
            # RegisterHotKey rejected the combo (e.g. already owned by another
            # app, or unparseable). Roll back and surface the failure.
            settings.set("hotkey", old)
            _register_all_hotkeys()
            QMessageBox.warning(
                None, "SoundDeck",
                f'Could not register hotkey "{new_combo}".\nReverted to {old}.',
            )
            return
        print(f"[main] Hotkey rebound to {new_combo.upper()}")

    overlay = OverlayWindow(
        audio           = audio,
        hdr             = hdr,
        profiles        = profiles,
        display         = display,
        mixer           = mixer,
        settings        = settings,
        gsync           = gsync,
        caps_registry   = caps_registry,
        change_hotkey_fn= rebind_hotkey,
        profile_hotkeys_changed_fn=_register_all_hotkeys,
    )

    exe_path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    tray = TrayManager(
        audio            = audio,
        show_overlay_fn  = lambda: QTimer.singleShot(0, overlay.show_overlay),
        quit_fn          = app.quit,
        exe_path         = exe_path,
        change_hotkey_fn = lambda: QTimer.singleShot(0, overlay.open_hotkey_dialog),
    )
    tray.start()

    overlay._fade_out.finished.connect(tray.update_tooltip)

    bridge.toggle_overlay.connect(lambda: QTimer.singleShot(0, overlay.toggle_overlay))
    bridge.apply_profile.connect(overlay.apply_profile_by_hotkey)

    def _on_system_resume() -> None:
        # RegisterHotKey survives sleep, but we belt-and-suspenders refresh
        # ownership tables in case the shell process briefly stomped them.
        QTimer.singleShot(0, hotkeys.reregister_all)
        # COM proxies for endpoint volume/peak meter become dead pointers
        # after suspend, producing "Element not found" spam until evicted.
        try:
            audio.invalidate_volume_cache()
        except Exception:
            pass
        # Force the overlay to re-read live default IDs next refresh instead
        # of trusting whatever stale value sat in _active_*_id during sleep.
        try:
            QTimer.singleShot(0, overlay.invalidate_state)
        except Exception:
            pass
        print("[main] System resume/unlock — caches invalidated, hotkeys re-registered")

    native_filter = _NativeFilter(hotkeys, _on_system_resume)
    app.installNativeEventFilter(native_filter)

    # WTSRegisterSessionNotification needs a real HWND; winId() realizes one.
    try:
        wts = ctypes.windll.wtsapi32
        wts.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        wts.WTSRegisterSessionNotification.restype  = wintypes.BOOL
        wts.WTSRegisterSessionNotification(
            wintypes.HWND(int(overlay.winId())), _NOTIFY_FOR_THIS_SESSION)
    except Exception as e:
        print(f"[main] WTS session notification registration failed: {e}")

    _register_all_hotkeys()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
