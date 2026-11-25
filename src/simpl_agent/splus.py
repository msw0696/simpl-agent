"""Compile SIMPL+ modules with Crestron's own command-line compiler, SPlusCC.exe (no window, no admin).

    SPlusCC.exe \\rebuild <module.usp> \\target series3 series4

It writes the module's .ush header and SPlsWork output next to the .usp, and prints, per target:

    Compiling for 4-Series Output: '<path>'...
    [<path>] Error 1001 (Line 9) - Undefined variable: 'NOTHERE'   (the code is optional)
    [<path>] * WARNING  * (Line 50) - <message>
    Total Error(s): 1
    Total Warning(s): 0

and exits non-zero when there are errors. Never talks to a processor.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

SPLUSCC = Path(r"C:\Program Files (x86)\Crestron\Simpl\SPlusCC.exe")
TARGETS = ("series2", "series3", "series4")
TARGET_RE = re.compile(r"Compiling for (?P<target>[\w-]+) Output")
MSG_RE = re.compile(r"^\[(?P<file>[^\]]+)\]\s+(?:\*\s*)?(?P<sev>error|warning|notice)\s*(?P<code>\d+)?\s*"
                    r"(?:\*\s*)?\((?:line\s+)?(?P<line>\d+)\)\s*-\s*(?P<msg>.*)$", re.IGNORECASE)
TOTAL_RE = re.compile(r"Total (?P<kind>Error|Warning)\(s\):\s*(?P<n>\d+)", re.IGNORECASE)


def parse_output(text: str) -> dict:
    """Messages and totals per target from SPlusCC's console output."""
    targets: dict[str, dict] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = TARGET_RE.search(line)
        if m:
            current = targets.setdefault(m.group("target"), {"errors": 0, "warnings": 0, "messages": []})
            continue
        m = MSG_RE.match(line)
        if m and current is not None:
            msg = {"severity": m.group("sev").lower(), "line": int(m.group("line")),
                   "file": Path(m.group("file")).name, "message": m.group("msg").strip()}
            if m.group("code"):
                msg["code"] = int(m.group("code"))
            current["messages"].append(msg)
            continue
        m = TOTAL_RE.search(line)
        if m and current is not None:
            current["errors" if m.group("kind").lower() == "error" else "warnings"] = int(m.group("n"))
    return targets


def fix_line_endings(path: Path) -> bool:
    """Give a .usp CRLF line endings; True if it changed.

    SPlusCC needs them: in a file with bare LF line endings a ``//`` comment runs on to the next
    CR, so everything after the first one is silently dropped and the module compiles "clean"
    with no pins or code (SPlusCC 4.06, 2026-11-25; BOM, UTF-8 text and CR-only were fine).
    """
    data = Path(path).read_bytes()
    fixed = re.sub(rb"\r?\n", b"\r\n", data)
    if fixed == data:
        return False
    Path(path).write_bytes(fixed)
    return True


def module_pins(ush: Path) -> dict | None:
    """The pins and parameters SIMPL will show for a compiled module, read from its .ush."""
    from .analysis import SPLUS_CODE, _module_fields, module_layout
    from .catalog.symlib import LibSymbol

    fields = _module_fields(str(ush))
    if fields is None:
        return None
    lay = module_layout(SPLUS_CODE, LibSymbol(code=SPLUS_CODE, name=fields.get("Name", ""), fields=fields))

    def pins(rows: list) -> list[dict]:
        return [{"pin": n, "name": nm, **({"type": t} if t else {})} for n, nm, t in rows]

    return {"symbol_name": fields.get("Name", ""), "inputs": pins(lay["inputs"]), "outputs": pins(lay["outputs"]),
            "parameters": pins(lay["parameters"])}


def compare_pins(old: dict, new: dict) -> dict | None:
    """How a module's pins changed between two builds (module_pins results), or None if they didn't.

    Placed copies keep their wires by position in each pin list (SIMPL 4.32, 2026-11-25), so any
    change but a pure rename leaves wires on the wrong pins or stops the compile. ``wires_stay``
    is True only when nothing moved, appeared, disappeared or changed type (renames only)."""
    out: dict = {}
    stay = True
    for side in ("inputs", "outputs", "parameters"):
        a = [(p["name"], (p.get("type") or "").lower()) for p in old.get(side, [])]
        b = [(p["name"], (p.get("type") or "").lower()) for p in new.get(side, [])]
        if a == b:
            continue
        an_, bn = [n for n, _ in a], [n for n, _ in b]
        moved = [n for n in an_ if n in bn and an_.index(n) != bn.index(n)]
        retyped = [n for n, t in a if n in bn and b[bn.index(n)][1] != t]
        removed = [n for n in an_ if n not in bn]
        added = [n for n in bn if n not in an_]
        renamed_only = (len(a) == len(b) and not moved and not retyped
                        and all(x[1] == y[1] for x, y in zip(a, b, strict=True)))
        stay = stay and renamed_only
        out[side] = {"before": an_, "after": bn,
                     **({"renamed": [f"{x[0]} -> {y[0]}" for x, y in zip(a, b, strict=True) if x[0] != y[0]]}
                        if renamed_only else
                        {k: v for k, v in (("removed", removed), ("added", added), ("moved", moved),
                                           ("type_changed", retyped)) if v})}
    if not out:
        return None
    return {**out, "wires_stay": stay}


