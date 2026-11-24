"""M3 tools: apply_edits, edit_history, undo_last_edit, restore_version, wait_for_simpl_save.

Mixed into server.Tools. The write gate, in order:

1. .smw only, a SIMPL Windows program, CRLF line endings.
2. The caller's ``revision`` must match the file (re-checked just before writing).
3. If SIMPL has the file open, the user must have saved there (user_confirmed_saved=true).
   SIMPL shows no readable unsaved-changes marker, and accepting SIMPL's reload prompt
   after the write would discard unsaved work, so Claude has to ask.
4. Ops that create records need a file saved by SIMPL 4.3x (shapes proven only there).
5. All ops apply in memory first; any failure leaves the file untouched.
6. The result must not add a structural problem (checks.py).
7. Back up, write atomically, record history.

SIMPL runs as administrator, so SIMPL Agent can't press Save or Reload for the
user; wait_for_simpl_save watches the file instead.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import analysis as an
from .checks import structural_problems
from .errors import ToolError
from .history import History, sha256
from .smw import rawfile, save
from .smw.edit import EditError, Editor
from .smw.model import load

SUMMARY_MAX = 120
CREATING_OPS = {"add_symbol", "add_folder"}
OP_KEYS: dict[str, tuple[set[str], set[str]]] = {
    # op: (required keys, optional keys)
    "add_symbol": ({"symbol", "folder", "inputs", "outputs"}, {"parameters", "comment", "new_signal_type"}),
    "add_folder": ({"name"}, {"parent"}),
    "connect": ({"symbol", "pin"}, {"signal", "new_signal_type"}),
    "set_parameter": ({"symbol", "pin", "value"}, set()),
    "set_comment": ({"symbol", "text"}, set()),
    "rename_signal": ({"signal", "new_name"}, set()),
    "rename_folder": ({"folder", "new_name"}, set()),
    "remove_symbol": ({"symbol"}, set()),
    "move_symbol": ({"symbol", "folder"}, set()),
}


def _problem_keys(prog, lib) -> dict[tuple, dict[str, Any]]:
    """Problems keyed by what they're about (code, signal handle, symbols), not by text,
    so renaming a signal doesn't make its existing warning look new."""
    by_name = {s.name: h for h, s in prog.signals.items()}
    out = {}
    for p in an.find_problems(prog, lib):
        # A signal's problem is the same problem however many symbols touch it.
        key = (p.code, by_name.get(p.signal)) if p.signal is not None else (p.code, tuple(p.symbols))
        out[key] = {"code": p.code, "signal": p.signal, "message": p.message}
    return out


