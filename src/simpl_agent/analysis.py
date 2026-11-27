"""Read-side analysis of a loaded program: folders, pin names, signal flow, problems.

Problem rules mirror SIMPL 4.32's compiler messages, checked against real
compiles (docs/format.md section 7):

* LGCMCVT102 warning: a signal is on an input but nothing drives it.
* LGCMCVT103 notice:  a signal is driven but goes to no input.
* LGCMCVT220 warning: a digital signal has a second driving source.

Built-in signals (0, 1, Local) and placeholder names starting with ``//`` are
exempt. Symbols the library marks as sharing outputs (Buffer, panels...) don't
count as a second source; analog and serial signals may have several sources.
SIMPL also skips the second-driver check whenever a macro or SIMPL+ module is one
of the drivers. All of these are confirmed by SIMPL 4.32 compiles (docs/format.md).
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .catalog.symlib import LibSymbol, SymbolLibrary, parse_tio
from .smw import rawfile
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
    """1-based position among the parent's children."""
    s = prog.symbols.get(handle)
    if not s or s.parent is None or s.parent not in prog.symbols:
        return None
    kids = prog.symbols[s.parent].children
    return kids.index(handle) + 1 if handle in kids else None


def simpl_number(prog: Program, handle: int) -> str | None:
    """SIMPL's own symbol number, as its compiler prints it: 'S-2.3' is the 3rd symbol
    in the folder that is 2nd in Logic. Confirmed by SIMPL 4.32 (F12 round 2, 2026-11-24).
    None for symbols outside the Logic folder (devices, macro roots)."""
    parts: list[int] = []
    seen: set[int] = set()
    h = handle
    while True:
        s = prog.symbols.get(h)
        if s is None or h in seen:
            return None
        seen.add(h)
        parent = prog.symbols.get(s.parent) if s.parent is not None else None
        if parent is None:
            return None
        pos = position_in_folder(prog, h)
        if pos is None:
            return None
        parts.append(pos)
        if parent.parent is None:
            if not (is_folder(parent) and (parent.name or "") == "Logic"):
                return None
            return "S-" + ".".join(str(p) for p in reversed(parts))
        h = parent.handle


MACRO_CODE, SPLUS_CODE = 155, 103


def module_definition(program_path: Path | None, symbol: Symbol,
                      installed: Path | None = None) -> LibSymbol | None:
    """Pin names for a macro or SIMPL+ module, read from its own file.

    Macros (SmC 155) name their file in Nm ('X.umc' or a Crestron 'X.cmc'); the file is
    in the program's folder or SIMPL's installed modules and holds a Symbol record.
    SIMPL+ modules (SmC 103) name 'X.usp'; their compiled header 'X.ush' sits beside
    the program. Returns None when the file isn't found.
    """
    if symbol.code not in (MACRO_CODE, SPLUS_CODE) or not symbol.name:
        return None
    name = symbol.name.strip()
    candidates: list[Path] = []
    folders = [program_path.parent] if program_path is not None else []
    if installed is not None:
        folders.append(installed)
    if symbol.code == SPLUS_CODE:
        stem = name[:-4] if name.lower().endswith(".usp") else name
        candidates = [f / f"{stem}.ush" for f in folders]
    else:
        candidates = [f / name for f in folders]
    for c in candidates:
        fields = _module_fields(str(c))
        if fields is not None:
            return LibSymbol(code=symbol.code, name=fields.get("Name", name), fields=fields)
    return None


EXTENDER_CODE = 2942  # a panel's Smart Graphics object or CH5 contract component
GUI_EXTENSION_KINDS = {"1": "Smart Graphics (.sgd)", "2": "CH5 contract (.chd)"}
_SOID_RE = re.compile(r"(?:Smart Object ID\s*=\s*|Control Join Id\s+)(\d+)", re.I)


