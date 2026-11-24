"""Drive SIMPL Windows' own window, for proof rounds (see docs/format.md).

SIMPL's manifest asks for administrator rights, and Windows then blocks normal programs
from seeing or clicking its window. Started with __COMPAT_LAYER=RunAsInvoker it runs with
the user's own rights, and this tool can screenshot it and send it the mouse and keyboard.
It uses the real cursor: nobody else should use the PC while it runs.

    python tools/simpl_gui.py launch [file.smw]   start SIMPL without admin rights (optionally a program)
    python tools/simpl_gui.py shot [out.png]       screenshot of SIMPL's window (window coordinates)
    python tools/simpl_gui.py screen [out.png]     screenshot of the whole desktop
    python tools/simpl_gui.py windows              SIMPL's top-level windows (dialogs included)
    python tools/simpl_gui.py click X Y [right|double]   click at window coordinates
    python tools/simpl_gui.py drag X1 Y1 X2 Y2     drag with the left button
    python tools/simpl_gui.py type "text"          type text
    python tools/simpl_gui.py keys ctrl+s          press a key combination (alt+f, enter, esc, f12, tab ...)
    python tools/simpl_gui.py maximize | close
Coordinates are pixels relative to the top-left of SIMPL's main window (or of the foreground
SIMPL dialog when one is open: `shot` says which).
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
OUT_DIR = Path(os.environ.get("TEMP", ".")) / "simpl_gui"

user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels everywhere
except Exception:
    user32.SetProcessDPIAware()

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP = 0x0002, 0x0004, 0x0008, 0x0010
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def simpl_pids() -> set[int]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq smpwin.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"smpwin')}


def windows() -> list[tuple[int, str, tuple[int, int, int, int], bool]]:
    """(hwnd, title, rect, is_foreground) for SIMPL's visible top-level windows."""
    pids, found = simpl_pids(), []
    fg = user32.GetForegroundWindow()

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left > 20:
                found.append((hwnd, buf.value, (r.left, r.top, r.right, r.bottom), hwnd == fg))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def target() -> tuple[int, str, tuple[int, int, int, int]]:
    """The window coordinates refer to: a SIMPL dialog if one is foreground, else the main window."""
    ws = windows()
    if not ws:
        sys.exit("SIMPL isn't running (python tools/simpl_gui.py launch)")
    for h, t, r, fg in ws:
        if fg:
            return h, t, r
    main = max(ws, key=lambda w: (w[2][2] - w[2][0]) * (w[2][3] - w[2][1]))
    return main[0], main[1], main[2]


def focus() -> tuple[int, str, tuple[int, int, int, int]]:
    h, t, r = target()
    if user32.GetForegroundWindow() == h:
        return h, t, r
    user32.SetForegroundWindow(h)
    time.sleep(0.2)
    if user32.GetForegroundWindow() != h:
        # Windows only lets the foreground process hand focus over; a click on the title bar does.
        _send(_mouse(MOUSEEVENTF_MOVE, r[0] + 200, r[1] + 12))
        _send(_mouse(LEFTDOWN, r[0] + 200, r[1] + 12), _mouse(LEFTUP, r[0] + 200, r[1] + 12))
        time.sleep(0.3)
    return target()


def _abs(x: int, y: int) -> tuple[int, int]:
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return int((x - vx) * 65535 / max(vw - 1, 1)), int((y - vy) * 65535 / max(vh - 1, 1))


def _mouse(flags: int, x: int, y: int) -> INPUT:
    ax, ay = _abs(x, y)
    return INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(ax, ay, 0, flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)))


def _key(vk: int, up: bool = False, scan: int = 0, unicode: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_UNICODE if unicode else 0)
    return INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20,
      "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23, "up": 0x26, "down": 0x28, "left": 0x25,
      "right": 0x27, "pgup": 0x21, "pgdn": 0x22, "insert": 0x2D, "apps": 0x5D,
      **{f"f{i}": 0x6F + i for i in range(1, 13)}}


def keys(combo: str) -> None:
    parts = combo.lower().split("+")
    vks = [VK[p] if p in VK else ord(p.upper()) for p in parts]
    _send(*[_key(v) for v in vks], *[_key(v, up=True) for v in reversed(vks)])


