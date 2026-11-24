"""Check add_device's rules against every device SIMPL saved in the public corpus.

For each device sitting in a slot, rebuild what add_device would write from today's
libraries and compare it with what SIMPL wrote:
- the device record's keys (order) and SlC rule,
- its fixed children (slot type + child device code),
- the Db companion,
- its logic symbol: code, keys, and pin counts (exact = never expanded by the user).
Values that follow the Crestron database (RelStat, ProdLine, ObjVer, symbol Nm) are only
compared in files saved with the same database (SmVr 1247).

    python tools/prove_devices.py [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.catalog.devices import load_devices  # noqa: E402
from simpl_agent.catalog.index import load_index  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS, iter_files  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.device_edit import (  # noqa: E402
    PROVEN_SLOTS,
    device_record,
    instance_name,
    symbol_counts,
    symbol_shape_problem,
)
from simpl_agent.smw.model import load  # noqa: E402

CURRENT_DB = "1247"
COUNT_KEYS = ("n1I", "n2I", "n1O", "mI", "mO", "tO")


USER_KEYS = {"EtH", "VtpH", "CsH", "CmH", "EthUpl"}  # set later by the user (IP, panel file, ...)


def keyseq(rec) -> list[str]:
    return [k for k in rec.keys()
            if k != "ObjTp" and k not in USER_KEYS and not (k[0] == "C" and k[1:].isdigit())]


def check_device(prog, d, devlib, lib, same_db: bool) -> tuple[str, list[str]]:
    """('skip'|'ok'|'fail', reasons): would add_device have written this device's records?"""
    dd = devlib.get(d.code)
    if dd is None:
        return "skip", ["not in today's device library"]
    slot = prog.devices.get(d.parent)
    if slot is None or slot.record.get("DvF") != "Sl":
        return "skip", ["not in a slot"]
    if dd.symbol_code is None:
        return "skip", ["no logic symbol of its own"]
    expands = dd.numbered("Expand")
    if any(e != "FixedSlot" for e in expands) or any(not dd.fields.get(f"Fixed{i}") for i in range(1, len(expands) + 1)):
        return "skip", ["configurable or empty slots"]
    ls = lib.get(dd.symbol_code)
    if ls is None:
        return "skip", ["symbol not in library"]
    if symbol_shape_problem(ls):
        return "skip", [symbol_shape_problem(ls)]
    r = d.record
    why = []
    want = device_record(name=instance_name(dd), handle=0, parent=0, dd=dd, slot_code=r.get("SlC"),
                         dvvr=r.get("DvVr") or "", address="", symbol=0,
                         db=0 if r.get("DbH") is not None else None, et=None, children=[1] if expands else [])
    want_keys = [k for k, _ in want if k != "ObjTp" and not (k[0] == "C" and k[1:].isdigit())]
    if r.get("DvVr") is None:
        want_keys.remove("DvVr")
    if keyseq(r) != want_keys:
        why.append(f"Dv keys {keyseq(r)} != {want_keys}")
    if same_db:
        for key, v in (("RelStat", dd.fields.get("CDSReleaseStatus") or "Release"),
                       ("ObjVer", dd.fields.get("ObjVer") or "1"), ("ProdLine", dd.fields.get("CDSProdLine"))):
            if r.get(key) != v:
                why.append(f"{key}={r.get(key)} want {v}")
    if slot.name == "FixedSlot" and r.get("SlC") != slot.record.get("SlC"):
        why.append("fixed child without its slot's SlC")
    if slot.name in PROVEN_SLOTS and r.get("SlC") is not None:
        why.append("network device with SlC")
    if slot.name in PROVEN_SLOTS and r.get("DbH") is None:
        why.append("network device without Db")
    # Fixed children: slot type, then the child device's code.
    want_kids = []
    for i in range(1, len(expands) + 1):
        hits = [x.code for x in devlib.devices.values() if x.name == dd.fields[f"Fixed{i}"]]
        want_kids.append(("FixedSlot", hits[0] if len(hits) == 1 else None))
    got_kids = []
    for h in dict.fromkeys(d.children):
        k = prog.devices.get(h)
        ch = prog.devices.get(k.children[0]) if k is not None and k.children else None
        got_kids.append((k.name if k else None, ch.code if ch is not None else None))
    if got_kids != want_kids:
        why.append(f"children {got_kids} != {want_kids}")
    if r.get("DbH") is not None:
        db = next((x for x in prog.raw.of_type("Db") if x.get("H") == r.get("DbH")), None)
        if db is None or [db.get("Whc"), db.get("Mnf")] != ["3", "Crestron"]:
            why.append(f"Db {[(k, v) for k, v in db.lines[2:5]] if db else None}")
    s = prog.symbols.get(d.symbol) if d.symbol is not None else None
    expanded = False
    if s is None:
        why.append("symbol missing")
    else:
        if s.code != dd.symbol_code:
            why.append(f"SmC {s.code} != {dd.symbol_code}")
        pc = symbol_counts(ls)
        got = {k: int(s.record.get(k) or 0) for k in COUNT_KEYS}
        expanded = got != pc
        if any(got[k] < pc[k] for k in ("n1I", "n2I", "n1O")):
            why.append(f"counts {got} below fresh {pc}")
        if s.record.get("Cmn1") not in (None, d.name):
            pass  # renamed in the logic view: user's choice
        if same_db and s.record.get("Nm") != ls.fields.get("Name"):
            why.append(f"symbol Nm {s.record.get('Nm')!r} != {ls.fields.get('Name')!r}")
    if why:
        return "fail", why
    return "ok", (["expanded"] if expanded else [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    devlib, lib = load_devices(), load_index().library
    per_code: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    reasons = collections.Counter()
    examples: dict[int, list] = collections.defaultdict(list)
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        raw = rawfile.read(f)
        hd = raw.first("Hd")
        same_db = hd is not None and hd.get("SmVr") == CURRENT_DB
        prog = load(raw)
        seen = set()
        for d in prog.devices.values():
            if id(d) in seen or d.code is None or d.record.get("DvF") == "Sl":
                continue
            seen.add(id(d))
            verdict, why = check_device(prog, d, devlib, lib, same_db)
            per_code[d.code][verdict] += 1
            if verdict == "fail":
                for w in why:
                    reasons[w.split(" ")[0] + " " + (w.split(" ")[1] if len(w.split(" ")) > 1 else "")] += 1
                if len(examples[d.code]) < 2:
                    examples[d.code].append((f.name, why[:2]))
            elif verdict == "skip":
                reasons["skip: " + why[0][:50]] += 1
    ok_codes = [c for c, n in per_code.items() if n["ok"] and not n["fail"]]
    mixed = [c for c, n in per_code.items() if n["ok"] and n["fail"]]
    bad = [c for c, n in per_code.items() if n["fail"] and not n["ok"]]
    inst = collections.Counter()
    for n in per_code.values():
        inst.update(n)
    print(f"instances: {dict(inst)}")
    print(f"device codes: all-ok {len(ok_codes)}, mixed {len(mixed)}, all-fail {len(bad)}, "
          f"skipped-only {sum(1 for n in per_code.values() if not n['ok'] and not n['fail'])}")
    print("top failure reasons:")
    for k, v in reasons.most_common(15):
        print(f"  {v:6d} {k}")
    for c in (bad + mixed)[:12]:
        dd = devlib.get(c)
        print(c, dd.name if dd else "?", dict(per_code[c]), examples[c][:1])
    if a.json:
        Path(a.json).write_text(json.dumps({"ok": sorted(ok_codes), "mixed": sorted(mixed), "bad": sorted(bad)}))


if __name__ == "__main__":
    main()
