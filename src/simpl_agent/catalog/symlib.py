"""Reader for SIMPL's symbol library, ``Cresdb\\Programming\\symlib.tio``.

Different syntax from .smw: records are ``[BEGIN]`` ... ``[END]``, lines are
indented, and ``;`` starts a comment. Read from the local install at run time;
no Crestron data is ever copied into this repo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

DEFAULT_SYMLIB = Path(r"C:\Program Files (x86)\Crestron\Cresdb\Programming\symlib.tio")


@dataclass
class LibSymbol:
    code: int
    name: str
    fields: dict[str, str]

    def cues(self, prefix: str) -> dict[int, str]:
        """Pin names, e.g. ``cues("InputCue")`` -> ``{1: "enable", ...}``."""
        out = {}
        for k, v in self.fields.items():
            if k.startswith(prefix) and k[len(prefix):].isdigit():
                out[int(k[len(prefix):])] = v
        return dict(sorted(out.items()))

    @property
    def shares_outputs(self) -> bool:
        """True if several of these may drive one signal (Buffer, panels...).

        Hypothesis: ``SymJam=NonExclusive``. Checked against the corpus in
        docs/format.md; not yet confirmed by Crestron documentation.
        """
        return self.fields.get("SymJam", "").replace("-", "") == "NonExclusive"


@dataclass
class SymbolLibrary:
    symbols: dict[int, LibSymbol] = field(default_factory=dict)
    records: list[dict[str, str]] = field(default_factory=list)

    @cached_property
    def by_name(self) -> dict[str, list[LibSymbol]]:
        out: dict[str, list[LibSymbol]] = {}
        for s in self.symbols.values():
            out.setdefault(s.name.lower(), []).append(s)
        return out

    def get(self, code: int | None) -> LibSymbol | None:
        return self.symbols.get(code) if code is not None else None


def parse_tio(text: str) -> list[dict[str, str]]:
    """Records of a .tio file as dicts (first value wins for repeated keys)."""
    records: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for line in text.splitlines():
        s = line.strip()
        if s == "[BEGIN]":
            cur = {}
        elif s == "[END]":
            if cur is not None:
                records.append(cur)
            cur = None
        elif cur is not None and s and not s.startswith(";"):
            k, sep, v = s.partition("=")
            if sep and k not in cur:
                cur[k] = v
    return records


def load_symlib(path: Path = DEFAULT_SYMLIB) -> SymbolLibrary:
    records = parse_tio(path.read_bytes().decode("latin-1"))
    lib = SymbolLibrary(records=records)
    for r in records:
        if r.get("ObjTp") == "Symbol" and r.get("Code", "").lstrip("-").isdigit():
            code = int(r["Code"])
            lib.symbols[code] = LibSymbol(code=code, name=r.get("Name", ""), fields=r)
    return lib
