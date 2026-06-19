"""
caps — capability registry for SoundDeck Mode framework.

Build the registry once at startup with the live managers; pass the resulting
Registry to OverlayWindow. Adding a new capability = new module + one line in
build_default_registry().
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from .base import Capability, Registry
from .audio_output  import AudioOutputCap
from .audio_comms   import AudioCommsCap
from .audio_volume  import AudioVolumeCap
from .refresh_rate  import RefreshRateCap
from .gsync_global  import GSyncGlobalCap
from .hdr           import HDRCap

if TYPE_CHECKING:
    from audio   import AudioManager
    from display import DisplayManager
    from hdr     import HDRManager
    from gsync   import GSyncManager


def build_default_registry(
    audio:   "AudioManager",
    display: "DisplayManager",
    hdr:     "HDRManager",
    gsync:   "GSyncManager",
) -> Registry:
    r = Registry()
    r.register(AudioOutputCap(audio))
    r.register(AudioCommsCap(audio))
    r.register(AudioVolumeCap(audio))
    r.register(RefreshRateCap(display))
    r.register(GSyncGlobalCap(gsync))
    r.register(HDRCap(hdr))
    return r


__all__ = ["Capability", "Registry", "build_default_registry"]