@lru_cache(maxsize=64)
def _extender_file_cached(path: str, mtime: float) -> tuple[dict[str, str], ...]:
    raw = rawfile.parse_text(Path(path).read_bytes().decode("latin-1"))
    return tuple(r.as_dict() for r in raw.of_type("Symbol"))


def panel_of(prog: Program, h: int):
    """The device whose logic symbol a (possibly nested) extender sits under, or None."""
    by_symbol = {d.symbol: d for d in prog.devices.values() if d.symbol is not None}
    cur = prog.symbols[h].parent if h in prog.symbols else None
    seen = set()
    while cur is not None and cur in prog.symbols and cur not in seen:
        seen.add(cur)
        if cur in by_symbol:
            return by_symbol[cur]
        cur = prog.symbols[cur].parent
    return None


def gui_extension(prog: Program, device, program_path: Path | None) -> dict | None:
    """A panel's GUI extension file (VTP record): kind, path as written, and where it is."""
    vh = device.record.get("VtpH") if device is not None else None
    v = next((r for r in prog.raw.of_type("VTP") if r.get("H") == vh), None) if vh else None
    if v is None or not v.get("SGDFile"):
        return None
    written = v.get("SGDFile")
    src = Path(written.replace("\\", "/"))
    if not src.is_absolute() and program_path is not None:
        src = program_path.parent / src
    # SIMPL keeps its own copy of the imported file in the program folder (<name>.sgd_ / .chd_) and
    # opens the program from it even when the original has moved (SIMPL help: Importing GUI
    # Extenders). Without it, SIMPL reports problems loading and comments out the extenders.
    copy = program_path.parent / (src.name + "_") if program_path is not None else None
    have_copy, have_src = bool(copy and copy.is_file()), src.is_file()
    use = copy if have_copy else src
    out = {"kind": GUI_EXTENSION_KINDS.get(v.get("GuiExtType") or "", "unknown"), "file": written,
           "found": have_copy or have_src, "path": str(use), "contract_id": v.get("ContractID"),
           "simpl_copy": str(copy) if have_copy else None, "source_found": have_src}
    if have_copy and have_src:
        try:
            if copy.read_bytes() != src.read_bytes():
                out["source_changed"] = True  # SIMPL offers to sync the panel's extenders
        except OSError:
            pass
    return out


def extender_definition(prog: Program, symbol: Symbol, program_path: Path | None) -> LibSymbol | None:
    """Pin names for a panel extender (SmC 2942), from the panel's .chd contract or .sgd Smart Graphics file.

    The extender sits under the panel's logic symbol (possibly in contract folders); the panel's
    device points to a VTP record naming the file, relative to the program. The file holds one
    Symbol per object; the placed extender's P1 is its Smart Object ID (control join ID), given in
    each definition's Hint. Matched by that ID, else by name: 207 of 207 corpus extenders with a
    file fit their definition's pin counts (12 only by ID: panels that copied another's objects).
    """
    if symbol.code != EXTENDER_CODE:
        return None
    ext = gui_extension(prog, panel_of(prog, symbol.handle), program_path)
    if ext is None or not ext["found"]:
        return None
    path = Path(ext["path"])
    try:
        defs = _extender_file_cached(str(path), path.stat().st_mtime)
    except (OSError, ValueError):
        return None
    soid = (symbol.record.get("P1") or "").strip().rstrip("dD")
    hit = next((d for d in defs if (m := _SOID_RE.search(d.get("Hint") or "")) and m.group(1) == soid), None)
    if hit is None:
        hit = next((d for d in defs if (d.get("Name") or "").lower() == (symbol.name or "").lower()), None)
    if hit is None:
        return None
    return LibSymbol(code=EXTENDER_CODE, name=hit.get("Name") or symbol.name or "", fields=hit)


UNUSED_PIN = "[~UNUSED~]"
REFERENCE_NAME = "[Reference Name]"


def _int(v: str | None) -> int:
    return int(v) if v and str(v).lstrip("-").isdigit() else 0


