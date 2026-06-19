"""
caps/base.py — Capability protocol + central registry.

A Capability is a thin adapter over an existing manager (audio, display, hdr,
gsync, …). Each capability has a stable string `name` used as the key in
`Mode.caps` JSON. Apply runs on a COM-initialized worker thread; never call
these on the Qt UI thread.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional


class Capability(ABC):
    name:  str = ""
    label: str = ""

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def current(self) -> Optional[dict]: ...

    @abstractmethod
    def apply(self, state: dict) -> bool: ...


class Registry:
    def __init__(self) -> None:
        self._caps: Dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        if not cap.name:
            raise ValueError("capability missing name")
        self._caps[cap.name] = cap

    def get(self, name: str) -> Optional[Capability]:
        return self._caps.get(name)

    def all(self) -> Dict[str, Capability]:
        return dict(self._caps)

    def availability(self) -> Dict[str, bool]:
        return {n: c.available() for n, c in self._caps.items()}

    def snapshot(self) -> Dict[str, dict]:
        """Capture {name: current_state} for every available capability that has
        a readable current state. Calls into COM / NVAPI — run on a worker
        thread, never the Qt UI thread. A failing capability is skipped, not
        fatal, so one bad driver can't sink the whole snapshot."""
        out: Dict[str, dict] = {}
        for name, cap in self._caps.items():
            try:
                if cap.available():
                    state = cap.current()
                    if state is not None:
                        out[name] = state
            except Exception:
                continue
        return out
