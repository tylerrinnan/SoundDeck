"""caps/audio_comms.py — default communications capture endpoint."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .base import Capability

if TYPE_CHECKING:
    from audio import AudioManager


class AudioCommsCap(Capability):
    name  = "audio.comms"
    label = "Communications Device"

    def __init__(self, audio: "AudioManager") -> None:
        self._audio = audio

    def available(self) -> bool:
        return True

    def current(self) -> Optional[dict]:
        try:
            did = self._audio.get_default_comms_capture_id()
        except Exception:
            return None
        return {"device_id": did or ""}

    def apply(self, state: dict) -> bool:
        did = state.get("device_id", "")
        if not did:
            return False
        try:
            present = {d.id for d in self._audio.get_recording_devices()}
            if did not in present:
                print(f"[caps.audio.comms] device {did!r} not present, skipping")
                return False
        except Exception:
            pass
        try:
            self._audio.set_comms_capture_device(did)
            return True
        except Exception as e:
            print(f"[caps.audio.comms] apply error: {e}")
            return False