def module_layout(code: int, d: LibSymbol) -> dict:
    """A module's pins as SIMPL places it, from its definition (docs/format.md "Modules").

    Macros (155) use NumFixedInputs/Outputs/Params. SIMPL+ modules (103) use the
    minimum array sizes (MinVariable*, per list); parameters are NumFixedParams plus
    MinVariableParams. Proven by rebuilding 610 of 631 placed modules in the corpus.
    Returns counts and, per pin, (number, name, type).
    """
    f = d.fields
    if code == MACRO_CODE:
        n1i, n2i = _int(f.get("NumFixedInputs")), 0
        n1o, n2o = _int(f.get("NumFixedOutputs")), 0
        npar = _int(f.get("NumFixedParams"))
    else:
        n1i, n2i = _int(f.get("MinVariableInputs")), _int(f.get("MinVariableInputsList2"))
        n1o, n2o = _int(f.get("MinVariableOutputs")), _int(f.get("MinVariableOutputsList2"))
        npar = _int(f.get("NumFixedParams")) + _int(f.get("MinVariableParams"))

    def pins(letter: str, n1: int, n2: int) -> list[tuple[int, str, str]]:
        p1, p2 = ("InputCue", "InputList2Cue") if letter == "I" else ("OutputCue", "OutputList2Cue")
        t1, t2 = ("InputSigType", "InputList2SigType") if letter == "I" else ("OutputSigType", "OutputList2SigType")
        c1, c2 = d.cues(p1), d.cues(p2)
        out = []
        for n in range(1, n1 + 1):
            out.append((n, _cue(c1, n) or f"{letter.lower()}{n}", f.get(f"{t1}{n}") or f.get(f"{t1}1") or ""))
        for k in range(1, n2 + 1):
            out.append((n1 + k, _cue(c2, k) or f"list 2 pin {k}", f.get(f"{t2}{k}") or f.get(f"{t2}1") or ""))
        return out

    pc = d.cues("ParamCue")
    params = []
    for n in range(1, npar + 1):
        name, t = pc.get(n, f"p{n}"), f.get(f"ParamSigType{n}") or ""
        if code == SPLUS_CODE and t.lower() == "list":
            name = name.split(",", 1)[0]  # SPlusCC writes a drop-down's cue as 'Mode,0d,1d,2d'
        params.append((n, name, t))
    return {"n1I": n1i, "n2I": n2i, "n1O": n1o, "n2O": n2o,
            "inputs": pins("I", n1i, n2i), "outputs": pins("O", n1o, n2o), "parameters": params}


@lru_cache(maxsize=64)
def _splus_lists_cached(path: str, mtime: float) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in parse_tio(Path(path).read_bytes().decode("latin-1")):
        h, vn = r.get("H", ""), r.get("VN", "")
        if r.get("ObjTp") != "Dp" or not h.isdigit() or not vn.isdigit() or int(vn) == 0:
            continue
        opts = [(r.get(f"Val{i}", ""), r.get(f"Lbl{i}", "")) for i in range(1, int(vn) + 1)]
        out[int(h)] = {"default": r.get("DV"), "options": opts}
    return out


def splus_parameter_lists(path: Path | None, symbol_name: str) -> dict[int, dict]:
    """A SIMPL+ module's drop-down parameters, from the Dp records of its .ush beside the program:
    {parameter n: {"default": value, "options": [(value, label), ...]}}. Dp H=n is parameter n
    (37 of 37 placed SIMPL+ list parameters in the corpus). When one is picked, SIMPL stores the
    value in P<n> and its label in Plb<n>. Macros (.umc/.cmc) number theirs differently; not used."""
    if path is None or not symbol_name.lower().endswith(".usp"):
        return {}
    ush = path.parent / (symbol_name[:-4] + ".ush")
    try:
        return _splus_lists_cached(str(ush), ush.stat().st_mtime)
    except OSError:
        return {}


