"""Adding a device the way SIMPL 4.3x does (docs/format.md "Adding a device").

Decoded from a SIMPL 4.32 save of an empty CP4N, then a TSW-1070 at IP ID 03, then an
EISC at 04 (f12-round5). Every rule here reproduces those files byte for byte, and the
built-in CP4N records in the same file (tests/test_device_edit.py).

What SIMPL writes for a device placed at a free address:
- Every free address of a slot type sits in one record (a handle list with gaps). The
  slot at the chosen address leaves it, keeps its handle and gets ``mC=1 C1=<device>``.
- The device's own slots: position n has slot type ``Expand<n>`` (a missing n repeats the
  previous type and its fixed device), up to MaxSlots. ``Fixed<n>`` names a device SIMPL puts
  there itself, recursively. Handles go depth first: device, then each position's slot followed
  by the subtree of its fixed device. Empty slots of one type share a record (at most 501 slots,
  then another record). Slot addresses are decimal unless the slot type says HEX; IR and power
  slots carry ``SlF=Ex``. A device in a slot carries the slot's SlC; one on a network doesn't.
- Devices are named by iodev InstanceName (else Name). A Db record (Whc=3, Mnf=Crestron,
  Mdl=<Name>) for the device on the network, and an Et record when the library gives the
  device a default IP address.
- A logic symbol for each device that has one (``SymbolCode``), under the nearest ancestor's
  symbol; the network's container symbol lists its devices in address order. Pin counts come
  from the symbol library: each of the three lists is MinVariable* if given, else Expand_by
  when the list exists. Only n1I, n2I and n1O are stored; mI is every input, mO output lists
  1+2, tO every output.

Any device whose shape these rules cover can be added. tools/prove_devices.py rebuilds every
such device subtree in the public corpus and compares it with what SIMPL saved.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..catalog.devices import DeviceDef, DeviceLibrary
from .model import Device, format_handles, parse_handles
from .rawfile import Record

if TYPE_CHECKING:
    from ..catalog.symlib import LibSymbol
    from .edit import Editor

# Device codes whose records were proven by a SIMPL 4.32 save (f12-round5): the device and
# any fixed children. Others need their own proof round first.
# Network ID slots (IP IDs, Cresnet IDs) whose devices follow these rules in the corpus: no SlC, a Db
# record, free IDs in one record. P4Ethernet is also proven by SIMPL 4.32 saves (f12-round5/6).
PROVEN_SLOTS = {"P4Ethernet", "P3Ethernet", "MC3Ethernet", "P4Cresnet", "P3Cresnet"}
NETWORK_LABELS = {"P4Ethernet": "Ethernet IP ID (4-Series)", "P3Ethernet": "Ethernet IP ID (3-Series)",
                  "MC3Ethernet": "Ethernet IP ID (MC3)", "P4Cresnet": "Cresnet ID (4-Series)",
                  "P3Cresnet": "Cresnet ID (3-Series)"}
NOT_USED = {"Not_Used", "NotUsed"}
ADDRESS_RE = re.compile(r"^(?:0x)?([0-9A-Fa-f]{1,2})$")
LISTS = ("", "List2", "List3")
PARAM_DEFAULTS = {"PermanentStringSize": "255d"}
# A device symbol's "Name" parameter starts as the device's own name (17 of 17 corpus devices
# not renamed since; the 52 others were renamed by users, the parameter keeping the original).
NAME_PARAM = "Name"


def _slot_rules() -> dict:
    """How SIMPL writes a device a user puts into a slot (tools/build_slot_rules.py): per device code,
    and per slot type where every instance agrees."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "catalog" / "slot_device_rules.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


_RULES = _slot_rules()
SLOT_DEVICE_RULES = {int(c): r for c, r in _RULES.get("codes", {}).items()}
SLOT_TYPE_RULES: dict[str, dict] = dict(_RULES.get("slot_types", {}))
# Card types proven by SIMPL 4.32 saves that the corpus doesn't show (f12-round8).
SLOT_DEVICE_RULES.setdefault(5917, {"slc": False, "db": True, "seen": 0})  # DMC-4KZ-C-DSP


