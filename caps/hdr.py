"""caps/hdr.py — HDR per display via DisplayConfig SetAdvancedColorState."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .base import Capability

if TYPE_CHECKING:
    from hdr import HDRManager


class HDRCap(Capability):
    name  = "display.hdr"
    label = "HDR"

    def __init__(self, hdr: "HDRManager") -> None:
        self._hdr = hdr

    def available(self) -> bool:
        try:
            return bool(self._hdr.get_hdr_states())
        except Exception:
            return False

    def current(self) -> Optional[dict]:
        try:
            states = self._hdr.get_hdr_states()
        except Exception:
            return None
        return {"per_display": dict(states)} if states else None

    def apply(self, state: dict) -> bool:
        per = state.get("per_display") or {}
        if not per:
            return False
        any_ok = False
        for dev_name, on in per.items():
            try:
                if self._hdr.set_hdr_state(dev_name, bool(on)):
                    any_ok = True
            except Exception as e:
                print(f"[caps.display.hdr] apply error on {dev_name}: {e}")
        return any_ok
