"""SettingsManager defaults, persistence, unknown-key filtering, and batch()."""
import json

import settings


def _mgr(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    return settings.SettingsManager()


def test_defaults(tmp_path, monkeypatch):
    s = _mgr(tmp_path, monkeypatch)
    assert s.get("hotkey") == "ctrl+shift+a"
    assert s.get("overlay_width") == 370


def test_set_persists(tmp_path, monkeypatch):
    s = _mgr(tmp_path, monkeypatch)
    s.set("overlay_width", 440)
    assert settings.SettingsManager().get("overlay_width") == 440


def test_load_ignores_unknown_keys(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"overlay_width": 500, "bogus": 123}), encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    s = settings.SettingsManager()
    assert s.get("overlay_width") == 500
    assert s.get("bogus") is None


def test_batch_defers_single_write(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    s = settings.SettingsManager()
    with s.batch():
        s.set("overlay_width", 300)
        s.set("overlay_opacity", 80)
        assert not path.exists()        # nothing flushed mid-batch
    assert path.exists()                # one flush on exit
    reloaded = settings.SettingsManager()
    assert reloaded.get("overlay_width") == 300
    assert reloaded.get("overlay_opacity") == 80