def address_for_slot(address: str | int, slot_info: dict) -> str:
    """The address text SIMPL uses in a slot of this type: hex IDs, else decimal positions."""
    if slot_info.get("AddressFormat") == "HEX":
        return normalise_address(address)
    text = str(address).strip()
    if not text.isdigit() or not 0 < int(text) < 10000:
        raise ValueError(f"bad slot number {address!r}: give a number such as 1 or '01'")
    return f"{int(text):02d}"


def normalise_address(address: str | int) -> str:
    """'3', '03', '0x03' or 3 -> '03' (IP IDs are hex, two digits, upper case)."""
    if isinstance(address, int):
        if not 0 < address < 256:
            raise ValueError(f"address {address} is out of range")
        return f"{address:02X}"
    m = ADDRESS_RE.match(str(address).strip())
    if not m:
        raise ValueError(f"bad address {address!r}: give a hex IP ID such as '03' or '1A'")
    return f"{int(m.group(1), 16):02X}"


DRIVER_EXPAND = "expand_parameters_with_total_inputs_and_outputs"


def _int(v: str | None, default: int = 0) -> int:
    return int(v) if v and v.isdigit() else default


def driver_layout(ls: LibSymbol) -> tuple[int, int, int] | None:
    """(inputs, outputs, parameters) for serial-driver style symbols: fixed pins plus the variable
    ones (minimum, at least 1), and a parameter for each fixed one and each variable pin. Matches
    SIMPL 4.32's COM 2-Way Serial Driver records (6301: 5/3/3, 6361: 3/2/3; f12-round8)."""
    f = ls.fields
    if f.get("Expand") != DRIVER_EXPAND:
        return None
    vi = _int(f.get("MinVariableInputs"), 1) or 1
    vo = _int(f.get("MinVariableOutputs"), 1) or 1
    return (_int(f.get("NumFixedInputs")) + vi, _int(f.get("NumFixedOutputs")) + vo,
            _int(f.get("NumFixedParams")) + vi + vo)


def symbol_counts(ls: LibSymbol) -> dict[str, int]:
    """Pin counts of a freshly placed device symbol, and the stored keys."""
    f = ls.fields
    drv = driver_layout(ls)
    if drv is not None:
        return {"n1I": drv[0], "n2I": 0, "n1O": drv[1], "mI": drv[0], "mO": drv[1], "tO": drv[1]}

    def size(direction: str, suffix: str) -> int:
        v = f.get(f"MinVariable{direction}s{suffix}")
        if v is not None and v.isdigit():
            return int(v)
        if ls.cues(f"{direction}{suffix}Cue") and (f.get("Expand_by") or "").isdigit():
            return int(f["Expand_by"])
        return 0

    ins = [size("Input", s) for s in LISTS]
    outs = [size("Output", s) for s in LISTS]
    return {"n1I": ins[0], "n2I": ins[1], "n1O": outs[0],
            "mI": sum(ins), "mO": outs[0] + outs[1], "tO": sum(outs)}


def symbol_shape_problem(ls: LibSymbol) -> str | None:
    """Why this device symbol's fresh record can't be built yet (None if it can)."""
    f = ls.fields
    if driver_layout(ls) is not None:
        return None  # serial drivers: parameters are written blank
    if f.get("CheckCnx") is None and f.get("Expand"):
        # SIMPL marks these incomplete as soon as they're placed (the Virtual Communication Port, CF=1 in its
        # own save; f12-round8) and won't compile until they're wired. Without Expand they're fine
        # (CEN-RGBHV8x4, CEN-IO-COM-102).
        return "SIMPL marks its symbol incomplete until pins are wired; not supported yet"
    for k in ("NumFixedInputs", "NumFixedOutputs", "MinVariableParams"):
        if f.get(k) not in (None, "0"):
            return f"its symbol has {k}, which isn't proven for devices"
    n = int(f.get("NumFixedParams") or 0)
    for i in range(1, n + 1):
        if f.get(f"ParamCue{i}") not in PARAM_DEFAULTS and f.get(f"ParamCue{i}") != NAME_PARAM:
            return f"its symbol's parameter {f.get(f'ParamCue{i}')!r} has no known default"
    return None


