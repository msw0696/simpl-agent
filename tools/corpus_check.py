"""Measure format hypotheses across the SIMPL corpus.

Each check counts how many items it applied to and how many broke it, split by
source (installed Crestron macros vs public GitHub programs). The results feed
docs/format.md. Reads files in place; copies nothing.

Usage:  python -I tools/corpus_check.py [--json out.json] [roots...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.catalog.symlib import DEFAULT_SYMLIB, load_symlib  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS, INSTALLED_MODULES, iter_files  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.model import load, numbered, parse_handles  # noqa: E402

LIB = load_symlib() if DEFAULT_SYMLIB.exists() else None


class Tally:
    def __init__(self) -> None:
        self.applied: Counter[str] = Counter()
        self.broken: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)
        self.notes: dict[str, Counter] = defaultdict(Counter)

    def check(self, name: str, ok: bool, example: str = "") -> None:
        self.applied[name] += 1
        if not ok:
            self.broken[name] += 1
            if len(self.examples[name]) < 3:
                self.examples[name].append(example)

    def note(self, name: str, value) -> None:
        self.notes[name][str(value)] += 1


def check_file(path: Path, t: Tally) -> None:
    data = path.read_bytes()
    raw = rawfile.parse(data)
    t.check("roundtrip byte-identical", raw.to_bytes() == data, path.name)
    p = load(raw)
    tag = path.name
    t.note("signature", p.kind)
    t.note("newline", repr(raw.newline))

    # --- handles unique per record type
    for typ in ("Sg", "Sm"):
        hs = [r.get("H") for r in raw.of_type(typ)]
        t.check(f"{typ}.H unique in file", len(hs) == len(set(hs)), tag)
        t.check(f"{typ}.H all integers", all(h is not None and h.isdigit() for h in hs), tag)
        ints = [int(h) for h in hs if h and h.isdigit()]
        t.check(f"{typ} records sorted by H", ints == sorted(ints), tag)
        if ints:
            gaps = max(ints) - len(set(ints))
            t.note(f"{typ} handle gaps (max H minus count)", "0" if gaps <= 0 else ("1-9" if gaps < 10 else "10+"))
    dv_hs = [h for r in raw.of_type("Dv") for h in parse_handles(r.get("H"))]
    if dv_hs:
        t.check("Dv handles (ranges expanded) unique", len(dv_hs) == len(set(dv_hs)), tag)

    # --- built-in signals
    bi = p.builtin_signals
    if bi:
        t.check("Hd S0Nd/S1Nd/SLNd == 1/2/3", bi == {"0": 1, "1": 2, "Local": 3}, f"{tag}: {bi}")
        sg_hs = {int(r.get("H")) for r in raw.of_type("Sg") if (r.get("H") or "").isdigit()}
        t.check("no Sg record for built-in handles", not (set(bi.values()) & sg_hs), tag)
        if sg_hs:
            t.check("min Sg.H > 3", min(sg_hs) > 3, f"{tag}: min {min(sg_hs)}")

    # --- signal records
    names = Counter()
    for r in raw.of_type("Sg"):
        t.note("Sg.SgTp", r.get("SgTp"))
        t.note("Sg key order", ",".join(r.keys()))
        names[(r.get("Nm") or "").lower()] += 1
    t.check("Sg names unique (case-insensitive)", all(n == 1 for n in names.values()), tag)

    # --- symbol records
    for h, s in p.symbols.items():
        rec = s.record
        where = f"{tag} Sm#{h}"
        for letter, total_key in (("I", "mI"), ("O", "mO"), ("P", "mP"), ("C", "mC")):
            pins = numbered(rec, letter)
            total = rec.get(total_key)
            if pins:
                t.check(f"Sm {letter}* present => {total_key} present", total is not None, where)
            if total is not None and total.isdigit():
                t.check(f"Sm max {letter} index <= {total_key}", not pins or max(pins) <= int(total), where)
                if letter in ("P", "C"):
                    t.check(f"Sm {letter} pins dense 1..{total_key}", sorted(pins) == list(range(1, int(total) + 1)), where)
        for n, v in numbered(rec, "I").items():
            t.check("Sm I* value is integer", v.isdigit(), f"{where} I{n}={v}")
        for n, v in numbered(rec, "O").items():
            t.check("Sm O* value is integer", v.isdigit(), f"{where} O{n}={v}")
        for sig in list(s.inputs.values()) + list(s.outputs.values()):
            t.check("Sm I/O handle resolves to a signal", sig in p.signals, f"{where} -> {sig}")
        outs = numbered(rec, "O")
        if outs and (rec.get("tO") or "").isdigit():
            t.check("Sm max O index <= tO", max(outs) <= int(rec.get("tO")), where)
        if rec.get("tO") is not None and rec.get("mO") is not None:
            t.note("Sm tO vs mO", "equal" if rec.get("tO") == rec.get("mO") else "differ")
        if s.parent is not None:
            par = p.symbols.get(s.parent)
            t.check("Sm PrH resolves to a symbol", par is not None, where)
            if par:
                t.check("Sm listed in parent's C*", h in par.children, where)
        for c in s.children:
            ch = p.symbols.get(c)
            t.check("Sm C* resolves to a symbol", ch is not None, f"{where} C->{c}")
            if ch:
                t.check("Sm child's PrH == parent", ch.parent == h, f"{where} C->{c}")
        if s.device is not None and p.devices:
            dv = p.devices.get(s.device)
            t.check("Sm DvH resolves to a device", dv is not None, where)
            if dv:
                t.check("Device SmH points back to symbol", dv.symbol == h, where)
        t.note("Sm first keys", ",".join(rec.keys()[:3]))

    # --- outputs: a digital signal driven by more than one output.
    # Exempt: built-ins, '//' placeholder names, analog/serial signals,
    # Argument Definition (SmC 55, a macro's argument list), and symbols the
    # library marks SymJam=NonExclusive (Buffer, panels...).
    drivers: dict[int, list] = defaultdict(list)
    for s in p.symbols.values():
        if s.code == 55:
            continue
        for sig in s.outputs.values():
            drivers[sig].append(s)
    bi_h = set(bi.values())
    for sig, ss in drivers.items():
        if len(ss) < 2 or sig in bi_h:
            continue
        sg = p.signals.get(sig)
        if sg is None or sg.name.startswith("//") or sg.type != "digital":
            continue
        lib_syms = [LIB.get(s.code) if LIB else None for s in ss]
        if all(ls is not None and ls.shares_outputs for ls in lib_syms):
            continue
        kinds = "+".join(sorted({(ls.name if ls else f"code{s.code}") for ls, s in zip(lib_syms, ss, strict=True)}))
        involves_module = any(s.code in (103, 155) for s in ss)
        name = ("digital signal multi-driven (involves SIMPL+/macro)" if involves_module
                else "digital signal multi-driven (plain symbols)")
        t.check(name, False, f"{tag}: {sg.name} <- {kinds}")
        t.note("multi-driven symbol mix", kinds)

    # --- devices
    seen = set()
    for dv in p.devices.values():
        if id(dv) in seen:
            continue
        seen.add(id(dv))
        where = f"{tag} Dv#{dv.record.get('H')}"
        is_processor = p.header is not None and p.header.get("CnH") in dv.record.get("H", "").split(",")
        if is_processor:
            t.note("processor Dv PrH", dv.parent)
        elif dv.parent is not None:
            par = p.devices.get(dv.parent)
            t.check("Dv PrH resolves to a device", par is not None, where)
            if par:
                t.check("Dv listed in parent's C* (any of its handles)", bool(set(dv.handles) & set(par.children)), where)
        if dv.symbol is not None:
            t.check("Dv SmH resolves to a symbol", dv.symbol in p.symbols, where)
        mc = dv.record.get("mC")
        if mc is not None:
            t.check("Dv C* count == mC", len(dv.children) == int(mc), where)

    if p.header is not None and p.devices:
        cnh = p.header.get("CnH")
        if cnh is not None:
            dv = p.devices.get(int(cnh))
            t.check("Hd CnH is a device", dv is not None, tag)
            if dv:
                t.check("Hd CnC == that device's DvC", p.header.get("CnC") == dv.record.get("DvC"), tag)
                t.check("processor device has no parent", dv.parent in (None, 1), f"{tag}: PrH={dv.parent}")

    # --- record type order
    order = []
    for r in raw.records:
        ty = r.type or "(none)"
        if not order or order[-1] != ty:
            order.append(ty)
    t.check("each record type appears in one run", len(order) == len(set(order)), f"{tag}: {order}")
    t.note("record type order", " ".join(order))
    if raw.first("FSgntr") is not None:
        t.note("SavedBy", re.sub(r"\.\d+$", "", raw.first("FSgntr").get("SavedBy") or "?"))


def run(sources: dict[str, list[Path]]) -> dict:
    report = {}
    for label, roots in sources.items():
        t = Tally()
        n = 0
        for f in iter_files(*roots):
            try:
                check_file(f, t)
            except Exception as e:  # noqa: BLE001 - record and continue
                t.check("file loads without exception", False, f"{f.name}: {type(e).__name__}: {e}")
            n += 1
        report[label] = {
            "files": n,
            "checks": {k: {"applied": t.applied[k], "broken": t.broken[k], "examples": t.examples.get(k, [])}
                       for k in sorted(t.applied)},
            "notes": {k: dict(v.most_common(12)) for k, v in sorted(t.notes.items())},
        }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    sources = {"installed .cmc macros": [INSTALLED_MODULES], "github .smw programs": [GITHUB_CORPUS]}
    report = run(sources)
    for label, r in report.items():
        print(f"\n=== {label}: {r['files']} files")
        for k, c in r["checks"].items():
            flag = "OK " if c["broken"] == 0 else "BAD"
            print(f"  {flag} {k}: {c['broken']}/{c['applied']} broken  {c['examples'][:2] if c['broken'] else ''}")
        for k, v in r["notes"].items():
            print(f"  note {k}: {v}")
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
