"""Adding a device the way SIMPL 4.3x does (docs/format.md "Adding a device").

Decoded from a SIMPL 4.32 save of an empty CP4N, then a TSW-1070 at IP ID 03, then an
EISC at 04 (f12-round5). Every rule here reproduces those files byte for byte, and the
built-in CP4N records in the same file (tests/test_device_edit.py).

What SIMPL writes for a device placed at a free address:
- Every free address of a slot type sits in one record (a handle list with gaps). The
  slot at the chosen address leaves it, keeps its handle and gets ``mC=1 C1=<device>``.
- A Dv record for the device (handle = max + 1) and, for each fixed child slot
  (``Expand<n>=FixedSlot``, ``Fixed<n>=<device name>``), a FixedSlot record and the
  child device. A child device carries its slot's SlC; a device on a network does not.
- A Db record (Whc=3, Mnf=Crestron, Mdl=<name>) for the device on the network, and an
  Et record when the library gives the device a default IP address.
- A logic symbol for each device (``SymbolCode``), the network's container symbol
  listing them in address order. Pin counts come from the symbol library: each of the
  three lists is MinVariable* if given, else Expand_by when the list exists. Only n1I,
  n2I and n1O are stored; mI is every input, mO output lists 1+2, tO every output.

Only devices proven by a real SIMPL save are allowed (``PROVEN_DEVICE_CODES``).
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
PROVEN_DEVICE_CODES = {6395, 232}  # TSW-1070 (with TSW-1070 Buttons), Ethernet Intersystem Communications
PROVEN_SLOTS = {"P4Ethernet"}  # 4-Series Ethernet IP IDs
NOT_USED = {"Not_Used", "NotUsed"}
ADDRESS_RE = re.compile(r"^(?:0x)?([0-9A-Fa-f]{1,2})$")
LISTS = ("", "List2", "List3")
PARAM_DEFAULTS = {"PermanentStringSize": "255d"}


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


def symbol_counts(ls: LibSymbol) -> dict[str, int]:
    """Pin counts of a freshly placed device symbol, and the stored keys."""
    f = ls.fields

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
    for k in ("NumFixedInputs", "NumFixedOutputs", "MinVariableParams"):
        if f.get(k) not in (None, "0"):
            return f"its symbol has {k}, which isn't proven for devices"
    n = int(f.get("NumFixedParams") or 0)
    for i in range(1, n + 1):
        if f.get(f"ParamCue{i}") not in PARAM_DEFAULTS:
            return f"its symbol's parameter {f.get(f'ParamCue{i}')!r} has no known default"
    return None


def device_record(*, name: str, handle: int, parent: int, dd: DeviceDef, slot_code: str | None, dvvr: str,
                  address: str, symbol: int, db: int | None, et: int | None,
                  children: list[int]) -> list[tuple[str | None, str]]:
    f = dd.fields
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Dv"), ("Nm", name), ("H", str(handle)), ("PrH", str(parent)), ("DvC", str(dd.code)),
        ("ObjVer", f.get("ObjVer") or "1"),
    ]
    if slot_code is not None:
        lines.append(("SlC", slot_code))
    lines += [("DvVr", dvvr), ("Ad", address), ("SmH", str(symbol)),
              ("RelStat", f.get("CDSReleaseStatus") or "Release")]
    if f.get("CDSProdLine"):
        lines.append(("ProdLine", f["CDSProdLine"]))
    if db is not None:
        lines.append(("DbH", str(db)))
    if et is not None:
        lines.append(("EtH", str(et)))
    if children:
        lines.append(("mC", str(len(children))))
        lines += [(f"C{i}", str(c)) for i, c in enumerate(children, 1)]
    return lines


def slot_record(*, name: str, handle: int, parent: int, slot_code: str, dvvr: str, address: str,
                child: int) -> list[tuple[str | None, str]]:
    return [("ObjTp", "Dv"), ("Nm", name), ("H", str(handle)), ("PrH", str(parent)), ("ObjVer", "1"),
            ("SlC", slot_code), ("DvF", "Sl"), ("DvVr", dvvr), ("Ad", address), ("mC", "1"), ("C1", str(child))]


def device_symbol_record(*, handle: int, ls: LibSymbol, smvr: str, device: int, parent: int, comment: str,
                         children: list[int]) -> list[tuple[str | None, str]]:
    f = ls.fields
    c = symbol_counts(ls)
    lines: list[tuple[str | None, str]] = [
        ("ObjTp", "Sm"), ("H", str(handle)), ("SmC", str(ls.code)), ("Nm", f.get("Name") or ""),
        ("ObjVer", f.get("ObjVer") or "1"), ("SmVr", smvr), ("DvH", str(device)), ("PrH", str(parent)), ("CF", "2"),
    ]
    lines += [(k, str(c[k])) for k in ("n1I", "n2I", "n1O") if c[k]]
    lines.append(("Cmn1", comment))
    if children:
        lines.append(("mC", str(len(children))))
        lines += [(f"C{i}", str(x)) for i, x in enumerate(children, 1)]
    lines += [(k, str(c[k])) for k in ("mI", "mO", "tO") if c[k]]
    n = int(f.get("NumFixedParams") or 0)
    if n:
        lines.append(("mP", str(n)))
        lines += [(f"P{i}", PARAM_DEFAULTS[f[f"ParamCue{i}"]]) for i in range(1, n + 1)]
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


def _plan_children(devlib: DeviceLibrary, dd: DeviceDef) -> list[tuple[str, DeviceDef]]:
    """[(slot type, child device)] for the device's fixed slots; refuses other shapes."""
    from .edit import EditError

    expands = dd.numbered("Expand")
    fixed = dd.numbered("Fixed")
    out = []
    for i, slot in enumerate(expands, 1):
        child_name = dd.fields.get(f"Fixed{i}")
        if slot != "FixedSlot" or not child_name:
            raise EditError(f"{dd.name} has a configurable slot ({slot}); only fixed child slots are supported")
        hits = [d for d in devlib.devices.values() if d.name == child_name]
        if len(hits) != 1:
            raise EditError(f"{dd.name}'s fixed child {child_name!r} isn't in the device library exactly once")
        if hits[0].numbered("Expand"):
            raise EditError(f"{child_name} has slots of its own; not supported yet")
        out.append((slot, hits[0]))
    if len(fixed) != len(out):
        raise EditError(f"{dd.name}'s fixed children don't match its slots")
    return out


