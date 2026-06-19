"""
audio.py — Windows Core Audio device management.
"""

import ctypes
import threading
from dataclasses import dataclass
from typing import Any, List, Optional

# ── comtypes cache fix for PyInstaller frozen exes ────────────────────────────
# comtypes tries to write generated wrapper .py files to disk at import time.
# In a --windowed frozen exe this fails silently and breaks all COM calls.
# Setting gen_dir=None forces in-memory generation instead.
import comtypes.client
comtypes.client.gen_dir = None

import comtypes
from comtypes import GUID, CLSCTX_ALL

from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.constants import CLSID_MMDeviceEnumerator, EDataFlow, DEVICE_STATE

from log import log as _log

# ── Role constants ────────────────────────────────────────────────────────────
E_CONSOLE    = 0
E_MULTIMEDIA = 2
E_COMMS      = 1

# ── IPolicyConfigVista via direct vtable dispatch ─────────────────────────────
# On Windows 11, CoCreateInstance with IID {568B9108...} returns E_NOINTERFACE
# because CPolicyConfigClient no longer advertises that IID via QueryInterface.
# Fix: create as IUnknown (always works) then call vtable slot 13 directly.
#
# Confirmed vtable layout (slots 0-2 = IUnknown, then IPolicyConfigVista):
#   3  GetMixFormat        9  GetShareMode
#   4  GetDeviceFormat    10  SetShareMode
#   5  ResetDeviceFormat  11  GetPropertyValue
#   6  SetDeviceFormat    12  SetPropertyValue
#   7  GetProcessingPeriod 13 SetDefaultEndpoint  ← we only need this
#   8  SetProcessingPeriod 14 SetEndpointVisibility

class _RAWGUID(ctypes.Structure):
    """ctypes GUID struct — separate from comtypes.GUID to avoid conflicts."""
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

_CLSID_PolicyConfig = _RAWGUID(
    0x870AF99C, 0x171D, 0x4F9E,
    (ctypes.c_ubyte * 8)(0xAF, 0x0D, 0xE6, 0x3D, 0xF4, 0x0C, 0x2B, 0xC9),
)
_IID_IUnknown = _RAWGUID(
    0x00000000, 0x0000, 0x0000,
    (ctypes.c_ubyte * 8)(0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46),
)
# IPolicyConfigVista IID — used for QueryInterface after in-process object creation
_IID_PolicyConfigVista = _RAWGUID(
    0x568B9108, 0x44BF, 0x40B4,
    (ctypes.c_ubyte * 8)(0x90, 0x06, 0x86, 0xAF, 0xE5, 0xB5, 0xA6, 0x20),
)
# IPolicyConfig IID — Windows 11 dropped IPolicyConfigVista from QI; this one still works.
# Same vtable layout: SetDefaultEndpoint is at slot 13.
_IID_PolicyConfig = _RAWGUID(
    0xF8679F50, 0x850A, 0x41CF,
    (ctypes.c_ubyte * 8)(0x9C, 0x72, 0x43, 0x0F, 0x29, 0x02, 0x90, 0xC8),
)

_ole32 = ctypes.windll.ole32
# Use c_long (NOT HRESULT) so failure codes are returned as values, not raised.
_ole32.CoCreateInstance.restype = ctypes.c_long
_ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(_RAWGUID),          # rclsid
    ctypes.c_void_p,                   # pUnkOuter
    ctypes.c_ulong,                    # dwClsContext
    ctypes.POINTER(_RAWGUID),          # riid
    ctypes.POINTER(ctypes.c_void_p),   # ppv
]

def _vtable(ptr: ctypes.c_void_p) -> Any:
    """Return the vtable pointer array for a COM object pointer."""
    return ctypes.cast(
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_size_t))[0],
        ctypes.POINTER(ctypes.c_size_t),
    )

