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


def compile_module(path: Path, targets: list[str], timeout_s: int = 600, exe: Path = SPLUSCC) -> dict:
    """Run SPlusCC on one .usp and return the parsed result."""
    path = Path(path)
    ush = path.with_suffix(".ush")
    before = ush.stat().st_mtime if ush.exists() else None
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
    return {"compiled": errors == 0 and bool(per_target), "exit_code": r.returncode, "errors": errors,
            "warnings": warnings, "targets": per_target,
            "ush_written": after is not None and after != before, "ush": str(ush) if ush.exists() else None}