@lru_cache(maxsize=256)
def _module_fields_cached(path: str, mtime: float) -> dict[str, str] | None:
    data = Path(path).read_bytes().decode("latin-1")
    if path.lower().endswith(".ush"):
        recs = parse_tio(data)
        sym = next((r for r in recs if r.get("ObjTp") == "Symbol"), None)
        return dict(sym) if sym else None
    raw = rawfile.parse_text(data)
    sym = raw.first("Symbol")
    return sym.as_dict() if sym is not None else None


def _module_fields(path: str) -> dict[str, str] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    try:
        return _module_fields_cached(path, st.st_mtime)
    except (OSError, ValueError):
        return None


def pin_label(ls: LibSymbol | None, symbol: Symbol, letter: str, n: int) -> str:
    """The library's name for input/output/param pin ``n`` (I/O/P), or a generic one.

    A name ending in '#' repeats: with cues [enable, i#], pin 2 is i1, pin 3 is i2.
    On symbols with several pin lists (panels, modules, extenders) pins run through list 1, 2
    and 3 with the placed record's sizes; a list with no name for a pin gives 'list N pin k'.
    """
    generic = {"I": f"i{n}", "O": f"o{n}", "P": f"p{n}"}[letter]
    if ls is None:
        return generic
    prefix = {"I": "InputCue", "O": "OutputCue", "P": "ParamCue"}[letter]
    if letter in "IO":
        side = "Input" if letter == "I" else "Output"
        rec = symbol.record
        multi = (ls.fields.get("HasExtraPinLists") == "True" or bool(ls.cues(f"{side}List2Cue"))
                 or bool(ls.cues(f"{side}List3Cue")))
        n1 = _int(rec.get("n1I" if letter == "I" else "n1O"))
        if multi and (n1 or rec.get("n1I" if letter == "I" else "n1O") is None) and n > n1:
            # Pins run through list 1 (digital), list 2 (analog) and list 3 (serial) with the placed
            # record's sizes; SIMPL leaves out a zero n1I, as on a serial-only contract component.
            n2 = _int(rec.get("n2I")) if letter == "I" else _int(rec.get("mO")) - n1
            lst, k = (2, n - n1) if (n <= n1 + n2 or not ls.cues(f"{side}List3Cue")) else (3, n - n1 - n2)
            cue = _cue(ls.cues(f"{side}List{lst}Cue"), k)
            if cue is not None:
                return cue
            return f"list {lst} pin {k}"
    return _cue(ls.cues(prefix), n) or generic


def _cue(cues: dict[int, str], n: int) -> str | None:
    """Pin n's name. A pin's own name wins; a name ending in '#' only fills in the
    numbered pins after it that have no name of their own ('i#' -> i1, i2, ...).
    Module files can have ordinary pin names that happen to end in '#'."""
    own = cues.get(n)
    if own is not None and not own.endswith("#"):
        return own
    rep = max((k for k, v in cues.items() if v.endswith("#") and k <= n), default=None)
    if rep is not None:
        return cues[rep][:-1] + str(n - rep + 1)
    return own


def _pin_type(f: dict[str, str], key: str, n: int) -> str:
    """A module pin's type: its own SigType, else the nearest one before it (an array's pins
    share their first pin's type)."""
    k = max((i for i in range(1, n + 1) if f.get(f"{key}{i}")), default=None)
    return (f.get(f"{key}{k}") or "").lower() if k else ""