class EditTools:
    """Methods expect ToolError, _read_program, index(), windows() from server.Tools."""

    # ------------------------------------------------------------ gate
    def _open_in_simpl(self, p: Path) -> list[dict[str, Any]]:
        from .server import parse_simpl_title

        out = []
        for w in map(parse_simpl_title, self.windows()):
            try:
                if w["file"] and Path(w["file"]).resolve() == p.resolve():
                    out.append(w)
            except OSError:
                continue
        return out

    def _gate(self, path: str, revision: str, user_confirmed_saved: bool = False) -> tuple[Path, bytes, Any]:
        p, data, prog = self._read_program(path)
        if p.suffix.lower() != ".smw" or prog.kind != "SimplWindow":
            raise ToolError("only SIMPL Windows programs (.smw) can be edited")
        if prog.raw.newline != "\r\n":
            raise ToolError("this file doesn't have SIMPL's CRLF line endings (copied through git?); "
                            "open and save it in SIMPL first")
        if not revision or sha256(data) != revision:
            raise ToolError("the file has changed since you read it (revision mismatch). Read it again "
                            "(describe_program) and use the new revision; SIMPL may have renumbered symbols.")
        if self._open_in_simpl(p) and not user_confirmed_saved:
            raise ToolError("SIMPL has this program open. Ask the user to save it in SIMPL (Ctrl+S) and "
                            "confirm; then read it again and call with user_confirmed_saved=true. (SIMPL Agent "
                            "can't see unsaved changes in SIMPL, and SIMPL's reload after the edit would "
                            "discard them.)")
        if p.exists() and not (p.stat().st_mode & 0o200):
            raise ToolError(f"{p.name} is read-only")
        return p, data, prog

    @staticmethod
    def _check_ops(edits: Any) -> list[dict[str, Any]]:
        if not isinstance(edits, list) or not edits:
            raise ToolError("edits must be a non-empty list of operations")
        if len(edits) > 200:
            raise ToolError("at most 200 operations per call")
        for i, e in enumerate(edits, 1):
            if not isinstance(e, dict) or e.get("op") not in OP_KEYS:
                raise ToolError(f"edit {i}: 'op' must be one of {sorted(OP_KEYS)}")
            need, may = OP_KEYS[e["op"]]
            keys = set(e) - {"op"}
            if need - keys:
                raise ToolError(f"edit {i} ({e['op']}): missing {sorted(need - keys)}")
            if keys - need - may:
                raise ToolError(f"edit {i} ({e['op']}): unknown {sorted(keys - need - may)}")
        return edits

    def _apply_one(self, ed: Editor, e: dict[str, Any]) -> None:
        op = e["op"]
        if op == "add_symbol":
            ref = e["symbol"]
            code = None
            if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
                code = int(ref)
            elif ed.lib is not None:
                hits = ed.lib.by_name.get(str(ref).strip().lower(), [])
                code = hits[0].code if len(hits) == 1 else None
            if code is None:
                raise EditError(f"unknown or ambiguous library symbol {ref!r}; use its code from find_library_symbols")
            ed.add_symbol(code, e["folder"], list(e["inputs"]), list(e["outputs"]),
                          params=[str(x) for x in e.get("parameters") or []], comment=e.get("comment"),
                          new_signal_type=e.get("new_signal_type", "digital"))
        elif op == "add_folder":
            ed.add_folder(e["name"], e.get("parent", "Logic"))
        elif op == "connect":
            ed.connect(e["symbol"], e["pin"], e.get("signal"), new_signal_type=e.get("new_signal_type", "digital"))
        elif op == "set_parameter":
            ed.set_parameter(e["symbol"], e["pin"], e["value"])
        elif op == "set_comment":
            ed.set_comment(e["symbol"], e["text"])
        elif op == "rename_signal":
            ed.rename_signal(e["signal"], e["new_name"])
        elif op == "rename_folder":
            ed.rename_folder(e["folder"], e["new_name"])
        elif op == "remove_symbol":
            ed.remove_symbol(e["symbol"])
        elif op == "move_symbol":
            ed.move_symbol(e["symbol"], e["folder"])

    def _after_write_note(self, p: Path) -> str:
        if self._open_in_simpl(p):
            return ("Tell the user: switch to SIMPL; it will say the file changed and offer to reload. "
                    "Click Yes, then compile (F12). Saving in SIMPL without reloading would overwrite "
                    "this edit.")
        return "Tell the user to open the program in SIMPL and compile (F12)."

    # ------------------------------------------------------------ tools
    def apply_edits(self, path: str, revision: str, summary: str, edits: list[dict[str, Any]],
                    dry_run: bool = False, user_confirmed_saved: bool = False) -> dict[str, Any]:
        if not isinstance(summary, str) or not summary.strip() or "\n" in summary or len(summary) > SUMMARY_MAX:
            raise ToolError(f"give a one-line summary (up to {SUMMARY_MAX} characters) for the history")
        edits = self._check_ops(edits)
        p, data, prog = self._gate(path, revision, user_confirmed_saved or dry_run)
        sig = prog.signature
        rel = (sig.get("RelVrs") or "") if sig is not None else ""
        if any(e["op"] in CREATING_OPS for e in edits) and not rel.startswith("4.3"):
            raise ToolError(f"this file was saved by SIMPL {rel or '?'}; adding symbols or folders is only "
                            "proven for files saved by SIMPL 4.3x. Open and save it in SIMPL 4.32 first.")
        lib = self.index().library
        ed = Editor(rawfile.parse(data), lib)
        before_struct = structural_problems(ed.prog)
        before_probs = _problem_keys(ed.prog, lib)
        for i, e in enumerate(edits, 1):
            try:
                self._apply_one(ed, e)
            except EditError as err:
                raise ToolError(f"edit {i} ({e['op']}) refused, nothing was changed: {err}") from err
        new_bytes = ed.raw.to_bytes()
        check = load(rawfile.parse(new_bytes))
        added = sorted(structural_problems(check) - before_struct)
        if added:
            raise ToolError(f"the result would break the file's structure, nothing was changed: {added[:5]}")
        after_probs = _problem_keys(check, lib)
        result = {
            "changes": ed.log.lines,
            "new_problems": [after_probs[k] for k in sorted(after_probs.keys() - before_probs.keys(), key=str)],
            "problems_fixed": len(before_probs.keys() - after_probs.keys()),
        }
        if dry_run:
            return {"path": str(p), "dry_run": True, "written": False, **result}
        if sha256(p.read_bytes()) != revision:
            raise ToolError("the file changed while the edit was being prepared; read it again")
        backup = save.write(ed.raw, p)
        hist = History(p)
        new_rev = sha256(new_bytes)
        entry = hist.add(kind="edit", summary=summary.strip(), ops=edits, changes=ed.log.lines,
                         revision_before=revision, revision_after=new_rev,
                         backup=str(backup.relative_to(hist.folder)).replace("\\", "/") if backup else None,
                         simpl_version=rel)
        return {"path": str(p), "written": True, "revision": new_rev, "history_id": entry["id"],
                **result, "next_step": self._after_write_note(p)}

    def edit_history(self, path: str, limit: int = 20) -> dict[str, Any]:
        p, data, _ = self._read_program(path)
        hist = History(p)
        entries = hist.entries()
        current = sha256(data)
        last = entries[-1] if entries else None
        rows = [{k: e.get(k) for k in ("id", "time", "kind", "summary", "changes", "undoes")} for e in entries]
        return {
            "path": str(p), "revision": current, "entries": rows[-max(1, min(int(limit), 200)):],
            "total": len(entries),
            "changed_outside_simpl_agent": bool(last and last.get("revision_after") != current),
        }

    def undo_last_edit(self, path: str, revision: str, user_confirmed_saved: bool = False) -> dict[str, Any]:
        p, data, _ = self._gate(path, revision, user_confirmed_saved)
        hist = History(p)
        target = hist.undo_target()
        if target is None:
            raise ToolError("there's nothing to undo")
        if target.get("revision_after") != revision:
            raise ToolError("the file has changed since that edit (probably saved in SIMPL), so undo could lose "
                            "work. Use restore_version to see what would be lost.")
        old = hist.backup_bytes(target)
        backup = save.write(rawfile.parse(old), p)
        entry = hist.add(kind="undo", undoes=target["id"], summary=f"undo: {target.get('summary')}",
                         revision_before=revision, revision_after=sha256(old),
                         backup=str(backup.relative_to(hist.folder)).replace("\\", "/") if backup else None)
        return {"path": str(p), "undid": {"id": target["id"], "summary": target.get("summary")},
                "revision": sha256(old), "history_id": entry["id"], "next_step": self._after_write_note(p)}

    def restore_version(self, path: str, revision: str, before_entry: int | str,
                        confirm: bool = False, user_confirmed_saved: bool = False) -> dict[str, Any]:
        """Put the file back as it was before history entry ``before_entry`` ('start' = before the first)."""
        p, data, _ = self._gate(path, revision, user_confirmed_saved or not confirm)
        hist = History(p)
        entries = hist.entries()
        if not entries:
            raise ToolError("this program has no SIMPL Agent history")
        if str(before_entry).strip().lower() == "start":
            target = entries[0]
        else:
            target = next((e for e in entries if str(e["id"]) == str(before_entry).strip()), None)
            if target is None:
                raise ToolError(f"no history entry {before_entry!r}; see edit_history")
        lost = [{"id": e["id"], "summary": e.get("summary")} for e in entries if e["id"] >= target["id"]]
        outside = entries[-1].get("revision_after") != revision
        preview = {"path": str(p), "restores_to": f"before entry {target['id']} ({target.get('summary')})",
                   "would_undo": lost, "also_loses_changes_made_in_simpl": outside}
        if not confirm:
            return {**preview, "written": False,
                    "next_step": "Show the user what would be lost; call again with confirm=true only if they agree."}
        old = hist.backup_bytes(target)
        backup = save.write(rawfile.parse(old), p)
        entry = hist.add(kind="restore", summary=f"restore to before entry {target['id']}",
                         revision_before=revision, revision_after=sha256(old),
                         backup=str(backup.relative_to(hist.folder)).replace("\\", "/") if backup else None)
        return {**preview, "written": True, "revision": sha256(old), "history_id": entry["id"],
                "next_step": self._after_write_note(p)}

    def wait_for_simpl_save(self, path: str, revision: str, timeout_s: int = 30) -> dict[str, Any]:
        """Wait until the file differs from ``revision`` (the user saved in SIMPL), up to timeout_s."""
        p, data, _ = self._read_program(path)
        deadline = time.monotonic() + max(1, min(int(timeout_s), 120))
        current = sha256(data)
        while current == revision and time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                current = sha256(p.read_bytes())
            except OSError:
                continue  # SIMPL may be mid-write
        open_in = self._open_in_simpl(p)
        return {"path": str(p), "saved": current != revision, "revision": current,
                "open_in_simpl": bool(open_in),
                "next_step": "Read the program again before editing: SIMPL may have renumbered symbols."
                if current != revision else "Not saved yet; call again to keep waiting."}
