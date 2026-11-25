"""Live link to SIMPL Windows: save the open program, and reload it after SIMPL Agent writes it.

SIMPL's manifest asks for administrator rights; a normal program can't send messages to an elevated
window. Started with __COMPAT_LAYER=RunAsInvoker (``launch``), SIMPL runs with the user's own rights
and takes plain window messages, with no clicking and even while the screen is locked
(checked on SIMPL 4.32, 2026-11-24):
- WM_COMMAND with the File > Save menu item's ID saves the program;
- after the file changes on disk, WM_ACTIVATEAPP makes SIMPL check it and ask (a "Crestron SIMPL
  Windows" Yes/No box) whether to reload; BM_CLICK on Yes reloads it.
- Project > Convert/Compile by its menu ID compiles; SIMPL then shows "Compile Complete" (a summary and
  "Transfer Program?" Yes/No, always answered No) and lists its messages in "Program Compilation".
Nothing here sends anything to a processor; the Transfer menu is never used.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

SMPWIN = Path(r"C:\Program Files (x86)\Crestron\Simpl\smpwin.exe")
WM_COMMAND, WM_ACTIVATEAPP, BM_CLICK = 0x0111, 0x001C, 0x00F5
PROMPT_TITLE = "Crestron SIMPL Windows"


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def _windows() -> list[tuple[int, int, str]]:
    """(hwnd, pid, title) for visible windows of smpwin.exe processes."""
    if sys.platform != "win32":
        return []
    u = _user32()
    out: list[tuple[int, int, str]] = []
    cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _image_name(pid.value).lower() == "smpwin.exe":
            out.append((hwnd, pid.value, buf.value))
        return True

    u.EnumWindows(cb_t(cb), 0)
    return out


def _image_name(pid: int) -> str:
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
        return ""
    finally:
        k.CloseHandle(h)


def is_elevated(pid: int) -> bool | None:
    """True if the process runs as administrator (None if it can't be told)."""
    k, a = ctypes.windll.kernel32, ctypes.windll.advapi32
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        tok = wintypes.HANDLE()
        if not a.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
            return None
        try:
            val, n = wintypes.DWORD(), wintypes.DWORD()
            if not a.GetTokenInformation(tok, 20, ctypes.byref(val), 4, ctypes.byref(n)):  # TokenElevation
                return None
            return bool(val.value)
        finally:
            k.CloseHandle(tok)
    finally:
        k.CloseHandle(h)


def _title_path(title: str) -> Path | None:
    if "(" not in title:
        return None
    inner = title.rsplit("(", 1)[1].rstrip(")").strip()
    return Path(inner) if inner else None


def find(path: Path) -> tuple[int, int] | None:
    """(hwnd, pid) of the SIMPL main window that has ``path`` open."""
    try:
        want = Path(path).resolve()
    except OSError:
        return None
    for hwnd, pid, title in _windows():
        p = _title_path(title)
        try:
            if title.startswith("SIMPL Windows") and p is not None and p.resolve() == want:
                return hwnd, pid
        except OSError:
            continue
    return None


def status(path: Path) -> dict:
    """Whether SIMPL has ``path`` open, and whether SIMPL Agent can save and reload it there."""
    hit = find(path)
    if hit is None:
        return {"open": False, "controllable": False}
    hwnd, pid = hit
    elev = is_elevated(pid)
    return {"open": True, "controllable": elev is False, "elevated": elev, "pid": pid}


def _menu_id(hwnd: int, path: tuple[str, ...]) -> int | None:
    u = _user32()
    menu = u.GetMenu(hwnd)
    for depth, want in enumerate(path):
        hit = None
        for i in range(u.GetMenuItemCount(menu)):
            buf = ctypes.create_unicode_buffer(256)
            u.GetMenuStringW(menu, i, buf, 256, 0x400)  # MF_BYPOSITION
            if buf.value.replace("&", "").split("\t")[0].strip().rstrip(".").strip().lower() == want:
                hit = i
                break
        if hit is None:
            return None
        if depth == len(path) - 1:
            cmd = u.GetMenuItemID(menu, hit)
            return None if cmd in (0, 0xFFFFFFFF) else cmd
        menu = u.GetSubMenu(menu, hit)
    return None


def _dialogs(pid: int) -> list[int]:
    return [h for h, p, t in _windows() if p == pid and t == PROMPT_TITLE]


def _buttons(hwnd: int) -> dict[str, int]:
    u = _user32()
    out: dict[str, int] = {}
    cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(ch, _):
        n = u.GetWindowTextLengthW(ch)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(ch, b, n + 1)
        out[b.value] = ch
        return True

    u.EnumChildWindows(hwnd, cb_t(cb), 0)
    return out


def save(path: Path, timeout_s: float = 30) -> bool:
    """Save the program in SIMPL (File > Save). True once SIMPL has rewritten the file."""
    hit = find(path)
    if hit is None or is_elevated(hit[1]) is not False:
        return False
    hwnd, pid = hit
    cmd = _menu_id(hwnd, ("file", "save"))
    if cmd is None:
        return False
    before = os.path.getmtime(path)
    _user32().PostMessageW(hwnd, WM_COMMAND, cmd, 0)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        time.sleep(0.3)
        if os.path.getmtime(path) != before and not _dialogs(pid):
            time.sleep(0.5)  # let SIMPL finish writing
            return True
    return False


def reload(path: Path, timeout_s: float = 15) -> bool:
    """After SIMPL Agent rewrote ``path``, have SIMPL notice and answer its reload prompt with Yes."""
    hit = find(path)
    if hit is None or is_elevated(hit[1]) is not False:
        return False
    hwnd, pid = hit
    u = _user32()
    u.PostMessageW(hwnd, WM_ACTIVATEAPP, 1, 0)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        time.sleep(0.3)
        for d in _dialogs(pid):
            b = _buttons(d)
            if set(b) >= {"&Yes", "&No"}:
                u.SendMessageW(b["&Yes"], BM_CLICK, 0, 0)
                for _ in range(40):
                    time.sleep(0.25)
                    if not _dialogs(pid):
                        return True
                return False
    return False


def launch(path: Path | None = None) -> int:
    """Start SIMPL without administrator rights (so the live link works). Returns its pid."""
    env = dict(os.environ, __COMPAT_LAYER="RunAsInvoker")
    args = [str(SMPWIN)] + ([str(Path(path).resolve())] if path else [])
    proc = subprocess.Popen(args, env=env, close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
    return proc.pid


def _child_texts(hwnd: int) -> list[tuple[int, str, str]]:
    """(child hwnd, class, text) of a dialog. WM_GETTEXT works across processes where GetWindowText doesn't."""
    u = _user32()
    out: list[tuple[int, str, str]] = []
    cb_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(ch, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(ch, cls, 64)
        n = u.SendMessageW(ch, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
        buf = ctypes.create_unicode_buffer(n + 1)
        u.SendMessageW(ch, 0x000D, n + 1, buf)  # WM_GETTEXT
        out.append((ch, cls.value, buf.value))
        return True

    u.EnumChildWindows(hwnd, cb_t(cb), 0)
    return out


def _list_lines(hwnd: int) -> list[str]:
    u = _user32()
    lines: list[str] = []
    for ch, cls, _ in _child_texts(hwnd):
        if cls.lower() == "listbox":
            for i in range(u.SendMessageW(ch, 0x018B, 0, 0)):  # LB_GETCOUNT
                n = u.SendMessageW(ch, 0x018A, i, 0)  # LB_GETTEXTLEN
                buf = ctypes.create_unicode_buffer(max(n, 0) + 1)
                u.SendMessageW(ch, 0x0189, i, buf)  # LB_GETTEXT
                lines.append(buf.value)
    return lines


ROUTINE = {"Compiling...", "Program Compilation", "Compile Complete"}


def _handle_known(h: int, title: str, texts: list[tuple[int, str, str]], auto: list[str]) -> bool:
    """Answer the routine dialogs SIMPL shows around a compile (as smpc does). True if handled."""
    u = _user32()
    b = {t.replace("&", "").strip(): ch for ch, c, t in texts if c.lower() == "button" and t.strip()}
    body = " ".join(t.strip() for _, c, t in texts if c.lower() in ("static", "edit") and t.strip())
    if title == "Commented out Symbols and/or Devices" and "Yes" in b:
        u.SendMessageW(b["Yes"], BM_CLICK, 0, 0)  # compile without the commented-out parts, as SIMPL normally does
        auto.append("Commented out Symbols and/or Devices -> Yes (continue)")
        return True
    if title == "Operation Complete" and "Skip Details" in b:
        if "error" in body.lower() or "fatal" in body.lower():
            return False  # a real loading problem: report it
        u.SendMessageW(b["Skip Details"], BM_CLICK, 0, 0)
        auto.append(f"Operation Complete ({body}) -> Skip Details")
        return True
    return False


def compile_open(path: Path, timeout_s: float = 600) -> dict:
    """Compile the program SIMPL has open (it must run without admin rights). Returns the summary text,
    SIMPL's message lines, dialogs it answered (routine ones only; Transfer Program? is always No), any
    other dialogs (reported, never answered beyond a plain OK), and whether it finished."""
    hit = find(path)
    if hit is None or is_elevated(hit[1]) is not False:
        raise RuntimeError("SIMPL doesn't have this program open without admin rights")
    hwnd, pid = hit
    cmd = _menu_id(hwnd, ("project", "convert/compile"))
    if cmd is None:
        raise RuntimeError("SIMPL's Convert/Compile menu item wasn't found")
    u = _user32()
    auto: list[str] = []
    other: list[dict] = []
    summary = None

    def scan() -> None:
        nonlocal summary
        for h, p2, title in _windows():
            if p2 != pid or h == hwnd or title.startswith("SIMPL Windows"):
                continue
            if title in ("Compiling...", "Program Compilation"):
                continue
            texts = _child_texts(h)
            if title == "Compile Complete":
                summary = "\n".join(t for _, c, t in texts if c.lower() == "edit")
                b = {t: ch for ch, c, t in texts if c.lower() == "button"}
                if "&No" in b:
                    u.SendMessageW(b["&No"], BM_CLICK, 0, 0)  # never Transfer Program
                continue
            if _handle_known(h, title, texts, auto):
                continue
            # Anything else (e.g. "Incomplete Symbols"): report it. Only a box whose one button is OK (just
            # information) is dismissed, so SIMPL isn't left waiting; questions are never answered.
            other.append({"title": title, "text": " ".join(t.strip() for _, c, t in texts
                                                              if c.lower() in ("static", "edit") and t.strip())})
            b = {t.replace("&", ""): ch for ch, c, t in texts if c.lower() == "button" and t.strip()}
            if set(b) == {"OK"}:
                u.SendMessageW(b["OK"], BM_CLICK, 0, 0)

    # Dialogs left over from loading the program come first.
    for _ in range(6):
        scan()
        if other:
            return {"finished": False, "summary": "", "lines": [], "dialogs": other, "auto": auto}
        time.sleep(0.5)
    u.PostMessageW(hwnd, WM_COMMAND, cmd, 0)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end and summary is None and not other:
        time.sleep(0.5)
        scan()
    lines: list[str] = []
    time.sleep(0.5)
    for h, p2, title in _windows():
        if p2 == pid and title == "Program Compilation":
            lines = _list_lines(h)
            close_btn = {t: ch for ch, c, t in _child_texts(h) if c.lower() == "button"}.get("Close")
            if close_btn:
                u.SendMessageW(close_btn, BM_CLICK, 0, 0)
    if summary is not None:
        auto.append("Transfer Program? -> No")
    return {"finished": summary is not None, "summary": summary or "", "lines": lines, "dialogs": other,
            "auto": auto}


def close(path: Path, timeout_s: float = 15) -> bool:
    """Close SIMPL (the window that has ``path`` open), answering No to any save prompt."""
    hit = find(path)
    if hit is None:
        return True
    hwnd, pid = hit
    u = _user32()
    u.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        time.sleep(0.4)
        wins = [w for w in _windows() if w[1] == pid]
        if not wins:
            return True
        for h, _, title in wins:
            b = _buttons(h)
            if title == PROMPT_TITLE and "&No" in b:
                u.SendMessageW(b["&No"], BM_CLICK, 0, 0)
    return False
