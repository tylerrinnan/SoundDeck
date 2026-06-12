"""
display.py — Refresh rate enumeration and switching via Windows DisplayConfig/ChangeDisplaySettings.
"""

import ctypes
import ctypes.wintypes as wt
from typing import List, Optional, Tuple

_user32 = ctypes.windll.user32

ENUM_CURRENT_SETTINGS  = 0xFFFFFFFF  # -1 as DWORD
DM_DISPLAYFREQUENCY    = 0x00400000
DISP_CHANGE_SUCCESSFUL = 0
CDS_UPDATEREGISTRY        = 0x00000001
CDS_GLOBAL                = 0x00000008
DISPLAY_DEVICE_ACTIVE     = 0x00000001
DISPLAY_DEVICE_PRIMARY    = 0x00000004


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName",        ctypes.c_wchar * 32),
        ("dmSpecVersion",       wt.WORD),
        ("dmDriverVersion",     wt.WORD),
        ("dmSize",              wt.WORD),
        ("dmDriverExtra",       wt.WORD),
        ("dmFields",            wt.DWORD),
        # DUMMYUNIONNAME (position/orientation union — we only need position)
        ("dmPositionX",         ctypes.c_int32),
        ("dmPositionY",         ctypes.c_int32),
        ("dmDisplayOrientation", wt.DWORD),
        ("dmDisplayFixedOutput", wt.DWORD),
        ("dmColor",             wt.SHORT),
        ("dmDuplex",            wt.SHORT),
        ("dmYResolution",       wt.SHORT),
        ("dmTTOption",          wt.SHORT),
        ("dmCollate",           wt.SHORT),
        ("dmFormName",          ctypes.c_wchar * 32),
        ("dmLogPixels",         wt.WORD),
        ("dmBitsPerPel",        wt.DWORD),
        ("dmPelsWidth",         wt.DWORD),
        ("dmPelsHeight",        wt.DWORD),
        ("dmDisplayFlags",      wt.DWORD),
        ("dmDisplayFrequency",  wt.DWORD),
        # Remaining fields (ICMMethod … PanningHeight) — pad to 220 bytes total
        ("_pad",                ctypes.c_byte * 32),
    ]


class _DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb",           wt.DWORD),
        ("DeviceName",   ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags",   wt.DWORD),
        ("DeviceID",     ctypes.c_wchar * 128),
        ("DeviceKey",    ctypes.c_wchar * 128),
    ]


def _make_devmode() -> DEVMODEW:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(dm)
    return dm


class DisplayManager:
    __slots__ = ()

    def get_all_displays(self) -> List[Tuple[str, str]]:
        """Return (device_name, label) for every active display, primary first."""
        primary: List[Tuple[str, str]] = []
        others:  List[Tuple[str, str]] = []
        dd = _DISPLAY_DEVICE()
        dd.cb = ctypes.sizeof(dd)
        i = 0
        num = 0
        while True:
            if not _user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
            if dd.StateFlags & DISPLAY_DEVICE_ACTIVE:
                num += 1
                label = f"Display {num}"
                if dd.StateFlags & DISPLAY_DEVICE_PRIMARY:
                    label += " (Primary)"
                    primary.append((dd.DeviceName, label))
                else:
                    others.append((dd.DeviceName, label))
            i += 1
        return primary + others

    def get_primary_display_name(self) -> str:
        """Return device name of the primary display (e.g. r'\\\\.\\DISPLAY1')."""
        dd = _DISPLAY_DEVICE()
        dd.cb = ctypes.sizeof(dd)
        _user32.EnumDisplayDevicesW(None, 0, ctypes.byref(dd), 0)
        return dd.DeviceName

    def _resolve_name(self, display_name: Optional[str]) -> str:
        return display_name or self.get_primary_display_name()

    def get_current_refresh_rate(self, display_name: Optional[str] = None) -> int:
        dm = _make_devmode()
        if _user32.EnumDisplaySettingsExW(
            self._resolve_name(display_name), ENUM_CURRENT_SETTINGS, ctypes.byref(dm), 0
        ):
            return int(dm.dmDisplayFrequency)
        return 0

    def get_available_refresh_rates(self, display_name: Optional[str] = None) -> List[int]:
        """Return sorted list of distinct refresh rates for the current resolution."""
        name = self._resolve_name(display_name)
        dm = _make_devmode()
        if not _user32.EnumDisplaySettingsExW(name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm), 0):
            return []
        cur_w, cur_h = dm.dmPelsWidth, dm.dmPelsHeight

        rates: set[int] = set()
        i = 0
        while _user32.EnumDisplaySettingsExW(name, i, ctypes.byref(dm), 0):
            if dm.dmPelsWidth == cur_w and dm.dmPelsHeight == cur_h and dm.dmDisplayFrequency > 0:
                rates.add(int(dm.dmDisplayFrequency))
            i += 1
        return sorted(rates)

    def set_refresh_rate(self, hz: int, display_name: Optional[str] = None) -> bool:
        """Switch the display to the given refresh rate. Returns True on success."""
        name = self._resolve_name(display_name)
        dm = _make_devmode()
        if not _user32.EnumDisplaySettingsExW(name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm), 0):
            return False

        dm.dmDisplayFrequency = hz
        dm.dmFields |= DM_DISPLAYFREQUENCY
        return _user32.ChangeDisplaySettingsExW(
            name, ctypes.byref(dm), None, CDS_UPDATEREGISTRY | CDS_GLOBAL, None,
        ) == DISP_CHANGE_SUCCESSFUL
