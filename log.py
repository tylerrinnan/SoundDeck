"""
log.py — single logging sink for SoundDeck.

Replaces the per-module hand-rolled loggers (which re-opened the log file on
every call). One `logging.FileHandler` keeps the file open for the process
lifetime; a stdout handler mirrors lines when run from source. All output goes
to the same `sounddeck` logger so audio/gsync/hdr share one file + format.

    from log import log
    log("[audio] something happened")          # plain-string call sites

    from log import get_logger
    _log = get_logger("hdr")                    # stdlib-style child logger
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_PATH = Path.home() / "AppData" / "Roaming" / "SoundDeck" / "sounddeck.log"

_ROOT_NAME = "sounddeck"


def _configure() -> logging.Logger:
    logger = logging.getLogger(_ROOT_NAME)
    if logger.handlers:               # already configured (idempotent on re-import)
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter("%(message)s")
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass                          # disk unavailable — fall through to stdout only
    if sys.stdout is not None:        # None in a --windowed frozen exe; guard it
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


_logger = _configure()


def get_logger(name: str = "") -> logging.Logger:
    """Return the shared logger, or a named child that inherits its handlers."""
    return logging.getLogger(f"{_ROOT_NAME}.{name}") if name else _logger


def log(msg: str) -> None:
    """Append one already-formatted line to the SoundDeck log."""
    _logger.info(msg)
