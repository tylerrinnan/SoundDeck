"""Durability/atomicity guarantees of storage.atomic_write_json / read_json."""
import json
from pathlib import Path

import pytest

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


def test_write_retries_when_target_is_briefly_locked(tmp_path, monkeypatch):
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"v": 0}), encoding="utf-8")   # valid primary to rotate
    real_replace = storage.os.replace
    swaps = {"n": 0}

    def flaky_replace(src, dst):
        if Path(dst) == p:                # only the tmp->primary swap is contended
            swaps["n"] += 1
            if swaps["n"] < 3:
                raise PermissionError("locked by AV / Search Indexer")
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", flaky_replace)
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)
    storage.atomic_write_json(p, {"v": 1})
    assert storage.read_json(p) == {"v": 1}
    assert swaps["n"] == 3                 # failed twice, succeeded on the third


def test_write_raises_and_cleans_up_after_exhausting_retries(tmp_path, monkeypatch):
    p = tmp_path / "data.json"            # no prior primary -> no .bak rotation

    def always_locked(src, dst):
        raise PermissionError("permanently locked")

    monkeypatch.setattr(storage.os, "replace", always_locked)
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)
    with pytest.raises(PermissionError):
        storage.atomic_write_json(p, {"v": 1})
    assert list(tmp_path.glob("*.tmp")) == []   # temp file removed in finally
