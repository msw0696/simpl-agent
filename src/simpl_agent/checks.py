"""Structural checks: rules SIMPL's own files always follow (docs/format.md).

apply_edits refuses to write a file if an edit adds a violation that wasn't
there before. These are format rules, not logic warnings (find_problems).
"""
from __future__ import annotations

from collections import Counter

from .smw.model import Program, numbered, parse_handles


def structural_problems(prog: Program) -> set[str]:
    out: set[str] = set()
    raw = prog.raw

    # Handles: integers, unique per type, records sorted by handle.
    for typ in ("Sm", "Sg"):
        hs = [r.get("H") for r in raw.of_type(typ)]
        if not all(h is not None and h.isdigit() for h in hs):
            out.add(f"{typ} record with a non-numeric handle")
            continue
        ints = [int(h) for h in hs]
        for h, n in Counter(ints).items():
            if n > 1:
                out.add(f"{typ} handle {h} is used {n} times")
        if ints != sorted(ints):
            out.add(f"{typ} records are not in handle order")
    dv = [h for r in raw.of_type("Dv") for h in parse_handles(r.get("H"))]
    for h, n in Counter(dv).items():
        if n > 1:
            out.add(f"device handle {h} is used {n} times")

    # Each record type in one unbroken run.
    seen: list[str] = []
    for r in raw.records:
        t = r.type or "(none)"
        if not seen or seen[-1] != t:
            if t in seen:
                out.add(f"{t} records are split into more than one block")
            seen.append(t)

    # Signal names unique, ignoring case.
    names = Counter(s.name.lower() for s in prog.signals.values() if s.record is not None)
    for name, n in names.items():
        if n > 1:
            out.add(f"signal name {name!r} is used {n} times")

    for h, s in prog.symbols.items():
        rec = s.record
        for letter, total_key in (("I", "mI"), ("O", "tO")):
            pins = numbered(rec, letter)
            for n, v in pins.items():
                if not v.isdigit() or int(v) not in prog.signals:
                    out.add(f"#{h} {letter}{n} points to a missing signal")
            total = rec.get(total_key)
            if pins and (not total or not total.isdigit() or max(pins) > int(total)):
                out.add(f"#{h} has pin {letter}{max(pins)} beyond its {total_key}={total}")
        params = numbered(rec, "P")
        mp = rec.get("mP")
        if params and sorted(params) != list(range(1, int(mp or 0) + 1)):
            out.add(f"#{h} parameters don't run P1..P{mp}")
        kids = numbered(rec, "C")
        mc = rec.get("mC")
        if kids and sorted(kids) != list(range(1, int(mc or 0) + 1)):
            out.add(f"#{h} children don't run C1..C{mc}")
        if mc is not None and not kids:
            out.add(f"#{h} has mC={mc} but no children")
        if s.parent is not None:
            par = prog.symbols.get(s.parent)
            if par is None:
                out.add(f"#{h} has a missing parent #{s.parent}")
            elif h not in par.children:
                out.add(f"#{h} isn't listed in its parent #{s.parent}")
        for c in s.children:
            ch = prog.symbols.get(c)
            if ch is None:
                out.add(f"#{h} lists a missing child #{c}")
            elif ch.parent != h:
                out.add(f"#{h} lists #{c}, whose parent is #{ch.parent}")
    return out
