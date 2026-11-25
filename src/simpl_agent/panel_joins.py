"""M7: a touch panel's joins against the SIMPL program (CH5 Agent's joins.json).

The join map lists, per join (type and number), the SIMPL signal on each side: ``in`` is the
signal into the panel (feedback), ``out`` the one it drives (a press), the same as wire_joins.
``joins_without_simpl_signals`` are joins the panel uses that have no SIMPL name yet.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .smw.joins import TYPES, is_join_symbol, read_joins
from .smw.model import Program

DIRECTIONS = ("in", "out")


class JoinMapError(ValueError):
    pass


def _join(j: Any, where: str, need_signal: bool) -> dict[str, Any]:
    if not isinstance(j, dict):
        raise JoinMapError(f"{where}: each join must be an object, got {j!r}")
    t = str(j.get("type", "")).lower()
    n = j.get("join")
    if t not in TYPES or not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise JoinMapError(f"{where}: bad join {j!r} (need type digital/analog/serial and a join number from 1)")
    out: dict[str, Any] = {"type": t, "join": n}
    for d in DIRECTIONS:
        v = j.get(d)
        if v is not None:
            if not isinstance(v, str) or not v.strip() or "\r" in v or "\n" in v:
                raise JoinMapError(f"{where}: {t} join {n} '{d}' must be a signal name")
            out[d] = v.strip()
    if need_signal and not any(d in out for d in DIRECTIONS):
        raise JoinMapError(f"{where}: {t} join {n} has no 'in' or 'out' signal")
    return out


def load_join_map(path: str | Path) -> dict[str, Any]:
    """Read and check a joins.json: {xpanel_ip_id?, joins: [...], joins_without_simpl_signals?: [...]}."""
    p = Path(path)
    if p.suffix.lower() != ".json" or not p.is_file():
        raise JoinMapError(f"{p} isn't a .json join map")
    try:
        data = json.loads(p.read_text("utf-8-sig"))
    except (OSError, ValueError) as e:
        raise JoinMapError(f"couldn't read {p}: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("joins"), list):
        raise JoinMapError(f"{p} has no 'joins' list (expected CH5 Agent's joins.json)")
    joins = [_join(j, "joins", True) for j in data["joins"]]
    unnamed = [_join(j, "joins_without_simpl_signals", False) for j in data.get("joins_without_simpl_signals") or []]
    seen: set[tuple[str, int]] = set()
    for j in joins + unnamed:
        key = (j["type"], j["join"])
        if key in seen:
            raise JoinMapError(f"{j['type']} join {j['join']} is listed twice in {p.name}")
        seen.add(key)
    ip = data.get("xpanel_ip_id")
    return {"path": str(p), "ip_id": str(ip).strip() if ip not in (None, "") else None,
            "joins": joins, "unnamed": unnamed}


def panel_symbols(prog: Program, lib) -> list[dict[str, Any]]:
    """Devices whose logic symbol has digital/analog/serial join lists (panels, XPanels, EISCs)."""
    from .devices import device_rows

    out = []
    for row in device_rows(prog, limit=5000):
        h = int(row["symbol"][1:]) if row.get("symbol") else None
        s = prog.symbols.get(h) if h is not None else None
        ls = lib.get(s.code) if (s is not None and lib is not None and s.code is not None) else None
        if ls is not None and is_join_symbol(ls):
            out.append({**row, "handle": h})
    return out


def _same_id(a: str | None, b: str | None) -> bool:
    try:
        return a is not None and b is not None and int(str(a), 16) == int(str(b), 16)
    except ValueError:
        return False


def find_panel(prog: Program, lib, ip_id: str | None, symbol: int | None) -> tuple[dict[str, Any], list[str]]:
    """The panel to check: ``symbol`` if given, else the one device at the join map's IP ID."""
    panels = panel_symbols(prog, lib)
    notes: list[str] = []
    if symbol is not None:
        hit = [p for p in panels if p["handle"] == symbol]
        if not hit:
            raise JoinMapError(f"#{symbol} isn't a panel, XPanel or EISC symbol; device_tree lists them")
        if ip_id and not _same_id(hit[0].get("address"), ip_id):
            notes.append(f"The join map is for IP ID {ip_id}, but #{symbol} ({hit[0]['name']}) is at "
                         f"{hit[0].get('address')}: check it's the right panel.")
        return hit[0], notes
    if not ip_id:
        raise JoinMapError("the join map has no xpanel_ip_id; give the panel's symbol ('#h' from device_tree)")
    hit = [p for p in panels if _same_id(p.get("address"), ip_id)]
    if not hit:
        raise JoinMapError(f"no panel, XPanel or EISC at IP ID {ip_id} in this program; add it first "
                           "(add_device) or give its symbol")
    if len(hit) > 1:
        where = ", ".join(f"#{p['handle']} {p['name']} in {p['in']}" for p in hit)
        raise JoinMapError(f"more than one panel at IP ID {ip_id} ({where}); give the symbol")
    return hit[0], notes


def check(prog: Program, sym: int, jm: dict[str, Any]) -> dict[str, Any]:
    """Each join direction in the map against what the program wires on the panel symbol."""
    have = read_joins(prog.symbols[sym].record)

    def name(h: int | None) -> str | None:
        if h is None:
            return None
        sg = prog.signals.get(h)
        return sg.name if sg is not None else f"#{h}"

    ok, missing, different = [], [], []
    for j in jm["joins"]:
        key = (j["type"], j["join"])
        for d in DIRECTIONS:
            want = j.get(d)
            if want is None:
                continue
            cur = name(have.get(key, {}).get(d))
            row = {"type": j["type"], "join": j["join"], "direction": d, "panel_map": want}
            if cur is None:
                missing.append(row)
            elif cur.lower() == want.lower():
                ok.append(row)
            else:
                different.append({**row, "program": cur})
    unnamed = []
    for j in jm["unnamed"]:
        wired = {d: name(h) for d, h in have.get((j["type"], j["join"]), {}).items()}
        unnamed.append({"type": j["type"], "join": j["join"], "program": wired or None})
    in_map = {(j["type"], j["join"]) for j in jm["joins"] + jm["unnamed"]}
    not_on_panel = [{"type": t, "join": n, **{d: name(h) for d, h in v.items()}}
                    for (t, n), v in sorted(have.items(), key=lambda kv: (TYPES.index(kv[0][0]), kv[0][1]))
                    if (t, n) not in in_map]
    fix: dict[tuple[str, int], dict[str, Any]] = {}
    for r in missing:
        fix.setdefault((r["type"], r["join"]), {"type": r["type"], "join": r["join"]})[r["direction"]] = r["panel_map"]
    return {
        "matches": not missing and not different,
        "counts": {"ok": len(ok), "missing": len(missing), "different": len(different),
                   "panel_joins_without_signal_names": len(unnamed), "wired_but_not_on_panel": len(not_on_panel)},
        "missing": missing, "different": different,
        "panel_joins_without_signal_names": unnamed, "wired_but_not_on_panel": not_on_panel,
        "wire_joins_for_missing": list(fix.values()),
    }
