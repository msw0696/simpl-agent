"""Semantic view over a RawFile: signals, symbols, devices.

Read-only for now (M0). Every object keeps a reference to its raw Record, so
later edit ops change records in place. Field meanings are hypotheses checked
against the corpus by ``tools/corpus_check.py``; see ``docs/format.md``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rawfile import RawFile, Record

PIN_KEY = re.compile(r"^([IOPC])(\d+)$")

# Signal type codes seen in Sg.SgTp. A missing SgTp means digital.
SIGNAL_TYPES = {None: "digital", "2": "analog", "4": "serial"}


def parse_handles(text: str | None) -> list[int]:
    """Parse a handle list such as ``7``, ``7.258`` or ``515,551.553``.

    ``a.b`` is the inclusive range a..b; items are comma separated.
    """
    if not text:
        return []
    out: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.partition(".")
        a = int(lo)
        b = int(hi) if hi else a
        out.extend(range(a, b + 1))
    return out


def format_handles(handles: list[int]) -> str:
    """Inverse of parse_handles: consecutive runs as 'a.b', joined by commas
    (round-trips every Dv handle list in the corpus, 40,917 of 40,917)."""
    hs = sorted(handles)
    out, i = [], 0
    while i < len(hs):
        j = i
        while j + 1 < len(hs) and hs[j + 1] == hs[j] + 1:
            j += 1
        out.append(str(hs[i]) if i == j else f"{hs[i]}.{hs[j]}")
        i = j + 1
    return ",".join(out)


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def numbered(rec: Record, letter: str) -> dict[int, str]:
    """``{n: value}`` for keys like I1, I2 ... (sparse: missing means unconnected)."""
    out: dict[int, str] = {}
    for k, v in rec.lines:
        if k and k[0] == letter:
            m = PIN_KEY.match(k)
            if m and m.group(1) == letter:
                out[int(m.group(2))] = v
    return out


@dataclass
class Signal:
    handle: int
    name: str
    type: str
    record: Record | None = None  # None for the built-in 0 / 1 / Local signals


@dataclass
class Symbol:
    handle: int
    code: int | None  # SmC: index into the symbol library (symlib.tio)
    name: str | None  # Nm: instance name, if any
    parent: int | None  # PrH
    children: list[int]  # C1..C{mC}
    inputs: dict[int, int]  # pin number -> signal handle (I*)
    outputs: dict[int, int]  # pin number -> signal handle (O*)
    params: dict[int, str]  # pin number -> literal value (P*)
    device: int | None  # DvH
    comment: str | None  # Cmn1
    record: Record


@dataclass
class Device:
    handles: list[int]  # a Dv record can cover a range of handles (empty slots)
    name: str | None
    parent: int | None
    children: list[int]
    address: str | None  # Ad: slot or ID (hex for IP / Cresnet IDs)
    code: int | None  # DvC: device database code
    symbol: int | None  # SmH
    record: Record


@dataclass
class Program:
    raw: RawFile
    header: Record | None
    signature: Record | None
    signals: dict[int, Signal] = field(default_factory=dict)
    symbols: dict[int, Symbol] = field(default_factory=dict)
    devices: dict[int, Device] = field(default_factory=dict)

    @property
    def kind(self) -> str | None:
        return self.signature.get("Sgntr") if self.signature else None

    @property
    def builtin_signals(self) -> dict[str, int]:
        """Handles SIMPL reserves for the constant signals, from the header."""
        h = self.header
        if h is None:
            return {}
        out = {}
        for key, name in (("S0Nd", "0"), ("S1Nd", "1"), ("SLNd", "Local")):
            v = _int(h.get(key))
            if v is not None:
                out[name] = v
        return out

    def signal_name(self, handle: int) -> str:
        s = self.signals.get(handle)
        return s.name if s else f"#{handle}?"


def load(raw: RawFile) -> Program:
    prog = Program(raw=raw, header=raw.first("Hd"), signature=raw.first("FSgntr"))
    for name, h in prog.builtin_signals.items():
        prog.signals[h] = Signal(handle=h, name=name, type="digital")

    for rec in raw.records:
        t = rec.type
        if t == "Sg":
            h = _int(rec.get("H"))
            if h is None:
                continue
            prog.signals[h] = Signal(
                handle=h,
                name=rec.get("Nm", "") or "",
                type=SIGNAL_TYPES.get(rec.get("SgTp"), f"type{rec.get('SgTp')}"),
                record=rec,
            )
        elif t == "Sm":
            h = _int(rec.get("H"))
            if h is None:
                continue
            prog.symbols[h] = Symbol(
                handle=h,
                code=_int(rec.get("SmC")),
                name=rec.get("Nm"),
                parent=_int(rec.get("PrH")),
                children=[int(v) for _, v in sorted(numbered(rec, "C").items()) if _int(v) is not None],
                inputs={n: int(v) for n, v in numbered(rec, "I").items() if _int(v) is not None},
                outputs={n: int(v) for n, v in numbered(rec, "O").items() if _int(v) is not None},
                params=numbered(rec, "P"),
                device=_int(rec.get("DvH")),
                comment=rec.get("Cmn1"),
                record=rec,
            )
        elif t == "Dv":
            hs = parse_handles(rec.get("H"))
            dev = Device(
                handles=hs,
                name=rec.get("Nm"),
                parent=_int(rec.get("PrH")),
                children=[int(v) for _, v in sorted(numbered(rec, "C").items()) if _int(v) is not None],
                address=rec.get("Ad"),
                code=_int(rec.get("DvC")),
                symbol=_int(rec.get("SmH")),
                record=rec,
            )
            for h in hs:
                prog.devices[h] = dev
    return prog
