"""Compile a program with SIMPL Windows through the "\\SIMPL Agent\\Compile" scheduled task.

SIMPL runs as administrator, so the compile is done by smpc (MIT, Norgate-AV/smpc) inside an
elevated scheduled task installed once by tools/compile_task/setup.ps1. This side only writes
a request file, starts the task and waits for the result file; the task validates the request
(a .smw under an allowed folder) and refuses anything else.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

TASK = r"\SIMPL Agent\Compile"
INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "SimplAgent"
MESSAGE_RE = re.compile(r"(ERROR|WARNING|NOTICE)\s*\((\w+)\)\s*:?\s*\**\s*(.*)")


def work_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SimplAgent" / "compile"


class CompileError(RuntimeError):
    pass


def installed() -> bool:
    return (INSTALL_DIR / "smpc.exe").exists() and (INSTALL_DIR / "compile.ps1").exists()


def parse_output(text: str) -> dict[str, Any]:
    """SIMPL's messages and counts from smpc's console output."""
    messages = []
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        m = MESSAGE_RE.search(line)
        if not m:
            continue
        severity, code, rest = m.group(1).lower(), m.group(2), m.group(3).strip()
        # smpc may print the text on the next line, as SIMPL's own log does.
        if not rest and i + 1 < len(lines):
            rest = lines[i + 1].lstrip("* ").strip()
        messages.append({"severity": severity, "code": code, "message": rest.strip('"').strip()})
    counts: dict[str, int] = {}
    for key, label in (("errors", "Program Errors"), ("warnings", "Program Warnings"), ("notices", "Program Notices")):
        m = re.search(re.escape(label) + r"\s*:\s*(\d+)", text)
        if m:
            counts[key] = int(m.group(1))
    if not counts:
        for key in ("error", "warning", "notice"):
            counts[key + "s"] = sum(1 for x in messages if x["severity"] == key)
    return {"counts": counts, "messages": messages}


def compile_program(path: Path, timeout_s: int = 1500, poll_s: float = 2.0) -> dict[str, Any]:
    if not installed():
        raise CompileError("the compile task isn't installed (see tools/compile_task/setup.ps1)")
    wd = work_dir()
    wd.mkdir(parents=True, exist_ok=True)
    req_id = uuid.uuid4().hex
    result_path = wd / "result.json"
    try:
        result_path.unlink()
    except FileNotFoundError:
        pass
    tmp = wd / "request.json.tmp"
    tmp.write_text(json.dumps({"id": req_id, "path": str(path)}), "utf-8")
    os.replace(tmp, wd / "request.json")
    run = subprocess.run(["schtasks", "/run", "/tn", TASK], capture_output=True, text=True)
    if run.returncode != 0:
        raise CompileError(f"couldn't start the compile task: {(run.stderr or run.stdout).strip()}")
    deadline = time.monotonic() + timeout_s
    started = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        try:
            res = json.loads(result_path.read_text("utf-8-sig"))
        except (FileNotFoundError, ValueError):
            if time.monotonic() - started > 60:
                raise CompileError("the compile task didn't start within a minute "
                                   "(is another compile running?)") from None
            continue
        if res.get("id") != req_id:
            continue
        if res.get("state") == "refused":
            raise CompileError(f"the compile task refused: {res.get('error')}")
        if res.get("state") == "done":
            output = res.get("output") or ""
            parsed = parse_output(output)
            return {"exit_code": res.get("exit_code"), **parsed, "output": output[-6000:]}
    raise CompileError(f"no result after {timeout_s} s; the compile may still be running")
