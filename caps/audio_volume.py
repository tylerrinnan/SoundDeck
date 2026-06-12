"""caps/audio_volume.py — master volume on a specific render endpoint.

State is keyed by device_id because volume is per-device. If device_id is
empty, falls back to the current default render endpoint at apply-time.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .base import Capability

if TYPE_CHECKING:
    from audio import AudioManager


class AudioVolumeCap(Capability):
    name  = "audio.volume"
    label = "Output Volume"

    def __init__(self, audio: "AudioManager") -> None:
        self._audio = audio

    def available(self) -> bool:
        return True

    def current(self) -> Optional[dict]:
        try:
            did = self._audio.get_default_output_id() or ""
            level = self._audio.get_volume(did) if did else 1.0
        except Exception:
            return None
        return {"device_id": did, "level": float(level)}

    def apply(self, state: dict) -> bool:
        level = float(state.get("level", 1.0))
        did = state.get("device_id", "")
        if not did:
            try:
                did = self._audio.get_default_output_id() or ""
            except Exception:
                did = ""
        if not did:
            return False
        try:
            self._audio.set_volume(did, max(0.0, min(1.0, level)))
            return True
        except Exception as e:
            print(f"[caps.audio.volume] apply error: {e}")
            return False