def type_text(text: str) -> None:
    for ch in text:
        _send(_key(0, scan=ord(ch), unicode=True), _key(0, up=True, scan=ord(ch), unicode=True))
        time.sleep(0.01)


def click(x: int, y: int, how: str = "left") -> None:
    _, _, r = focus()
    sx, sy = r[0] + x, r[1] + y
    _send(_mouse(MOUSEEVENTF_MOVE, sx, sy))
    time.sleep(0.05)
    down, up = (RIGHTDOWN, RIGHTUP) if how == "right" else (LEFTDOWN, LEFTUP)
    for _ in range(2 if how == "double" else 1):
        _send(_mouse(down, sx, sy), _mouse(up, sx, sy))
        time.sleep(0.05)


def drag(x1: int, y1: int, x2: int, y2: int) -> None:
    _, _, r = focus()
    a, b = (r[0] + x1, r[1] + y1), (r[0] + x2, r[1] + y2)
    _send(_mouse(MOUSEEVENTF_MOVE, *a))
    time.sleep(0.1)
    _send(_mouse(LEFTDOWN, *a))
    time.sleep(0.3)
    # Small first steps so the tree control's drag detection starts, then the rest of the way.
    for dx in (2, 4, 6, 10, 14):
        _send(_mouse(MOUSEEVENTF_MOVE, a[0] + dx, a[1] + dx // 2))
        time.sleep(0.08)
    steps = 40
    for i in range(1, steps + 1):
        _send(_mouse(MOUSEEVENTF_MOVE, a[0] + (b[0] - a[0]) * i // steps, a[1] + (b[1] - a[1]) * i // steps))
        time.sleep(0.03)
    for wiggle in (2, -2, 0):
        _send(_mouse(MOUSEEVENTF_MOVE, b[0] + wiggle, b[1]))
        time.sleep(0.15)
    time.sleep(0.4)
    _send(_mouse(LEFTUP, *b))


def shot(out: Path | None = None, whole: bool = False) -> Path:
    from PIL import ImageGrab

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(out) if out else OUT_DIR / f"shot-{int(time.time() * 1000)}.png"
    if whole:
        img = ImageGrab.grab(all_screens=True)
        img = img.resize((img.width // 2, img.height // 2))
        info = "whole desktop at half size"
    else:
        h, t, r = target()
        img = ImageGrab.grab(bbox=r, all_screens=True)
        info = f"{t!r} {r[2] - r[0]}x{r[3] - r[1]} (window coordinates, 1:1)"
    img.save(out)
    print(out, info)
    return out


def launch(program: str | None = None) -> None:
    env = dict(os.environ, __COMPAT_LAYER="RunAsInvoker")
    args = [str(SMPWIN)] + ([str(Path(program).resolve())] if program else [])
    subprocess.Popen(args, env=env, close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
    for _ in range(60):
        time.sleep(1)
        if windows():
            break
    time.sleep(3)
    print("SIMPL windows:", [(t, r) for _, t, r, _ in windows()])


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "launch":
        launch(rest[0] if rest else None)
    elif cmd == "shot":
        shot(Path(rest[0]) if rest else None)
    elif cmd == "screen":
        shot(Path(rest[0]) if rest else None, whole=True)
    elif cmd == "windows":
        for h, t, r, fg in windows():
            print(h, repr(t), r, "FOREGROUND" if fg else "")
    elif cmd == "click":
        click(int(rest[0]), int(rest[1]), rest[2] if len(rest) > 2 else "left")
    elif cmd == "drag":
        drag(*(int(v) for v in rest[:4]))
    elif cmd == "type":
        focus()
        type_text(rest[0])
    elif cmd == "keys":
        focus()
        keys(rest[0])
    elif cmd == "maximize":
        h, _, _ = target()
        user32.ShowWindow(h, 3)
    elif cmd == "close":
        for h, _, _, _ in windows():
            user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
    else:
        sys.exit(f"unknown command {cmd!r}\n{__doc__}")
    time.sleep(0.4)


if __name__ == "__main__":
    main(sys.argv[1:])