def module_fit_issues(prog: Program, s: Symbol, f: dict[str, str]) -> list[str]:
    """Why placed SIMPL+ module ``s`` doesn't fit the module build with Symbol fields ``f``:
    pin counts outside its ranges, or wired signals of the wrong type. [] when it fits."""
    r = s.record
    n1i, n2i, n1o = _int(r.get("n1I")), _int(r.get("n2I")), _int(r.get("n1O"))
    counts = {
        "digital inputs": (n1i, "MinVariableInputs", "MaxVariableInputs", 0),
        "analog/serial inputs": (n2i, "MinVariableInputsList2", "MaxVariableInputsList2", 0),
        "digital outputs": (n1o, "MinVariableOutputs", "MaxVariableOutputs", 0),
        "analog/serial outputs": (_int(r.get("mO")) - n1o, "MinVariableOutputsList2", "MaxVariableOutputsList2", 0),
        "parameters": (_int(r.get("mP")), "MinVariableParams", "MaxVariableParams", _int(f.get("NumFixedParams"))),
    }
    issues = []
    for what, (have, lo_k, hi_k, fixed) in counts.items():
        lo = fixed + _int(f.get(lo_k))
        hi = fixed + max(_int(f.get(hi_k)), _int(f.get(lo_k)))
        if not lo <= have <= hi:
            want = str(lo) if lo == hi else f"{lo} to {hi}"
            issues.append(f"{have} {what} placed, the module now has {want}")
    if not issues:
        builtin = set(prog.builtin_signals.values())
        for letter, pins, n1, k1, k2 in (("I", s.inputs, n1i, "InputSigType", "InputList2SigType"),
                                         ("O", s.outputs, n1o, "OutputSigType", "OutputList2SigType")):
            for n, h in sorted(pins.items()):
                sg = prog.signals.get(h)
                if sg is None or h in builtin:
                    continue
                t = (_pin_type(f, k1, n) or "digital") if n <= n1 else _pin_type(f, k2, n - n1)
                t = "serial" if t in ("string", "buffer") else t
                if t in ("digital", "analog", "serial") and sg.type != t:
                    issues.append(f"pin {letter}{n} is now {t}, but its signal \"{sg.name}\" is {sg.type}")
    return issues


def gui_extension_problems(prog: Program, program_path: Path | None) -> list[Problem]:
    """Panels whose Smart Graphics (.sgd) or CH5 contract (.chd) file SIMPL won't find, or whose source
    file changed since it was imported. SIMPL's help (GUI Extender Error Lookup, 285/286/313-316):
    without the file it comments out that panel's extenders; a changed source asks for a sync.
    Seen in SIMPL 4.32: without the program-folder copy, "Problems Loading Program" (2026-11-27)."""
    out: list[Problem] = []
    if program_path is None:
        return out
    for d in {id(x): x for x in prog.devices.values()}.values():
        ext = gui_extension(prog, d, program_path)
        if ext is None:
            continue
        who = f"{d.name or 'panel'} at {d.address or '?'}"
        sym = [d.symbol] if d.symbol is not None else []
        if not ext["found"]:
            out.append(Problem("warning", "SA-GUI-FILE-MISSING",
                               f"{who}: its {ext['kind']} file {ext['file']!r} isn't beside the program, nor SIMPL's "
                               "copy of it (<name>_ in the program folder). SIMPL will report problems loading the "
                               "program and comment out the panel's extenders.", symbols=sym))
        elif ext.get("source_changed"):
            out.append(Problem("notice", "SA-GUI-FILE-CHANGED",
                               f"{who}: {ext['file']!r} has changed since it was imported. SIMPL will offer to sync "
                               "the panel's extenders when the program is opened (Manage GUI Extenders).",
                               symbols=sym))
    return out


def module_problems(prog: Program, program_path: Path | None, installed: Path | None = None) -> list[Problem]:
    """Placed SIMPL+ modules that no longer fit their compiled module (.ush beside the program).

    SIMPL keeps a placed module's wires by position in each pin list, never by name (tested in
    SIMPL 4.32, 2026-11-25). When the module's pins change: added or retyped pins make the
    symbol incomplete, so nothing compiles; a removed pin compiles with notice 202 and the wires
    shift onto other pins. Pin counts outside the module's range and signals of the wrong type
    are caught here. Swapped or renamed pins leave no trace in the program (splus_compile
    reports those when it recompiles the module).
    """
    out: list[Problem] = []
    if program_path is None:
        return out
    for s in prog.symbols.values():
        if s.code != SPLUS_CODE:
            continue
        d = module_definition(program_path, s, installed)
        if d is None:
            continue
        issues = module_fit_issues(prog, s, d.fields)
        if issues:
            where = simpl_number(prog, s.handle) or f"#{s.handle}"
            out.append(Problem(
                "warning", "SA-MODULE-CHANGED",
                f"{s.name} at {where} no longer matches its compiled module: {'; '.join(issues[:4])}. SIMPL keeps "
                "the wires by position, so they may be on the wrong pins (or SIMPL won't compile). Re-place it: "
                "remove_symbol, then add_module with connect by pin name.",
                symbols=[s.handle]))
    return out


