"""
storage.py — Durable, atomic JSON persistence shared by settings.py and
profiles.py.

Why this exists: Path.write_text is neither atomic nor durable. It truncates
the file then writes, and only reaches the OS page cache — Windows flushes
lazily. A sleep/hibernate/power-off can therefore (a) leave a truncated file
mid-write or (b) lose a fully-written-but-unflushed file on resume.

atomic_write_json fixes both: write a temp file in the same directory, flush +
fsync it to the platter, then os.replace it over the target (atomic on NTFS,
same volume). The previous good copy is rotated to "<name>.bak" so there is
always at least one intact copy; read_json transparently falls back to it.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


def _bak_path(path: Path) -> Path:
    return Path(str(path) + ".bak")


def read_json(path: Path) -> Optional[Any]:
    """Load JSON, falling back to the .bak sidecar if the primary is missing or
    corrupt (e.g. truncated by power loss). Returns None only when neither a
    valid primary nor a valid backup exists."""
    for p in (path, _bak_path(path)):
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[storage] {p.name} unreadable ({e}); trying backup")
            continue
    return None


def atomic_write_json(path: Path, data: Any) -> None:
    """Durably write `data` as JSON to `path`.

    temp file -> flush+fsync -> atomic os.replace. The current primary is
    rotated to <name>.bak first, but ONLY if it is itself valid JSON, so a
    corrupt primary can never clobber a good backup.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)

    # Preserve last-known-good as .bak (never overwrite a good backup with junk).
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
            os.replace(path, _bak_path(path))
        except (json.JSONDecodeError, OSError):
            pass

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())          # force bytes to disk before swap
        # os.replace is atomic on NTFS (same volume). Retry briefly to ride out
        # transient locks from AV / Search Indexer touching the file.
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
