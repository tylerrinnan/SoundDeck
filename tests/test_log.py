"""log: the shared sink is configured once and degrades gracefully.

The module configures a process-wide singleton logger at import, so these tests
treat _configure() as idempotent and restore global handler state where they
deliberately poke at it.
"""
import logging

import log


def test_configure_is_idempotent():
    # already configured at import; a second call returns the same logger untouched
    assert log._configure() is log._logger


def test_get_logger_named_is_child_of_root():
    child = log.get_logger("audio")
    assert child.name == "sounddeck.audio"
    assert log.get_logger() is log._logger      # no name -> the shared root logger


def test_log_emits_without_error():
    assert log.log("[test] coverage smoke line") is None   # must not raise


def test_configure_survives_filehandler_failure(monkeypatch):
    """If the log file can't be opened (disk gone), configuration must fall back
    to stdout-only rather than crash."""
    logger = log._logger
    saved = logger.handlers[:]
    logger.handlers.clear()                     # force past the idempotent guard

    def boom(*_a, **_k):
        raise OSError("no disk")

    monkeypatch.setattr(log.logging, "FileHandler", boom)
    try:
        assert log._configure() is logger       # OSError swallowed; still returns the logger
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    finally:
        logger.handlers[:] = saved              # restore real handlers for other tests
