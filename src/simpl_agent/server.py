"""SIMPL Agent MCP server (stdio).

M1 tools are read-only:

* ``simpl_agent_status``      what's installed and whether SIMPL Windows has a program open
* ``describe_program``        a program's header, processor, counts and top-level folders
* ``find_library_symbols``    search SIMPL's installed symbol library
* ``library_symbol_details``  one library symbol's pins, parameters and rules

Every call is appended to ``%LOCALAPPDATA%\\SimplAgent\\audit.jsonl`` (time, tool,
arguments, outcome, duration), whatever the outcome. Read results carry a
``revision`` (SHA-256 of the file's bytes): SIMPL can renumber handles when it
saves, so later edit tools will refuse a stale revision.

Nothing here writes to a program, talks to a processor, or uses the network.
Never print to stdout: it carries the MCP protocol.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from . import analysis as an
from .catalog.index import LibraryIndex, cache_dir, load_index
from .catalog.symlib import DEFAULT_SYMLIB
from .edit_tools import EditTools
from .errors import ToolError
from .smw import rawfile
from .smw.edit import FOLDER_CODE, is_simple, load_verified_codes
from .smw.model import Program, load

TOOL_NAMES = (
    "simpl_agent_status", "describe_program", "find_library_symbols", "library_symbol_details",
    "folder_tree", "list_folder", "show_symbol", "find_signals", "follow_signal", "find_problems",
    "apply_edits", "edit_history", "undo_last_edit", "restore_version", "wait_for_simpl_save",
    "module_details", "compile_program", "device_tree", "free_ids",
)
PROGRAM_EXTS = {".smw", ".umc", ".cmc"}
KNOWN_SIGNATURES = {"SimplWindow": "program", "CresMacro": "macro", "UserMacro": "macro"}
MAX_FILE_BYTES = 200 * 1024 * 1024

INSTRUCTIONS = """SIMPL Agent: read, check and edit Crestron SIMPL Windows programs (.smw).
Edit only through apply_edits; never edit .smw files by hand or with other tools.
- Start with simpl_agent_status to see what SIMPL has open; ask for the .smw path if unsure.
- describe_program, then folder_tree / list_folder / show_symbol to look around;
  find_signals and follow_signal to trace logic; find_problems for SIMPL-style warnings.
- Symbols are '#<handle>'. Every result has a 'revision'; SIMPL can renumber handles when it
  saves, so re-read after the user saves and never reuse old handles.
