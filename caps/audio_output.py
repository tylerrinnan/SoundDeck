"""caps/audio_output.py — default render endpoint (CONSOLE+MULTIMEDIA roles)."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .base import Capability

if TYPE_CHECKING:
    from audio import AudioManager


class AudioOutputCap(Capability):
    name  = "audio.output"
    label = "Output Device"

    def __init__(self, audio: "AudioManager") -> None:
        self._audio = audio

    def available(self) -> bool:
        return True

    def current(self) -> Optional[dict]:
        try:
            did = self._audio.get_default_output_id()
        except Exception:
            return None
        return {"device_id": did or ""}

    def apply(self, state: dict) -> bool:
        did = state.get("device_id", "")
        if not did:
            return False
        # Guard against profiles holding device IDs that aren't currently
        # plugged in — SetDefaultEndpoint returns S_OK either way, but audio
        # silently doesn't switch and the UI is left showing a ghost active.
        try:
            present = {d.id for d in self._audio.get_playback_devices()}
            if did not in present:
                print(f"[caps.audio.output] device {did!r} not present, skipping")
                return False
        except Exception:
            pass  # if enumeration fails, fall through and let set_output_device try
        try:
            self._audio.set_output_device(did)
            return True
        except Exception as e:
            print(f"[caps.audio.output] apply error: {e}")
            return False