def add_device(ed: Editor, devlib: DeviceLibrary, device: str | int, address: str | int,
               network: str | int | None = None, *, allow_unproven: bool = False) -> int:
    """Place ``device`` at ``address`` on a network. Returns the device's symbol handle."""
    from .edit import EditError

    if ed.lib is None:
        raise EditError("the symbol library isn't available")
    dd = find_device_def(devlib, device)
    if dd.code not in PROVEN_DEVICE_CODES and not allow_unproven:
        raise EditError(f"{dd.name} (code {dd.code}) isn't proven yet: adding devices is limited to ones whose "
                        "records were checked against a real SIMPL save")
    try:
        addr = normalise_address(address)
    except ValueError as e:
        raise EditError(str(e)) from None

    # The free slot holding that address, on a network whose slot type the device may occupy.
    slot_types = [s for s in dd.occupies if s in PROVEN_SLOTS]
    if not slot_types:
        raise EditError(f"{dd.name} doesn't go in a supported slot type (it occupies {dd.occupies[:6]})")
    candidates = []
    for c in _unique_devices(ed):
        if c.record.get("DvF") == "Sl":
            continue
        if network is not None and str(network).strip().lower() not in {f"#{c.handles[0]}", (c.name or "").lower()}:
            continue
        for h in c.children:
            k = ed.prog.devices.get(h)
            if k is None or k.record.get("DvF") != "Sl" or k.name not in slot_types:
                continue
            addrs = (k.address or "").split(",")
            if addr in addrs:
                candidates.append((c, k, addrs))
                break
    if not candidates:
        raise EditError(f"no {'/'.join(slot_types)} slot at address {addr}; check free_ids")
    if len(candidates) > 1:
        raise EditError(f"address {addr} exists on {len(candidates)} networks; give network")
    container, slot, addrs = candidates[0]
    if slot.children:
        used = ed.prog.devices.get(slot.children[0])
        raise EditError(f"address {addr} is already used by {used.name if used else '?'}")
    if container.symbol is None or container.symbol not in ed.prog.symbols:
        raise EditError(f"network {container.name} has no logic symbol to put the device under")

    children = _plan_children(devlib, dd)
    lib_syms = []
    for d in [dd] + [c for _, c in children]:
        code = d.symbol_code
        ls = ed.lib.get(code) if code is not None else None
        if ls is None:
            raise EditError(f"{d.name}'s logic symbol ({code}) isn't in the symbol library")
        why = symbol_shape_problem(ls)
        if why:
            raise EditError(f"{d.name} can't be added yet: {why}")
        lib_syms.append(ls)

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

        # 2. Handles for everything new.
        sm_h = ed._next_handle("Sm")
        db_h = ed._next_handle("Db")
        et_h = ed._next_handle("Et") if dd.fields.get("DefaultIP") else None
        child_dv = []  # (slot handle, device handle, slot type, def, symbol handle)
        nxt_dv, nxt_sm = dev_h + 1, sm_h + 1
        for slot_type, cd in children:
            child_dv.append((nxt_dv, nxt_dv + 1, slot_type, cd, nxt_sm))
            nxt_dv += 2
            nxt_sm += 1

        # 3. Device records, at the end of the Dv run (their handles are the highest).
        new_dv = [device_record(name=dd.name, handle=dev_h, parent=hs[i], dd=dd, slot_code=None, dvvr=dvvr,
                                address=addr, symbol=sm_h, db=db_h, et=et_h,
                                children=[s for s, *_ in child_dv])]
        for n, (s_h, c_h, slot_type, cd, c_sm) in enumerate(child_dv, 1):
            info = devlib.slots.get(slot_type) or {}
            code = info.get("Code")
            if not code:
                raise EditError(f"slot type {slot_type} isn't in the device library")
            new_dv.append(slot_record(name=slot_type, handle=s_h, parent=dev_h, slot_code=code, dvvr=dvvr,
                                      address=f"{n:02X}", child=c_h))
            new_dv.append(device_record(name=cd.name, handle=c_h, parent=s_h, dd=cd, slot_code=code, dvvr=dvvr,
                                        address=f"{n:02X}", symbol=c_sm, db=None, et=None, children=[]))
        for lines in new_dv:
            _insert_dv_sorted(ed, Record(lines=lines))

        # 4. Companions: Db (and Et when the device has a default IP).
        ed._insert_record(Record(lines=[("ObjTp", "Db"), ("H", str(db_h)), ("DvH", str(dev_h)), ("Whc", "3"),
                                        ("Mnf", "Crestron"), ("Mdl", dd.name)]), "Db", after_types=("Dv", "Cm"))
        if et_h is not None:
            ed._insert_record(Record(lines=[("ObjTp", "Et"), ("H", str(et_h)), ("DvH", str(dev_h)),
                                            ("IPM", "255.255.255.0"), ("IPA", dd.fields["DefaultIP"])]),
                              "Et", after_types=("Dv", "Cm", "Db", "Cs", "Bk", "Bw"))

        # 5. Logic symbols: the device's, then each child's under it.
        ed._insert_record(Record(lines=device_symbol_record(
            handle=sm_h, ls=lib_syms[0], smvr=smvr, device=dev_h, parent=container.symbol, comment=dd.name,
            children=[c_sm for *_, c_sm in child_dv])), "Sm", after_types=("Bw", "Bk"))
        for (s_h, c_h, slot_type, cd, c_sm), ls in zip(child_dv, lib_syms[1:]):
            ed._insert_record(Record(lines=device_symbol_record(
                handle=c_sm, ls=ls, smvr=smvr, device=c_h, parent=sm_h, comment=cd.name, children=[])),
                "Sm", after_types=("Bw", "Bk"))

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
               + (f" (+{len(child_dv)} fixed child)" if child_dv else ""))
    return sm_h
