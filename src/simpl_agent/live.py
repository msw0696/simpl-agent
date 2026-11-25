"""Live link to SIMPL Windows: save the open program, and reload it after SIMPL Agent writes it.

SIMPL's manifest asks for administrator rights; a normal program can't send messages to an elevated
window. Started with __COMPAT_LAYER=RunAsInvoker (``launch``), SIMPL runs with the user's own rights
and takes plain window messages, with no clicking and even while the screen is locked
(checked on SIMPL 4.32, 2026-11-24):
- WM_COMMAND with the File > Save menu item's ID saves the program;
- after the file changes on disk, WM_ACTIVATEAPP makes SIMPL check it and ask (a "Crestron SIMPL
  Windows" Yes/No box) whether to reload; BM_CLICK on Yes reloads it.
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
