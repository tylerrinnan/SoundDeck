"""
profiles.py — Named Mode persistence.

Storage format (profiles.json):

    {
      "active": "Gaming" | null,
      "profiles": [
        {
          "name":     str,
          "caps":     { "<cap.name>": { ...state... }, ... },
          "hotkey":   str,
          "triggers": [ {"kind": "process_start", "match": "game.exe"}, ... ]
        },
        ...
      ]
    }

Legacy flat shape (output_device_id / comms_device_id / output_volume /
refresh_rate) is auto-migrated at load time. New writes always emit the caps
shape.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from mode import Mode, make_audio_mode, migrate_flat_dict
from storage import atomic_write_json, read_json

PROFILES_PATH = Path.home() / "AppData" / "Roaming" / "SoundDeck" / "profiles.json"


# Back-compat: existing call sites do `from profiles import Profile` and
# construct via the flat-fields shape. Route those constructions through
# make_audio_mode so storage is consistently caps-shaped.
def Profile(  # noqa: N802 — mimics the old class name
    name:             str,
    output_device_id: str   = "",
    comms_device_id:  str   = "",
    output_volume:    float = 1.0,
    refresh_rate:     int   = 0,
    hotkey:           str   = "",
) -> Mode:
    return make_audio_mode(
        name             = name,
        output_device_id = output_device_id,
        comms_device_id  = comms_device_id,
        output_volume    = output_volume,
        refresh_rate     = refresh_rate,
        hotkey           = hotkey,
    )


class ProfileManager:
    def __init__(self) -> None:
        self._profiles: List[Mode] = []
        self._active_name: Optional[str] = None
        self.load()

    # ── Persistence ───────────────────────────────────────────────────────────
    def load(self) -> None:
        try:
            data = read_json(PROFILES_PATH)
            if data is None:
                return  # no file yet (or both copies gone) — keep current state
            if isinstance(data, list):
                raw_profiles = data
                self._active_name = None
            else:
                raw_profiles = data.get("profiles", [])
                self._active_name = data.get("active")
            self._profiles = [migrate_flat_dict(p) for p in raw_profiles]
        except Exception as e:
            # Don't wipe in-memory state on a transient error — a later save()
            # would otherwise overwrite the on-disk copy with nothing.
            print(f"[profiles] load error: {e}")

    def save(self) -> None:
        try:
            atomic_write_json(
                PROFILES_PATH,
                {"active": self._active_name, "profiles": [asdict(p) for p in self._profiles]},
            )
        except Exception as e:
            print(f"[profiles] save error: {e}")

    # ── Active profile ─────────────────────────────────────────────────────────
    def get_active(self) -> Optional[str]:
        return self._active_name

    def set_active(self, name: Optional[str]) -> None:
        self._active_name = name
        self.save()

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def get_profiles(self) -> List[Mode]:
        return list(self._profiles)

    def get(self, name: str) -> Optional[Mode]:
        for p in self._profiles:
            if p.name == name:
                return p
        return None

    def add_or_update(self, profile: Mode) -> None:
        for i, p in enumerate(self._profiles):
            if p.name == profile.name:
                self._profiles[i] = profile
                self.save()
                return
        self._profiles.append(profile)
        self.save()

    def rename(self, old_name: str, new_name: str) -> bool:
        for p in self._profiles:
            if p.name == old_name:
                p.name = new_name
                self.save()
                return True
        return False

    def delete(self, name: str) -> bool:
        before = len(self._profiles)
        self._profiles = [p for p in self._profiles if p.name != name]
        if len(self._profiles) < before:
            self.save()
            return True
        return False
