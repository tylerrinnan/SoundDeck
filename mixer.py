"""
mixer.py — Per-app audio session enumeration and volume control.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List

import psutil
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume


@dataclass
class AudioSession:
    pid: int
    name: str
    volume: float   # 0.0–1.0
    muted: bool
    exe_path: str = ""   # full path to the process image, for icon extraction


class MixerManager:
    _CACHE_TTL = 5.0  # seconds — COM pointers are only valid within the same STA

    def __init__(self) -> None:
        # Per-thread cache: each COM pool worker has its own STA, so a
        # cached ISimpleAudioVolume pointer is only valid on the thread
        # that obtained it. Sharing across threads = RPC errors.
        self._iface_local = threading.local()

    def _cache(self) -> dict:
        cache = getattr(self._iface_local, "cache", None)
        if cache is None:
            cache = {}
            self._iface_local.cache = cache
        return cache

    def _enum_all_endpoints(self):
        """Yield (IAudioSessionControl2, _PycawSession) from all active render endpoints."""
        from pycaw.api.audiopolicy import IAudioSessionControl2
        from pycaw.utils import AudioSession as _PycawSession
        from pycaw.constants import EDataFlow

        seen_instance_ids: set = set()
        devices = AudioUtilities.GetAllDevices(
            data_flow=EDataFlow.eRender.value,
            device_state=0x1,
        )
        for dev in devices:
            try:
                enumerator = dev.AudioSessionManager.GetSessionEnumerator()
                for i in range(enumerator.GetCount()):
                    ctl = enumerator.GetSession(i)
                    if ctl is None:
                        continue
                    ctl2 = ctl.QueryInterface(IAudioSessionControl2)
                    if ctl2 is None:
                        continue
                    try:
                        inst_id = ctl2.GetSessionInstanceIdentifier()
                        if inst_id in seen_instance_ids:
                            continue
                        seen_instance_ids.add(inst_id)
                    except Exception:
                        pass
                    yield _PycawSession(ctl2)
            except Exception:
                continue

    def get_sessions(self) -> List[AudioSession]:
        """
        Enumerate active audio sessions from ALL render endpoints.
        Must be called from a thread with CoInitialize().
        """
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        try:
            raw_sessions = list(self._enum_all_endpoints())
        except Exception as e:
            print(f"[mixer] all-endpoint enumeration error: {e}")
            try:
                raw_sessions = AudioUtilities.GetAllSessions()
            except Exception as e2:
                print(f"[mixer] GetAllSessions fallback error: {e2}")
                return []

        seen_pids: set[int] = set()
        result: List[AudioSession] = []
        sys_vol: float | None = None
        sys_muted = False
        name_counts: dict[str, int] = {}

        for s in raw_sessions:
            try:
                iface = s._ctl.QueryInterface(ISimpleAudioVolume)
                vol   = float(iface.GetMasterVolume())
                muted = bool(iface.GetMute())
            except Exception:
                continue

            proc_id: int = s.ProcessId if s.Process is None else s.Process.pid

            if proc_id == 0:
                if sys_vol is None:
                    sys_vol   = vol
                    sys_muted = muted
                continue

            if proc_id in seen_pids:
                continue
            seen_pids.add(proc_id)

            display_name, exe_path = self._process_info(proc_id)
            name_counts[display_name] = name_counts.get(display_name, 0) + 1
            result.append(AudioSession(pid=proc_id, name=display_name, volume=vol,
                                       muted=muted, exe_path=exe_path))

        # Disambiguate duplicate display names by appending PID
        for s in result:
            if name_counts[s.name] > 1:
                s.name = f"{s.name} ({s.pid})"

        if sys_vol is not None:
            result.insert(0, AudioSession(pid=0, name="System",
                                          volume=sys_vol, muted=sys_muted))

        result.sort(key=lambda s: (s.pid != 0, s.name.lower()))
        return result

    @staticmethod
    def _process_info(pid: int) -> tuple[str, str]:
        """Return (display_name, exe_path) for a PID. exe_path is "" if the
        process is gone or its image path is inaccessible."""
        try:
            p = psutil.Process(pid)
            name = p.name().removesuffix(".exe").replace("_", " ").title()
            try:
                exe = p.exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                exe = ""
            return name, exe
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return f"PID {pid}", ""

    def _find_session_iface(self, pid: int):
        """Return ISimpleAudioVolume for the given PID.

        Caches COM pointers for _CACHE_TTL seconds to avoid repeated full
        enumeration during rapid slider adjustments. Cache is per-thread —
        the pointer is only valid on the STA that produced it.
        """
        import time
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        now = time.monotonic()
        cache = self._cache()

        cached = cache.get(pid)
        if cached and (now - cached[0]) < self._CACHE_TTL:
            try:
                cached[1].GetMasterVolume()  # probe — will raise if stale
                return cached[1]
            except Exception:
                del cache[pid]

        try:
            for s in self._enum_all_endpoints():
                proc_id = s.ProcessId if s.Process is None else s.Process.pid
                if proc_id == pid:
                    iface = s._ctl.QueryInterface(ISimpleAudioVolume)
                    cache[pid] = (now, iface)
                    return iface
        except Exception:
            pass

        # Fallback: single default-device enumeration
        try:
            for s in AudioUtilities.GetAllSessions():
                proc_id = s.ProcessId if s.Process is None else s.Process.pid
                if proc_id == pid:
                    iface = s._ctl.QueryInterface(ISimpleAudioVolume)
                    cache[pid] = (now, iface)
                    return iface
        except Exception:
            pass

        return None

    def set_session_volume(self, pid: int, level: float) -> None:
        iface = self._find_session_iface(pid)
        if iface:
            try:
                iface.SetMasterVolume(max(0.0, min(1.0, level)), None)
            except Exception:
                pass

    def set_session_mute(self, pid: int, muted: bool) -> None:
        iface = self._find_session_iface(pid)
        if iface:
            try:
                iface.SetMute(muted, None)
            except Exception:
                pass
