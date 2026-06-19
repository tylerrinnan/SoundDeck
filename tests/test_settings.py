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


def _boom(*_a, **_k):
    raise OSError("simulated disk error")


def test_load_survives_read_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "read_json", _boom)
    s = settings.SettingsManager()                 # must not raise
    assert s.get("hotkey") == "ctrl+shift+a"       # falls back to defaults


def test_save_survives_write_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    s = settings.SettingsManager()
    monkeypatch.setattr(settings, "atomic_write_json", _boom)
    s.set("overlay_width", 999)                    # error is swallowed
    assert s.get("overlay_width") == 999           # in-memory value still updated


def test_nested_batch_flushes_once_on_outermost_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    s = settings.SettingsManager()
    writes = {"n": 0}
    real = settings.atomic_write_json

    def counting(path, data):
        writes["n"] += 1
        return real(path, data)

    monkeypatch.setattr(settings, "atomic_write_json", counting)
    with s.batch():
        s.set("overlay_width", 300)
        with s.batch():                            # inner exit: depth 2->1, no flush
            s.set("overlay_opacity", 70)
        assert writes["n"] == 0
    assert writes["n"] == 1                         # single flush at the outermost exit