def device_record(*, name: str, handle: int, parent: int, dd: DeviceDef, slot_code: str | None, dvvr: str,
                  address: str, symbol: int | None, db: int | None, et: int | None,
                  children: list[int], cm: int | None = None) -> list[tuple[str | None, str]]:
    f = dd.fields
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Dv"), ("Nm", name), ("H", str(handle)), ("PrH", str(parent)), ("DvC", str(dd.code)),
        ("ObjVer", f.get("ObjVer") or "1"),
    ]
    if slot_code is not None:
        lines.append(("SlC", slot_code))
    lines += [("DvVr", dvvr), ("Ad", address)]
    if symbol is not None:
        lines.append(("SmH", str(symbol)))
    lines.append(("RelStat", f.get("CDSReleaseStatus") or "Release"))
    if f.get("CDSProdLine"):
        lines.append(("ProdLine", f["CDSProdLine"]))
    if db is not None:
        lines.append(("DbH", str(db)))
    if et is not None:
        lines.append(("EtH", str(et)))
    if cm is not None:
        lines.append(("CmH", str(cm)))
    if children:
        lines.append(("mC", str(len(children))))
        lines += [(f"C{i}", str(c)) for i, c in enumerate(children, 1)]
    return lines


def slot_record(*, name: str, handles: list[int], parent: int, slot_code: str, dvvr: str, addresses: list[str],
                child: int | None, slf: str | None = None, objver: str = "1") -> list[tuple[str | None, str]]:
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Dv"), ("Nm", name), ("H", format_handles(handles)), ("PrH", str(parent)), ("ObjVer", objver),
        ("SlC", slot_code), ("DvF", "Sl")]
    if slf:
        lines.append(("SlF", slf))
    lines += [("DvVr", dvvr), ("Ad", ",".join(addresses))]
    if child is not None:
        lines += [("mC", "1"), ("C1", str(child))]
    return lines


CM_KEYS = (("Ptl", "Protocol"), ("Tis", None), ("BRt", "Baud"), ("Pty", "Parity"), ("SBt", "Stopbits"),
           ("DBt", "Databits"), ("hHs", "HWHandshaking"), ("sHs", "SWHandshaking"))


def com_settings(slot_info: dict) -> list[tuple[str, str]] | None:
    """A COM port's default settings, as SIMPL writes them in a Cm record for the driver placed on it:
    each Property<n> is 'Name,default,choices...'. Ports without hardware handshaking get no hHs.
    Key order holds in all 198 modern corpus Cm records; values match SIMPL 4.32's (f12-round8)."""
    if slot_info.get("Transport") != "COM":
        return None
    props = {}
    for k, v in slot_info.items():
        if k.startswith("Property"):
            parts = v.split(",")
            if len(parts) > 1:
                props[parts[0]] = parts[1]
    out = []
    for key, prop in CM_KEYS:
        if prop is None:
            out.append((key, "1"))
        elif prop in props:
            out.append((key, props[prop]))
    return out


MAX_SLOTS_PER_RECORD = 501  # 39 of 39 corpus records that hit it


def slot_address(slot_info: dict, pos: int) -> str:
    return f"{pos:02X}" if slot_info.get("AddressFormat") == "HEX" else f"{pos:02d}"


def slot_layout(devlib: DeviceLibrary, dd: DeviceDef) -> list[tuple[int, str, DeviceDef | None]]:
    """[(position, slot type, fixed device or None)] for positions 1..max(MaxSlots, last Expand).

    A position without its own Expand<n> repeats the previous one, fixed device included
    (an ST-IO's relays fill positions 5-12 from Expand5/Fixed5)."""
    from .edit import EditError

    expands = {int(k[6:]): v for k, v in dd.fields.items() if k.startswith("Expand") and k[6:].isdigit()}
    if not expands:
        return []
    n = max(int(dd.fields.get("MaxSlots") or 0), max(expands))
    out, cur, cur_fixed = [], "NotUsed", None
    for pos in range(1, n + 1):
        if pos in expands:
            cur, cur_fixed = expands[pos], None
            # Fixed<n>: a built-in device. DefDev<n>: the device SIMPL drops in by default (a DM-MD8x8's
            # "DM Outputs" in slots 17 and 21; SIMPL 4.32 save, f12-round8).
            name = dd.fields.get(f"Fixed{pos}") or dd.fields.get(f"DefDev{pos}")
            if name:
                hits = [d for d in devlib.devices.values() if d.name == name]
                if len(hits) != 1:
                    raise EditError(f"{dd.name}'s fixed device {name!r} isn't in the device library exactly once")
                cur_fixed = hits[0]
        out.append((pos, cur, cur_fixed))
    return out


