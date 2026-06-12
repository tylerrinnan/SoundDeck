"""caps/gsync_global.py — global VRR_MODE via NVAPI DRS."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .base import Capability

if TYPE_CHECKING:
    from gsync import GSyncManager


class GSyncGlobalCap(Capability):
    name  = "gsync.global"
    label = "Global G-Sync"

    def __init__(self, gsync: "GSyncManager") -> None:
        self._gsync = gsync

    def available(self) -> bool:
        try:
            return bool(self._gsync.is_available())
        except Exception:
            return False

    def current(self) -> Optional[dict]:
        try:
            mode = self._gsync.get_global_mode()
        except Exception:
            return None
        return {"mode": int(mode)} if mode is not None else None

    def apply(self, state: dict) -> bool:
        mode = state.get("mode")
        if mode is None:
            return False
        try:
            return bool(self._gsync.set_global_mode(int(mode)))
        except Exception as e:
            print(f"[caps.gsync.global] apply error: {e}")
            return False
