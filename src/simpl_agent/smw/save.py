"""Write a program to disk safely: back up first, write atomically."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .rawfile import RawFile

BACKUP_DIR = ".simpl-agent/backups"


def backup(path: Path) -> Path | None:
    """Copy ``path`` into ``.simpl-agent/backups`` next to it. Returns the copy's path."""
    path = Path(path)
    if not path.exists():
        return None
    folder = path.parent / BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{path.stem}.{stamp}{path.suffix}"
    n = 1
    while dest.exists():
        dest = folder / f"{path.stem}.{stamp}-{n}{path.suffix}"
        n += 1
    shutil.copy2(path, dest)
    return dest


def write(raw: RawFile, path: Path, *, make_backup: bool = True) -> Path | None:
    """Write ``raw`` to ``path``. Backs up an existing file first; returns the backup path."""
    path = Path(path)
    saved = backup(path) if make_backup else None
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(raw.to_bytes())
    os.replace(tmp, path)
    return saved
