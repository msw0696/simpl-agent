"""Edit operations on a SIMPL program.

Rules (from docs/format.md):
- Change existing records in place; build records only for new things.
- New ``Sm``/``Sg`` records go at the end of their run (records are sorted by
  handle), with handle = max + 1. How SIMPL itself allocates is still unknown.
- Keys follow the order SIMPL 4.3x writes them.
- Only "simple" library symbols can be added for now: Smpl-C=1, DeviceCode=0,
  one pin list. For those the corpus shows n1I == mI and n1O == mO == tO.

Nothing here touches the disk; ``save.py`` does backups and writing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog.symlib import LibSymbol, SymbolLibrary
from .model import Program, Symbol, load
from .rawfile import RawFile, Record

SIGNAL_TYPE_CODES = {"digital": None, "analog": "2", "serial": "4"}
# SIMPL's help ("Naming Signals"): not starting with a digit; no , : ; or \; SIMPL turns a space into "_".
# Every signal name in the 380 public programs fits (2026-11-27).
NAME_RE = re.compile(r"^[^\x00-\x20\x7f-\xff0-9,:;\\][^\x00-\x20\x7f-\xff,:;\\]*$")
# SIMPL's help ("Edit Program Header"): letters, digits, - and _. All 294 corpus tags fit.
PIT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_NAME = 100
FOLDER_CODE = 156


class EditError(ValueError):
    """An edit that can't be applied. Nothing has been changed when this is raised."""


def check_parameter_value(d: LibSymbol | None, n: int, value: str, who: str, template: bool = False) -> None:
    """Refuse a parameter value SIMPL would reject or misread (SIMPL help: Compiler Errors 105-107,
    125; docs/format.md "Parameter values"). ``d`` is the symbol's definition, for its type.
    ``template``: the value is inside a macro file, where it may name the macro's own parameters
    (#Name, or \\[#Name\\] inside a string) for SIMPL to fill in, so only the one-line rule applies."""
    from .. import analysis as an

    if any(c in value for c in "\r\n"):
        raise EditError("a parameter value must be one line")
    if template:
        return
    issue = an.parameter_value_issue(value, an.parameter_type(d, n))
    if issue:
        name = (d.cues("ParamCue").get(n) if d is not None else None) or f"P{n}"
        raise EditError(f"{who}: parameter {name!r} = {value!r}: {issue[1]} (SIMPL: {issue[0]})")


@dataclass
class EditLog:
    lines: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.lines.append(text)


def is_simple(ls: LibSymbol) -> bool:
    """Library symbols add_symbol can build: Smpl-C=1, not a device, one pin list."""
    f = ls.fields
    return (
        f.get("Smpl-C") == "1"
        and f.get("DeviceCode", "0") == "0"
        and not any(k.startswith(("InputList2", "OutputList2", "InputList3", "OutputList3")) for k in f)
    )


def load_verified_codes() -> set[int] | None:
    """Simple-symbol codes whose 4.3x records the corpus proved (tools/build_verified_codes.py)."""
    path = Path(__file__).resolve().parents[1] / "catalog" / "verified_simple_codes.json"
    if not path.exists():
        return None
    return {int(c) for c in json.loads(path.read_text("utf-8"))["codes"]}