def placed_copies(usp: Path, old_fields: dict[str, str], new_pins: dict) -> list[dict]:
    """Copies of ``usp`` placed in the programs beside it, with their wiring named by the module's
    previous build (``old_fields``), and how to re-place each one by name."""
    from . import analysis as an
    from .catalog.symlib import LibSymbol
    from .smw import rawfile
    from .smw.model import load

    old = LibSymbol(code=an.SPLUS_CODE, name=old_fields.get("Name", ""), fields=old_fields)
    new_in = {p["name"] for p in new_pins.get("inputs", [])}
    new_out = {p["name"] for p in new_pins.get("outputs", [])}
    new_par = {p["name"] for p in new_pins.get("parameters", [])}
    out = []
    for prog_path in sorted(usp.parent.glob("*.smw")):
        try:
            prog = load(rawfile.read(prog_path))
        except Exception:  # noqa: BLE001 - not a readable program; skip it
            continue
        for s in prog.symbols.values():
            if s.code != an.SPLUS_CODE or (s.name or "").strip().lower() != usp.name.lower():
                continue
            names = {h: sg.name for h, sg in prog.signals.items()}
            wired_in = {an.pin_label(old, s, "I", n): names.get(h, f"#{h}") for n, h in sorted(s.inputs.items())}
            wired_out = {an.pin_label(old, s, "O", n): names.get(h, f"#{h}") for n, h in sorted(s.outputs.items())}
            params = {an.pin_label(old, s, "P", n): v for n, v in sorted(s.params.items())
                      if an.pin_label(old, s, "P", n) not in (an.UNUSED_PIN, an.REFERENCE_NAME)}
            connect = {k: v for k, v in wired_in.items() if k in new_in}
            connect.update({k: v for k, v in wired_out.items() if k in new_out and k not in connect})
            gone = {k: v for k, v in {**wired_in, **wired_out}.items() if k not in new_in | new_out}
            stale = an.module_fit_issues(prog, s, old_fields)
            out.append({
                **({"already_out_of_date": "This copy didn't fit the previous build either ("
                    + "; ".join(stale[:3]) + "), so it was placed with an older one: the pin names in "
                    "'wiring_before' may be wrong. Check its wiring with the user."} if stale else {}),
                "program": str(prog_path), "symbol": f"#{s.handle}", "simpl_number": an.simpl_number(prog, s.handle),
                "wiring_before": {"inputs": wired_in, "outputs": wired_out, "parameters": params},
                "re_place_with": {"remove_symbol": f"#{s.handle}",
                                  "add_module": {"module": usp.name, "connect": connect,
                                                 "parameters": {k: v for k, v in params.items() if k in new_par}}},
                **({"signals_on_removed_pins": gone} if gone else {}),
            })
    return out


def compile_module(path: Path, targets: list[str], timeout_s: int = 600, exe: Path = SPLUSCC) -> dict:
    """Run SPlusCC on one .usp and return the parsed result (fixing its line endings first)."""
    path = Path(path)
    crlf_fixed = fix_line_endings(path)
    ush = path.with_suffix(".ush")
    before = ush.stat().st_mtime if ush.exists() else None
    old_pins = module_pins(ush) if before is not None else None
    if old_pins is not None:
        from .analysis import _module_fields

        old_fields = dict(_module_fields(str(ush)) or {})
    # One command-line string: SPlusCC reads its own switches ('\\rebuild', '\\target').
    cmd = subprocess.list2cmdline([str(exe), "\\rebuild", str(path), "\\target", *targets])
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout_s,
                       cwd=str(path.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (r.stdout + r.stderr).decode("latin-1")
    if "command line parameters:" in text and "Compiling for" not in text:
        raise RuntimeError("SPlusCC didn't accept the command line")
    per_target = parse_output(text)
    errors = sum(t["errors"] for t in per_target.values())
    warnings = sum(t["warnings"] for t in per_target.values())
    after = ush.stat().st_mtime if ush.exists() else None
    written = after is not None and after != before
    pins = module_pins(ush) if written else None
    changed = compare_pins(old_pins, pins) if old_pins is not None and pins is not None else None
    copies = placed_copies(path, old_fields, pins) if changed else []
    return {"compiled": errors == 0 and bool(per_target), "exit_code": r.returncode, "errors": errors,
            "warnings": warnings, "targets": per_target,
            "ush_written": written, "ush": str(ush) if ush.exists() else None,
            **({"line_endings_fixed": True} if crlf_fixed else {}),
            **({"module": pins} if pins is not None else {}),
            **({"pins_changed": changed} if changed else {}),
            **({"placed_copies": copies} if copies else {})}
