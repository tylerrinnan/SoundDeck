"""Mode caps shape, back-compat views, and legacy-flat migration."""
from mode import make_audio_mode, migrate_flat_dict


def test_make_audio_mode_caps_shape():
    m = make_audio_mode("Game", output_device_id="out1", comms_device_id="mic1",
                        output_volume=0.5, refresh_rate=144, hotkey="ctrl+1")
    assert m.name == "Game"
    assert m.hotkey == "ctrl+1"
    assert m.caps["audio.output"] == {"device_id": "out1"}
    assert m.caps["audio.comms"] == {"device_id": "mic1"}
    assert m.caps["audio.volume"] == {"device_id": "out1", "level": 0.5}
    assert m.caps["display.refresh"] == {"hz": 144}


def test_make_audio_mode_omits_empty_optionals():
    m = make_audio_mode("X")
    assert "audio.output" not in m.caps
    assert "audio.comms" not in m.caps
    assert "display.refresh" not in m.caps
    # volume cap is always present (it stores the level even at default)
    assert m.caps["audio.volume"] == {"device_id": "", "level": 1.0}


def test_backcompat_property_views():
    m = make_audio_mode("Y", output_device_id="o", comms_device_id="c",
                        output_volume=0.25, refresh_rate=60)
    assert m.output_device_id == "o"
    assert m.comms_device_id == "c"
    assert m.output_volume == 0.25
    assert m.refresh_rate == 60


def test_refresh_rate_setter_sets_and_clears():
    m = make_audio_mode("Z")
    m.refresh_rate = 120
    assert m.caps["display.refresh"] == {"hz": 120}
    m.refresh_rate = 0  # 0 = "do not touch" sentinel -> cap removed
    assert "display.refresh" not in m.caps


def test_migrate_legacy_flat_dict():
    flat = {"name": "Old", "output_device_id": "o", "comms_device_id": "c",
            "output_volume": 0.5, "refresh_rate": 144, "hotkey": "alt+2"}
    m = migrate_flat_dict(flat)
    assert m.name == "Old"
    assert m.hotkey == "alt+2"
    assert m.output_device_id == "o"
    assert m.comms_device_id == "c"
    assert m.refresh_rate == 144


def test_audio_setters_preserve_sibling_caps():
    # A mode carrying display/gsync caps must keep them when an audio field
    # is edited — this is the regression the merge fix guards against.
    m = make_audio_mode("P", output_device_id="o1", refresh_rate=144)
    m.caps["display.hdr"] = {"per_display": {r"\\.\DISPLAY1": True}}
    m.caps["gsync.global"] = {"mode": 2}

    m.output_device_id = "o2"
    m.comms_device_id = "c2"
    m.output_volume = 0.3

    assert m.output_device_id == "o2"
    assert m.comms_device_id == "c2"
    assert m.output_volume == 0.3
    assert m.caps["audio.volume"] == {"device_id": "o2", "level": 0.3}
    # siblings survived
    assert m.caps["display.hdr"] == {"per_display": {r"\\.\DISPLAY1": True}}
    assert m.caps["gsync.global"] == {"mode": 2}
    assert m.refresh_rate == 144


def test_clearing_audio_field_removes_only_its_cap():
    m = make_audio_mode("Q", output_device_id="o", comms_device_id="c")
    m.comms_device_id = ""
    assert "audio.comms" not in m.caps
    assert m.caps["audio.output"] == {"device_id": "o"}


def test_clearing_output_device_removes_its_cap():
    m = make_audio_mode("R", output_device_id="o1", comms_device_id="c1")
    m.output_device_id = ""             # falsy -> drop the output cap entirely
    assert "audio.output" not in m.caps
    assert m.caps["audio.comms"] == {"device_id": "c1"}


def test_migrate_is_idempotent_on_caps_shape():
    already = {"name": "New", "caps": {"audio.output": {"device_id": "o"}},
               "hotkey": "x", "triggers": [{"kind": "k"}]}
    m = migrate_flat_dict(already)
    assert m.caps == {"audio.output": {"device_id": "o"}}
    assert m.output_device_id == "o"
    assert m.hotkey == "x"
    assert m.triggers == [{"kind": "k"}]