class Editor:
    def __init__(
        self,
        raw: RawFile,
        library: SymbolLibrary | None = None,
        verified_codes: set[int] | None | str = "default",
        program_path: Path | None = None,
        installed_modules: Path | None = None,
    ) -> None:
        """``verified_codes``: codes add_symbol may build; "default" loads the shipped list,
        None allows every simple symbol (tests only). ``program_path`` lets add_module find
        module files beside the program; ``installed_modules`` is SIMPL's Cresdb\\Modules."""
        self.raw = raw
        self.lib = library
        self.program_path = Path(program_path) if program_path else None
        self.installed_modules = installed_modules
        # Editing a macro file itself (.umc/.cmc): parameter values are templates (#Name).
        self.is_macro_file = bool(self.program_path and self.program_path.suffix.lower() in (".umc", ".cmc"))
        self.verified_codes = load_verified_codes() if verified_codes == "default" else verified_codes
        self.log = EditLog()
        self.prog: Program = load(raw)

    # ------------------------------------------------------------ helpers
    def _reload(self) -> None:
        self.prog = load(self.raw)

    def find_signal(self, ref: str | int) -> int:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.startswith("#") and ref[1:].isdigit()):
            h = int(str(ref).lstrip("#"))
            if h not in self.prog.signals:
                raise EditError(f"no signal #{h}")
            return h
        matches = [s.handle for s in self.prog.signals.values() if s.name.lower() == ref.lower()]
        if not matches:
            raise EditError(f"no signal named {ref!r}")
        return matches[0]

    def find_symbol(self, ref: str | int) -> int:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.startswith("#") and ref[1:].isdigit()):
            h = int(str(ref).lstrip("#"))
            if h not in self.prog.symbols:
                raise EditError(f"no symbol #{h}")
            return h
        raise EditError(f"refer to symbols by handle, e.g. '#31' (got {ref!r})")

    def find_folder(self, ref: str | int) -> int:
        """A folder by handle or by name (``Cmn1`` of a SmC 156 symbol). 'Logic' is the root."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.startswith("#")):
            h = self.find_symbol(ref)
            if self.prog.symbols[h].code != FOLDER_CODE:
                raise EditError(f"#{h} is not a folder")
            return h
        from ..analysis import display_name  # the name the read tools show (comment's first line)

        hits = [
            s.handle for s in self.prog.symbols.values()
            if s.code == FOLDER_CODE and display_name(s).lower() == ref.lower()
        ]
        if len(hits) != 1:
            raise EditError(f"{len(hits)} folders named {ref!r}; use a handle")
        return hits[0]

    def check_new_name(self, name: str, *, ignore: int | None = None) -> None:
        if not name or len(name) > MAX_NAME or name != name.strip() or not NAME_RE.match(name):
            raise EditError(
                f"bad signal name {name!r}: use printable ASCII, up to {MAX_NAME} characters, not starting with "
                "a digit, with no spaces (SIMPL uses _), commas, colons, semicolons or backslashes"
            )
        if name.lower() in ("0", "1", "local"):
            raise EditError(f"{name!r} is a built-in signal")
        for s in self.prog.signals.values():
            if s.handle != ignore and s.name.lower() == name.lower():
                raise EditError(f"signal {name!r} already exists (#{s.handle})")

    def _next_handle(self, obj_type: str, floor: int = 1) -> int:
        hs = [int(r.get("H")) for r in self.raw.of_type(obj_type) if (r.get("H") or "").isdigit()]
        return max([floor - 1, *hs]) + 1

    def _insert_record(self, rec: Record, obj_type: str, after_types: tuple[str, ...]) -> None:
        """Insert at the end of ``obj_type``'s run, or after the last of ``after_types``."""
        idx = None
        for i, it in enumerate(self.raw.items):
            if isinstance(it, Record) and it.type == obj_type:
                idx = i
        if idx is None:
            for i, it in enumerate(self.raw.items):
                if isinstance(it, Record) and it.type in after_types:
                    idx = i
        if idx is None:
            raise EditError(f"don't know where to put the first {obj_type} record")
        self.raw.items.insert(idx + 1, rec)

    # ------------------------------------------------------------ signals
    def rename_signal(self, ref: str | int, new_name: str) -> int:
        h = self.find_signal(ref)
        sig = self.prog.signals[h]
        if sig.record is None:
            raise EditError(f"{sig.name!r} is a built-in signal and can't be renamed")
        self.check_new_name(new_name, ignore=h)
        old = sig.name
        sig.record.set("Nm", new_name)
        self._reload()
        self.log.add(f"renamed signal #{h} {old!r} -> {new_name!r}")
        return h

    def add_signal(self, name: str, type: str = "digital") -> int:
        if type not in SIGNAL_TYPE_CODES:
            raise EditError(f"signal type must be one of {sorted(SIGNAL_TYPE_CODES)}")
        self.check_new_name(name)
        h = self._next_handle("Sg", floor=4)
        lines: list[tuple[str | None, str]] = [("ObjTp", "Sg"), ("H", str(h)), ("Nm", name)]
        if SIGNAL_TYPE_CODES[type]:
            lines.append(("SgTp", SIGNAL_TYPE_CODES[type]))
        self._insert_record(Record(lines=lines), "Sg", after_types=("Sm",))
        self._reload()
        self.log.add(f"added {type} signal #{h} {name!r}")
        return h

    def signal_for(self, ref: str | int | None, *, create_type: str | None = None) -> int | None:
        """Resolve a pin's signal; create it when it doesn't exist and ``create_type`` is given."""
        if ref is None or ref == "":
            return None
        try:
            return self.find_signal(ref)
        except EditError:
            if create_type is None or not isinstance(ref, str) or ref.startswith("#"):
                raise
            return self.add_signal(ref, create_type)

    # ------------------------------------------------------------ symbols
    def _simple_library_symbol(self, code: int) -> LibSymbol:
        if self.lib is None:
            raise EditError("the symbol library isn't loaded")
        ls = self.lib.get(code)
        if ls is None:
            raise EditError(f"symbol code {code} is not in the installed library")
        if not is_simple(ls):
            raise EditError(f"{ls.name!r} isn't a simple logic symbol; adding it isn't supported yet")
        if self.verified_codes is not None and code not in self.verified_codes:
            raise EditError(
                f"{ls.name!r} hasn't been seen in a SIMPL 4.3x file yet, so its record shape is unproven"
            )
        return ls

    def add_symbol(
        self,
        code: int,
        folder: str | int,
        inputs: list[str | int | None],
        outputs: list[str | int | None],
        params: list[str] | None = None,
        comment: str | None = None,
        new_signal_type: str = "digital",
        allow_second_driver: bool = False,
        allow_empty_pins: bool = False,
    ) -> int:
        """Add a simple logic symbol to ``folder``. Pins are wired by position.

        Signals named in ``inputs``/``outputs`` that don't exist yet are created
        as ``new_signal_type``. An output may not drive a signal that already
        has a driver unless the symbol shares outputs (Buffer and similar).
        ``allow_second_driver`` is only for format experiments.
        """
        ls = self._simple_library_symbol(code)
        parent = self.find_folder(folder)
        params = params or []
        f = ls.fields
        n_fixed_in = int(f.get("NumFixedInputs", "0"))
        n_fixed_out = int(f.get("NumFixedOutputs", "0"))
        n_fixed_par = int(f.get("NumFixedParams", "0"))
        max_vin = int(f.get("MaxVariableInputs", "0"))
        max_vout = int(f.get("MaxVariableOutputs", "0"))
        if not (n_fixed_in <= len(inputs) <= n_fixed_in + max_vin) and max_vin:
            raise EditError(f"{ls.name} takes {n_fixed_in}..{n_fixed_in + max_vin} inputs")
        if not max_vin and len(inputs) != n_fixed_in:
            raise EditError(f"{ls.name} takes exactly {n_fixed_in} inputs")
        if not max_vout and len(outputs) != n_fixed_out:
            raise EditError(f"{ls.name} takes exactly {n_fixed_out} outputs")
        if max_vout and not (n_fixed_out <= len(outputs) <= n_fixed_out + max_vout):
            raise EditError(f"{ls.name} takes {n_fixed_out}..{n_fixed_out + max_vout} outputs")
        if f.get("Expand") == "expand_inputs_with_outputs" and (
            len(inputs) - n_fixed_in != len(outputs) - n_fixed_out
        ):
            raise EditError(
                f"{ls.name}: each extra input comes with an output "
                f"({n_fixed_in} fixed inputs, {n_fixed_out} fixed outputs); got {len(inputs)} in, {len(outputs)} out"
            )
        if len(params) < n_fixed_par:
            raise EditError(f"{ls.name} needs {n_fixed_par} parameter(s): {list(ls.cues('ParamCue').values())}")
        for n, v in enumerate(params, 1):
            check_parameter_value(ls, n, str(v), ls.name, template=self.is_macro_file)

        if not allow_empty_pins and (any(r in (None, "") for r in inputs) or any(r in (None, "") for r in outputs)):
            # SIMPL marks a symbol with an empty required pin incomplete (CF=1); which pins are
            # optional isn't known yet, so every pin must be wired.
            raise EditError(f"{ls.name}: wire every input and output (use the built-in signals 0 or 1 for constants)")

        # Resolve everything before changing anything, so errors leave no trace.
        snapshot = self._snapshot()
        try:
            in_h = [self._typed_signal(r, ls, "I", n, new_signal_type) for n, r in enumerate(inputs, 1)]
            out_h = [self._typed_signal(r, ls, "O", n, new_signal_type) for n, r in enumerate(outputs, 1)]
            if not allow_second_driver:
                for sig in out_h:
                    if sig is not None:
                        self.check_can_drive(sig, ls)
            h = self._next_handle("Sm")
            hd = self.prog.header
            lines = simple_symbol_lines(
                handle=h, code=code, name=ls.name, smvr=hd.get("SmVr") if hd is not None else None,
                parent=parent, inputs=in_h, outputs=out_h, params=params, comment=comment,
            )
            self._insert_record(Record(lines=lines), "Sm", after_types=("Bw", "Bk"))
            self._append_child(parent, h)
        except Exception:
            self._restore(snapshot)
            raise
        self._reload()
        self.log.add(f"added {ls.name} #{h} in folder #{parent}")
        return h

    # ------------------------------------------------------------ shared rules and plumbing
    def _snapshot(self) -> list:
        return [it if isinstance(it, str) else Record(lines=list(it.lines), closed=it.closed) for it in self.raw.items]

    def _restore(self, snapshot: list) -> None:
        self.raw.items = snapshot
        self._reload()

    @staticmethod
    def pin_types(ls: LibSymbol | None, letter: str, n: int, record: Record | None = None) -> list[str]:
        """The signal types a library symbol's pin takes, from its Input/OutputSigType<n>;
        [] when the library doesn't say (then it's usually digital, but not always).

        Trusted only where the numbering is the library's: logic symbols with one pin list, and
        device symbols whose placed ``record`` uses list 1 only, for pins within it. Elsewhere it
        isn't (a DIN-1DIM4's pin 1 is analog though InputSigType1 says Digital: 50 such pins in
        the corpus). Checked on 380 corpus programs: 13,514 logic pins and 1,239 device pins
        (COM drivers included) all match, 0 mismatches.
        """
        if ls is None:
            return []
        f = ls.fields
        multi = ls.fields.get("HasExtraPinLists") == "True" or any("List2" in k or "List3" in k for k in f)
        if multi:
            if f.get("DeviceCode", "0") in ("", "0") or record is None:
                return []
            return Editor._device_list_pin_type(f, letter, n, record)
        if f.get("DeviceCode", "0") not in ("", "0"):
            n1 = record.get("n1I" if letter == "I" else "n1O") if record is not None else None
            if (record is None or any(k in record for k in ("n2I", "n2O", "n3I", "n3O"))
                    or not n1 or not n1.isdigit() or n > int(n1)):
                return []
        t = (ls.fields.get(f"{'Input' if letter == 'I' else 'Output'}SigType{n}") or "").lower()
        if "any" in t:
            return []
        return [k for k in ("digital", "analog", "serial") if k in t or (k == "serial" and "string" in t)]

    @staticmethod
    def _device_list_pin_type(f: dict[str, str], letter: str, n: int, record: Record) -> list[str]:
        """A pin's type on a device symbol with several pin lists (panels, EISCs, dimmers...).

        Pins are numbered through list 1, then list 2, then list 3, with the placed record's sizes
        (n1I, n2I; n1O, mO - n1O). A pin takes its own list's library type (the nearest one at or
        before it: arrays share it); an untyped list is digital, analog, serial for lists 1, 2, 3.
        Checked on every wired pin of such device symbols in the SIMPL 4.x corpus: 64,525 pins,
        0 exceptions (2026-11-25). A DIN-1DIM4 placed with no list-1 pins starts with list 2, so
        its pin 1 is analog although InputSigType1 says Digital.
        """
        def g(k: str) -> int:
            v = record.get(k)
            return int(v) if v and v.isdigit() else 0

        side = "Input" if letter == "I" else "Output"
        n1 = g("n1I") if letter == "I" else g("n1O")
        n2 = g("n2I") if letter == "I" else g("mO") - g("n1O")
        if n <= n1:
            lst, k, key = 1, n, f"{side}SigType"
        elif n <= n1 + n2:
            lst, k, key = 2, n - n1, f"{side}List2SigType"
        else:
            lst, k, key = 3, n - n1 - n2, f"{side}List3SigType"
        j = max((i for i in range(1, k + 1) if f.get(f"{key}{i}")), default=None)
        t = (f.get(f"{key}{j}") or "").lower() if j else ""
        if not t:
            return [("digital", "analog", "serial")[lst - 1]]
        if "any" in t:
            return []
        return [x for x in ("digital", "analog", "serial") if x in t or (x == "serial" and ("string" in t or "buffer" in t))]

    def _typed_signal(self, ref: str | int | None, ls: LibSymbol | None, letter: str, n: int,
                      default_type: str, record: Record | None = None) -> int | None:
        """A pin's signal: new signals get the pin's own type when it has exactly one (a Serial
        Send's out$ is serial), else ``default_type``. An existing signal of the wrong type is
        refused, as SIMPL won't connect it."""
        types = self.pin_types(ls, letter, n, record)
        h = self.signal_for(ref, create_type=types[0] if len(types) == 1 else default_type)
        if h is None or not types or h in set(self.prog.builtin_signals.values()):
            return h
        sg = self.prog.signals.get(h)
        if sg is not None and sg.type not in types and not sg.name.startswith("//"):
            name = (ls.cues("InputCue" if letter == "I" else "OutputCue").get(n) if ls else None) or f"{letter}{n}"
            raise EditError(f"pin {letter}{n} ({name}) takes {'/'.join(types)} signals, but {sg.name!r} is {sg.type}")
        return h

    def check_can_drive(self, sig: int, driver: LibSymbol | None) -> None:
        """Refuse an output that would give a digital signal a second driver.

        The same rule as find_problems' LGCMCVT220, confirmed by SIMPL 4.32: built-ins can't
        be driven; analog/serial signals and '//' placeholders may have several drivers;
        symbols that share outputs (Buffer...) may drive a signal together.
        """
        if sig in set(self.prog.builtin_signals.values()):
            raise EditError(f"the built-in signal {self.prog.signal_name(sig)!r} can't be driven")
        sg = self.prog.signals.get(sig)
        if sg is None or sg.type != "digital" or sg.name.startswith("//"):
            return
        drivers = [s for s in self.prog.symbols.values() if s.code != 55 and sig in s.outputs.values()]
        if not drivers:
            return
        lib_of = (lambda c: self.lib.get(c)) if self.lib else (lambda c: None)
        if driver is not None and driver.shares_outputs and all(
            (ls := lib_of(s.code)) is not None and ls.shares_outputs for s in drivers
        ):
            return
        raise EditError(
            f"signal {sg.name!r} already has a driver (#{drivers[0].handle}); SIMPL would warn LGCMCVT220. "
            "Only Buffers and similar symbols may share a digital signal."
        )

    def _symbol(self, ref: str | int, *, allow_folder: bool = False) -> Symbol:
        s = self.prog.symbols[self.find_symbol(ref)]
        if s.code == FOLDER_CODE and not allow_folder:
            raise EditError(f"#{s.handle} is a folder; use the folder operations")
        return s

    @staticmethod
    def _parse_pin(pin: str, letters: str) -> tuple[str, int]:
        p = str(pin).strip().upper()
        if len(p) < 2 or p[0] not in letters or not p[1:].isdigit() or int(p[1:]) < 1:
            raise EditError(f"pin must look like {' or '.join(c + '1' for c in letters)} (got {pin!r})")
        return p[0], int(p[1:])

    @staticmethod
    def _set_pin_key(rec: Record, letter: str, n: int, value: str | None) -> None:
        """Set (or remove, with None) pin key I<n>/O<n> in SIMPL's key order."""
        key = f"{letter}{n}"
        if value is None:
            rec.delete(key)
            return
        if key in rec:
            rec.set(key, value)
            return
        # After the highest existing pin of the same letter below n, else after the count key.
        anchor = {"I": "mI", "O": "tO"}[letter]
        best = -1
        for k in rec.keys():
            if len(k) > 1 and k[0] == letter and k[1:].isdigit() and best < int(k[1:]) < n:
                best = int(k[1:])
        rec.set(key, value, after=f"{letter}{best}" if best > 0 else anchor)

    def _rebuild_children(self, parent: int, children: list[int]) -> None:
        """Rewrite a folder's C1..Cn and mC (no mC when it's empty, as SIMPL writes it)."""
        rec = self.prog.symbols[parent].record
        idx = next((i for i, (k, _) in enumerate(rec.lines) if k == "mC"), None)
        rec.lines = [(k, v) for k, v in rec.lines
                     if not (k and k[0] == "C" and k[1:].isdigit()) and k != "mC"]
        if not children:
            return
        if idx is None:
            anchor = next((i for i, (k, _) in reversed(list(enumerate(rec.lines)))
                           if k and (k.startswith("Cmn") or k in ("OpF", "CF"))), len(rec.lines) - 1)
            idx = anchor + 1
        block = [("mC", str(len(children)))] + [(f"C{i}", str(c)) for i, c in enumerate(children, 1)]
        rec.lines[idx:idx] = block

    def _subtree(self, h: int) -> set[int]:
        out, todo = set(), [h]
        while todo:
            x = todo.pop()
            if x in out or x not in self.prog.symbols:
                continue
            out.add(x)
            todo.extend(self.prog.symbols[x].children)
        return out

    # ------------------------------------------------------------ pin, parameter and comment edits
    def connect(self, symbol: str | int, pin: str, signal: str | int | None,
                new_signal_type: str = "digital") -> None:
        """Wire an existing pin (I<n> or O<n>) to a signal, creating the signal if it's new.
        signal None disconnects the pin."""
        s = self._symbol(symbol)
        letter, n = self._parse_pin(pin, "IO")
        total = s.record.get("mI" if letter == "I" else "tO")
        if not total or not total.isdigit() or n > int(total):
            raise EditError(f"#{s.handle} has no pin {letter}{n} (it has {total or 0}); adding pins isn't supported yet")
        snapshot = self._snapshot()
        old = (s.inputs if letter == "I" else s.outputs).get(n)
        try:
            if signal in (None, ""):
                self._set_pin_key(s.record, letter, n, None)
                self._reload()
                self.release(old)
                self.log.add(f"disconnected #{s.handle} {letter}{n}" if old is not None
                             else f"#{s.handle} {letter}{n} was already unconnected")
                return
            sig = self._typed_signal(signal, self.lib.get(s.code) if self.lib else None, letter, n, new_signal_type,
                                     record=s.record)
            if letter == "O" and s.outputs.get(n) != sig:
                self.check_can_drive(sig, self.lib.get(s.code) if self.lib else None)
            self._set_pin_key(s.record, letter, n, str(sig))
        except Exception:
            self._restore(snapshot)
            raise
        self._reload()
        if old != sig:
            self.release(old)
        self.log.add(f"connected #{s.handle} {letter}{n} to {self.prog.signal_name(sig)!r}")

    def release(self, handle: int | None) -> None:
        """Note a signal a pin let go of; finish() removes it if nothing uses it by then."""
        if handle is not None:
            self.__dict__.setdefault("_released", set()).add(handle)

    def finish(self) -> list[str]:
        """End of an edit: remove signals pins let go of that nothing uses any more, as SIMPL does
        on its next save (it dropped one after a join was rewired, 2026-11-25). Returns their names."""
        names = self._drop_unused(self.__dict__.pop("_released", set()))
        if names:
            self.log.add(f"removed signals nothing uses any more: {names}")
        return names

    def _drop_unused(self, handles) -> list[str]:
        """Remove the given signals if no symbol uses them any more: SIMPL doesn't keep unused
        signals (it dropped one on re-save after a join was rewired, 2026-11-25). Returns names."""
        used = {h for o in self.prog.symbols.values() for h in list(o.inputs.values()) + list(o.outputs.values())}
        builtin = set(self.prog.builtin_signals.values())
        gone = sorted({h for h in handles if h not in used and h not in builtin and h in self.prog.signals
                       and self.prog.signals[h].record is not None})
        if not gone:
            return []
        names = [self.prog.signals[h].name for h in gone]
        drop = {id(self.prog.signals[h].record) for h in gone}
        self.raw.items = [it for it in self.raw.items if id(it) not in drop]
        self._reload()
        return names

    def set_parameter(self, symbol: str | int, pin: str, value: str) -> None:
        """Change an existing parameter P<n> (e.g. '5s', '50%', '10d')."""
        s = self._symbol(symbol)
        _, n = self._parse_pin(pin, "P")
        if f"P{n}" not in s.record:
            raise EditError(f"#{s.handle} has no parameter P{n} (it has {s.record.get('mP') or 0})")
        from .. import analysis as an

        if s.code in an.MODULE_CODES:
            d = an.module_definition(self.program_path, s, self.installed_modules) if self.program_path else None
        else:
            d = self.lib.get(s.code) if self.lib is not None else None
        check_parameter_value(d, n, str(value), f"#{s.handle}", template=self.is_macro_file)
        s.record.set(f"P{n}", str(value))
        self._reload()
        self.log.add(f"set #{s.handle} P{n} = {value!r}")

    def set_comment(self, ref: str | int, text: str) -> None:
        """Replace a symbol's whole comment. Line breaks become SIMPL's two-backslash breaks.
        Empty text removes it. Folders are renamed with rename_folder instead."""
        s = self._symbol(ref)
        rec = s.record
        if "\r" in text or "\\" in text:
            raise EditError("comments can't contain backslashes or carriage returns")
        encoded = "\\\\".join(line.rstrip() for line in text.split("\n")).strip()
        rec.lines = [(k, v) for k, v in rec.lines if not (k and k.startswith("Cmn"))]
        if encoded:
            anchor = next((k for k in ("n1O", "n2I", "n1I", "CF") if k in rec), None)
            rec.set("Cmn1", encoded, after=anchor)
        self._reload()
        self.log.add(f"set comment on #{s.handle}")

    def set_program_header(self, program_id_tag: str | None = None, program_name: str | None = None) -> None:
        """Project > Edit Program Header: the Program ID Tag (``PIT``, which SIMPL needs before it
        compiles; a new program leaves it blank) and the Program Name (``PgmNm``, between
        ``DvcDbVr`` and ``CltNm`` in SIMPL's saves)."""
        hd = self.prog.header
        if hd is None:
            raise EditError("this program has no header record")
        if program_id_tag is None and program_name is None:
            raise EditError("give program_id_tag and/or program_name")
        for label, v in (("program_id_tag", program_id_tag), ("program_name", program_name)):
            if v is not None and (not v.strip() or v != v.strip() or any(c in v for c in "\r\n\\[]=")):
                raise EditError(f"bad {label} {v!r}: one line, no surrounding spaces, no \\ [ ] =")
        if program_id_tag is not None and not PIT_RE.match(program_id_tag):
            raise EditError(f"bad program_id_tag {program_id_tag!r}: SIMPL allows letters, digits, - and _ only")
        if program_id_tag is not None:
            if "PIT" not in hd and "ZeroOnIoOk" not in hd:
                raise EditError("this header has no PIT line, and where SIMPL puts one isn't known for it")
            hd.set("PIT", program_id_tag, after="ZeroOnIoOk")
            self.log.add(f"set Program ID Tag to {program_id_tag!r}")
        if program_name is not None:
            if "PgmNm" not in hd and "DvcDbVr" not in hd:
                raise EditError("this header has no PgmNm line, and where SIMPL puts one isn't known for it")
            hd.set("PgmNm", program_name, after="DvcDbVr")
            self.log.add(f"set Program Name to {program_name!r}")
        self._reload()

    # ------------------------------------------------------------ folder and structure edits
    def rename_folder(self, folder: str | int, new_name: str) -> None:
        h = self.find_folder(folder)
        s = self.prog.symbols[h]
        if s.parent is None:
            raise EditError("the Logic folder can't be renamed")
        if not new_name or new_name != new_name.strip() or "\\" in new_name or any(c in new_name for c in "\r\n"):
            raise EditError(f"bad folder name {new_name!r}: one line, no backslashes")
        from ..analysis import comment_lines

        for c in self.prog.symbols[s.parent].children:
            o = self.prog.symbols.get(c)
            if o is not None and c != h and o.code == FOLDER_CODE and self._folder_name(o).lower() == new_name.lower():
                raise EditError(f"a folder named {new_name!r} is already there (#{c})")
        old = self._folder_name(s)
        lines = comment_lines(s)
        lines = [new_name] + lines[1:]
        rec = s.record
        rec.lines = [(k, v) for k, v in rec.lines if not (k and k.startswith("Cmn"))]
        anchor = next((k for k in reversed(rec.keys()) if k in ("OpF", "CF", "LogModDh", "PropF")), "PrH")
        rec.set("Cmn1", "\\\\".join(lines), after=anchor)
        self._reload()
        self.log.add(f"renamed folder #{h} {old!r} -> {new_name!r}")

    @staticmethod
    def _folder_name(s: Symbol) -> str:
        from ..analysis import display_name

        return display_name(s)

    def _check_movable(self, s: Symbol) -> None:
        if s.parent is None or s.parent not in self.prog.symbols:
            raise EditError(f"#{s.handle} is a top-level node and can't be moved or removed")
        if s.device is not None:
            raise EditError(f"#{s.handle} belongs to a device; device symbols can't be moved or removed yet")
        if self.prog.symbols[s.parent].code != FOLDER_CODE:
            raise EditError(f"#{s.handle} isn't in a Logic folder")

    def remove_symbol(self, ref: str | int) -> list[str]:
        """Remove a logic symbol, or an empty folder. Signals nothing uses any more are
        removed too (SIMPL doesn't keep unused signals). Returns those signals' names."""
        s = self._symbol(ref, allow_folder=True)
        self._check_movable(s)
        if s.code == FOLDER_CODE and s.children:
            raise EditError(f"folder #{s.handle} isn't empty; move or remove what's inside first")
        snapshot = self._snapshot()
        try:
            touched = set(s.inputs.values()) | set(s.outputs.values())
            parent = s.parent
            self._rebuild_children(parent, [c for c in self.prog.symbols[parent].children if c != s.handle])
            self.raw.items = [it for it in self.raw.items if it is not s.record]
            self._reload()
            names = self._drop_unused(touched)
            self._clear_folder_flags(parent)
        except Exception:
            self._restore(snapshot)
            raise
        self._reload()
        self.log.add(f"removed #{s.handle}" + (f" and unused signals {names}" if names else ""))
        return names

    def _incomplete_inside(self, folder: int) -> bool:
        for c in self.prog.symbols[folder].children:
            cs = self.prog.symbols.get(c)
            if cs is None:
                continue
            if cs.code == FOLDER_CODE:
                if self._incomplete_inside(c):
                    return True
            elif cs.record.get("CF") == "1":
                return True
        return False

    def _clear_folder_flags(self, folder: int | None) -> None:
        """SIMPL marks every folder above an incomplete symbol incomplete too (CF=1), and clears the
        mark when nothing incomplete is left inside: a folder is never marked without an incomplete
        symbol in it (0 of 7,547 corpus folders), and SIMPL 4.32 cleared it on re-save after a
        changed SIMPL+ module was replaced (2026-11-25). Walks up from ``folder``."""
        while folder is not None and folder in self.prog.symbols:
            f = self.prog.symbols[folder]
            if f.code != FOLDER_CODE:
                break
            if f.record.get("CF") == "1" and not self._incomplete_inside(folder):
                f.record.set("CF", "2")
            folder = f.parent

    def move_symbol(self, ref: str | int, folder: str | int) -> None:
        """Move a logic symbol or folder into another folder (to the end of it)."""
        s = self._symbol(ref, allow_folder=True)
        self._check_movable(s)
        target = self.find_folder(folder)
        if target in self._subtree(s.handle):
            raise EditError("a folder can't be moved into itself")
        if target == s.parent:
            return
        snapshot = self._snapshot()
        try:
            old = s.parent
            self._rebuild_children(old, [c for c in self.prog.symbols[old].children if c != s.handle])
            s.record.set("PrH", str(target))
            self._reload()
            self._append_child(target, s.handle)
            self._reload()
            self._clear_folder_flags(old)
        except Exception:
            self._restore(snapshot)
            raise
        self._reload()
        self.log.add(f"moved #{s.handle} to folder #{target}")

    # ------------------------------------------------------------ modules
    def module_definition(self, module: str):
        """A macro (.umc/.cmc) or SIMPL+ (.usp) module's definition and layout."""
        from .. import analysis as an

        name = str(module).strip()
        low = name.lower()
        if low.endswith((".umc", ".cmc")):
            code = an.MACRO_CODE
        elif low.endswith(".usp"):
            code = an.SPLUS_CODE
        else:
            raise EditError(f"module must be a .umc or .cmc macro or a .usp SIMPL+ module file name (got {name!r})")
        if any(c in name for c in "\\/:"):
            raise EditError("give the module's file name only; it must sit next to the program "
                            "(or, for Crestron .cmc macros, in SIMPL's installed modules)")
        probe = Symbol(handle=0, code=code, name=name, parent=None, children=[], inputs={}, outputs={},
                       params={}, device=None, comment=None, record=Record())
        d = an.module_definition(self.program_path, probe, self.installed_modules)
        if d is None:
            where = "next to the program" + (" or in SIMPL's installed modules" if code == an.MACRO_CODE else "")
            need = f"{name[:-4]}.ush (compile the SIMPL+ module in SIMPL once)" if code == an.SPLUS_CODE else name
            raise EditError(f"can't find {need} {where}")
        if code == an.SPLUS_CODE:
            if self.program_path is None or not (self.program_path.parent / name).exists():
                raise EditError(f"{name} must be next to the program so SIMPL can compile it")
            # SIMPL only adds a module that targets the program's control system, and comments out one
            # that doesn't (SIMPL help: Modules Targeting 4-Series; Warning 153). All 365 placed SIMPL+
            # modules in the corpus target their program's class.
            cls, targets = getattr(self, "processor_class", None), an.module_targets(d)
            if cls and targets and cls not in targets:
                want = an.SERIES_OF_CLASS.get(cls, f"class {cls}").lower().replace("-", "")
                built = ", ".join(an.SERIES_OF_CLASS.get(t, t) for t in targets)
                raise EditError(f"{name} was compiled for {built} only, but this program's processor is "
                                f"{an.SERIES_OF_CLASS.get(cls, cls)}: recompile it with splus_compile targets "
                                f"including '{want}'")
        # Modules with pin groups ([~BeginGroup~]) get per-pin group state (GrpStI/GrpStO) when SIMPL
        # saves them. It's display state: a Philips Hue Bridge placed without it compiled with 0 errors
        # in SIMPL 4.32 (F12 round 4, 2026-11-24), so these are allowed.
        return code, d, an.module_layout(code, d)

    def add_module(
        self,
        module: str,
        folder: str | int,
        connect: dict[str, str] | None = None,
        parameters: dict[str, str] | list[str] | None = None,
        comment: str | None = None,
        new_signal_type: str | None = None,
    ) -> int:
        """Place a macro or SIMPL+ module in ``folder`` and wire pins by name.

        ``connect`` maps pin names (as in the module file, or 'I3'/'O2') to signal names;
        pins not listed stay unconnected (normal for modules). New signals get the pin's
        type (digital/analog/serial) unless the pin takes any type, when
        ``new_signal_type`` decides. ``parameters`` gives every real parameter, in order or
        by name; placeholder slots ([~UNUSED~], [Reference Name]) stay empty.
        """
        from .. import analysis as an

        code, d, lay = self.module_definition(module)
        parent = self.find_folder(folder)
        connect = dict(connect or {})

        def index(letter: str) -> dict[str, int]:
            pins = lay["inputs"] if letter == "I" else lay["outputs"]
            names: dict[str, int] = {}
            for n, nm, _ in pins:
                names.setdefault(nm.lower(), n)
                names[f"{letter.lower()}{n}"] = n
            return names

        by_in, by_out = index("I"), index("O")
        in_pins = {n: (nm, t) for n, nm, t in lay["inputs"]}
        out_pins = {n: (nm, t) for n, nm, t in lay["outputs"]}
        wiring: list[tuple[str, int, str]] = []
        for pin, sig in connect.items():
            key = str(pin).strip().lower()
            letter = n = None
            if key in by_in and key not in by_out:
                letter, n = "I", by_in[key]
            elif key in by_out and key not in by_in:
                letter, n = "O", by_out[key]
            elif key in by_in and key in by_out:
                raise EditError(f"pin {pin!r} is both an input and an output; use 'I<n>' or 'O<n>'")
            else:
                raise EditError(f"{module} has no pin {pin!r}; see module_details for its pin names")
            nm, _ = (in_pins if letter == "I" else out_pins)[n]
            if nm == an.UNUSED_PIN:
                raise EditError(f"{letter}{n} is an unused placeholder pin in {module}")
            if sig in (None, ""):
                continue
            wiring.append((letter, n, sig))

        real_params = [(n, nm) for n, nm, _ in lay["parameters"] if nm not in (an.UNUSED_PIN, an.REFERENCE_NAME)]
        values = {n: "" for n, _, _ in lay["parameters"]}
        if isinstance(parameters, dict):
            lookup = {nm.lower(): n for n, nm in real_params}
            for k, v in parameters.items():
                if str(k).lower() not in lookup:
                    raise EditError(f"{module} has no parameter {k!r}; its parameters are {[nm for _, nm in real_params]}")
                values[lookup[str(k).lower()]] = str(v)
        elif parameters is not None:
            if len(parameters) != len(real_params):
                raise EditError(f"{module} takes {len(real_params)} parameter(s): {[nm for _, nm in real_params]}")
            for (n, _), v in zip(real_params, parameters, strict=True):
                values[n] = str(v)
        missing = [nm for n, nm in real_params if values[n] == ""]
        if missing:
            raise EditError(f"{module}: give a value for every parameter; missing {missing}")
        if any(c in v for v in values.values() for c in "\r\n"):
            raise EditError("parameter values must be one line")
        # Drop-down parameters (SIMPL+ propList): only listed values, as SIMPL's drop-down allows. The
        # label may be given instead. SIMPL stores the label too (Plb<n>, after P<n>); SIMPL 4.32 keeps
        # a record with or without it byte for byte, and shows the label.
        labels: dict[int, str] = {}
        if code == an.SPLUS_CODE:
            names = {n: nm for n, nm, _ in lay["parameters"]}
            for n, spec in an.splus_parameter_lists(self.program_path, str(module).strip()).items():
                if n not in values or values[n] == "":
                    continue
                v, opts = values[n], spec["options"]
                hit = (next((o for o in opts if o[0] == v), None)
                       or next((o for o in opts if o[1].lower() == v.lower()), None)
                       or next((o for o in opts if o[0].lower() == v.lower()), None))
                if hit is None:
                    shown = ", ".join(f"{val} ({lbl})" for val, lbl in opts)
                    raise EditError(f"{module}: parameter {names.get(n, n)!r} is a drop-down; give one of {shown}")
                values[n] = hit[0]
                if hit[1]:
                    labels[n] = hit[1]
        for n, v in values.items():
            check_parameter_value(d, n, v, str(module), template=self.is_macro_file)

        # SIMPL requires every pin with a plain name (9,963 of 9,963 wired in the corpus);
        # [bracketed] pins are optional. Unused required pins get SIMPL's standard placeholder
        # for the pin's type, as programmers do (//__digital_reserved__ and friends).
        wired = {(letter, n) for letter, n, _ in wiring}
        placeholders: list[str] = []
        for letter, pins in (("I", lay["inputs"]), ("O", lay["outputs"])):
            n1 = lay["n1I"] if letter == "I" else lay["n1O"]
            for n, nm, t in pins:
                if (letter, n) in wired or nm == an.UNUSED_PIN or nm.startswith("["):
                    continue
                t = (t or "").lower()
                if not t and code == an.SPLUS_CODE and n <= n1:
                    t = "digital"
                kinds = [k for k in ("digital", "analog", "serial") if k in t or (k == "serial" and "string" in t)]
                if len(kinds) != 1:
                    raise EditError(f"{module}: pin {letter}{n} ({nm}) must be connected and can take any signal "
                                    "type, so give it a signal in 'connect'")
                wiring.append((letter, n, f"//__{kinds[0]}_reserved__"))
                placeholders.append(f"{letter}{n} {nm}")

        snapshot = self._snapshot()
        try:
            ins: dict[int, int] = {}
            outs: dict[int, int] = {}
            for letter, n, sig in wiring:
                pin_type = ((in_pins if letter == "I" else out_pins)[n][1] or "").lower()
                n1 = lay["n1I"] if letter == "I" else lay["n1O"]
                if not pin_type and code == an.SPLUS_CODE and n <= n1:
                    pin_type = "digital"  # untyped first-list SIMPL+ pins: digital in 1,698 of 1,698
                fixed = [t for t in ("digital", "analog", "serial") if t in pin_type or (t == "serial" and "string" in pin_type)]
                create = fixed[0] if len(fixed) == 1 else (new_signal_type or None)
                try:
                    h = self.signal_for(sig, create_type=create)
                except EditError:
                    if create is None:
                        raise EditError(f"pin {letter}{n} takes more than one signal type; set new_signal_type "
                                        f"for new signal {sig!r}") from None
                    raise
                sg = self.prog.signals.get(h)
                builtin = h in set(self.prog.builtin_signals.values())
                if fixed and sg is not None and not builtin and sg.type not in fixed:
                    raise EditError(f"pin {letter}{n} ({(in_pins if letter == 'I' else out_pins)[n][0]}) takes "
                                    f"{'/'.join(fixed)} signals, but {sg.name!r} is {sg.type}")
                if letter == "O":
                    self.check_can_drive(h, d)
                    outs[n] = h
                else:
                    ins[n] = h
            h = self._next_handle("Sm")
            lines = module_lines(
                handle=h, code=code, name=str(module).strip(), objver=d.fields.get("ObjVer") or "1",
                parent=parent, n1i=lay["n1I"], n2i=lay["n2I"], n1o=lay["n1O"], n2o=lay["n2O"],
                inputs=ins, outputs=outs, params=[values[n] for n, _, _ in lay["parameters"]], comment=comment,
                param_labels=labels,
            )
            self._insert_record(Record(lines=lines), "Sm", after_types=("Bw", "Bk"))
            self._append_child(parent, h)
        except Exception:
            self._restore(snapshot)
            raise
        self._reload()
        self.log.add(f"added module {module} #{h} in folder #{parent}"
                     + (f"; {len(placeholders)} unused required pins on SIMPL's //__…_reserved__ placeholders"
                        if placeholders else ""))
        return h

    def _append_child(self, parent: int, child: int) -> None:
        rec = self.prog.symbols[parent].record
        n = int(rec.get("mC") or 0) + 1
        if "mC" in rec:
            rec.set("mC", str(n))
            last = f"C{n - 1}" if n > 1 else "mC"
            rec.set(f"C{n}", str(child), after=last)
        else:
            # Folder with no children yet: mC then C1 go after Cmn*/CF (SIMPL's order).
            anchor = next((k for k in reversed(rec.keys()) if k.startswith("Cmn") or k in ("OpF", "CF")), None)
            rec.set("mC", "1", after=anchor)
            rec.set("C1", str(child), after="mC")

    def add_device(self, devlib, device: str | int, address: str | int, network: str | int | None = None,
                   parameters: dict | list | None = None, connect: dict | None = None) -> int:
        """Place a device at a free address (IP ID) on a network; see device_edit.py."""
        from .device_edit import add_device

        return add_device(self, devlib, device, address, network, parameters=parameters, connect=connect)

    def wire_joins(self, symbol: str | int, joins: list[dict], keep_existing: bool = False) -> list[str]:
        """Connect a panel's or EISC's joins by type and number; see joins.py."""
        from .joins import wire_joins

        return wire_joins(self, symbol, joins, keep_existing=keep_existing)

    def remove_device(self, devlib, device: str | int) -> list[str]:
        """Remove a device and everything inside it, as SIMPL's Delete does; see device_edit.py."""
        from .device_edit import remove_device

        return remove_device(self, devlib, device)

    def add_folder(self, name: str, parent: str | int = "Logic") -> int:
        """Add an empty folder (subsystem) inside ``parent``, the way SIMPL 4.3x writes one."""
        if not name or name != name.strip() or "\\" in name or "\r" in name or "\n" in name or len(name) > MAX_NAME:
            raise EditError(f"bad folder name {name!r}: one line, no backslashes, up to {MAX_NAME} characters")
        par = self.find_folder(parent)
        from ..analysis import display_name

        for c in self.prog.symbols[par].children:
            s = self.prog.symbols.get(c)
            if s is not None and s.code == FOLDER_CODE and display_name(s).lower() == name.lower():
                raise EditError(f"folder {name!r} already exists there (#{c})")
        snapshot = [it if isinstance(it, str) else Record(lines=list(it.lines), closed=it.closed) for it in self.raw.items]
        try:
            h = self._next_handle("Sm")
            hd = self.prog.header
            lines = folder_lines(handle=h, smvr=hd.get("SmVr") if hd is not None else None,
                                 parent=par, name=name, children=[])
            self._insert_record(Record(lines=lines), "Sm", after_types=("Bw", "Bk"))
            self._append_child(par, h)
        except Exception:
            self.raw.items = snapshot
            self._reload()
            raise
        self._reload()
        self.log.add(f"added folder {name!r} #{h} in #{par}")
        return h


