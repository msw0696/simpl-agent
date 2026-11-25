"""M8: reading saved SIMPL Debugger traces (Toolbox > SIMPL Debugger > Logging).

The layout comes from the format strings in Toolbox's ``SIMPL Debugger.ocx`` and its help,
not yet from a real saved log, so every line that doesn't fit is counted and shown:

- a signal transition: ``<time>: <signal> -> <value>``;
- another event: ``<time>: [<type>] : <message>`` (types seen in the binary: Console Data,
  SIMPL+ Trace, User Stimulus, Signal Monitor Status);
- a user timestamp: ``<time>: *** Timestamp <n>``;
- the Trace window's clipboard copy: ``<time>\\t<value>\\t<signal>`` (shown in the help).

``<time>`` is one of the Debugger's trace time formats: ``HH:MM:SS - MM-DD-YYYY`` (time of day),
``HH:MM:SS.mmm``, ``<d> days, HH:MM:SS.mmm`` or ``<n> ms`` (relative to the previous event).
Values are kept exactly as written: digital 0/1 (the help's screenshots), analog as set in the
Debugger (decimal, ``####h``, ``##.###%`` or a time), serial with ``\\xHH`` escapes.
Module signals are prefixed ``::`` by the Debugger. Traces are client data, like programs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_TRACE_BYTES = 300 * 1024 * 1024

TIME_RES = [
    ("time of day", re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}) - (\d{2})-(\d{2})-(\d{4})")),
    ("days and time", re.compile(r"^(\d+) days?, (\d{1,2}):(\d{2}):(\d{2})\.(\d{3})")),
    ("time with milliseconds", re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})")),
    ("time", re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?![.\d])")),
    ("milliseconds since previous event", re.compile(r"^(\d+) ms")),
]
EVENT_RE = re.compile(r"^\[([^\]]+)\] : ?(.*)$")
STAMP_RE = re.compile(r"^\*\*\* Timestamp (\d+)(.*)$")


@dataclass
class Entry:
    line: int            # 1-based line number in the file
    time: str            # as written
    seconds: float | None  # comparable time where the format allows it
    kind: str            # "signal" | "event" | "timestamp"
    signal: str | None = None
    value: str | None = None
    event_type: str | None = None
    message: str | None = None

    def as_dict(self) -> dict:
        d = {"line": self.line, "time": self.time}
        if self.kind == "signal":
            d.update(signal=self.signal, value=self.value)
        elif self.kind == "event":
            d.update(event=self.event_type, message=self.message)
        else:
            d.update(timestamp=self.message)
        return d


def _seconds(fmt: str, m: re.Match, prev: float | None) -> float | None:
    g = [int(x) for x in m.groups()]
    if fmt == "time of day":
        return g[0] * 3600 + g[1] * 60 + g[2]  # the date is kept in 'time'
    if fmt == "days and time":
        return g[0] * 86400 + g[1] * 3600 + g[2] * 60 + g[3] + g[4] / 1000
    if fmt == "time with milliseconds":
        return g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
    if fmt == "time":
        return g[0] * 3600 + g[1] * 60 + g[2]
    if fmt == "milliseconds since previous event":
        return (prev or 0.0) + g[0] / 1000
    return None


def _split_signal(rest: str, names: set[str] | None) -> tuple[str, str] | None:
    """'<signal> -> <value>'. A name or a serial value may itself hold ' -> ': with the program's
    signal names, the split whose left side is a known name wins."""
    parts = rest.split(" -> ")
    if len(parts) < 2:
        if rest.endswith(" ->"):
            return rest[:-3], ""
        return None
    if names and len(parts) > 2:
        for i in range(1, len(parts)):
            name = " -> ".join(parts[:i])
            if name.lower() in names:
                return name, " -> ".join(parts[i:])
    return parts[0], " -> ".join(parts[1:])


def parse_trace(text_lines, names: set[str] | None = None) -> dict:
    """Parse a trace's lines. ``names``: the program's signal names (lower case), if known."""
    entries: list[Entry] = []
    unparsed: list[tuple[int, str]] = []
    formats: dict[str, int] = {}
    prev: float | None = None
    for i, raw in enumerate(text_lines, 1):
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if "\t" in line:  # the Trace window's clipboard copy: time, value, name
            cols = line.split("\t")
            if len(cols) == 3:
                for fmt, rx in TIME_RES:
                    m = rx.match(cols[0].strip())
                    if m and m.end() == len(cols[0].strip()):
                        prev = _seconds(fmt, m, prev)
                        formats[fmt + " (copied)"] = formats.get(fmt + " (copied)", 0) + 1
                        entries.append(Entry(i, cols[0].strip(), prev, "signal", signal=cols[2].strip(),
                                             value=cols[1]))
                        break
                else:
                    unparsed.append((i, line))
                continue
        hit = next(((f, mm) for f, rx in TIME_RES if (mm := rx.match(line)) and line[mm.end():mm.end() + 2] == ": "),
                   None)
        if hit is None:
            unparsed.append((i, line))
            continue
        fmt, m = hit
        time, rest = line[:m.end()], line[m.end() + 2:]
        secs = _seconds(fmt, m, prev)
        e = None
        if (s := STAMP_RE.match(rest)) is not None:
            e = Entry(i, time, secs, "timestamp", message=f"Timestamp {s.group(1)}{s.group(2)}".strip())
        elif (ev := EVENT_RE.match(rest)) is not None:
            e = Entry(i, time, secs, "event", event_type=ev.group(1).strip(), message=ev.group(2))
        elif (sv := _split_signal(rest, names)) is not None:
            e = Entry(i, time, secs, "signal", signal=sv[0].strip(), value=sv[1])
        if e is None:
            unparsed.append((i, line))
            continue
        prev = secs
        formats[fmt] = formats.get(fmt, 0) + 1
        entries.append(e)
    return {"entries": entries, "unparsed": unparsed, "time_formats": formats}


def read_trace_file(path: Path, names: set[str] | None = None) -> dict:
    """A saved trace (.txt or .log), read as the Debugger writes it (ANSI, cp1252)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"{p} doesn't exist")
    if p.stat().st_size > MAX_TRACE_BYTES:
        raise ValueError(f"{p} is larger than {MAX_TRACE_BYTES // (1024 * 1024)} MB")
    with p.open("r", encoding="cp1252", errors="replace", newline="") as f:
        return parse_trace(f, names)
