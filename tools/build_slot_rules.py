"""Measure how SIMPL writes devices that users put into configurable slots (cards in frames,
drivers on ports), per device type, from the public corpus.

For each device code found in a non-fixed slot of a device on a network, in files saved since
SmVr 1200, record whether its Dv record carried SlC and whether it had a Db record. A code is
usable only when every instance agrees and it was seen at least twice. Writes
src/simpl_agent/catalog/slot_device_rules.json (codes and booleans only; no Crestron data).

    python tools/build_slot_rules.py
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simpl_agent.catalog.devices import load_devices  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS, iter_files  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.device_edit import slot_layout  # noqa: E402
from simpl_agent.smw.model import load  # noqa: E402

OUT = ROOT / "src" / "simpl_agent" / "catalog" / "slot_device_rules.json"


def main() -> None:
    dl = load_devices()
    seen: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    by_slot: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        raw = rawfile.read(f)
        hd = raw.first("Hd")
        if int((hd.get("SmVr") if hd else "0") or 0) < 1200:
            continue
        prog = load(raw)
        dbs = {r.get("H"): r for r in raw.of_type("Db")}
        for d in {id(x): x for x in prog.devices.values()}.values():
            if d.code is None or d.record.get("DvF") == "Sl":
                continue
            slot = prog.devices.get(d.parent)
            frame = prog.devices.get(slot.parent) if slot is not None and slot.parent is not None else None
            fdd = dl.get(frame.code) if frame is not None and frame.code is not None else None
            if slot is None or fdd is None or slot.record.get("DvF") != "Sl":
                continue
            a = slot.address or ""
            if not a.isdigit():
                continue
            fixed = {p: fx for p, _, fx in slot_layout(dl, fdd)}
            if fixed.get(int(a)) is not None:
                continue  # placed by SIMPL itself, not by a user
            db = dbs.get(d.record.get("DbH") or "")
            if db is not None and (db.get("Whc") != "3" or db.get("LgF") or db.get("DrF")):
                continue  # a database driver or module the user attached afterwards
            seen[d.code][(d.record.get("SlC") is not None, db is not None)] += 1
            by_slot[slot.name or ""][(d.record.get("SlC") is not None, db is not None)] += 1
    rules = {}
    for code, c in sorted(seen.items()):
        if len(c) == 1 and sum(c.values()) >= 2:
            (slc, db), n = next(iter(c.items()))
            rules[str(code)] = {"slc": slc, "db": db, "seen": n}
    # Slot types where every instance, of whatever device, agrees (at least 5): a fallback for device
    # types the corpus doesn't show.
    slots = {}
    for name, c in sorted(by_slot.items()):
        if len(c) == 1 and sum(c.values()) >= 5:
            (slc, db), n = next(iter(c.items()))
            slots[name] = {"slc": slc, "db": db, "seen": n}
    OUT.write_text(json.dumps({"note": "How SIMPL writes a device a user puts into a slot; measured by "
                                       "tools/build_slot_rules.py", "codes": rules, "slot_types": slots},
                              indent=1) + "\n", "utf-8")
    print("slot types:", slots)
    mixed = {c: dict(v) for c, v in seen.items() if len(v) > 1}
    print(f"usable codes: {len(rules)}; mixed: {len(mixed)}; seen once: "
          f"{sum(1 for v in seen.values() if len(v) == 1 and sum(v.values()) == 1)}")
    for c in list(rules)[:40]:
        print(" ", c, dl.get(int(c)).name, rules[c])
    for c, v in list(mixed.items())[:10]:
        print("  mixed", c, dl.get(c).name, v)


if __name__ == "__main__":
    main()
