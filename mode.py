"""
mode.py — Mode dataclass: a named, persistable bundle of capability states.

A Mode replaces the old flat Profile. Each entry in `caps` is one capability's
serialized state, keyed by Capability.name. Missing key = "do not touch on
apply" (replaces the old refresh_rate=0 sentinel).

Back-compat property views expose the old flat audio/refresh fields so the
existing overlay.py call sites keep working unchanged.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Mode:
    name:     str
    caps:     Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hotkey:   str        = ""
    triggers: List[Dict]  = field(default_factory=list)

    # ── Back-compat flat-field views ──────────────────────────────────────
    @property
    def output_device_id(self) -> str:
        return self.caps.get("audio.output", {}).get("device_id", "")

    @property
    def comms_device_id(self) -> str:
        return self.caps.get("audio.comms", {}).get("device_id", "")

    @property
    def output_volume(self) -> float:
        return float(self.caps.get("audio.volume", {}).get("level", 1.0))

    @property
    def refresh_rate(self) -> int:
        return int(self.caps.get("display.refresh", {}).get("hz", 0))

    @refresh_rate.setter
    def refresh_rate(self, hz: int) -> None:
        if hz:
            self.caps["display.refresh"] = {"hz": int(hz)}
        else:
            self.caps.pop("display.refresh", None)


def make_audio_mode(
    name:             str,
    output_device_id: str   = "",
    comms_device_id:  str   = "",
    output_volume:    float = 1.0,
    refresh_rate:     int   = 0,
    hotkey:           str   = "",
) -> Mode:
    """Build a Mode from the legacy flat audio fields. Used by overlay.py call
    sites that still construct via the old shape — keep until widgets.py grows
    a real ModeEditorDialog."""
    caps: Dict[str, Dict[str, Any]] = {}
    if output_device_id:
        caps["audio.output"] = {"device_id": output_device_id}
    if comms_device_id:
        caps["audio.comms"] = {"device_id": comms_device_id}
    caps["audio.volume"] = {"device_id": output_device_id, "level": float(output_volume)}
    if refresh_rate:
        caps["display.refresh"] = {"hz": int(refresh_rate)}
    return Mode(name=name, caps=caps, hotkey=hotkey)


def migrate_flat_dict(p: dict) -> Mode:
    """Convert a legacy flat profile dict (output_device_id/comms_device_id/
    output_volume/refresh_rate/hotkey) to a Mode. Idempotent on new shape."""
    if "caps" in p:
        return Mode(
            name     = p.get("name", ""),
            caps     = dict(p.get("caps") or {}),
            hotkey   = p.get("hotkey", ""),
            triggers = list(p.get("triggers") or []),
        )
    return make_audio_mode(
        name             = p.get("name", ""),
        output_device_id = p.get("output_device_id", ""),
        comms_device_id  = p.get("comms_device_id", ""),
        output_volume    = float(p.get("output_volume", 1.0)),
        refresh_rate     = int(p.get("refresh_rate", 0)),
        hotkey           = p.get("hotkey", ""),
    )
