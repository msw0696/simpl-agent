"""Read-side analysis of a loaded program: folders, pin names, signal flow, problems.

Problem rules mirror SIMPL 4.32's compiler messages, checked against real
compiles (docs/format.md section 7):

* LGCMCVT102 warning: a signal is on an input but nothing drives it.
* LGCMCVT103 notice:  a signal is driven but goes to no input.
* LGCMCVT220 warning: a digital signal has a second driving source.

Built-in signals (0, 1, Local) and placeholder names starting with ``//`` are
exempt. Symbols the library marks as sharing outputs (Buffer, panels...) don't
count as a second source; analog and serial signals may have several sources.
Those two exemptions match the corpus, but SIMPL hasn't confirmed them yet.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .catalog.symlib import LibSymbol, SymbolLibrary
from .smw.model import Program, Symbol

FOLDER_CODE = 156
ARG_DEFINITION_CODE = 55
MODULE_CODES = {103, 155}  # SIMPL+ module, macro


def is_folder(s: Symbol) -> bool:
    return s.code == FOLDER_CODE


COMMENT_BREAK = "\\\\"  # SIMPL stores a comment's line breaks as two backslashes
COMMENT_SUFFIX = re.compile(r"\|\|\d+$")  # e.g. '||1' at the end; meaning unknown


def comment_lines(symbol: Symbol) -> list[str]:
    """A symbol's comment as lines: Cmn1, Cmn2... joined, split at SIMPL's line breaks."""
    raw = "".join(v for k, v in symbol.record.lines if k and k.startswith("Cmn"))
    raw = COMMENT_SUFFIX.sub("", raw)
    lines = [ln.rstrip() for ln in raw.split(COMMENT_BREAK)]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def display_name(s: Symbol, lib: SymbolLibrary | None = None) -> str:
    """What SIMPL shows: a folder's name (its comment's first line), else the symbol's name."""
    if is_folder(s):
        lines = comment_lines(s)
        return (lines[0] if lines else (s.name if s.name and s.name != "SUBSYSTEM" else "")) or f"folder #{s.handle}"
    if s.name:
        return s.name
    ls = lib.get(s.code) if lib else None
    return ls.name if ls else f"symbol code {s.code}"


def folder_path(prog: Program, handle: int, lib: SymbolLibrary | None = None) -> str:
    """'Logic\\Room A\\Projector' for a symbol's parent chain (folders only)."""
    parts: list[str] = []
    seen: set[int] = set()
    s = prog.symbols.get(handle)
    cur = prog.symbols.get(s.parent) if s and s.parent is not None else None
    while cur is not None and cur.handle not in seen:
        seen.add(cur.handle)
        parts.append(display_name(cur, lib))
        cur = prog.symbols.get(cur.parent) if cur.parent is not None else None
    return "\\".join(reversed(parts))


def position_in_folder(prog: Program, handle: int) -> int | None:
    """1-based position among the parent's children (SIMPL's 'S-n', inferred)."""
    s = prog.symbols.get(handle)
    if not s or s.parent is None or s.parent not in prog.symbols:
        return None
    kids = prog.symbols[s.parent].children
    return kids.index(handle) + 1 if handle in kids else None


def pin_label(ls: LibSymbol | None, symbol: Symbol, letter: str, n: int) -> str:
    """The library's name for input/output/param pin ``n`` (I/O/P), or a generic one.

    A name ending in '#' repeats: with cues [enable, i#], pin 2 is i1, pin 3 is i2.
    Pins past the first pin list (panels, devices) get a generic name for now.
    """
    generic = {"I": f"i{n}", "O": f"o{n}", "P": f"p{n}"}[letter]
    if ls is None:
        return generic
    prefix = {"I": "InputCue", "O": "OutputCue", "P": "ParamCue"}[letter]
    first_list = {"I": "n1I", "O": "n1O"}.get(letter)
    if first_list:
        n1 = symbol.record.get(first_list)
        if n1 and n1.isdigit() and n > int(n1) and ls.fields.get("HasExtraPinLists") == "True":
            return f"list 2 pin {n - int(n1)}"
    cues = ls.cues(prefix)
    rep = next((k for k, v in cues.items() if v.endswith("#")), None)
    if rep is not None and n >= rep:
        return cues[rep][:-1] + str(n - rep + 1)
    if n in cues:
        return cues[n]
    return generic