def _policy_set_default(device_id: str, role: int) -> int:
    """
    Call CPolicyConfigClient::SetDefaultEndpoint(device_id, role).

    Strategy: try CLSCTX values in order until one creates the object, then
    QI for IPolicyConfigVista and call vtable slot 13 = SetDefaultEndpoint.
    All HRESULT-returning ctypes calls use c_long return type so failures are
    returned as values instead of being auto-raised as OSError.
    """
    pv = ctypes.c_void_p()
    hr = -1
    for clsctx, label in [(1, "INPROC_SERVER"), (4, "LOCAL_SERVER"), (23, "ALL")]:
        hr = _ole32.CoCreateInstance(
            ctypes.byref(_CLSID_PolicyConfig),
            None,
            clsctx,
            ctypes.byref(_IID_IUnknown),
            ctypes.byref(pv),
        )
        _log(f"[audio] CoCreateInstance({label}) hr={hr & 0xFFFFFFFF:#010x}")
        if hr == 0 and pv:
            break

    if hr != 0 or not pv:
        _log("[audio] all CoCreateInstance attempts failed")
        return hr

    unk_vtbl = _vtable(pv)

    # QueryInterface — try IPolicyConfigVista first, then IPolicyConfig (Windows 11).
    # Both interfaces have SetDefaultEndpoint at vtable slot 13.
    # c_long return so E_NOINTERFACE is a value we branch on, not an auto-raised exception.
    qi = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(_RAWGUID),
        ctypes.POINTER(ctypes.c_void_p),
    )(unk_vtbl[0])

    qi_ok = False
    pv2 = ctypes.c_void_p()
    for iid, name in [
        (_IID_PolicyConfigVista, "IPolicyConfigVista"),
        (_IID_PolicyConfig,      "IPolicyConfig"),
    ]:
        pv2 = ctypes.c_void_p()
        hr_qi = qi(pv, ctypes.byref(iid), ctypes.byref(pv2))
        _log(f"[audio] QI({name}) hr={hr_qi & 0xFFFFFFFF:#010x}")
        if hr_qi == 0 and pv2:
            qi_ok = True
            _log(f"[audio] using {name} ptr")
            break

    if not qi_ok:
        _log("[audio] all QI attempts failed, using IUnknown fallback")

    use_ptr = pv2 if qi_ok else pv
    iface_vtbl = _vtable(use_ptr)

    try:
        # c_long return type — prevents auto-raise so we always get a log line.
        fn = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,   # this
            ctypes.c_wchar_p,  # pwstrDeviceId
            ctypes.c_uint,     # ERole
        )(iface_vtbl[13])
        hr2 = fn(use_ptr, device_id, role)
        _log(f"[audio] vtable[13](role={role}) hr={hr2 & 0xFFFFFFFF:#010x}")
        return hr2
    finally:
        if qi_ok:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(_vtable(pv2)[2])(pv2)
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(unk_vtbl[2])(pv)


@dataclass
class AudioDevice:
    id: str
    name: str

    def icon(self) -> str:
        n = self.name.lower()
        if any(w in n for w in ("headphone", "headset", "earphone", "earbuds")):
            return "🎧"
        if "speaker" in n:
            return "🔊"
        if any(w in n for w in ("monitor", "hdmi", "display", " dp")):
            return "🖥️"
        if "tv" in n:
            return "📺"
        if any(w in n for w in ("usb", "digital", "spdif", "optical")):
            return "🎵"
        return "🔈"

    def short_name(self, max_len: int = 28) -> str:
        name = self.name
        for suffix in (
            " (High Definition Audio Device)",
            " (Realtek High Definition Audio)",
            " (NVIDIA High Definition Audio)",
            " (AMD High Definition Audio)",
        ):
            name = name.replace(suffix, "")
        return (name[:max_len - 1] + "...") if len(name) > max_len else name


