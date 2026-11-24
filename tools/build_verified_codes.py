"""List the simple-symbol codes whose records SIMPL 4.3x wrote in the corpus.

add_symbol only builds these: each one's record shape has been rebuilt exactly
by the corpus test. Writes src/simpl_agent/catalog/verified_simple_codes.json
(code numbers and counts only; no Crestron data).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simpl_agent.catalog import load_symlib  # noqa: E402
from simpl_agent.corpus import default_roots, iter_files  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.edit import is_simple  # noqa: E402
from simpl_agent.smw.model import load  # noqa: E402


def main() -> int:
    lib = load_symlib()
    seen: Counter[int] = Counter()
    for path in iter_files(*default_roots()):
        raw = rawfile.read(path)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        for s in load(raw).symbols.values():
            ls = lib.get(s.code)
            if ls and is_simple(ls) and s.record.get("ObjVer") == "1":
                seen[s.code] += 1
    out = ROOT / "src/simpl_agent/catalog/verified_simple_codes.json"
    out.write_text(json.dumps({"source": "SIMPL 4.3x saves in the local corpus",
                               "codes": {str(c): n for c, n in sorted(seen.items())}}, indent=1) + "\n", "utf-8")
    print(f"{len(seen)} verified codes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