def built_in_by_fixed(dd: DeviceDef, pos: int) -> bool:
    """True if position ``pos`` gets its device from Fixed<n> (a built-in part), not DefDev<n>."""
    for k in range(pos, 0, -1):
        if f"Expand{k}" in dd.fields:
            return bool(dd.fields.get(f"Fixed{k}"))
    return False


def symbol_code_for(dd: DeviceDef, series: str | None) -> int | None:
    """The logic symbol for this device on this processor family: SymbolCode6 (3- and 4-Series; SIMPL 4.32
    used it on a CP4N for the Virtual Communication Port and TCP/IP Client, f12-round8), SymbolCode5
    (2-Series), else SymbolCode."""
    key = "SymbolCode5" if series == "2" else "SymbolCode6"
    v = dd.fields.get(key) or dd.fields.get("SymbolCode") or ""
    return int(v) if v.lstrip("-").isdigit() else None


def processor_series(ed: Editor, devlib: DeviceLibrary) -> str | None:
    hd = ed.prog.header
    cnh = hd.get("CnH") if hd is not None else None
    proc = ed.prog.devices.get(int(cnh)) if cnh and cnh.isdigit() else None
    pdd = devlib.get(proc.code) if proc is not None else None
    line = (pdd.fields.get("CDSProdLine") or "") if pdd else ""
    return "2" if "2-Series" in line and "3-Series" not in line and "4-Series" not in line else None


def device_symbol(lib, dd: DeviceDef, series: str | None = None):
    """The library symbol add_device would write for ``dd`` (None if it has none); EditError if it can't."""
    from .edit import EditError

    code = symbol_code_for(dd, series)
    if code is None:
        return None
    ls = lib.get(code) if lib is not None else None
    if ls is None:
        raise EditError(f"{dd.name}'s logic symbol ({code}) isn't in the symbol library")
    why = symbol_shape_problem(ls)
    if why:
        raise EditError(f"{dd.name} can't be added yet: {why}")
    return ls


def support_problem(devlib: DeviceLibrary, lib, dd: DeviceDef, series: str | None = None) -> str | None:
    """Why add_device can't place ``dd`` (None if it can): its own symbol, and everything SIMPL puts inside it."""
    from .edit import EditError

    if symbol_code_for(dd, series) is None:
        return "it has no logic symbol of its own; it's part of another device"
    if (not any(t in PROVEN_SLOTS for t in dd.occupies) and dd.code not in SLOT_DEVICE_RULES
            and not any(t in SLOT_TYPE_RULES for t in dd.occupies)):
        return "it goes in a slot SIMPL Agent can't fill yet"
    seen: set[int] = set()

    def walk(d: DeviceDef, depth: int) -> None:
        if d.code in seen:
            return
        seen.add(d.code)
        if depth > 8:
            raise EditError(f"{d.name} nests too deeply")
        device_symbol(lib, d, series)
        for _, typ, fixed in slot_layout(devlib, d):
            if typ not in devlib.slots:
                raise EditError(f"{d.name}: slot type {typ} isn't in the device library")
            if fixed is not None:
                walk(fixed, depth + 1)

    try:
        walk(dd, 0)
    except EditError as e:
        return str(e)
    return None


