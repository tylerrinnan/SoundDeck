"""parse_combo: combo string -> (mods, vk), the contract RegisterHotKey relies on.

Also covers HotkeyManager durability — the desired set must survive transient
RegisterHotKey failures (the resume/boot bug) by retrying via reconcile()."""
from hotkeys import (
    parse_combo, HotkeyManager,
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT,
)


class FakeWin:
    """In-memory stand-in for Win32 RegisterHotKey/UnregisterHotKey.

    `owned` holds (mods, vk) pairs that another app/the shell currently holds —
    registering one fails, modelling the transient conflict seen on resume/boot.
    `lost()` drops every live registration without telling the manager, modelling
    Windows silently clearing the process's hotkeys across a suspend."""

    def __init__(self):
        self.live = {}        # hk_id -> (mods, vk)
        self.owned = set()    # (mods, vk) pairs that fail to register
        self.attempts = []    # every register attempt, for assertions

    def register(self, hk_id, mods, vk):
        self.attempts.append((mods, vk))
        if (mods, vk) in self.owned:
            return False
        self.live[hk_id] = (mods, vk)
        return True

    def unregister(self, hk_id):
        self.live.pop(hk_id, None)

    def lost(self):
        self.live.clear()


def _mgr(win):
    return HotkeyManager(register_fn=win.register, unregister_fn=win.unregister)


def test_ctrl_shift_letter():
    mods, vk = parse_combo("ctrl+shift+a")
    assert mods == MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
    assert vk == ord("A")


def test_function_key():
    mods, vk = parse_combo("alt+f4")
    assert mods == MOD_ALT | MOD_NOREPEAT
    assert vk == 0x73  # VK_F4


def test_win_aliases_collapse_to_same_flag():
    for token in ("win", "windows", "super", "meta"):
        mods, vk = parse_combo(f"{token}+d")
        assert mods == MOD_WIN | MOD_NOREPEAT
        assert vk == ord("D")


def test_digit_and_oem_punctuation():
    assert parse_combo("ctrl+1")[1] == ord("1")
    assert parse_combo("ctrl+,")[1] == 0xBC
    assert parse_combo("ctrl+/")[1] == 0xBF


def test_norepeat_always_set():
    mods, _ = parse_combo("ctrl+a")
    assert mods & MOD_NOREPEAT


def test_case_insensitive():
    assert parse_combo("CTRL+SHIFT+A") == parse_combo("ctrl+shift+a")


def test_unknown_token_returns_none():
    assert parse_combo("ctrl+nope") is None


def test_empty_returns_none():
    assert parse_combo("") is None


def test_modifiers_without_key_returns_none():
    assert parse_combo("ctrl+shift") is None


# ── HotkeyManager durability ──────────────────────────────────────────────────

def test_set_bindings_registers_all_and_dispatch_routes():
    win = FakeWin()
    mgr = _mgr(win)
    fired = []
    failed = mgr.set_bindings([
        ("ctrl+shift+a", lambda: fired.append("main")),
        ("ctrl+shift+1", lambda: fired.append("solo")),
        ("ctrl+shift+2", lambda: fired.append("friends")),
    ])
    assert failed == []
    assert len(win.live) == 3
    assert mgr.has("ctrl+shift+1") and mgr.has("CTRL+SHIFT+2")
    for hk_id in list(win.live):       # every live id dispatches its callback
        mgr.dispatch(hk_id)
    assert sorted(fired) == ["friends", "main", "solo"]


def test_unparseable_combo_is_skipped_not_fatal():
    win = FakeWin()
    mgr = _mgr(win)
    failed = mgr.set_bindings([("ctrl+nope", lambda: None), ("ctrl+shift+a", lambda: None)])
    assert failed == []                 # bad combo skipped, good one still registered
    assert mgr.has("ctrl+shift+a")
    assert len(win.live) == 1


def test_transient_failure_then_reconcile_recovers():
    """A combo owned by another app at first must register once it is released —
    the manager keeps the intent and retries instead of dropping it."""
    win = FakeWin()
    mgr = _mgr(win)
    solo = parse_combo("ctrl+shift+1")  # (mods, vk)
    win.owned.add(solo)
    failed = mgr.set_bindings([
        ("ctrl+shift+a", lambda: None),
        ("ctrl+shift+1", lambda: None),
    ])
    assert failed == ["ctrl+shift+1"]
    assert not mgr.has("ctrl+shift+1")
    assert mgr.pending() == ["ctrl+shift+1"]

    win.owned.discard(solo)             # the conflicting app releases it
    assert mgr.reconcile() == []        # self-heal
    assert mgr.has("ctrl+shift+1")
    assert mgr.pending() == []