class AudioManager:

    def __init__(self) -> None:
        # Initialize COM on this thread
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        self._ep_volume_cache: dict = {}  # device_id -> IAudioEndpointVolume
        self._peak_cache: dict = {}  # device_id -> IAudioMeterInformation
        self._peak_fallback: dict = {}  # device_id -> fallback device_id
        self._peak_fallback_probed: dict = {}  # device_id -> bool
        # Per-thread IMMDeviceEnumerator. COM objects are apartment-bound, so
        # each COM-pool worker keeps its own; recreated on demand if a call
        # drops it (e.g. a dead proxy after suspend). Reusing it avoids a
        # CoCreateInstance on every enumeration / default-device lookup.
        self._enum_local = threading.local()
        # Serialize SetDefaultEndpoint across the COM pool — rapid clicks
        # otherwise interleave on three pool threads, producing non-deterministic
        # final default (visible in log as doubled vtable[13] lines).
        self._policy_lock = threading.Lock()

    def _enumerator(self) -> Any:
        """Return this thread's cached IMMDeviceEnumerator, creating it lazily.

        Typed Any: comtypes builds the COM vtable methods (EnumAudioEndpoints,
        GetDefaultAudioEndpoint, GetDevice) dynamically, so static stubs don't
        see them."""
        enum = getattr(self._enum_local, "enum", None)
        if enum is None:
            enum = comtypes.client.CreateObject(
                CLSID_MMDeviceEnumerator, clsctx=CLSCTX_ALL, interface=IMMDeviceEnumerator
            )
            self._enum_local.enum = enum
        return enum

    def _drop_enumerator(self) -> None:
        """Discard this thread's cached enumerator so the next call rebuilds it.
        Called after any failure that may indicate a stale COM proxy."""
        self._enum_local.enum = None

    def _active_render_devices(self):
        # Enumerate render-only IDs via direct COM call (reliable across pycaw versions),
        # then filter AudioUtilities results so capture devices never appear.
        try:
            col = self._enumerator().EnumAudioEndpoints(
                EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
            render_ids = {col.Item(i).GetId() for i in range(col.GetCount())}
        except Exception as e:
            self._drop_enumerator()
            _log(f"[audio] _active_render_devices enumeration error: {e}")
            render_ids = None

        all_devs = AudioUtilities.GetAllDevices()
        if render_ids is None:
            return all_devs
        return [d for d in all_devs if d.id in render_ids]

    def _active_capture_devices(self):
        try:
            col = self._enumerator().EnumAudioEndpoints(
                EDataFlow.eCapture.value, DEVICE_STATE.ACTIVE.value)
            count = col.GetCount()
            capture_ids = {col.Item(i).GetId() for i in range(count)}
        except Exception as e:
            self._drop_enumerator()
            _log(f"[audio] _active_capture_devices enumeration error: {e}")
            return []

        result = []
        for dev in AudioUtilities.GetAllDevices():
            if dev.id in capture_ids:
                result.append(AudioDevice(id=dev.id, name=dev.FriendlyName or dev.id))
        if not result:
            # Fallback: pycaw didn't return these IDs — use the already-enumerated collection
            try:
                for i in range(count):
                    idev = col.Item(i)
                    dev_id = idev.GetId()
                    result.append(AudioDevice(id=dev_id, name=dev_id))
            except Exception as e2:
                _log(f"[audio] _active_capture_devices fallback error: {e2}")
        _log(f"[audio] found {len(result)} capture device(s): {[d.name for d in result]}")
        return result

    def get_playback_devices(self) -> List[AudioDevice]:
        result: List[AudioDevice] = []
        try:
            for dev in self._active_render_devices():
                name = dev.FriendlyName or dev.id
                result.append(AudioDevice(id=dev.id, name=name))
            _log(f"[audio] found {len(result)} playback device(s): {[d.name for d in result]}")
        except Exception as e:
            _log(f"[audio] enumerate error: {e}")
        return result

    def get_recording_devices(self) -> List[AudioDevice]:
        return self._active_capture_devices()

    def get_default_output_id(self) -> Optional[str]:
        return self._get_default_id(EDataFlow.eRender.value, E_CONSOLE)

    def get_default_comms_capture_id(self) -> Optional[str]:
        return self._get_default_id(EDataFlow.eCapture.value, E_COMMS)

    def _get_default_id(self, flow: int, role: int) -> Optional[str]:
        try:
            return self._enumerator().GetDefaultAudioEndpoint(flow, role).GetId()
        except Exception as e:
            self._drop_enumerator()
            _log(f"[audio] get_default_id(flow={flow}, role={role}) error: {e}")
            return None

    def set_output_device(self, device_id: str) -> None:
        _log(f"[audio] set_output_device: {device_id}")
        with self._policy_lock:
            try:
                for role in (E_CONSOLE, E_MULTIMEDIA):
                    hr = _policy_set_default(device_id, role)
                    _log(f"[audio] SetDefaultEndpoint(role={role}) hr={hr:#010x}")
            except Exception as e:
                _log(f"[audio] set_output_device error: {e}")
                import traceback
                _log(traceback.format_exc())
                return
        # Verify outside the lock so we don't block other waiters. If Windows
        # accepted the call but the audio engine is stuck (a known post-suspend
        # state on some drivers), this is the only signal we get.
        actual = self.get_default_output_id()
        if actual and actual != device_id:
            _log(f"[audio] WARN set_output_device: accepted but actual default still {actual!r}")

    def set_comms_capture_device(self, device_id: str) -> None:
        _log(f"[audio] set_comms_capture_device: {device_id}")
        with self._policy_lock:
            try:
                hr = _policy_set_default(device_id, E_COMMS)
                _log(f"[audio] SetDefaultEndpoint(comms capture) hr={hr:#010x}")
            except Exception as e:
                _log(f"[audio] set_comms_capture_device error: {e}")
                import traceback
                _log(traceback.format_exc())
                return
        actual = self.get_default_comms_capture_id()
        if actual and actual != device_id:
            _log(f"[audio] WARN set_comms_capture_device: accepted but actual still {actual!r}")

    def get_volume(self, device_id: str) -> float:
        try:
            ep = self._get_endpoint_volume(device_id)
            if ep:
                return float(ep.GetMasterVolumeLevelScalar())
        except Exception as e:
            _log(f"[audio] get_volume error: {e}")
            self._ep_volume_cache.pop(device_id, None)
        return 1.0

    def _get_endpoint_volume(self, device_id: str):
        """Get IAudioEndpointVolume via cache or direct COM device lookup."""
        if device_id in self._ep_volume_cache:
            return self._ep_volume_cache[device_id]
        # Direct lookup by device ID — avoids enumerating all devices.
        # Failures here are expected during the brief window an _active_*_id
        # has drifted past a removed device; logging would flood at 80 ms poll.
        try:
            dev = self._enumerator().GetDevice(device_id)
            ep = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol_iface = ep.QueryInterface(IAudioEndpointVolume)
            self._ep_volume_cache[device_id] = vol_iface
            return vol_iface
        except Exception:
            self._drop_enumerator()
        # Fallback: enumerate all devices
        try:
            for dev in self._active_render_devices():
                if dev.id == device_id:
                    self._ep_volume_cache[device_id] = dev.EndpointVolume
                    return dev.EndpointVolume
        except Exception:
            pass
        return None

    def invalidate_volume_cache(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._ep_volume_cache.clear()
            self._peak_cache.clear()
            self._peak_fallback.clear()
            self._peak_fallback_probed.clear()
        else:
            self._ep_volume_cache.pop(device_id, None)
            self._peak_cache.pop(device_id, None)
            self._peak_fallback.pop(device_id, None)
            self._peak_fallback_probed.pop(device_id, None)

    def set_volume(self, device_id: str, level: float) -> None:
        level = max(0.0, min(1.0, level))
        try:
            ep = self._get_endpoint_volume(device_id)
            if ep:
                ep.SetMasterVolumeLevelScalar(level, None)
        except Exception as e:
            _log(f"[audio] set_volume error: {e}")
            self._ep_volume_cache.pop(device_id, None)

    def get_mute(self, device_id: str) -> bool:
        try:
            ep = self._get_endpoint_volume(device_id)
            if ep:
                return bool(ep.GetMute())
        except Exception as e:
            _log(f"[audio] get_mute error: {e}")
            self._ep_volume_cache.pop(device_id, None)
        return False

    def set_mute(self, device_id: str, muted: bool) -> None:
        try:
            ep = self._get_endpoint_volume(device_id)
            if ep:
                ep.SetMute(bool(muted), None)
        except Exception as e:
            _log(f"[audio] set_mute error: {e}")
            self._ep_volume_cache.pop(device_id, None)

    def get_peak_level(self, device_id: str) -> float:
        try:
            meter = self._get_peak_meter(device_id)
            if meter:
                return float(meter.GetPeakValue())
        except Exception:
            self._peak_cache.pop(device_id, None)
        return 0.0

    def get_output_peak(self, device_id: str) -> float:
        """Get peak for output device, falling back to scanning all render endpoints."""
        val = self.get_peak_level(device_id)
        if val > 0.0:
            return val
        # Endpoint meter broken (e.g. SteelSeries Sonar) — use fallback
        fallback_id = self._peak_fallback.get(device_id)
        if fallback_id:
            return self.get_peak_level(fallback_id)
        # Throttle probing: only scan every 25 calls (~2s at 80ms interval)
        count = self._peak_fallback_probed.get(device_id, 0)
        self._peak_fallback_probed[device_id] = count + 1
        if count % 25 != 0:
            return 0.0
        try:
            col = self._enumerator().EnumAudioEndpoints(
                EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
            for i in range(col.GetCount()):
                dev = col.Item(i)
                did = dev.GetId()
                if did == device_id:
                    continue
                try:
                    ep = dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
                    meter = ep.QueryInterface(IAudioMeterInformation)
                    peak = float(meter.GetPeakValue())
                    if peak > 0.0:
                        self._peak_cache[did] = meter
                        self._peak_fallback[device_id] = did
                        return peak
                except Exception:
                    continue
        except Exception:
            self._drop_enumerator()
        return 0.0

    def _get_peak_meter(self, device_id: str):
        if device_id in self._peak_cache:
            return self._peak_cache[device_id]
        try:
            dev = self._enumerator().GetDevice(device_id)
            ep = dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
            meter = ep.QueryInterface(IAudioMeterInformation)
            self._peak_cache[device_id] = meter
            return meter
        except Exception:
            # Silent — polled at 80 ms; would flood the log when active_*_id
            # briefly references a removed/post-suspend device.
            self._drop_enumerator()
        return None