def module_lines(
    *,
    handle: int,
    code: int,
    name: str,
    objver: str,
    parent: int,
    n1i: int,
    n2i: int,
    n1o: int,
    n2o: int,
    inputs: dict[int, int],
    outputs: dict[int, int],
    params: list[str],
    comment: str | list[str] | None,
    param_labels: dict[int, str] | None = None,
) -> list[tuple[str | None, str]]:
    """The record SIMPL 4.3x writes for a placed macro (155) or SIMPL+ module (103).
    ``param_labels`` are drop-down labels (Plb<n>, right after P<n>).

    No SmVr. Count keys of zero are left out; SIMPL+ never stores n2O (its list-2
    outputs still count in mO/tO). Pins are sparse. Proven by rebuilding placed
    modules from the corpus exactly (tests/test_modules.py).
    """
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Sm"), ("H", str(handle)), ("SmC", str(code)), ("Nm", name), ("ObjVer", objver),
        ("PrH", str(parent)), ("CF", "2"),
    ]
    counts = [("n1I", n1i), ("n2I", n2i), ("n1O", n1o)] + ([("n2O", n2o)] if code == 155 else [])
    lines += [(k, str(v)) for k, v in counts if v]
    comments = [comment] if isinstance(comment, str) else list(comment or [])
    lines += [(f"Cmn{i}", c) for i, c in enumerate(comments, 1)]
    mi, mo = n1i + n2i, n1o + n2o
    if mi:
        lines.append(("mI", str(mi)))
        lines += [(f"I{n}", str(h)) for n, h in sorted(inputs.items())]
    if mo:
        lines += [("mO", str(mo)), ("tO", str(mo))]
        lines += [(f"O{n}", str(h)) for n, h in sorted(outputs.items())]
    if params:
        lines.append(("mP", str(len(params))))
        for i, v in enumerate(params, 1):
            lines.append((f"P{i}", v))
            if param_labels and i in param_labels:
                lines.append((f"Plb{i}", param_labels[i]))
    return lines


