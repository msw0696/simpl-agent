"""A slim, cached index of SIMPL's symbol library.

Parsing the full symlib.tio takes ~9 s and ~450 MB, too much for every server
start. The index keeps only what the tools need (names, pin names and types,
pin-count rules, a few flags) and is cached as JSON under %LOCALAPPDATA%,
keyed on the library file's size and modification time. The cache is built
from the local SIMPL install and never leaves this PC (it's Crestron data).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .symlib import DEFAULT_SYMLIB, LibSymbol, SymbolLibrary, parse_tio

INDEX_VERSION = 6
KEEP_FIELDS = {
    "Name", "Code", "Hint", "ObjVer", "Smpl-C", "DeviceCode", "SymbolTree", "ProgramTree",
    "NumFixedInputs", "NumFixedOutputs", "NumFixedParams",
    "MinVariableInputs", "MaxVariableInputs", "MinVariableOutputs", "MaxVariableOutputs",
    "MaxVariableParams", "Expand", "OffsetOutputs", "FixedInputPosition", "SymJam",
    "CDSReleaseStatus", "HelpID", "Expand_by", "MinVariableParams", "CheckCnx",
}
KEEP_PREFIXES = ("InputCue", "OutputCue", "ParamCue", "InputSigType", "OutputSigType", "ParamSigType", "DefVal",
                 "MinVariableInputsList", "MinVariableOutputsList",
                 # every pin type of lists 2 and 3, so device pins get their list's type (~0.7 MB)
                 "InputList2SigType", "OutputList2SigType", "InputList3SigType", "OutputList3SigType")
# Device symbols (device_edit.symbol_counts) need to know which pin lists exist; the first
# name of each list is enough (all of them would add ~50 MB).
# ... and the first 8 names and types of each list, so device pins can be wired by name (TX$, RX$ ...).
LIST_FIRST_CUES = {f"{d}List{n}{kind}{i}" for d in ("Input", "Output") for n in (2, 3)
                   for kind in ("Cue", "SigType") for i in range(1, 9)}
LIST2_RE = re.compile(r"^(InputList2|OutputList2|InputList3|OutputList3)")


def cache_dir() -> Path:
    base = os.environ.get("SIMPL_AGENT_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "SimplAgent"
    )
    return Path(base)


def _slim(rec: dict[str, str]) -> dict[str, str]:
    out = {k: v for k, v in rec.items() if k in KEEP_FIELDS or k in LIST_FIRST_CUES or k.startswith(KEEP_PREFIXES)}
    if any(LIST2_RE.match(k) for k in rec):
        out["HasExtraPinLists"] = "True"
    return out


@dataclass
class LibraryIndex:
    source: str
    library: SymbolLibrary
    trees: dict[int, str]  # SymbolTree code -> folder name in SIMPL's Symbol Library pane

    def search(self, query: str, limit: int = 20) -> list[LibSymbol]:
        q = query.lower().strip()
        words = q.split()
        scored = []
        for s in self.library.symbols.values():
            name = s.name.lower()
            hint = s.fields.get("Hint", "").lower()
            if not all(w in name or w in hint for w in words):
                continue
            rank = 0 if name == q else 1 if name.startswith(q) else 2 if q in name else 3
            scored.append((rank, len(name), s.name, s))
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored[:limit]]


def build_index(path: Path = DEFAULT_SYMLIB) -> dict:
    records = parse_tio(path.read_bytes().decode("latin-1"))
    symbols = {}
    trees = {}
    for r in records:
        t = r.get("ObjTp")
        code = r.get("Code", "")
        if t == "Symbol" and code.lstrip("-").isdigit():
            symbols[code] = _slim(r)
        elif t == "SymbolTree" and code.isdigit():
            trees[code] = r.get("Name", "")
    st = path.stat()
    return {
        "version": INDEX_VERSION,
        "source": str(path),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "symbols": symbols,
        "trees": trees,
    }


def _from_data(data: dict) -> LibraryIndex:
    lib = SymbolLibrary()
    for code, f in data["symbols"].items():
        lib.symbols[int(code)] = LibSymbol(code=int(code), name=f.get("Name", ""), fields=f)
    return LibraryIndex(source=data["source"], library=lib,
                        trees={int(k): v for k, v in data["trees"].items()})


def load_index(path: Path = DEFAULT_SYMLIB, cache: Path | None = None) -> LibraryIndex:
    """The library index, from cache when the library file hasn't changed."""
    cache = cache or (cache_dir() / "symlib-index.json")
    st = path.stat()
    if cache.exists():
        try:
            data = json.loads(cache.read_text("utf-8"))
            if (data.get("version") == INDEX_VERSION and data.get("source") == str(path)
                    and data.get("size") == st.st_size and data.get("mtime") == st.st_mtime):
                return _from_data(data)
        except (OSError, ValueError, KeyError):
            pass
    data = build_index(path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), "utf-8")
    os.replace(tmp, cache)
    return _from_data(data)