class _Build:
    """Records for a device and everything SIMPL puts inside it, numbered depth first."""

    def __init__(self, ed: Editor, devlib: DeviceLibrary, dvvr: str, smvr: str, next_sm: int,
                 next_cm: int = 1) -> None:
        self.ed, self.devlib, self.dvvr, self.smvr, self.next_sm = ed, devlib, dvvr, smvr, next_sm
        self.next_cm = next_cm
        self.cm: list[list[tuple[str | None, str]]] = []
        self.dv: list[list[tuple[str | None, str]]] = []
        self.sm: dict[int, list[tuple[str | None, str]]] = {}
        self.devices = 0
        self.needs_overrides = False
        self.series = processor_series(ed, devlib)

    def symbol_for(self, dd: DeviceDef):
        return device_symbol(self.ed.lib, dd, self.series)

    def device(self, dd: DeviceDef, *, handle: int, parent: int, address: str, slot_code: str | None,
               sym_parent: int, db: int | None = None, et: int | None = None, depth: int = 0,
               name_param: str | None = None, slot_info: dict | None = None) -> tuple[int, list[int]]:
        """Build ``dd`` at ``handle``. Returns (next free Dv handle, symbols to list under sym_parent)."""
        from .edit import EditError

        self.devices += 1
        if dd.fields.get("RequiresOverrides") == "True":
            self.needs_overrides = True
        if depth > 8 or self.devices > 2000:
            raise EditError(f"{dd.name} nests too deeply to build")
        ls = self.symbol_for(dd)
        sym = None
        if ls is not None:
            sym, self.next_sm = self.next_sm, self.next_sm + 1
        cm = None
        settings = com_settings(slot_info or {})
        if settings is not None:
            cm, self.next_cm = self.next_cm, self.next_cm + 1
            self.cm.append([("ObjTp", "Cm"), ("H", str(cm)), ("DvH", str(handle))] + settings)
        my_parent_sym = sym if sym is not None else sym_parent
        # A symbol's Name parameter: the device's own name, except that built-in parts (Fixed<n>)
        # take the name of the device they belong to (DMC-4KZ-C Advanced -> "DMC-4KZ-C"; f12-round8).
        name_param = name_param or instance_name(dd)
        nxt, slots, child_syms, empty = handle + 1, [], [], {}
        for pos, typ, fixed in slot_layout(self.devlib, dd):
            info = self.devlib.slots.get(typ)
            if not info or not info.get("Code"):
                raise EditError(f"{dd.name}: slot type {typ} isn't in the device library")
            sh, nxt = nxt, nxt + 1
            slots.append(sh)
            ad = slot_address(info, pos)
            slf = "Ex" if info.get("Transport") in ("IR", "Power") else None
            if fixed is None:
                empty.setdefault(typ, []).append((sh, ad, info, slf))
                continue
            ch = nxt
            self.dv.append(slot_record(name=typ, handles=[sh], parent=handle, slot_code=info["Code"], dvvr=self.dvvr,
                                       addresses=[ad], child=ch, slf=slf, objver=info.get("ObjVer") or "1"))
            nxt, syms = self.device(fixed, handle=ch, parent=sh, address=ad, slot_code=info["Code"],
                                    sym_parent=my_parent_sym, depth=depth + 1,
                                    name_param=name_param if built_in_by_fixed(dd, pos) else None, slot_info=info)
            child_syms += syms
        for typ, rows in empty.items():
            for i in range(0, len(rows), MAX_SLOTS_PER_RECORD):
                chunk = rows[i:i + MAX_SLOTS_PER_RECORD]
                self.dv.append(slot_record(name=typ, handles=[r[0] for r in chunk], parent=handle,
                                           slot_code=chunk[0][2]["Code"], dvvr=self.dvvr,
                                           addresses=[r[1] for r in chunk], child=None, slf=chunk[0][3],
                                           objver=chunk[0][2].get("ObjVer") or "1"))
        self.dv.append(device_record(name=instance_name(dd), handle=handle, parent=parent, dd=dd, slot_code=slot_code,
                                     dvvr=self.dvvr, address=address, symbol=sym, db=db, et=et, children=slots,
                                     cm=cm))
        if sym is None:
            return nxt, child_syms
        self.sm[sym] = device_symbol_record(handle=sym, ls=ls, smvr=self.smvr, device=handle, parent=sym_parent,
                                            comment=instance_name(dd), children=child_syms, name=dd.name,
                                            name_param=name_param)
        return nxt, [sym]


