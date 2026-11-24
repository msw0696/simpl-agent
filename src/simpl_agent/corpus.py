"""Where the test corpus lives. None of these files are ever copied into the repo."""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

SIMPL_EXTS = {".smw", ".cmc", ".umc"}

# Crestron macros installed with SIMPL (read in place, never copied).
INSTALLED_MODULES = Path(r"C:\Program Files (x86)\Crestron\Cresdb\Modules")
# Public programs downloaded by tools/fetch_github_corpus.py.
GITHUB_CORPUS = Path(os.environ.get("SIMPL_CORPUS", r"C:\Users\matth\simpl-corpus")) / "github"


def iter_files(*roots: Path, exts: set[str] = SIMPL_EXTS) -> Iterator[Path]:
    """All SIMPL files under ``roots``; extensions match case-insensitively."""
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in exts:
                yield p


def default_roots() -> list[Path]:
    return [r for r in (INSTALLED_MODULES, GITHUB_CORPUS) if r.is_dir()]
