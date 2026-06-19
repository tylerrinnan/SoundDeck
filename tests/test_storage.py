"""Durability/atomicity guarantees of storage.atomic_write_json / read_json."""
import json
from pathlib import Path

import storage


def _bak(p: Path) -> Path:
    return Path(str(p) + ".bak")


def test_round_trip(tmp_path):
    p = tmp_path / "data.json"
    payload = {"a": 1, "b": [1, 2, 3], "c": "x"}
    storage.atomic_write_json(p, payload)
    assert storage.read_json(p) == payload


def test_missing_returns_none(tmp_path):
    assert storage.read_json(tmp_path / "absent.json") is None


def test_creates_parent_dirs(tmp_path):
    p = tmp_path / "nested" / "deep" / "data.json"
    storage.atomic_write_json(p, {"v": 1})
    assert storage.read_json(p) == {"v": 1}


def test_bak_holds_previous_version(tmp_path):
    p = tmp_path / "data.json"
    storage.atomic_write_json(p, {"v": 1})
    storage.atomic_write_json(p, {"v": 2})
    assert _bak(p).exists()
    assert json.loads(_bak(p).read_text(encoding="utf-8")) == {"v": 1}
    assert storage.read_json(p) == {"v": 2}


def test_corrupt_primary_falls_back_to_bak(tmp_path):
    p = tmp_path / "data.json"
    storage.atomic_write_json(p, {"v": 1})
    storage.atomic_write_json(p, {"v": 2})       # bak == {"v": 1}
    p.write_text("{ truncated", encoding="utf-8")  # simulate power-loss mid-write
    assert storage.read_json(p) == {"v": 1}       # transparent recovery from bak


def test_corrupt_primary_never_clobbers_good_bak(tmp_path):
    p = tmp_path / "data.json"
    storage.atomic_write_json(p, {"v": 1})        # primary v1, no bak yet
    storage.atomic_write_json(p, {"v": 2})        # bak v1, primary v2
    p.write_text("CORRUPT", encoding="utf-8")     # primary now junk
    storage.atomic_write_json(p, {"v": 3})        # must NOT rotate junk into bak
    assert json.loads(_bak(p).read_text(encoding="utf-8")) == {"v": 1}
    assert storage.read_json(p) == {"v": 3}
