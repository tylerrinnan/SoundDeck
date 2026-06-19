"""ProfileManager CRUD, active-profile tracking, persistence, legacy migration."""
import json

import profiles
from mode import make_audio_mode


def _mgr(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES_PATH", tmp_path / "profiles.json")
    return profiles.ProfileManager()


def test_add_then_update_in_place(tmp_path, monkeypatch):
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("A", output_device_id="o1"))
    m.add_or_update(make_audio_mode("A", output_device_id="o2"))
    assert m.get("A").output_device_id == "o2"
    assert len(m.get_profiles()) == 1


def test_persistence_round_trip(tmp_path, monkeypatch):
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("A", output_device_id="o1", refresh_rate=144))
    m.set_active("A")
    reloaded = profiles.ProfileManager()   # same monkeypatched path
    assert [p.name for p in reloaded.get_profiles()] == ["A"]
    assert reloaded.get_active() == "A"
    assert reloaded.get("A").refresh_rate == 144


def test_hotkey_survives_save_load(tmp_path, monkeypatch):
    """A profile's bound hotkey must persist across a process restart — this is
    what the global-hotkey re-registration reads back on next launch."""
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("solo", output_device_id="o1", hotkey="ctrl+shift+1"))
    m.add_or_update(make_audio_mode("friends", output_device_id="o2", hotkey="ctrl+shift+2"))
    reloaded = profiles.ProfileManager()
    assert reloaded.get("solo").hotkey == "ctrl+shift+1"
    assert reloaded.get("friends").hotkey == "ctrl+shift+2"


def test_hotkey_preserved_when_only_audio_caps_updated(tmp_path, monkeypatch):
    """Editing a profile's audio selection in place must not drop its hotkey
    (overlay._update_active_profile mutates audio caps but leaves hotkey)."""
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("solo", output_device_id="o1", hotkey="ctrl+shift+1"))
    prof = m.get("solo")
    prof.output_device_id = "o2"        # simulate a device re-selection
    m.add_or_update(prof)
    assert profiles.ProfileManager().get("solo").hotkey == "ctrl+shift+1"


def test_rename(tmp_path, monkeypatch):
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("A"))
    assert m.rename("A", "B") is True
    assert m.get("A") is None
    assert m.get("B") is not None
    assert m.rename("missing", "X") is False


def test_delete(tmp_path, monkeypatch):
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("A"))
    assert m.delete("A") is True
    assert m.get("A") is None
    assert m.delete("A") is False


def test_get_profiles_returns_copy(tmp_path, monkeypatch):
    m = _mgr(tmp_path, monkeypatch)
    m.add_or_update(make_audio_mode("A"))
    m.get_profiles().clear()              # mutating the copy must not affect state
    assert len(m.get_profiles()) == 1


def test_legacy_flat_list_is_migrated_on_load(tmp_path, monkeypatch):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([
        {"name": "Old", "output_device_id": "o", "output_volume": 0.5, "refresh_rate": 60},
    ]), encoding="utf-8")
    monkeypatch.setattr(profiles, "PROFILES_PATH", path)
    m = profiles.ProfileManager()
    assert m.get("Old").output_device_id == "o"
    assert m.get("Old").refresh_rate == 60
    assert m.get_active() is None   # bare-list legacy shape has no active marker


def test_profile_factory_builds_caps_shaped_mode():
    """The legacy flat Profile(...) factory must yield a caps-shaped Mode."""
    m = profiles.Profile("Game", output_device_id="o1", comms_device_id="m1",
                          output_volume=0.5, refresh_rate=144, hotkey="ctrl+1")
    assert m.name == "Game"
    assert m.hotkey == "ctrl+1"
    assert m.caps["audio.output"] == {"device_id": "o1"}
    assert m.caps["display.refresh"] == {"hz": 144}


def _boom(*_a, **_k):
    raise OSError("simulated disk error")


def test_load_survives_read_error(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES_PATH", tmp_path / "profiles.json")
    monkeypatch.setattr(profiles, "read_json", _boom)
    m = profiles.ProfileManager()              # must not raise
    assert m.get_profiles() == []


def test_save_survives_write_error(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES_PATH", tmp_path / "profiles.json")
    m = profiles.ProfileManager()
    monkeypatch.setattr(profiles, "atomic_write_json", _boom)
    m.add_or_update(make_audio_mode("A", output_device_id="o1"))   # error swallowed
    assert m.get("A") is not None              # in-memory state intact