@dataclass
class Flow:
    """Who drives each signal and where it goes."""

    drivers: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))
    destinations: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))
    # Inside a macro: signals on the Argument Definition (the macro's own pins).
    arg_in: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))
    arg_out: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))


def signal_flow(prog: Program) -> Flow:
    f = Flow()
    for s in prog.symbols.values():
        if s.code == ARG_DEFINITION_CODE:
            # A macro's argument list, seen from inside the macro: its inputs are the
            # macro's incoming arguments (sources) and its outputs are the outgoing
            # arguments (destinations). Measured: undriven-signal counts in installed
            # macros equal the Argument Definition's input counts when this is ignored.
            # Kept apart from real drivers: inside macros an incoming argument often
            # also has a Buffer or module on it, which isn't a second driver.
            for n, sig in s.inputs.items():
                f.arg_in[sig].append((s.handle, n))
            for n, sig in s.outputs.items():
                f.arg_out[sig].append((s.handle, n))
            continue
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


def find_problems(prog: Program, lib: SymbolLibrary | None,
                  program_path: Path | None = None, installed: Path | None = None) -> list[Problem]:
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
        has_source = bool(drv or flow.arg_in.get(h))
        goes_out = bool(dst or flow.arg_out.get(h))
        if dst and not has_source:
            out.append(Problem("warning", "LGCMCVT102", f'Signal "{sg.name}" has no driving source.',
                               signal=sg.name, symbols=sorted({s for s, _ in dst})))
        if drv and not goes_out:
            out.append(Problem("notice", "LGCMCVT103", f'Signal "{sg.name}" has no destination.',
                               signal=sg.name, symbols=sorted({s for s, _ in drv})))
        if len(drv) > 1 and sg.type == "digital":
            def shares(sym_h: int) -> bool:
                ls = lib.get(prog.symbols[sym_h].code) if lib else None
                return bool(ls and ls.shares_outputs)
            # SIMPL doesn't report a second driver when a macro or SIMPL+ module is one of
            # the drivers: a real DMPS3 program with 9 such signals compiled with no
            # LGCMCVT220 (2026-11-24, docs/format.md "Real job").
            module = any(prog.symbols[s].code in MODULE_CODES for s, _ in drv)
            if not module and not all(shares(s) for s, _ in drv):
                for s, _ in drv[1:]:
                    where = simpl_number(prog, s) or f"#{s}"
                    out.append(Problem("warning", "LGCMCVT220",
                                       f'Signal "{sg.name}" on symbol {where} has a previously defined driving source.',
                                       signal=sg.name, symbols=[x for x, _ in drv]))

    for s in prog.symbols.values():
        # Parents inherit CF=1 from an incomplete child; report only the symbol itself.
        inherited = any(prog.symbols[c].record.get("CF") == "1" for c in s.children if c in prog.symbols)
        if s.record.get("CF") == "1" and not is_folder(s) and not inherited:
            out.append(Problem("warning", "SA-INCOMPLETE",
                               f"Symbol #{s.handle} ({display_name(s, lib)}) is marked incomplete by SIMPL: a required pin is empty.",
                               symbols=[s.handle]))
    out += module_problems(prog, program_path, installed)
    out += gui_extension_problems(prog, program_path)
    order = {"error": 0, "warning": 1, "notice": 2}
    out.sort(key=lambda p: order[p.severity])
    return out