def device_symbol_record(*, handle: int, ls: LibSymbol, smvr: str, device: int, parent: int, comment: str,
                         children: list[int], name: str | None = None,
                         name_param: str | None = None) -> list[tuple[str | None, str]]:
    """``name``: the symbol's Nm, the device's library Name (SIMPL 4.32 wrote 'DM-MD8x8' where the symbol
    library says 'DM-MD8X8', and 'DM-NVX-36x Stream Transmit' for a device named 'Stream Transmit')."""
    f = ls.fields
    c = symbol_counts(ls)
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Sm"), ("H", str(handle)), ("SmC", str(ls.code)), ("Nm", name or f.get("Name") or ""),
        ("ObjVer", f.get("ObjVer") or "1"), ("SmVr", smvr), ("DvH", str(device)), ("PrH", str(parent)), ("CF", "2"),
    ]
    lines += [(k, str(c[k])) for k in ("n1I", "n2I", "n1O") if c[k]]
    lines.append(("Cmn1", comment))
    if children:
        lines.append(("mC", str(len(children))))
        lines += [(f"C{i}", str(x)) for i, x in enumerate(children, 1)]
    # mO is written, even as 0, whenever there are outputs (20 of 20 corpus records with tO > 0, mO = 0).
    lines += [(k, str(c[k])) for k in ("mI", "mO", "tO") if c[k] or (k == "mO" and c["tO"])]
    drv = driver_layout(ls)
    if drv is not None:
        lines += [("mP", str(drv[2]))] + [(f"P{i}", "") for i in range(1, drv[2] + 1)]
        return lines
    n = int(f.get("NumFixedParams") or 0)
    if n:
        lines.append(("mP", str(n)))
        lines += [(f"P{i}", (name_param or comment) if f[f"ParamCue{i}"] == NAME_PARAM
                   else PARAM_DEFAULTS[f[f"ParamCue{i}"]])
                  for i in range(1, n + 1)]
    return lines


def _unique_devices(ed: Editor) -> list[Device]:
    seen, out = set(), []
    for d in ed.prog.devices.values():
        if id(d) not in seen:
            seen.add(id(d))
            out.append(d)
    return out


def _insert_dv_sorted(ed: Editor, rec: Record) -> None:
    """Insert a Dv record before the first Dv record with a higher first handle."""
    first = parse_handles(rec.get("H"))[0]
    last_dv = None
    for i, it in enumerate(ed.raw.items):
        if isinstance(it, Record) and it.type == "Dv":
            if parse_handles(it.get("H"))[0] > first:
                ed.raw.items.insert(i, rec)
                return
            last_dv = i
    if last_dv is None:
        raise ValueError("the program has no device records")
    ed.raw.items.insert(last_dv + 1, rec)


def instance_name(dd: DeviceDef) -> str:
    """The name SIMPL gives a placed device (Dv Nm, its symbol's Cmn1): iodev InstanceName if
    any, else Name. 3,389 of 3,395 corpus devices with an InstanceName; Db Mdl keeps Name."""
    return dd.fields.get("InstanceName") or dd.name


def find_device_def(devlib: DeviceLibrary, ref: str | int) -> DeviceDef:
    from .edit import EditError

    if isinstance(ref, int) or str(ref).strip().isdigit():
        dd = devlib.get(int(ref))
        if dd is None:
            raise EditError(f"no device with code {ref} in SIMPL's device library")
        return dd
    hits = [d for d in devlib.devices.values() if d.name.lower() == str(ref).strip().lower()]
    if len(hits) != 1:
        near = [d.name for d in devlib.find(str(ref))[:5]]
        raise EditError(f"{len(hits)} devices named {ref!r}" + (f"; did you mean {near}?" if near else ""))
    return hits[0]


