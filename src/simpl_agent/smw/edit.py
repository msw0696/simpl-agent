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
NAME_RE = re.compile(r"^[^\x00-\x20\x7f-\xff0-9][\x20-\x7e]*$")
MAX_NAME = 100
FOLDER_CODE = 156


class EditError(ValueError):
    """An edit that can't be applied. Nothing has been changed when this is raised."""


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
    ) -> None:
        """``verified_codes``: codes add_symbol may build; "default" loads the shipped list,
        None allows every simple symbol (tests only)."""
        self.raw = raw
        self.lib = library
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
        hits = [
            s.handle for s in self.prog.symbols.values()
            if s.code == FOLDER_CODE and ((s.comment or s.name or "").rstrip("\\").lower() == ref.lower())
        ]
        if len(hits) != 1:
            raise EditError(f"{len(hits)} folders named {ref!r}; use a handle")
        return hits[0]

    def check_new_name(self, name: str, *, ignore: int | None = None) -> None:
        if not name or len(name) > MAX_NAME or name != name.strip() or not NAME_RE.match(name):
            raise EditError(
                f"bad signal name {name!r}: use printable ASCII, up to {MAX_NAME} characters, "
                "not starting with a digit or space"
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

        # Resolve everything before changing anything, so errors leave no trace.
        snapshot = [it if isinstance(it, str) else Record(lines=list(it.lines), closed=it.closed) for it in self.raw.items]
        try:
            in_h = [self.signal_for(r, create_type=new_signal_type) for r in inputs]
            out_h = [self.signal_for(r, create_type=new_signal_type) for r in outputs]
            if not ls.shares_outputs and not allow_second_driver:
                driven = {sig for s in self.prog.symbols.values() if s.code != 55 for sig in s.outputs.values()}
                for sig in out_h:
                    if sig is not None and (sig in driven or sig <= 3):
                        raise EditError(f"signal {self.prog.signal_name(sig)!r} already has a driver")
            h = self._next_handle("Sm")
            hd = self.prog.header
            lines = simple_symbol_lines(
                handle=h, code=code, name=ls.name, smvr=hd.get("SmVr") if hd is not None else None,
                parent=parent, inputs=in_h, outputs=out_h, params=params, comment=comment,
            )
            self._insert_record(Record(lines=lines), "Sm", after_types=("Bw", "Bk"))
            self._append_child(parent, h)
        except Exception:
            self.raw.items = snapshot
            self._reload()
            raise
        self._reload()
        self.log.add(f"added {ls.name} #{h} in folder #{parent}")
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

    def set_comment(self, ref: str | int, text: str) -> None:
        h = self.find_symbol(ref)
        rec = self.prog.symbols[h].record
        if "\r" in text or "\n" in text:
            raise EditError("comments must be one line")
        anchor = next((k for k in ("n1O", "n2I", "n1I", "CF") if k in rec), None)
        rec.set("Cmn1", text, after=anchor)
        self._reload()
        self.log.add(f"set comment on #{h}")


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
