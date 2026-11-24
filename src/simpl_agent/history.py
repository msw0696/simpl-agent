"""Edit history kept next to each program, in .simpl-agent/ (SIMPL's archive skips it).

<program folder>/.simpl-agent/<program>.history.jsonl   one JSON line per change
<program folder>/.simpl-agent/backups/                  the file as it was before each change

Every entry stores the file's revision (SHA-256) before and after, so undo and
restore only act when the file is in the state they expect. Handles go stale
after SIMPL saves (it can renumber), so entries also keep names for people.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .smw.save import BACKUP_DIR

UNDOABLE = ("edit", "restore", "undo")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class History:
    program: Path

    @property
    def folder(self) -> Path:
        return self.program.parent / Path(BACKUP_DIR).parent

    @property
    def log_path(self) -> Path:
        return self.folder / f"{self.program.name}.history.jsonl"

    def entries(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        out = []
        for line in self.log_path.read_text("utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # a damaged line never blocks the rest
        return out

    def add(self, **entry: Any) -> dict[str, Any]:
        entries = self.entries()
        entry = {"id": (entries[-1]["id"] + 1) if entries else 1,
                 "time": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def undo_target(self) -> dict[str, Any] | None:
        """The most recent change that hasn't been undone (undos are undone in turn)."""
        undone: set[int] = set()
        for e in reversed(self.entries()):
            if e["id"] in undone:
                continue
            if e.get("kind") == "undo":
                undone.add(e["undoes"])
                continue
            if e.get("kind") in UNDOABLE:
                return e
        return None

    def backup_bytes(self, entry: dict[str, Any]) -> bytes:
        """The file as it was before ``entry``, checked against the stored revision."""
        p = self.folder / entry["backup"]
        data = p.read_bytes()
        if sha256(data) != entry["revision_before"]:
            raise ValueError(f"backup {p.name} doesn't match its recorded revision; refusing to use it")
        return data