def add_device(ed: Editor, devlib: DeviceLibrary, device: str | int, address: str | int,
               network: str | int | None = None) -> int:
    """Place ``device`` at ``address`` on a network. Returns the device's symbol handle."""
    from .edit import EditError

    if ed.lib is None:
        raise EditError("the symbol library isn't available")
    dd = find_device_def(devlib, device)
    if dd.symbol_code is None:
        raise EditError(f"{dd.name} has no logic symbol of its own; it's part of another device")
    # Where it can go: an ID on a network, or (with network naming a frame) a slot of that frame.
    net_types = [t for t in dd.occupies if t in PROVEN_SLOTS]
    rule = SLOT_DEVICE_RULES.get(dd.code)
    other_types = [t for t in dd.occupies if t not in PROVEN_SLOTS]
    if not net_types and not other_types:
        raise EditError(f"{dd.name} doesn't occupy any slot type")
    candidates = []
    for c in _unique_devices(ed):
        if c.record.get("DvF") == "Sl":
            continue
        if network is not None and str(network).strip().lower() not in {f"#{c.handles[0]}", (c.name or "").lower()}:
            continue
        for h in dict.fromkeys(c.children):
            k = ed.prog.devices.get(h)
            if k is None or k.record.get("DvF") != "Sl" or k.name not in dd.occupies:
                continue
            on_network = k.name in PROVEN_SLOTS
            if not on_network and network is None:
                continue  # slots inside a frame are only used when the caller names the frame
            try:
                a = address_for_slot(address, devlib.slots.get(k.name) or {})
            except ValueError as e:
                raise EditError(str(e)) from None
            addrs = (k.address or "").split(",")
            if a in addrs:
                candidates.append((c, k, addrs, a, on_network))
                break
    if not candidates:
        types = "/".join(net_types) if network is None else "/".join(dd.occupies[:4])
        raise EditError(f"no {types} slot at address {address}" + (f" in {network}" if network else "")
                        + "; check free_ids or device_tree"
                        + ("" if net_types or network is not None else
                           f". {dd.name} goes in a frame's slot: give network (the frame, e.g. '#589')"))
    if len(candidates) > 1:
        raise EditError(f"address {address} exists on {len(candidates)} networks; give network")
    container, slot, addrs, addr, on_network = candidates[0]
    if slot.children:
        used = ed.prog.devices.get(slot.children[0])
        raise EditError(f"address {addr} is already used by {used.name if used else '?'}")
    if on_network:
        slot_code, with_db = None, True
    elif rule is None and slot.name in SLOT_TYPE_RULES:
        rule = SLOT_TYPE_RULES[slot.name]
        slot_code = slot.record.get("SlC") if rule["slc"] else None
        with_db = bool(rule["db"])
    elif rule is None:
        raise EditError(f"{dd.name} isn't supported in a slot yet: the public programs don't show how SIMPL "
                        "writes it consistently")
    else:
        slot_code = slot.record.get("SlC") if rule["slc"] else None
        with_db = bool(rule["db"])
    if container.symbol is None or container.symbol not in ed.prog.symbols:
        raise EditError(f"network {container.name} has no logic symbol to put the device under")

    _Build(ed, devlib, "", "", 0).symbol_for(dd)  # refuse unsupported symbols before changing anything
    hd = ed.prog.header
    smvr = (hd.get("SmVr") if hd is not None else None) or ""
    dvvr = slot.record.get("DvVr") or ""
    if not smvr or not dvvr:
        raise EditError("the program has no SmVr/DvVr version to stamp new records with")

    snapshot = ed._snapshot()
    try:
        # 1. Split the slot record so the chosen address has a record of its own.
        all_dv = [h for r in ed.raw.of_type("Dv") for h in parse_handles(r.get("H"))]
        dev_h = max(all_dv) + 1
        hs = parse_handles(slot.record.get("H"))
        i = addrs.index(addr)
        rec = slot.record
        keep = [(k, v) for k, v in rec.lines if k not in ("H", "Ad", "mC") and not (k and k[0] == "C" and k[1:].isdigit())]

        def piece(handles: list[int], ads: list[str], extra=()) -> Record:
            lines = []
            for k, v in keep:
                lines.append((k, v))
                if k == "Nm":
                    lines.append(("H", format_handles(handles)))
            lines.append(("Ad", ",".join(ads)))
            lines += list(extra)
            return Record(lines=lines)

        # SIMPL keeps every free address of a slot type in ONE record, gaps and all
        # (263,265.269,271.514): 259 of 259 corpus networks, and its re-save of f12-round6.
        pieces = [piece([hs[i]], [addr], [("mC", "1"), ("C1", str(dev_h))])]
        rest = [j for j in range(len(hs)) if j != i]
        if rest:
            pieces.append(piece([hs[j] for j in rest], [addrs[j] for j in rest]))
        # Dv records stay sorted by first handle (true in every corpus file), so taking the
        # first address moves the free record below the used one.
        ed.raw.items.remove(rec)
        for p in pieces:
            _insert_dv_sorted(ed, p)

        # 2. The device and everything SIMPL puts inside it, numbered depth first.
        sm_h = ed._next_handle("Sm")
        db_h = ed._next_handle("Db") if with_db else None
        et_h = ed._next_handle("Et") if dd.fields.get("DefaultIP") and on_network else None
        b = _Build(ed, devlib, dvvr, smvr, sm_h, next_cm=ed._next_handle("Cm"))
        b.device(dd, handle=dev_h, parent=hs[i], address=addr, slot_code=slot_code, sym_parent=container.symbol,
                 slot_info=devlib.slots.get(slot.name or "") or {},
                 db=db_h, et=et_h)
        for lines in b.dv:
            _insert_dv_sorted(ed, Record(lines=lines))

        for lines in b.cm:
            ed._insert_record(Record(lines=lines), "Cm", after_types=("Dv",))

        # 3. Companions: Db (and Et when the device has a default IP).
        if db_h is not None:
            db_lines = [("ObjTp", "Db"), ("H", str(db_h)), ("DvH", str(dev_h)), ("Whc", "3"), ("Mnf", "Crestron"),
                        ("Mdl", dd.name)]
            # Devices with DM label overrides placed on a network also get their description (25 of 25 in the
            # corpus; SIMPL 4.32 wrote it for a DM-MD8x8, not for its cards or 8 other devices, f12-round8).
            if on_network and dd.fields.get("RequiresOverrides") == "True" and dd.fields.get("Hint"):
                db_lines.append(("Tpe", dd.fields["Hint"]))
            ed._insert_record(Record(lines=db_lines), "Db", after_types=("Dv", "Cm"))
        if et_h is not None:
            ed._insert_record(Record(lines=[("ObjTp", "Et"), ("H", str(et_h)), ("DvH", str(dev_h)),
                                            ("IPM", "255.255.255.0"), ("IPA", dd.fields["DefaultIP"])]),
                              "Et", after_types=("Dv", "Cm", "Db", "Cs", "Bk", "Bw"))

        # A device with DM label overrides makes SIMPL add LabelOverrideStatus=2 at the end of the
        # header (3 of 3 such corpus programs, 0 of 63 others; SIMPL 4.32 save, f12-round8).
        if b.needs_overrides and hd is not None and hd.get("LabelOverrideStatus") is None:
            hd.lines.append(("LabelOverrideStatus", "2"))

        # 4. Logic symbols, in handle order.
        for h in sorted(b.sm):
            ed._insert_record(Record(lines=b.sm[h]), "Sm", after_types=("Bw", "Bk"))

        # 6. The network's symbol lists its devices in address order.
        ed._reload()
        par = ed.prog.symbols[container.symbol]

        def addr_key(h: int) -> int:
            s = ed.prog.symbols.get(h)
            d = ed.prog.devices.get(s.device) if s is not None and s.device is not None else None
            a = (d.address or "") if d is not None else ""
            return int(a, 16) if a and all(ch in "0123456789ABCDEFabcdef" for ch in a) else 1 << 30

        kids = sorted([*par.children, sm_h], key=addr_key)
        ed._rebuild_children(container.symbol, kids)
    except Exception:
        ed._restore(snapshot)
        raise
    ed._reload()
    ed.log.add(f"added {dd.name} at {slot.name} {addr} on {container.name}: device #{dev_h}, symbol #{sm_h}"
               + (f" (+{b.devices - 1} devices inside it)" if b.devices > 1 else ""))
    return sm_h