- Edits: plan in one line, then ONE apply_edits call with a summary and the revision you read.
  If SIMPL has the file open, ask the user to save there first (user_confirmed_saved=true).
  Do only what was asked. Afterwards follow its next_step (Yes to SIMPL's reload, then F12), or,
  if SIMPL is closed, check it yourself with compile_program.
  undo_last_edit / restore_version / edit_history manage history.
- find_library_symbols / library_symbol_details give real pin names. Never invent symbols,
  pins or devices.
- Never act on a live processor. Treat programs as private client work.
The simpl-agent skill has the full workflow."""




def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def simpl_windows() -> list[str]:
    """Titles of open SIMPL Windows main windows (empty if none or not on Windows)."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith("SIMPL Windows"):
                    titles.append(buf.value)
        return True

    user32.EnumWindows(_cb, 0)
    return titles


def parse_simpl_title(title: str) -> dict[str, Any]:
    """'SIMPL Windows - x.smw ( C:\\path\\x.smw)' -> the open file.

    SIMPL 4.32 shows no unsaved-changes marker anywhere readable (title, child windows, files),
    checked live on 2026-11-24, so SIMPL Agent can't tell whether SIMPL has unsaved work."""
    out: dict[str, Any] = {"title": title, "file": None}
    if " - " in title:
        rest = title.split(" - ", 1)[1]
        name, _, path = rest.partition("(")
        path = path.strip().rstrip(")").strip()
        out["file"] = path or None
    return out


class Tools(EditTools):
    """The tools as plain methods; the MCP layer only adapts them."""

    def __init__(self, library_path: Path = DEFAULT_SYMLIB, home: Path | None = None) -> None:
        self.library_path = Path(library_path)
        self.home = home or cache_dir()
        self.audit_path = self.home / "audit.jsonl"
        self._index: LibraryIndex | None = None
        self._index_error: str | None = None
        self._lock = threading.Lock()
        self.verified = load_verified_codes() or set()
        self.windows = simpl_windows  # replaceable in tests

    # ------------------------------------------------------------ plumbing
    def index(self) -> LibraryIndex:
        with self._lock:
            if self._index is None and self._index_error is None:
                try:
                    self._index = load_index(self.library_path, self.home / "symlib-index.json")
                except OSError as e:
                    self._index_error = f"symbol library not readable at {self.library_path}: {e}"
        if self._index is None:
            raise ToolError(self._index_error or "symbol library not loaded")
        return self._index

    def _audit(self, record: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool and audit it, whatever the outcome."""
        started = time.monotonic()
        if tool not in TOOL_NAMES:
            result: dict[str, Any] = {"ok": False, "error": f"no tool {tool!r}"}
            outcome = "refused"
        else:
            try:
                result = {"ok": True, **getattr(self, tool)(**arguments)}
                outcome = "ok"
            except ToolError as e:
                result, outcome = {"ok": False, "error": str(e)}, "refused"
            except Exception as e:  # noqa: BLE001 - reported to the client and logged
                result, outcome = {"ok": False, "error": f"{type(e).__name__}: {e}"}, "error"
        try:
            self._audit({"timestamp": _now(), "tool": tool, "arguments": arguments, "outcome": outcome,
                         "error": result.get("error"), "duration_s": round(time.monotonic() - started, 3)})
        except OSError:
            pass  # never fail a read because the log is unwritable
        return result

    def _read_program(self, path: str) -> tuple[Path, bytes, Program]:
        if not isinstance(path, str) or not path.strip():
            raise ToolError("give the full path to a .smw file")
        p = Path(path.strip().strip('"'))
        if p.suffix.lower() not in PROGRAM_EXTS:
            raise ToolError(f"{p.name}: only .smw, .umc and .cmc files can be read")
        if not p.is_file():
            raise ToolError(f"no such file: {p}")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ToolError(f"{p.name} is larger than {MAX_FILE_BYTES // 2**20} MB")
        data = p.read_bytes()
        raw = rawfile.parse(data)
        prog = load(raw)
        if prog.kind not in KNOWN_SIGNATURES:
            raise ToolError(
                f"{p.name} isn't a readable SIMPL program (signature {prog.kind!r}); "
                "it may be protected or not a SIMPL file"
            )
        return p, data, prog

    # ------------------------------------------------------------ tools
    def simpl_agent_status(self) -> dict[str, Any]:
        lib: dict[str, Any] = {"path": str(self.library_path), "found": self.library_path.exists()}
        if lib["found"]:
            try:
                ix = self.index()
                lib["symbols"] = len(ix.library.symbols)
            except ToolError as e:
                lib["error"] = str(e)
        return {
            "version": __version__,
            "milestone": "M4: devices (in progress)",
            "symbol_library": lib,
            "symbols_add_symbol_can_build": len(self.verified),
            "simpl_windows_open": [parse_simpl_title(t) for t in self.windows()],
            "audit_log": str(self.audit_path),
        }

    def describe_program(self, path: str, max_folders: int = 50) -> dict[str, Any]:
        p, data, prog = self._read_program(path)
        hd = prog.header
        sig = prog.signature
        cnh = hd.get("CnH") if hd is not None else None
        proc = prog.devices.get(int(cnh)) if cnh and cnh.isdigit() else None
        folders = [s for s in prog.symbols.values() if s.code == FOLDER_CODE]
        logic_root = next((s for s in folders if s.parent is None and (s.name or "") == "Logic"), None)

        def folder_name(s) -> str:
            return (s.comment or s.name or "").rstrip("\\") or f"#{s.handle}"

        def count_below(h: int, seen: set[int] | None = None) -> int:
            seen = seen if seen is not None else set()
            n = 0
            for c in prog.symbols[h].children:
                if c in prog.symbols and c not in seen:
                    seen.add(c)
                    n += 1 + count_below(c, seen)
            return n

        top = []
        if logic_root is not None:
            for c in logic_root.children:
                s = prog.symbols.get(c)
                if s is None:
                    continue
                top.append({
                    "handle": s.handle,
                    "name": folder_name(s) if s.code == FOLDER_CODE else (s.name or str(s.code)),
                    "is_folder": s.code == FOLDER_CODE,
                    "symbols_inside": count_below(s.handle) if s.code == FOLDER_CODE else 0,
                })
        types: dict[str, int] = {}
        for s in prog.signals.values():
            if s.record is not None:
                types[s.type] = types.get(s.type, 0) + 1
        open_in = [w for w in map(parse_simpl_title, self.windows())
                   if w["file"] and Path(w["file"]).resolve() == p.resolve()]
        return {
            "path": str(p),
            "revision": hashlib.sha256(data).hexdigest(),
            "kind": KNOWN_SIGNATURES[prog.kind],
            "simpl_version": sig.get("RelVrs") if sig is not None else None,
            "saved_by": sig.get("SavedBy") if sig is not None else None,
            "program_name": hd.get("PrNm") if hd is not None else None,
            "client": hd.get("CltNm") if hd is not None else None,
            "programmer": hd.get("PgmNm") if hd is not None else None,
            "processor": proc.name if proc else None,
            "counts": {
                "symbols": len(prog.symbols),
                "logic_symbols": count_below(logic_root.handle) if logic_root else 0,
                "folders": len(folders) - (1 if logic_root else 0),
                "signals": sum(types.values()),
                "signals_by_type": types,
                "device_records": len({id(d) for d in prog.devices.values()}),
            },
            "logic_top_level": top[:max_folders],
            "logic_top_level_total": len(top),
            "open_in_simpl": bool(open_in),
        }

    def _symbol_row(self, ix: LibraryIndex, s) -> dict[str, Any]:
        tree = s.fields.get("SymbolTree")
        return {
            "code": s.code,
            "name": s.name,
            "library_folder": ix.trees.get(int(tree)) if tree and tree.isdigit() else None,
            "kind": "logic" if is_simple(s) else ("device" if s.fields.get("DeviceCode", "0") != "0" else "other"),
            "add_symbol_supported": s.code in self.verified,
        }

    def find_library_symbols(self, query: str, limit: int = 20) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ToolError("give a word or two to search for, e.g. 'one shot'")
        limit = max(1, min(int(limit), 100))
        ix = self.index()
        hits = ix.search(query, limit=limit)
        return {"query": query, "results": [self._symbol_row(ix, s) for s in hits]}

    def library_symbol_details(self, symbol: str | int) -> dict[str, Any]:
        ix = self.index()
        s = None
        if isinstance(symbol, int) or (isinstance(symbol, str) and symbol.strip().lstrip("-").isdigit()):
            s = ix.library.get(int(symbol))
        elif isinstance(symbol, str):
            matches = ix.library.by_name.get(symbol.strip().lower(), [])
            s = matches[0] if matches else None
        if s is None:
            raise ToolError(f"no library symbol {symbol!r}; try find_library_symbols")
        f = s.fields

        def pins(prefix: str, type_prefix: str) -> list[dict[str, Any]]:
            out = []
            for n, cue in s.cues(prefix).items():
                t = f.get(f"{type_prefix}{n}")
                out.append({"pin": n, "name": cue, **({"type": t} if t else {})})
            return out

        def num(k: str) -> int | None:
            v = f.get(k)
            return int(v) if v and v.lstrip("-").isdigit() else None

        inputs, outputs = pins("InputCue", "InputSigType"), pins("OutputCue", "OutputSigType")

        def repeating(listed: list[dict[str, Any]], max_key: str, default: str) -> str | None:
            # A name ending in '#' repeats (i1, i2, ...). The library leaves some
            # repeating pins unnamed; SIMPL then numbers them i1.. / o1...
            for p in listed:
                if p["name"].endswith("#"):
                    return p["name"]
            return default if num(max_key) else None

        return {
            **self._symbol_row(ix, s),
            "hint": f.get("Hint"),
            "inputs": inputs,
            "outputs": outputs,
            "repeating_input_name": repeating(inputs, "MaxVariableInputs", "i#"),
            "repeating_output_name": repeating(outputs, "MaxVariableOutputs", "o#"),
            "pin_note": "Names ending in '#' repeat (i1, i2, ...). Names in [brackets] appear to be "
            "optional pins (inferred, unconfirmed). Pins are wired by position.",
            "parameters": pins("ParamCue", "ParamSigType"),
            "rules": {
                "fixed_inputs": num("NumFixedInputs") or 0,
                "fixed_outputs": num("NumFixedOutputs") or 0,
                "fixed_parameters": num("NumFixedParams") or 0,
                "max_extra_inputs": num("MaxVariableInputs") or 0,
                "max_extra_outputs": num("MaxVariableOutputs") or 0,
                "extra_inputs_come_with_outputs": f.get("Expand") == "expand_inputs_with_outputs",
                "outputs_may_share_a_signal": s.shares_outputs,
                "has_extra_pin_lists": f.get("HasExtraPinLists") == "True",
            },
            "release_status": f.get("CDSReleaseStatus"),
        }


    # ------------------------------------------------------------ M2: read and check
    def _load(self, path: str) -> tuple[Path, str, Program, Any]:
        p, data, prog = self._read_program(path)
        try:
            lib = self.index().library
        except ToolError:
            lib = None  # still useful without pin names
        return p, hashlib.sha256(data).hexdigest(), prog, lib

    @staticmethod
    def _page(items: list, offset: int, limit: int, cap: int = 500) -> tuple[list, dict]:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), cap))
        shown = items[offset:offset + limit]
        return shown, {"total": len(items), "offset": offset, "returned": len(shown)}

    def _symbol_ref(self, prog: Program, ref: str | int) -> int:
        s = str(ref).strip()
        if s.startswith("#"):
            s = s[1:]
        if not s.isdigit() or int(s) not in prog.symbols:
            raise ToolError(f"no symbol {ref!r}; symbols are referred to by handle, e.g. '#20'")
        return int(s)

    def _folder_ref(self, prog: Program, ref: str | int | None) -> int:
        folders = [s for s in prog.symbols.values() if an.is_folder(s)]
        if ref in (None, "", "Logic", "logic"):
            root = next((s for s in folders if s.parent is None and (s.name or "") == "Logic"), None)
            if root is None:
                raise ToolError("this file has no Logic folder")
            return root.handle
        if str(ref).strip().startswith("#"):
            h = self._symbol_ref(prog, ref)
            if not an.is_folder(prog.symbols[h]):
                raise ToolError(f"#{h} is a symbol, not a folder; use show_symbol")
            return h
        want = str(ref).strip().strip("\\").lower()

        def full(s) -> str:
            parent = an.folder_path(prog, s.handle)
            return (parent + "\\" if parent else "") + an.display_name(s)

        hits = [s.handle for s in folders if an.display_name(s).lower() == want or full(s).lower() == want]
        if len(hits) != 1:
            raise ToolError(f"{len(hits)} folders match {ref!r}; use the folder's handle from folder_tree")
        return hits[0]

    def _sig(self, prog: Program, h: int) -> dict[str, Any]:
        sg = prog.signals.get(h)
        return {"signal": sg.name if sg else f"#{h}?", "type": sg.type if sg else None}

    def _signal_ref(self, prog: Program, ref: str | int) -> int:
        s = str(ref).strip()
        if s.startswith("#") and s[1:].isdigit() and int(s[1:]) in prog.signals:
            return int(s[1:])
        hits = [x.handle for x in prog.signals.values() if x.name.lower() == s.lower()]
        if not hits:
            raise ToolError(f"no signal named {ref!r}; try find_signals")
        return hits[0]

    @staticmethod
    def _definition(p: Path, lib, s):
        """Pin names for a symbol: a macro's or SIMPL+ module's own file, else the library."""
        from .corpus import INSTALLED_MODULES

        if s.code in (an.MACRO_CODE, an.SPLUS_CODE):
            d = an.module_definition(p, s, INSTALLED_MODULES)
            if d is not None:
                return d
        return lib.get(s.code) if lib else None

    def _brief(self, prog: Program, lib, h: int) -> dict[str, Any]:
        s = prog.symbols[h]
        return {"symbol": f"#{h}", "name": an.display_name(s, lib), "folder": an.folder_path(prog, h, lib)}

    def folder_tree(self, path: str, max_depth: int = 6, limit: int = 300) -> dict[str, Any]:
        p, rev, prog, lib = self._load(path)
        root = self._folder_ref(prog, None)
        rows: list[dict[str, Any]] = []

        def walk(h: int, depth: int, seen: set[int]) -> int:
            n = 0
            for c in prog.symbols[h].children:
                if c not in prog.symbols or c in seen:
                    continue
                seen.add(c)
                n += 1
                if an.is_folder(prog.symbols[c]):
                    row = {"folder": f"#{c}", "name": an.display_name(prog.symbols[c]), "depth": depth}
                    rows.append(row)
                    inner = walk(c, depth + 1, seen) if depth < max_depth else 0
                    row["symbols_inside"] = inner
                    n += inner
            return n

        total = walk(root, 1, set())
        shown, page = self._page(rows, 0, limit, cap=1000)
        return {"path": str(p), "revision": rev, "root": f"#{root}", "logic_symbols": total,
                "folders": shown, "page": page}

    def list_folder(self, path: str, folder: str = "Logic", offset: int = 0, limit: int = 100) -> dict[str, Any]:
        p, rev, prog, lib = self._load(path)
        h = self._folder_ref(prog, folder)
        rows = []
        for c in prog.symbols[h].children:
            s = prog.symbols.get(c)
            if s is None:
                continue
            row: dict[str, Any] = {"symbol": f"#{c}", "simpl_number": an.simpl_number(prog, c), "name": an.display_name(s, lib),
                                   "is_folder": an.is_folder(s)}
            if s.comment and not an.is_folder(s):
                row["comment"] = "\n".join(an.comment_lines(s))
            if not an.is_folder(s):
                row["inputs"] = len(s.inputs)
                row["outputs"] = len(s.outputs)
            rows.append(row)
        shown, page = self._page(rows, offset, limit)
        parent = an.folder_path(prog, h)
        return {"path": str(p), "revision": rev, "folder": f"#{h}",
                "folder_path": (parent + "\\" if parent else "") + an.display_name(prog.symbols[h]),
                "symbols": shown, "page": page}

    def show_symbol(self, path: str, symbol: str) -> dict[str, Any]:
        p, rev, prog, lib = self._load(path)
        h = self._symbol_ref(prog, symbol)
        s = prog.symbols[h]
        ls = self._definition(p, lib, s)

        def pins(letter: str, conns: dict[int, int], total_key: str) -> list[dict[str, Any]]:
            total = s.record.get(total_key)
            n_max = int(total) if total and total.isdigit() else max(conns, default=0)
            return [{"pin": n, "name": an.pin_label(ls, s, letter, n),
                     **(self._sig(prog, conns[n]) if n in conns else {"signal": None})}
                    for n in range(1, n_max + 1)]

        comments = an.comment_lines(s)
        return {
            "path": str(p), "revision": rev, "symbol": f"#{h}", "name": an.display_name(s, lib),
            "library": {"code": s.code, "name": ls.name if ls else None},
            "folder": an.folder_path(prog, h, lib), "simpl_number": an.simpl_number(prog, h),
            "is_folder": an.is_folder(s), "comment": "\n".join(comments) or None,
            "complete": {"2": True, "1": False}.get(s.record.get("CF") or "", None),
            "device": f"#{s.device}" if s.device is not None else None,
            "inputs": pins("I", s.inputs, "mI"),
            "outputs": pins("O", s.outputs, "tO"),
            "parameters": [{"pin": n, "name": an.pin_label(ls, s, "P", n), "value": v}
                           for n, v in sorted(s.params.items())],
            "children": [f"#{c}" for c in s.children][:200],
        }

    def find_signals(self, path: str, query: str = "", signal_type: str = "", offset: int = 0,
                     limit: int = 100) -> dict[str, Any]:
        p, rev, prog, lib = self._load(path)
        if signal_type and signal_type not in ("digital", "analog", "serial"):
            raise ToolError("signal_type must be digital, analog or serial")
        flow = an.signal_flow(prog)
        q = (query or "").lower()
        rows = []
        for h, sg in sorted(prog.signals.items(), key=lambda kv: kv[1].name.lower()):
            if sg.record is None or (q and q not in sg.name.lower()) or (signal_type and sg.type != signal_type):
                continue
            rows.append({"signal": sg.name, "handle": f"#{h}", "type": sg.type,
                         "drivers": len(flow.drivers.get(h, [])), "destinations": len(flow.destinations.get(h, []))})
        shown, page = self._page(rows, offset, limit)
        return {"path": str(p), "revision": rev, "signals": shown, "page": page}

    def follow_signal(self, path: str, signal: str, limit: int = 100) -> dict[str, Any]:
        p, rev, prog, lib = self._load(path)
        h = self._signal_ref(prog, signal)
        flow = an.signal_flow(prog)

        def ends(pairs: list[tuple[int, int]], letter: str) -> list[dict[str, Any]]:
            out = []
            for sh, n in pairs[:limit]:
                s = prog.symbols[sh]
                ls = self._definition(p, lib, s)
                out.append({**self._brief(prog, lib, sh), "pin": f"{letter}{n}",
                            "pin_name": an.pin_label(ls, s, letter, n)})
            return out

        sg = prog.signals[h]
        drv, dst = flow.drivers.get(h, []), flow.destinations.get(h, [])
        out = {"path": str(p), "revision": rev, "signal": sg.name, "handle": f"#{h}", "type": sg.type,
               "built_in": sg.record is None,
               "driven_by": ends(drv, "O"), "goes_to": ends(dst, "I"),
               "totals": {"driven_by": len(drv), "goes_to": len(dst)}}
        if flow.arg_in.get(h):
            out["macro_input_argument"] = [f"I{n}" for _, n in flow.arg_in[h]]
        if flow.arg_out.get(h):
            out["macro_output_argument"] = [f"O{n}" for _, n in flow.arg_out[h]]
        return out

    def _device_library(self):
        from .catalog.devices import DEFAULT_IODEV, load_devices

        if getattr(self, "_devlib", None) is None:
            try:
                self._devlib = load_devices(DEFAULT_IODEV, self.home / "iodev-index.json")
            except OSError:
                self._devlib = None
        return self._devlib

    def device_tree(self, path: str, limit: int = 300) -> dict[str, Any]:
        from . import devices as dv

        p, rev, prog, lib = self._load(path)
        rows = dv.device_rows(prog, limit=max(1, min(int(limit), 2000)))
        hd = prog.header
        cnh = hd.get("CnH") if hd is not None else None
        proc = prog.devices.get(int(cnh)) if cnh and cnh.isdigit() else None
        return {"path": str(p), "revision": rev, "processor": proc.name if proc else None,
                "devices": rows, "count": len(rows)}

    def free_ids(self, path: str, network: str = "") -> dict[str, Any]:
        from . import devices as dv

        p, rev, prog, lib = self._load(path)
        nets = dv.networks(prog, self._device_library())
        if network:
            want = network.lower()
            nets = [n for n in nets if want in (n["network"] or "").lower() or want in (n["transport"] or "").lower()]
        return {"path": str(p), "revision": rev, "networks": nets}

    def compile_program(self, path: str, timeout_s: int = 1500) -> dict[str, Any]:
        """Compile with SIMPL Windows (via the installed compile task) and compare SIMPL's
        messages with find_problems."""
        from . import compile as cmp

        p, data, prog = self._read_program(path)
        if p.suffix.lower() != ".smw":
            raise ToolError("only programs (.smw) can be compiled")
        if not cmp.installed():
            raise ToolError("automatic compiling isn't set up on this PC; ask the user to press F12 in SIMPL")
        if self.windows():
            raise ToolError("SIMPL Windows is open. The compile drives SIMPL's window, so ask the user to close "
                            "SIMPL first (or to press F12 themselves).")
        before = hashlib.sha256(data).hexdigest()
        try:
            lib = self.index().library
        except ToolError:
            lib = None
        predicted = {(x.code, x.message) for x in an.find_problems(prog, lib)}
        try:
            r = cmp.compile_program(p, timeout_s=max(60, min(int(timeout_s), 3600)))
        except cmp.CompileError as e:
            raise ToolError(str(e)) from e
        got = {(m["code"], m["message"]) for m in r["messages"]}
        after = hashlib.sha256(p.read_bytes()).hexdigest()
        failed = "incomplete symbols" in r["output"] or (r["exit_code"] not in (0, None) and not r["messages"])
        return {
            "path": str(p),
            "compiled": not failed and r["counts"].get("errors", 0) == 0,
            "counts": r["counts"],
            "messages": r["messages"][:300],
            "matches_find_problems": got == predicted,
            "reported_by_simpl_only": sorted(got - predicted)[:50],
            "predicted_only": sorted(predicted - got)[:50],
            "file_changed_by_simpl": after != before,
            "revision": after,
            # Dialogs SIMPL showed (smpc clicks some through); any here deserve a look.
            "dialogs_seen": r.get("dialogs_seen", []),
            "dialogs_auto_confirmed": r.get("dialogs_auto_confirmed", []),
            "note": ("SIMPL couldn't compile: see 'output'." if failed else
                     "SIMPL's messages are the final word. If matches_find_problems is false, tell the user; "
                     "it may be a SIMPL Agent rule to fix."),
            **({"output": r["output"][-3000:]} if failed else {}),
        }

    def module_details(self, path: str, module: str) -> dict[str, Any]:
        """A macro's or SIMPL+ module's pins and parameters, as SIMPL would place it in ``path``."""
        from .corpus import INSTALLED_MODULES
        from .smw.edit import EditError, Editor

        p, data, _ = self._read_program(path)
        ed = Editor(rawfile.parse(data), None, program_path=p, installed_modules=INSTALLED_MODULES)
        try:
            code, d, lay = ed.module_definition(module)
        except EditError as e:
            raise ToolError(str(e)) from e

        def rows(items):
            return [{"pin": f"{n}", "name": nm, "type": t} for n, nm, t in items if nm != an.UNUSED_PIN]

        params = [{"pin": f"P{n}", "name": nm, "type": t} for n, nm, t in lay["parameters"]
                  if nm not in (an.UNUSED_PIN, an.REFERENCE_NAME)]
        return {
            "module": module, "kind": "macro" if code == an.MACRO_CODE else "SIMPL+",
            "name": d.name, "inputs": rows(lay["inputs"]), "outputs": rows(lay["outputs"]),
            "parameters_required": params,
            "note": "Wire pins by these names in apply_edits add_module 'connect'. Unlisted pins stay "
                    "unconnected. Every listed parameter needs a value.",
        }

    def find_problems(self, path: str, limit: int = 200) -> dict[str, Any]:
        p, rev, prog, lib = self._load(path)
        probs = an.find_problems(prog, lib)
        counts: dict[str, int] = {}
        for x in probs:
            counts[x.severity] = counts.get(x.severity, 0) + 1
        shown, page = self._page([x.as_dict() for x in probs], 0, limit, cap=2000)
        out = {"path": str(p), "revision": rev, "counts": counts, "problems": shown, "page": page,
               "note": "Codes LGCMCVT102/103/220 follow SIMPL 4.32's compiler messages (checked on a small "
                       "set of compiled files); SA-* are SIMPL Agent's own. "
                       "SIMPL's compile (F12) is the final word."}
        if prog.kind == "CresMacro":
            out["macro_note"] = ("This is a macro. Its arguments are treated as its inputs and outputs; "
                                 "results for macros haven't been checked against SIMPL yet.")
        return out


# ---------------------------------------------------------------------- MCP layer
def create_server(tools: Tools | None = None) -> Any:
    import anyio
    from mcp.server.mcpserver import MCPServer

    t = tools or Tools()
    server = MCPServer(name="simpl-agent", instructions=INSTRUCTIONS, version=__version__)

    async def _run(tool: str, **arguments: Any) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(lambda: t.call(tool, arguments))

    @server.tool(
        name="simpl_agent_status",
        description="Call first. SIMPL Agent's version and milestone, whether SIMPL's symbol library "
        "was found, and which program SIMPL Windows has open. It can't see unsaved changes in SIMPL. Read-only.",
    )
    async def simpl_agent_status() -> dict[str, Any]:
        return await _run("simpl_agent_status")

    @server.tool(
        name="describe_program",
        description="Read a SIMPL Windows program (.smw; also .umc/.cmc macros) without changing it: "
        "SIMPL version, processor, client and programmer, symbol/folder/signal counts, the top level "
        "of the Logic folder, whether SIMPL has it open, and its 'revision' (changes whenever the "
        "file changes). path: full Windows path.",
    )
    async def describe_program(path: str, max_folders: int = 50) -> dict[str, Any]:
        return await _run("describe_program", path=path, max_folders=max_folders)

    @server.tool(
        name="find_library_symbols",
        description="Search SIMPL's installed symbol library by name or hint words (e.g. 'one shot', "
        "'analog ramp'). Returns code, name, library folder, kind, and whether add_symbol can build it.",
    )
    async def find_library_symbols(query: str, limit: int = 20) -> dict[str, Any]:
        return await _run("find_library_symbols", query=query, limit=limit)

    @server.tool(
        name="library_symbol_details",
        description="One library symbol by code or exact name: its input, output and parameter pin "
        "names and types, and its pin rules (fixed pins, extra pins, whether outputs may share a "
        "signal). Use these names; never guess pins.",
    )
    async def library_symbol_details(symbol: str) -> dict[str, Any]:
        return await _run("library_symbol_details", symbol=symbol)

    @server.tool(name="folder_tree", description="The folder tree under Logic: each folder's handle, "
                 "name, depth and how many symbols are inside. Read-only.")
    async def folder_tree(path: str, max_depth: int = 6, limit: int = 300) -> dict[str, Any]:
        return await _run("folder_tree", path=path, max_depth=max_depth, limit=limit)

    @server.tool(name="list_folder", description="The symbols in one folder, in SIMPL's order (position "
                 "with SIMPL's own S-number, e.g. S-2.3, as its compiler prints it), with handle, "
                 "name, comment and pin counts. folder: 'Logic' (default), a folder "
                 "handle like '#25', or a folder name. Paged with offset/limit.")
    async def list_folder(path: str, folder: str = "Logic", offset: int = 0, limit: int = 100) -> dict[str, Any]:
        return await _run("list_folder", path=path, folder=folder, offset=offset, limit=limit)

    @server.tool(name="show_symbol", description="One symbol by handle ('#20'): its library type, folder, "
                 "comment, every input/output pin with the library pin name and the connected signal "
                 "(or none), and its parameters.")
    async def show_symbol(path: str, symbol: str) -> dict[str, Any]:
        return await _run("show_symbol", path=path, symbol=symbol)

    @server.tool(name="find_signals", description="Signals whose name contains query (all if empty), "
                 "optionally only digital/analog/serial, with how many outputs drive each and how many "
                 "inputs it goes to. Paged with offset/limit.")
    async def find_signals(path: str, query: str = "", signal_type: str = "", offset: int = 0,
                           limit: int = 100) -> dict[str, Any]:
        return await _run("find_signals", path=path, query=query, signal_type=signal_type,
                          offset=offset, limit=limit)

    @server.tool(name="follow_signal", description="Trace one signal (by name or '#handle'): every "
                 "symbol output that drives it and every symbol input it goes to, with folder and pin names.")
    async def follow_signal(path: str, signal: str, limit: int = 100) -> dict[str, Any]:
        return await _run("follow_signal", path=path, signal=signal, limit=limit)

    @server.tool(name="find_problems", description="Check a program the way SIMPL's compiler does: "
                 "signals with no driving source (LGCMCVT102), no destination (LGCMCVT103), a second "
                 "driver (LGCMCVT220), plus duplicate names, broken references and incomplete symbols. "
                 "Read-only; F12 in SIMPL is still the final check.")
    async def find_problems(path: str, limit: int = 200) -> dict[str, Any]:
        return await _run("find_problems", path=path, limit=limit)

    @server.tool(name="apply_edits", description="Change a program: ONE call with every operation the "
                 "request needs, applied together (all or nothing). Needs the 'revision' from your last "
                 "read and a one-line summary for the history. If SIMPL has the file open, first ask the user to "
                 "save in SIMPL (Ctrl+S) and pass user_confirmed_saved=true once they have. "
                 "Operations (op + fields): add_symbol {symbol (library code or exact name), folder, "
                 "inputs [signal names, in pin order], outputs [...], parameters?, comment?, "
                 "new_signal_type?}; add_folder {name, parent?}; connect {symbol '#h', pin 'I2'/'O1', "
                 "signal (omit to disconnect), new_signal_type?}; set_parameter {symbol, pin 'P1', value}; "
                 "set_comment {symbol, text}; add_module {module (file name, e.g. 'X.umc'/'X.usp'), folder, "
                 "connect {pin name: signal}, parameters [...] or {name: value}, comment?, new_signal_type?}; "
                 "add_device {device (exact name or code), address (IP ID the user chose, e.g. '03', or a "
                 "frame's slot number), network? (or the frame '#handle' for a card)} (see free_ids); "
                 "rename_signal {signal, new_name}; rename_folder {folder, "
                 "new_name}; remove_symbol {symbol}; move_symbol {symbol, folder}. New signal names are "
                 "created. Returns changes, new problems and next_step. dry_run=true checks without writing.")
    async def apply_edits(path: str, revision: str, summary: str, edits: list[dict[str, Any]],
                          dry_run: bool = False, user_confirmed_saved: bool = False) -> dict[str, Any]:
        return await _run("apply_edits", path=path, revision=revision, summary=summary, edits=edits,
                          dry_run=dry_run, user_confirmed_saved=user_confirmed_saved)

    @server.tool(name="module_details", description="A macro (.umc/.cmc) or SIMPL+ module (.usp) "
                 "beside the program: its input/output pin names and types and the parameters it "
                 "needs, before placing it with apply_edits add_module. module: the file name.")
    async def module_details(path: str, module: str) -> dict[str, Any]:
        return await _run("module_details", path=path, module=module)

    @server.tool(name="compile_program", description="Compile the program in SIMPL Windows (about a minute; "
                 "SIMPL opens and closes by itself) and return SIMPL's errors, warnings and notices, compared "
                 "with find_problems. Needs SIMPL to be closed and the compile task installed. Use it after "
                 "apply_edits instead of asking the user to press F12.")
    async def compile_program(path: str, timeout_s: int = 1500) -> dict[str, Any]:
        return await _run("compile_program", path=path, timeout_s=timeout_s)

    @server.tool(name="device_tree", description="Every device in the program (processor, cards, Ethernet "
                 "and Cresnet devices, ports): its handle, name, device code, address (IP ID / Cresnet ID / "
                 "port), where it sits, model, IP address and logic symbol. Read-only.")
    async def device_tree(path: str, limit: int = 300) -> dict[str, Any]:
        return await _run("device_tree", path=path, limit=limit)

    @server.tool(name="free_ids", description="Free and used IDs on each of the program's networks (Ethernet "
                 "IP IDs, Cresnet IDs, ports). network filters by name or transport, e.g. 'Ethernet'. Read-only; "
                 "never pick an IP ID for the user without asking.")
    async def free_ids(path: str, network: str = "") -> dict[str, Any]:
        return await _run("free_ids", path=path, network=network)

    @server.tool(name="edit_history", description="SIMPL Agent's change history for a program (newest "
                 "last), and whether the file changed outside SIMPL Agent since the last change.")
    async def edit_history(path: str, limit: int = 20) -> dict[str, Any]:
        return await _run("edit_history", path=path, limit=limit)

    @server.tool(name="undo_last_edit", description="Undo SIMPL Agent's most recent change. Only works "
                 "while the file is exactly as that change left it (needs the current revision).")
    async def undo_last_edit(path: str, revision: str, user_confirmed_saved: bool = False) -> dict[str, Any]:
        return await _run("undo_last_edit", path=path, revision=revision,
                          user_confirmed_saved=user_confirmed_saved)

    @server.tool(name="restore_version", description="Put a program back as it was before history entry "
                 "before_entry (an id from edit_history, or 'start'). Without confirm=true it only shows "
                 "what would be lost; show the user and ask before confirming.")
    async def restore_version(path: str, revision: str, before_entry: str, confirm: bool = False,
                              user_confirmed_saved: bool = False) -> dict[str, Any]:
        return await _run("restore_version", path=path, revision=revision, before_entry=before_entry,
                          confirm=confirm, user_confirmed_saved=user_confirmed_saved)

    @server.tool(name="wait_for_simpl_save", description="Wait (up to timeout_s, max 120) for the user to "
                 "save the program in SIMPL, i.e. for the file to differ from 'revision'. Call again to "
                 "keep waiting. SIMPL Agent can't press Save in SIMPL itself.")
    async def wait_for_simpl_save(path: str, revision: str, timeout_s: int = 30) -> dict[str, Any]:
        return await _run("wait_for_simpl_save", path=path, revision=revision, timeout_s=timeout_s)


    return server


def main() -> None:
    """Run the server over stdio until the client disconnects."""
    create_server().run("stdio")


if __name__ == "__main__":
    main()