def test_reregister_all_uses_desired_not_live_cache():
    """Regression for the resume bug: reregister_all must re-assert the full
    DESIRED set, so a combo that previously failed still recovers. The old
    cache-replay design could never retry a combo missing from the live map."""
    win = FakeWin()
    mgr = _mgr(win)
    friends = parse_combo("ctrl+shift+2")
    win.owned.add(friends)
    mgr.set_bindings([
        ("ctrl+shift+a", lambda: None),
        ("ctrl+shift+2", lambda: None),
    ])
    assert not mgr.has("ctrl+shift+2")  # failed, absent from the live cache

    win.owned.discard(friends)
    assert mgr.reregister_all() == []   # re-derives from desired, not live cache
    assert mgr.has("ctrl+shift+2")


def test_reregister_all_recovers_silent_loss_across_sleep():
    """Windows can drop a process's hotkeys across suspend without notice. The
    resume path drops the live regs and re-asserts the desired set."""
    win = FakeWin()
    mgr = _mgr(win)
    mgr.set_bindings([("ctrl+shift+a", lambda: None), ("ctrl+shift+1", lambda: None)])
    assert len(win.live) == 2

    win.lost()                          # suspend silently clears them
    assert win.live == {}
    mgr.reregister_all()
    assert len(win.live) == 2
    assert mgr.has("ctrl+shift+a") and mgr.has("ctrl+shift+1")


def test_reconcile_is_cheap_noop_when_all_live():
    win = FakeWin()
    mgr = _mgr(win)
    mgr.set_bindings([("ctrl+shift+a", lambda: None)])
    before = len(win.attempts)
    assert mgr.reconcile() == []        # nothing pending
    assert len(win.attempts) == before  # no RegisterHotKey calls made


def test_has_reflects_live_only_not_desired():
    win = FakeWin()
    mgr = _mgr(win)
    win.owned.add(parse_combo("ctrl+shift+1"))
    mgr.set_bindings([("ctrl+shift+1", lambda: None)])
    assert not mgr.has("ctrl+shift+1")  # desired but not live
    assert mgr.pending() == ["ctrl+shift+1"]


def test_clear_unregisters_and_drops_desired():
    win = FakeWin()
    mgr = _mgr(win)
    mgr.set_bindings([("ctrl+shift+a", lambda: None)])
    mgr.clear()
    assert win.live == {}
    assert mgr.pending() == []
    assert mgr.reconcile() == []        # desired set is empty after clear


def test_dispatch_unknown_id_returns_false():
    mgr = _mgr(FakeWin())
    assert mgr.dispatch(999) is False


def test_dispatch_swallows_callback_exception():
    win = FakeWin()
    mgr = _mgr(win)
    def boom():
        raise RuntimeError("nope")
    mgr.set_bindings([("ctrl+shift+a", boom)])
    hk_id = next(iter(win.live))
    assert mgr.dispatch(hk_id) is True   # raised, but reported handled


def test_parse_skips_empty_tokens():
    # a doubled '+' yields an empty token that must be skipped, not rejected
    mods, vk = parse_combo("ctrl++a")
    assert mods == MOD_CONTROL | MOD_NOREPEAT
    assert vk == ord("A")


def test_parse_rejects_unknown_single_char():
    assert parse_combo("ctrl+!") is None   # single char that is neither alnum nor OEM key


def test_set_bindings_skips_empty_combo():
    win = FakeWin()
    mgr = _mgr(win)
    failed = mgr.set_bindings([("", lambda: None), ("ctrl+a", lambda: None)])
    assert failed == []
    assert mgr.has("ctrl+a")
    assert not mgr.has("")
    assert len(win.live) == 1


def test_unregister_errors_are_swallowed():
    """A failing UnregisterHotKey (e.g. Windows already reclaimed the id across a
    suspend) must not abort the resume re-registration path."""
    def ok_register(hk_id, mods, vk):
        return True
    def boom_unregister(hk_id):
        raise RuntimeError("Win32 UnregisterHotKey failed")
    mgr = HotkeyManager(register_fn=ok_register, unregister_fn=boom_unregister)
    mgr.set_bindings([("ctrl+a", lambda: None)])
    failed = mgr.reregister_all()         # drops live regs (raising) then re-adds
    assert failed == []
    assert mgr.has("ctrl+a")
