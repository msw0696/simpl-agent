"""Wiring touch-panel and EISC joins by type and number (docs/format.md "Joins").

A panel-style device symbol (Expand_by, expand_inputs_with_outputs) has three pin lists:
digital, analog, serial. Inputs (feedback into the device) are numbered straight through:
digital join j is I j, analog join j is I n1I+j, serial join j is I n1I+n2I+j. Outputs (presses
out of it) the same way with n1O and n2O (n2O = mO - n1O). All 5,045 wired pins on such symbols
in modern corpus files fit this. A list's inputs and outputs always have the same length (93 of
101); lengths needn't be multiples of 32 (196, 269, 46 ... in the corpus), so a list grows to
exactly the join that needs it, and the pins of the lists after it move up.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .model import numbered
from .rawfile import Record

if TYPE_CHECKING:
    from .edit import Editor

TYPES = ("digital", "analog", "serial")
COUNT_KEYS = ("n1I", "n2I", "n1O", "mI", "mO", "tO")


def is_join_symbol(ls) -> bool:
    f = ls.fields
    return (f.get("Expand") == "expand_inputs_with_outputs" and (f.get("Expand_by") or "").isdigit()
            and bool(ls.cues("InputList2Cue") or ls.cues("OutputList2Cue")))


def list_sizes(rec: Record) -> tuple[list[int], list[int]]:
    """([digital, analog, serial] input counts, the same for outputs)."""
    def g(k: str) -> int:
        v = rec.get(k)
        return int(v) if v and v.isdigit() else 0

    n1i, n2i, n1o = g("n1I"), g("n2I"), g("n1O")
    ins = [n1i, n2i, max(g("mI") - n1i - n2i, 0)]
    n2o = max(g("mO") - n1o, 0)
    outs = [n1o, n2o, max(g("tO") - n1o - n2o, 0)]
    return ins, outs


def _rewrite(rec: Record, ins: list[int], outs: list[int], ipins: dict[int, str], opins: dict[int, str]) -> None:
    """Rewrite counts and pins in SIMPL's key order: n1I n2I n1O after CF; mI I* mO tO O* before mP."""
    keep = [(k, v) for k, v in rec.lines
            if not (k in COUNT_KEYS or (k and k[0] in "IO" and k[1:].isdigit()))]
    counts = [("n1I", ins[0]), ("n2I", ins[1]), ("n1O", outs[0])]
    head = [(k, str(v)) for k, v in counts if v]
    mi, mo, to = sum(ins), outs[0] + outs[1], sum(outs)
    pins: list[tuple[str | None, str]] = []
    if mi:
        pins.append(("mI", str(mi)))
        pins += [(f"I{n}", ipins[n]) for n in sorted(ipins)]
    if to:
        pins += [("mO", str(mo)), ("tO", str(to))]
        pins += [(f"O{n}", opins[n]) for n in sorted(opins)]
    out: list[tuple[str | None, str]] = []
    placed_head = placed_pins = False
    for k, v in keep:
        if k == "mP" and not placed_pins:
            out += pins
            placed_pins = True
        out.append((k, v))
        if k == "CF" and not placed_head:
            out += head
            placed_head = True
    if not placed_pins:
        out += pins
    rec.lines = out


def wire_joins(ed: Editor, symbol: str | int, joins: list[dict]) -> list[str]:
    """Connect joins: [{type: digital|analog|serial, join: n, in: signal?, out: signal?}]. ``in`` is the
    signal into the device (a panel's feedback), ``out`` the signal it drives (a press). Returns a summary."""
    from .edit import EditError

    sm = ed._symbol(symbol)
    ls = ed.lib.get(sm.code) if ed.lib is not None and sm.code is not None else None
    if ls is None or not is_join_symbol(ls):
        raise EditError(f"#{sm.handle} isn't a panel-style symbol with digital/analog/serial join lists; "
                        "use connect with pin numbers")
    if not isinstance(joins, list) or not joins:
        raise EditError("give joins: a list of {type, join, in?, out?}")
    cap = int(ls.fields.get("MaxVariableInputs") or 4000)
    rec = sm.record
    ins, outs = list_sizes(rec)
    old_ins, old_outs = list(ins), list(outs)
    plan = []
    for j in joins:
        if not isinstance(j, dict) or set(j) - {"type", "join", "in", "out"}:
            raise EditError(f"bad join {j!r}: use {{type, join, in?, out?}}")
        t = str(j.get("type", "")).lower()
        if t not in TYPES:
            raise EditError(f"join type must be digital, analog or serial (got {j.get('type')!r})")
        n = j.get("join")
        if not isinstance(n, int) or not 0 < n <= cap:
            raise EditError(f"join number must be 1-{cap} (got {n!r})")
        if j.get("in") is None and j.get("out") is None:
            raise EditError(f"join {t} {n}: give in and/or out")
        k = TYPES.index(t)
        size = max(ins[k], outs[k], n)
        ins[k] = outs[k] = size  # a list's inputs and outputs grow together
        plan.append((k, t, n, j.get("in"), j.get("out")))

    def move(pins: dict[int, int], old: list[int], new: list[int]) -> dict[int, str]:
        out = {}
        for p, h in pins.items():
            if p <= old[0]:
                q = p
            elif p <= old[0] + old[1]:
                q = p - old[0] + new[0]
            else:
                q = p - old[0] - old[1] + new[0] + new[1]
            out[q] = str(h)
        return out

    snapshot = ed._snapshot()
    done = []
    try:
        ipins = move(numbered(rec, "I"), old_ins, ins)
        opins = move(numbered(rec, "O"), old_outs, outs)
        for k, t, n, sin, sout in plan:
            if sin is not None:
                h = ed.signal_for(sin, create_type=t)
                sg = ed.prog.signals.get(h)
                if sg is not None and sg.record is not None and sg.type != t:
                    raise EditError(f"{t} join {n} takes a {t} signal, but {sg.name!r} is {sg.type}")
                ipins[sum(ins[:k]) + n] = str(h)
                done.append(f"{t} {n} in={ed.prog.signals[h].name}")
            if sout is not None:
                h = ed.signal_for(sout, create_type=t)
                sg = ed.prog.signals.get(h)
                if sg is not None and sg.record is not None and sg.type != t:
                    raise EditError(f"{t} join {n} drives a {t} signal, but {sg.name!r} is {sg.type}")
                ed.check_can_drive(h, ls)
                opins[sum(outs[:k]) + n] = str(h)
                done.append(f"{t} {n} out={ed.prog.signals[h].name}")
            ed._reload()
            sm = ed.prog.symbols[sm.handle]
        _rewrite(sm.record, ins, outs, ipins, opins)
    except Exception:
        ed._restore(snapshot)
        raise
    ed._reload()
    grew = [f"{TYPES[k]} {a}->{b}" for k, (a, b) in enumerate(zip(old_ins, ins, strict=True)) if b != a]
    ed.log.add(f"wired {len(plan)} joins on #{sm.handle}: " + ", ".join(done)
               + (f" (lists grown: {', '.join(grew)})" if grew else ""))
    return done