@dataclass
class Flow:
    """Who drives each signal and where it goes."""

    drivers: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))
    destinations: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))


def signal_flow(prog: Program) -> Flow:
    f = Flow()
    for s in prog.symbols.values():
        if s.code == ARG_DEFINITION_CODE:
            continue  # a macro's argument list, not live logic
        for n, sig in s.outputs.items():
            f.drivers[sig].append((s.handle, n))
        for n, sig in s.inputs.items():
            f.destinations[sig].append((s.handle, n))
    return f


@dataclass
class Problem:
    severity: str  # error | warning | notice
    code: str  # SIMPL's message code where one exists, else our own
    message: str
    signal: str | None = None
    symbols: list[int] = field(default_factory=list)
    confirmed: bool = True  # False: SIMPL hasn't been seen to report this case yet

    def as_dict(self) -> dict:
        d = {"severity": self.severity, "code": self.code, "message": self.message}
        if not self.confirmed:
            d["unconfirmed"] = "SIMPL hasn't been seen to report this case (SIMPL+ module or macro involved)"
        if self.signal is not None:
            d["signal"] = self.signal
        if self.symbols:
            d["symbols"] = self.symbols
        return d


def find_problems(prog: Program, lib: SymbolLibrary | None) -> list[Problem]:
    flow = signal_flow(prog)
    builtin = set(prog.builtin_signals.values())
    out: list[Problem] = []

    def exempt(h: int) -> bool:
        sg = prog.signals.get(h)
        return h in builtin or sg is None or sg.name.startswith("//")

    # Errors first: things SIMPL itself would never write.
    for s in prog.symbols.values():
        for letter, pins in (("I", s.inputs), ("O", s.outputs)):
            for n, h in pins.items():
                if h not in prog.signals:
                    out.append(Problem("error", "SA-MISSING-SIGNAL",
                                       f"Symbol #{s.handle} pin {letter}{n} points to signal #{h}, which doesn't exist.",
                                       symbols=[s.handle]))
    seen: dict[str, int] = {}
    for sg in prog.signals.values():
        if sg.record is None:
            continue
        key = sg.name.lower()
        if key in seen:
            out.append(Problem("error", "SA-DUPLICATE-NAME",
                               f'Signals #{seen[key]} and #{sg.handle} are both named "{sg.name}" (names must be unique, ignoring case).',
                               signal=sg.name))
        else:
            seen[key] = sg.handle

    for h, sg in sorted(prog.signals.items()):
        if exempt(h):
            continue
        drv = flow.drivers.get(h, [])
        dst = flow.destinations.get(h, [])
        if dst and not drv:
            out.append(Problem("warning", "LGCMCVT102", f'Signal "{sg.name}" has no driving source.',
                               signal=sg.name, symbols=sorted({s for s, _ in dst})))
        if drv and not dst:
            out.append(Problem("notice", "LGCMCVT103", f'Signal "{sg.name}" has no destination.',
                               signal=sg.name, symbols=sorted({s for s, _ in drv})))
        if len(drv) > 1 and sg.type == "digital":
            def shares(sym_h: int) -> bool:
                ls = lib.get(prog.symbols[sym_h].code) if lib else None
                return bool(ls and ls.shares_outputs)
            if not all(shares(s) for s, _ in drv):
                module = any(prog.symbols[s].code in MODULE_CODES for s, _ in drv)
                for s, _ in drv[1:]:
                    pos = position_in_folder(prog, s)
                    where = f"S-{pos}" if pos else f"#{s}"
                    out.append(Problem("warning", "LGCMCVT220",
                                       f'Signal "{sg.name}" on symbol {where} has a previously defined driving source.',
                                       signal=sg.name, symbols=[x for x, _ in drv], confirmed=not module))

    for s in prog.symbols.values():
        # Parents inherit CF=1 from an incomplete child; report only the symbol itself.
        inherited = any(prog.symbols[c].record.get("CF") == "1" for c in s.children if c in prog.symbols)
        if s.record.get("CF") == "1" and not is_folder(s) and not inherited:
            out.append(Problem("warning", "SA-INCOMPLETE",
                               f"Symbol #{s.handle} ({display_name(s, lib)}) is marked incomplete by SIMPL: a required pin is empty.",
                               symbols=[s.handle]))
    order = {"error": 0, "warning": 1, "notice": 2}
    out.sort(key=lambda p: order[p.severity])
    return out
