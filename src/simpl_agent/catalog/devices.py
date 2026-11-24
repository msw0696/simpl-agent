"""SIMPL's device library, Cresdb\\Programming\\iodev.tio (same [BEGIN]/[END] format as symlib).

IoDevice records describe devices: Code (Dv.DvC), Name, the slot types they can occupy
(Occupy1..n, matched against a slot record's Nm), their logic symbol (SymbolCode), default
network address and IP, and child slots (Expand*/Fixed*). Slot records describe slot types.
Read from the local install at run time and cached under %LOCALAPPDATA% like the symbol
library; never copied into the repo.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .index import cache_dir
from .symlib import parse_tio

DEFAULT_IODEV = Path(r"C:\Program Files (x86)\Crestron\Cresdb\Programming\iodev.tio")
INDEX_VERSION = 1


@dataclass
class DeviceDef:
    code: int
    name: str
    fields: dict[str, str]

    def numbered(self, prefix: str) -> list[str]:
        out = []
        n = 1
        while f"{prefix}{n}" in self.fields:
            out.append(self.fields[f"{prefix}{n}"])
            n += 1
        return out

    @property
    def occupies(self) -> list[str]:
        """Slot type names this device may sit in (e.g. P4Ethernet)."""
        return self.numbered("Occupy")

    @property
    def symbol_code(self) -> int | None:
        v = self.fields.get("SymbolCode", "")
        return int(v) if v.lstrip("-").isdigit() else None


@dataclass
class DeviceLibrary:
    source: str
    devices: dict[int, DeviceDef]
    slots: dict[str, dict[str, str]]  # slot records by Name

    def get(self, code: int | None) -> DeviceDef | None:
        return self.devices.get(code) if code is not None else None

    def find(self, name: str) -> list[DeviceDef]:
        q = name.strip().lower()
        exact = [d for d in self.devices.values() if d.name.lower() == q]
        if exact:
            return exact
        return sorted((d for d in self.devices.values() if q in d.name.lower()), key=lambda d: (len(d.name), d.name))

    def for_slot(self, slot_name: str) -> list[DeviceDef]:
        return [d for d in self.devices.values() if slot_name in d.occupies]


def _build(path: Path) -> dict:
    recs = parse_tio(path.read_bytes().decode("latin-1"))
    devices, slots = {}, {}
    for r in recs:
        t = r.get("ObjTp")
        if t == "IoDevice" and r.get("Code", "").lstrip("-").isdigit():
            devices[r["Code"]] = r
        elif t == "Slot" and r.get("Name"):
            slots[r["Name"]] = r
    st = path.stat()
    return {"version": INDEX_VERSION, "source": str(path), "size": st.st_size, "mtime": st.st_mtime,
            "devices": devices, "slots": slots}


def load_devices(path: Path = DEFAULT_IODEV, cache: Path | None = None) -> DeviceLibrary:
    cache = cache or (cache_dir() / "iodev-index.json")
    st = path.stat()
    data = None
    if cache.exists():
        try:
            data = json.loads(cache.read_text("utf-8"))
            if not (data.get("version") == INDEX_VERSION and data.get("source") == str(path)
                    and data.get("size") == st.st_size and data.get("mtime") == st.st_mtime):
                data = None
        except (OSError, ValueError):
            data = None
    if data is None:
        data = _build(path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), "utf-8")
        os.replace(tmp, cache)
    devs = {int(k): DeviceDef(code=int(k), name=v.get("Name", ""), fields=v) for k, v in data["devices"].items()}
    return DeviceLibrary(source=data["source"], devices=devs, slots=data["slots"])
