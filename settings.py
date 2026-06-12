"""
settings.py — App-wide settings persistence (not per-profile).
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from storage import atomic_write_json, read_json

SETTINGS_PATH = Path.home() / "AppData" / "Roaming" / "SoundDeck" / "settings.json"


class SettingsManager:
    _DEFAULTS: dict[str, Any] = {
        "hotkey":           "ctrl+shift+a",
        "overlay_width":    370,
        "overlay_theme":    "Violet",
        "overlay_opacity":  93,
        "overlay_position": "Center",
        # Last free-form window location [x, y]; None until the user moves or
        # dismisses the overlay. Takes priority over overlay_position on show.
        "overlay_geometry": None,
    }

    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(self._DEFAULTS)
        self._batch_depth = 0
        self.load()

    def load(self) -> None:
        try:
            raw = read_json(SETTINGS_PATH)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in self._DEFAULTS:
                        self._data[k] = v
        except Exception as e:
            print(f"[settings] load error: {e}")

    def save(self) -> None:
        if self._batch_depth > 0:
            return  # deferred until batch() exits
        try:
            atomic_write_json(SETTINGS_PATH, self._data)
        except Exception as e:
            print(f"[settings] save error: {e}")

    @contextmanager
    def batch(self):
        """Context manager to batch multiple set() calls into one disk write."""
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                self.save()

    def get(self, key: str) -> Any:
        return self._data.get(key, self._DEFAULTS.get(key))

    def set(self, key: str, val: Any) -> None:
        self._data[key] = val
        self.save()
