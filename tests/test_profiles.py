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
