"""
gsync.py — Global NVIDIA G-Sync Compatible (Adaptive Sync) toggle via NVAPI.

The runtime per-display API (NvAPI_DISP_SetAdaptiveSyncData) is volatile on
GeForce drivers: even when accepted, the driver auto-reverts the per-display
bDisableAdaptiveSync bit back to 0 within ~1 second. DRS_SaveSettings does
not change that, no per-display DRS setting exists in public NVAPI, and the
NVIDIA Quadro GSync API is for pro multi-GPU sync — not consumer VRR.

So this module exposes a single global toggle (NvAPI DRS VRR_MODE_ID, the
exact mechanism NVCP and the gsync-toggle utility use). Per-display state is
still readable for capability detection.

VRR_MODE values:
    0 = DISABLED                       — global G-Sync off
    1 = FULLSCREEN_ONLY
    2 = FULLSCREEN_AND_WINDOWED        — borderless + fullscreen ("on")
"""

from __future__ import annotations
import ctypes
import os
from typing import Dict, Optional

NVAPI_OK                = 0
NVAPI_SETTING_NOT_FOUND = -114


def _log(msg: str) -> None:
    try:
        p = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                         "SoundDeck", "sounddeck.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[gsync] " + msg + "\n")
    except Exception:
        pass


# ── NVAPI function offsets (stable across driver versions) ──────────────────
_FN_INIT                        = 0x0150E828
_FN_DISP_GET_DISPLAY_ID_BY_NAME = 0xAE457190
_FN_DISP_GET_ADAPTIVE_SYNC_DATA = 0xB73D1EE9
_FN_DRS_CREATE_SESSION          = 0x0694D52E
_FN_DRS_DESTROY_SESSION         = 0xDAD9CFF8
_FN_DRS_LOAD_SETTINGS           = 0x375DBD6B
_FN_DRS_SAVE_SETTINGS           = 0xFCBC7E14
_FN_DRS_GET_BASE_PROFILE        = 0xDA8466A0
_FN_DRS_GET_SETTING             = 0x73BF8338
_FN_DRS_SET_SETTING             = 0x577DD202

# ── NV_GET_ADAPTIVE_SYNC_DATA struct (40 bytes, ver=1) — for capability ────
_AS_STRUCT_SIZE = 40
_AS_GET_VER1    = _AS_STRUCT_SIZE | (1 << 16)   # 0x00010028

# ── DRS VRR_MODE ────────────────────────────────────────────────────────────
VRR_MODE_ID                       = 0x1194F158
VRR_MODE_DISABLED                 = 0
VRR_MODE_FULLSCREEN_ONLY          = 1
VRR_MODE_FULLSCREEN_AND_WINDOWED  = 2

NVAPI_UNICODE_STRING_MAX = 2048
NVAPI_BINARY_DATA_MAX    = 4096


class _NVDRS_BINARY_SETTING(ctypes.Structure):
    _fields_ = [
        ("valueLength", ctypes.c_uint32),
        ("valueData",   ctypes.c_uint8 * NVAPI_BINARY_DATA_MAX),
    ]


class _NVDRS_VALUE_UNION(ctypes.Union):
    _fields_ = [
        ("u32Value",    ctypes.c_uint32),
        ("binaryValue", _NVDRS_BINARY_SETTING),
        ("wszValue",    ctypes.c_uint16 * NVAPI_UNICODE_STRING_MAX),
    ]


class _NVDRS_SETTING(ctypes.Structure):
    _anonymous_ = ("_pre", "_cur")
    _fields_ = [
        ("version",             ctypes.c_uint32),
        ("settingName",         ctypes.c_uint16 * NVAPI_UNICODE_STRING_MAX),
        ("settingId",           ctypes.c_uint32),
        ("settingType",         ctypes.c_uint32),  # NVDRS_DWORD_TYPE = 0
        ("settingLocation",     ctypes.c_uint32),  # NVDRS_CURRENT_PROFILE_LOCATION = 0
        ("isCurrentPredefined", ctypes.c_uint32),
        ("isPredefinedValid",   ctypes.c_uint32),
        ("_pre",                _NVDRS_VALUE_UNION),
        ("_cur",                _NVDRS_VALUE_UNION),
    ]


_NVDRS_SETTING_VER = ctypes.sizeof(_NVDRS_SETTING) | (1 << 16)


