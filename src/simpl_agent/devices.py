"""Read-side view of a program's device tree: devices, their addresses and free IDs."""
from __future__ import annotations

from typing import Any

from .catalog.devices import DeviceLibrary
from .smw.model import Device, Program, parse_handles

NOT_USED = {"Not_Used", "NotUsed"}


def _unique(prog: Program) -> list[Device]:
    seen, out = set(), []
    for d in prog.devices.values():
        if id(d) not in seen:
            seen.add(id(d))
            out.append(d)
    return out


def is_slot(d: Device) -> bool:
    return d.record.get("DvF") == "Sl"


def path_of(prog: Program, d: Device) -> str:
    """'CP4N\\EthernetCard\\Ethernet Devices' for a device's ancestors (names only)."""
    parts, cur, seen = [], prog.devices.get(d.parent) if d.parent is not None else None, set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if not is_slot(cur):
            parts.append(cur.name or "?")
        cur = prog.devices.get(cur.parent) if cur.parent is not None else None
    return "\\".join(reversed(parts))


def device_rows(prog: Program, limit: int = 500) -> list[dict[str, Any]]:
    """Real devices (not slots), with where they sit and their address."""
    ets = {r.get("H"): r for r in prog.raw.of_type("Et")}
    dbs = {r.get("H"): r for r in prog.raw.of_type("Db")}
    rows = []
    for d in _unique(prog):
        if is_slot(d) or d.code is None:
            continue
        slot = prog.devices.get(d.parent) if d.parent is not None else None
        row: dict[str, Any] = {
            "device": f"#{d.handles[0]}", "name": d.name, "code": d.code, "address": d.address,
            "in": path_of(prog, d), "slot_type": slot.name if slot is not None and is_slot(slot) else None,
        }
        db = dbs.get(d.record.get("DbH") or "")
        if db is not None and db.get("Mdl"):
            row["model"] = db.get("Mdl")
        et = ets.get(d.record.get("EtH") or "")
        if et is not None and et.get("IPA"):
            row["ip_address"] = et.get("IPA")
        if d.symbol is not None:
            row["symbol"] = f"#{d.symbol}"
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def networks(prog: Program, devlib: DeviceLibrary | None) -> list[dict[str, Any]]:
    """Each addressable network (a container whose children are address slots) with free and used IDs."""
    out = []
    for c in _unique(prog):
        kids = [prog.devices.get(h) for h in c.children]
        slot_kids = [k for k in kids if k is not None and is_slot(k)]
        if not slot_kids or is_slot(c):
            continue
        # The network's slot type is the one covering most addresses (Cresnet also has a PowerSlot).
        counts: dict[str, int] = {}
        for k in slot_kids:
            if k.name not in NOT_USED:
                counts[k.name or ""] = counts.get(k.name or "", 0) + 1
        if not counts:
            continue
        slot_type = max(counts, key=lambda n: counts[n])
        info = devlib.slots.get(slot_type, {}) if devlib else {}
        label = info.get("Label")
        if label is None and devlib is not None:
            continue  # not an addressable network (e.g. card slots)
        free, used, seen = [], {}, set()
        for k in slot_kids:
            if id(k) in seen:
                continue
            seen.add(id(k))
            addrs = (k.address or "").split(",")
            if k.name != slot_type:
                continue
            if k.children:
                dev = prog.devices.get(k.children[0])
                for a in addrs:
                    used[a] = dev.name if dev is not None else "?"
            else:
                free.extend(a for a in addrs if a)
        if not free and not used:
            continue
        out.append({
            "network": c.name, "container": f"#{c.handles[0]}", "in": path_of(prog, c),
            "slot_type": slot_type, "id_label": label, "transport": info.get("Transport"),
            "free_count": len(free), "free_ids": free, "used": used,
        })
    return out


def free_slot_record(prog: Program, container: Device, address: str):
    """The slot record (single or range) in ``container`` that holds free ``address``."""
    for h in container.children:
        k = prog.devices.get(h)
        if k is None or not is_slot(k) or k.children or k.name in NOT_USED:
            continue
        addrs = (k.address or "").split(",")
        if address in addrs:
            return k, addrs, parse_handles(k.record.get("H"))
    return None