def folder_lines(
    *, handle: int, smvr: str | None, parent: int, name: str | list[str], children: list[int]
) -> list[tuple[str | None, str]]:
    """The record SIMPL 4.3x writes for a folder: Nm=SUBSYSTEM, the name in Cmn1."""
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Sm"), ("H", str(handle)), ("SmC", str(FOLDER_CODE)), ("Nm", "SUBSYSTEM"), ("ObjVer", "1"),
    ]
    if smvr:
        lines.append(("SmVr", smvr))
    lines += [("PrH", str(parent)), ("CF", "2")]
    comments = [name] if isinstance(name, str) else list(name)
    lines += [(f"Cmn{i}", c) for i, c in enumerate(comments, 1)]
    if children:
        lines.append(("mC", str(len(children))))
        lines += [(f"C{i}", str(c)) for i, c in enumerate(children, 1)]
    return lines


def simple_symbol_lines(
    *,
    handle: int,
    code: int,
    name: str,
    smvr: str | None,
    parent: int,
    inputs: list[int | None],
    outputs: list[int | None],
    params: list[str],
    comment: str | list[str] | None,
) -> list[tuple[str | None, str]]:
    """The record SIMPL 4.3x writes for a simple logic symbol (see docs/format.md).

    Counts of zero are left out (no ``n1O``/``mO``/``tO`` for a symbol with no
    outputs). A comment may span several ``Cmn<n>`` keys.
    """
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Sm"), ("H", str(handle)), ("SmC", str(code)), ("Nm", name), ("ObjVer", "1"),
    ]
    if smvr:
        lines.append(("SmVr", smvr))
    lines += [("PrH", str(parent)), ("CF", "2")]
    if inputs:
        lines.append(("n1I", str(len(inputs))))
    if outputs:
        lines.append(("n1O", str(len(outputs))))
    comments = [comment] if isinstance(comment, str) else list(comment or [])
    lines += [(f"Cmn{i}", c) for i, c in enumerate(comments, 1)]
    if inputs:
        lines.append(("mI", str(len(inputs))))
        lines += [(f"I{i}", str(s)) for i, s in enumerate(inputs, 1) if s is not None]
    if outputs:
        lines += [("mO", str(len(outputs))), ("tO", str(len(outputs)))]
        lines += [(f"O{i}", str(s)) for i, s in enumerate(outputs, 1) if s is not None]
    if params:
        lines.append(("mP", str(len(params))))
        lines += [(f"P{i}", v) for i, v in enumerate(params, 1)]
    return lines


def symbol_summary(p: Program, s: Symbol) -> str:
    ins = ", ".join(f"I{n}={p.signal_name(h)}" for n, h in sorted(s.inputs.items()))
    outs = ", ".join(f"O{n}={p.signal_name(h)}" for n, h in sorted(s.outputs.items()))
    return f"#{s.handle} {s.name or s.code}: {ins} -> {outs}"