class GSyncManager:
    """Global G-Sync Compatible (Adaptive Sync) toggle via NVAPI DRS."""

    def __init__(self) -> None:
        self._dll = None
        self._qi  = None
        self._fns: Dict[int, object] = {}
        self._available = False
        self._id_cache: Dict[str, int] = {}
        self._capable_cache: Dict[str, bool] = {}
        self._load()

    # ── NVAPI init ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            self._dll = ctypes.WinDLL("nvapi64.dll")
        except OSError as e:
            _log(f"WinDLL nvapi64.dll failed: {e}")
            return
        try:
            self._qi = self._dll.nvapi_QueryInterface
            self._qi.argtypes = [ctypes.c_uint32]
            self._qi.restype  = ctypes.c_void_p
        except AttributeError as e:
            _log(f"nvapi_QueryInterface missing: {e}")
            return
        init = self._fn(_FN_INIT)
        if init is None:
            _log("NvAPI_Initialize address not resolved")
            return
        rc = init()
        if rc != NVAPI_OK:
            _log(f"NvAPI_Initialize returned {rc}")
            return
        self._available = True
        _log("NVAPI initialized OK")

    def _fn(self, fid: int, *argtypes):
        cached = self._fns.get(fid)
        if cached is not None:
            return cached
        if self._qi is None:
            return None
        addr = self._qi(fid)
        if not addr:
            return None
        fn = ctypes.WINFUNCTYPE(ctypes.c_int32, *argtypes)(addr)
        self._fns[fid] = fn
        return fn

    def is_available(self) -> bool:
        return self._available

    # ── per-display capability (read-only) ─────────────────────────────────
    def _display_id(self, dev_name: str) -> Optional[int]:
        if not self._available:
            return None
        cached = self._id_cache.get(dev_name)
        if cached is not None:
            return cached
        fn = self._fn(_FN_DISP_GET_DISPLAY_ID_BY_NAME,
                      ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32))
        if fn is None:
            return None
        did = ctypes.c_uint32(0)
        try:
            ret = fn(dev_name.encode("ascii"), ctypes.byref(did))
        except Exception as e:
            _log(f"GetDisplayIdByDisplayName({dev_name!r}) raised: {e}")
            return None
        if ret != NVAPI_OK:
            return None
        self._id_cache[dev_name] = did.value
        return did.value

    def is_capable(self, dev_name: str) -> bool:
        """True if NVAPI considers this display Adaptive-Sync capable.

        Cached per dev_name: once a display has reported capable, never
        revoke. Some drivers fail this Get when global VRR_MODE=0, which
        would otherwise make the global pill vanish after toggling off.
        """
        if self._capable_cache.get(dev_name):
            return True
        did = self._display_id(dev_name)
        if did is None:
            return False
        fn = self._fn(_FN_DISP_GET_ADAPTIVE_SYNC_DATA,
                      ctypes.c_uint32, ctypes.c_void_p)
        if fn is None:
            return False
        buf = (ctypes.c_uint8 * _AS_STRUCT_SIZE)()
        ctypes.memset(buf, 0, _AS_STRUCT_SIZE)
        ctypes.c_uint32.from_buffer(buf, 0).value = _AS_GET_VER1
        try:
            ok = fn(did, buf) == NVAPI_OK
        except Exception:
            ok = False
        if ok:
            self._capable_cache[dev_name] = True
        return ok

    # ── DRS global VRR_MODE ────────────────────────────────────────────────
    def _drs_open(self):
        HSession = ctypes.c_void_p
        HProfile = ctypes.c_void_p
        create = self._fn(_FN_DRS_CREATE_SESSION,   ctypes.POINTER(HSession))
        load   = self._fn(_FN_DRS_LOAD_SETTINGS,    HSession)
        base   = self._fn(_FN_DRS_GET_BASE_PROFILE, HSession, ctypes.POINTER(HProfile))
        if not all((create, load, base)):
            return None
        h = HSession()
        if create(ctypes.byref(h)) != NVAPI_OK: return None
        if load(h)                  != NVAPI_OK: self._drs_close(h); return None
        prof = HProfile()
        if base(h, ctypes.byref(prof)) != NVAPI_OK:
            self._drs_close(h); return None
        return (h, prof)

    def _drs_close(self, h):
        destroy = self._fn(_FN_DRS_DESTROY_SESSION, ctypes.c_void_p)
        if destroy is not None:
            try: destroy(h)
            except Exception: pass

    def get_global_mode(self) -> Optional[int]:
        """Returns the current VRR_MODE_* value, or None if unreadable."""
        if not self._available:
            return None
        opened = self._drs_open()
        if opened is None:
            return None
        h, prof = opened
        try:
            getset = self._fn(_FN_DRS_GET_SETTING,
                              ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.c_uint32, ctypes.POINTER(_NVDRS_SETTING))
            if getset is None:
                return None
            s = _NVDRS_SETTING(); s.version = _NVDRS_SETTING_VER
            rc = getset(h, prof, VRR_MODE_ID, ctypes.byref(s))
            if rc == NVAPI_OK:
                return int(s.u32Value)
            if rc == NVAPI_SETTING_NOT_FOUND:
                return VRR_MODE_FULLSCREEN_ONLY  # NVCP default
            _log(f"DRS_GetSetting(VRR_MODE) rc={rc}")
            return None
        finally:
            self._drs_close(h)

    def set_global_mode(self, mode: int) -> bool:
        """Sets VRR_MODE to one of the VRR_MODE_* constants. Persistent."""
        if not self._available:
            return False
        opened = self._drs_open()
        if opened is None:
            return False
        h, prof = opened
        try:
            setset = self._fn(_FN_DRS_SET_SETTING,
                              ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(_NVDRS_SETTING))
            save   = self._fn(_FN_DRS_SAVE_SETTINGS, ctypes.c_void_p)
            if setset is None or save is None:
                return False
            s = _NVDRS_SETTING()
            s.version         = _NVDRS_SETTING_VER
            s.settingId       = VRR_MODE_ID
            s.settingType     = 0  # NVDRS_DWORD_TYPE
            s.settingLocation = 0  # NVDRS_CURRENT_PROFILE_LOCATION
            s.u32Value        = int(mode)
            if setset(h, prof, ctypes.byref(s)) != NVAPI_OK:
                _log(f"DRS_SetSetting(VRR_MODE={mode}) failed")
                return False
            if save(h) != NVAPI_OK:
                _log("DRS_SaveSettings failed"); return False
            _log(f"VRR_MODE -> {mode}")
            return True
        finally:
            self._drs_close(h)

    # ── public API consumed by overlay.py ──────────────────────────────────
    def is_global_enabled(self) -> Optional[bool]:
        """True if VRR_MODE != 0; None on read failure."""
        m = self.get_global_mode()
        return None if m is None else (m != VRR_MODE_DISABLED)

    def set_global_enabled(self, on: bool) -> bool:
        """Toggle global G-Sync. ON -> FULLSCREEN_AND_WINDOWED; OFF -> 0."""
        return self.set_global_mode(
            VRR_MODE_FULLSCREEN_AND_WINDOWED if on else VRR_MODE_DISABLED)
