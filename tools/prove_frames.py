"""Rebuild whole device subtrees (slots and fixed devices) from the libraries and compare
them with what SIMPL saved, for every device on a network ID in the public corpus.

Only "untouched" devices are compared: none of their configurable slots holds a device a
user added (those can't be predicted). Values that follow the Crestron database (RelStat,
ProdLine, ObjVer) are compared only in files saved with the same database (SmVr 1247).

    python tools/prove_frames.py
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.catalog.devices import load_devices  # noqa: E402
from simpl_agent.catalog.index import load_index  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS, iter_files  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.device_edit import PROVEN_SLOTS, _Build, slot_layout  # noqa: E402
from simpl_agent.smw.edit import EditError, Editor  # noqa: E402
from simpl_agent.smw.model import parse_handles  # noqa: E402

USER_KEYS = {"EtH", "VtpH", "CsH", "CmH", "EthUpl", "Loc", "SerialNum", "UiH", "Usd", "UplStr", "SbObjRev",
             "SerUpl"}
LOGIC_MODULE_KEYS = {"PSymH", "LSymH", "NmLogModSh", "MpDt"}  # a Crestron module the user attached
DB_VALUES = {"RelStat", "ProdLine", "ObjVer"}


def subtree_records(prog, d) -> list:
    out, todo, seen = [], [d], set()
    while todo:
        x = todo.pop()
        if id(x) in seen:
            continue
        seen.add(id(x))
        out.append(x.record)
        todo += [prog.devices[h] for h in x.children if h in prog.devices]
    return out


def user_touched(prog, devlib, d) -> bool:
    """True if anything inside ``d`` was added or attached by a user, not placed by SIMPL."""
    if any(k in d.record for k in LOGIC_MODULE_KEYS):
        return True
    dd = devlib.get(d.code)
    if dd is None:
        return True
    fixed = {p: fx for p, _, fx in slot_layout(devlib, dd)}
    for h in dict.fromkeys(d.children):
        k = prog.devices.get(h)
        if k is None or not k.children:
            continue
        a = k.address or ""
        pos = int(a) if a.isdigit() else int(a, 16) if a else None
        ch = prog.devices.get(k.children[0])
        if pos is None or fixed.get(pos) is None or ch is None or ch.code != fixed[pos].code:
            return True
        if user_touched(prog, devlib, ch):
            return True
    return False


def normal(lines, same_db: bool, drop_name: bool) -> tuple:
    out = []
    for k, v in lines:
        if k in ("ObjTp", "SmH", "DvVr") or k in USER_KEYS:
            continue
        if k in DB_VALUES and not same_db:
            v = "*"
        if k == "Nm" and drop_name:
            v = "*"
        out.append((k, v))
    return tuple(out)


def main() -> None:
    devlib, lib = load_devices(), load_index().library
    res = collections.Counter()
    why = collections.Counter()
    examples = collections.defaultdict(list)
    codes_ok, codes_bad = set(), set()
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        raw = rawfile.read(f)
        hd = raw.first("Hd")
        smvr = (hd.get("SmVr") if hd else "") or ""
        if int(smvr or 0) < 1200:
            continue
        ed = Editor(raw, lib)
        prog = ed.prog
        for d in {id(x): x for x in prog.devices.values()}.values():
            if d.code is None or d.record.get("DvF") == "Sl":
                continue
            slot = prog.devices.get(d.parent)
            dd = devlib.get(d.code)
            if slot is None or slot.name not in PROVEN_SLOTS or dd is None:
                continue
            lay = slot_layout(devlib, dd)
            if not lay:
                continue  # no slots of its own: covered by prove_devices.py
            # Skip devices where a user filled a configurable slot, at any depth, or attached a module.
            touched = user_touched(prog, devlib, d)
            if touched:
                res["skipped: user added a device inside"] += 1
                continue
            b = _Build(ed, devlib, d.record.get("DvVr") or "", smvr, 10 ** 6)
            try:
                b.device(dd, handle=d.handles[0], parent=d.parent, address=d.address or "", slot_code=None,
                         sym_parent=0, db=int(d.record.get("DbH")) if d.record.get("DbH") else None)
            except EditError as e:
                res["skipped: " + str(e).split(":")[-1].strip()[:60]] += 1
                continue
            same_db = smvr == "1247"
            got = {}
            for r in subtree_records(prog, d):
                got[r.get("H")] = normal(r.lines, same_db, r.get("DvF") != "Sl")
            want = {}
            for lines in b.dv:
                h = dict(lines)["H"]
                want[h] = normal(lines, same_db, dict(lines).get("DvF") != "Sl")
            if got == want:
                res["identical"] += 1
                codes_ok.add(d.code)
            else:
                res["different"] += 1
                codes_bad.add(d.code)
                missing = sorted(set(want) - set(got), key=lambda h: parse_handles(h)[0])[:2]
                extra = sorted(set(got) - set(want), key=lambda h: parse_handles(h)[0])[:2]
                diff = [h for h in want if h in got and want[h] != got[h]][:1]
                key = "handles differ" if (missing or extra) else "record content differs"
                why[key] += 1
                if len(examples[key]) < 4:
                    examples[key].append((dd.name, f.name, missing, extra,
                                          [(want[h], got[h]) for h in diff]))
    for k, v in res.most_common():
        print(f"{v:5d} {k}")
    print("device types identical:", len(codes_ok - codes_bad), " with a difference:", len(codes_bad))
    for k, v in why.items():
        print(k, v)
        for e in examples[k]:
            print("   ", str(e)[:600])


if __name__ == "__main__":
    main()
