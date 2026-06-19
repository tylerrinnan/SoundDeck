"""Registry behaviour, incl. snapshot() — the profile full-state capture path.

Uses stub capabilities so the test stays COM-free and deterministic.
"""
import pytest

from caps.base import Capability, Registry


class _Stub(Capability):
    def __init__(self, name, avail=True, current=None, raise_on_current=False):
        self.name = name
        self.label = name
        self._avail = avail
        self._current = current
        self._raise = raise_on_current
        self.applied = None

    def available(self):
        return self._avail

    def current(self):
        if self._raise:
            raise RuntimeError("boom")
        return self._current

    def apply(self, state):
        self.applied = state
        return True


def test_register_requires_name():
    r = Registry()
    with pytest.raises(ValueError):
        r.register(_Stub(""))


def test_get_and_all():
    r = Registry()
    a = _Stub("a")
    r.register(a)
    assert r.get("a") is a
    assert r.get("missing") is None
    assert set(r.all()) == {"a"}


def test_availability_map():
    r = Registry()
    r.register(_Stub("on", avail=True))
    r.register(_Stub("off", avail=False))
    assert r.availability() == {"on": True, "off": False}


def test_snapshot_collects_available_with_state():
    r = Registry()
    r.register(_Stub("audio.output", current={"device_id": "o"}))
    r.register(_Stub("display.refresh", current={"hz": 144}))
    snap = r.snapshot()
    assert snap == {"audio.output": {"device_id": "o"},
                    "display.refresh": {"hz": 144}}


def test_snapshot_skips_unavailable_none_and_raising():
    r = Registry()
    r.register(_Stub("ok", current={"x": 1}))
    r.register(_Stub("unavail", avail=False, current={"x": 2}))
    r.register(_Stub("no_state", current=None))
    r.register(_Stub("broken", raise_on_current=True))
    assert r.snapshot() == {"ok": {"x": 1}}
