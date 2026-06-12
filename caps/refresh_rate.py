"""caps/refresh_rate.py — primary display refresh rate."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .base import Capability

if TYPE_CHECKING:
    from display import DisplayManager


class RefreshRateCap(Capability):
    name  = "display.refresh"
    label = "Refresh Rate"

    def __init__(self, display: "DisplayManager") -> None:
        self._display = display

    def available(self) -> bool:
        return True

    def current(self) -> Optional[dict]:
        try:
            hz = self._display.get_current_refresh_rate()
        except Exception:
            return None
        return {"hz": int(hz)} if hz else None

    def apply(self, state: dict) -> bool:
        hz = int(state.get("hz", 0))
        if hz <= 0:
            return False
        try:
            return bool(self._display.set_refresh_rate(hz))
        except Exception as e:
            print(f"[caps.display.refresh] apply error: {e}")
            return False
