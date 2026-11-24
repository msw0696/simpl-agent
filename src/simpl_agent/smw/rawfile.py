"""Lossless reader and writer for SIMPL Windows text files (.smw, .cmc, .umc).

A file is a sequence of records:

    [
    Key=Value
    ...
    ]

Lines are CRLF when SIMPL writes them (files from git may have been normalised
to LF). Text is latin-1. ``parse(data).to_bytes() == data`` for every input:
anything that doesn't fit the record shape is kept as a stray line or a raw line
inside a record, so nothing is ever lost.

Nothing here knows what the record types mean; that is ``model.py``'s job.
Edits should change existing records in place (``Record.set``) and only build
new records for new things, so untouched bytes stay untouched.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

ENCODING = "latin-1"


@dataclass
class Record:
    """One ``[ ... ]`` block. ``lines`` holds ``(key, value)`` pairs in file order.

    A line without ``=`` is stored as ``(None, text)``. Keys may repeat.
    ``closed`` is False only for a final record with no ``]`` (a truncated file).
    """

    lines: list[tuple[str | None, str]] = field(default_factory=list)
    closed: bool = True

    @property
    def type(self) -> str | None:
        return self.get("ObjTp")

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self.lines:
            if k == key:
                return v
        return default

    def get_all(self, key: str) -> list[str]:
        return [v for k, v in self.lines if k == key]

    def keys(self) -> list[str]:
        return [k for k, _ in self.lines if k is not None]

    def __contains__(self, key: str) -> bool:
        return any(k == key for k, _ in self.lines)

    def set(self, key: str, value: str, *, after: str | None = None) -> None:
        """Replace the first ``key`` in place; if absent, insert after ``after`` (or append)."""
        for i, (k, _) in enumerate(self.lines):
            if k == key:
                self.lines[i] = (key, value)
                return
        if after is not None:
            for i, (k, _) in enumerate(self.lines):
                if k == after:
                    self.lines.insert(i + 1, (key, value))
                    return
        self.lines.append((key, value))

    def delete(self, key: str) -> int:
        """Remove every ``key`` line; returns how many were removed."""
        before = len(self.lines)
        self.lines = [(k, v) for k, v in self.lines if k != key]
        return before - len(self.lines)

    def as_dict(self) -> dict[str, str]:
        """First value for each key. Lossy; for reading only."""
        d: dict[str, str] = {}
        for k, v in self.lines:
            if k is not None and k not in d:
                d[k] = v
        return d


@dataclass
class RawFile:
    """A whole file: records and any stray lines between them, in order."""

    items: list[Record | str] = field(default_factory=list)
    newline: str = "\r\n"
    final_newline: bool = True

    @property
    def records(self) -> Iterator[Record]:
        return (it for it in self.items if isinstance(it, Record))

    def of_type(self, obj_type: str) -> Iterator[Record]:
        return (r for r in self.records if r.type == obj_type)

    def first(self, obj_type: str) -> Record | None:
        return next(self.of_type(obj_type), None)

    def to_text(self) -> str:
        out: list[str] = []
        for it in self.items:
            if isinstance(it, str):
                out.append(it)
                continue
            out.append("[")
            for k, v in it.lines:
                out.append(v if k is None else f"{k}={v}")
            if it.closed:
                out.append("]")
        text = self.newline.join(out)
        if self.final_newline:
            text += self.newline
        return text

    def to_bytes(self) -> bytes:
        return self.to_text().encode(ENCODING)


def detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    if crlf >= lf and crlf >= cr and crlf:
        return "\r\n"
    if cr > lf:
        return "\r"
    return "\n" if lf else "\r\n"


def parse_text(text: str) -> RawFile:
    newline = detect_newline(text)
    final_newline = text.endswith(newline)
    body = text[: -len(newline)] if final_newline else text
    lines = body.split(newline) if body else []

    items: list[Record | str] = []
    current: Record | None = None
    for line in lines:
        if current is None:
            if line == "[":
                current = Record()
            else:
                items.append(line)
        elif line == "]":
            items.append(current)
            current = None
        else:
            k, sep, v = line.partition("=")
            current.lines.append((k, v) if sep else (None, line))
    if current is not None:
        current.closed = False
        items.append(current)

    raw = RawFile(items=items, newline=newline, final_newline=final_newline)
    if raw.to_text() != text:
        # Mixed line endings (or similar): keep the file as stray lines so the
        # write-back is still exact. The structured view will be empty.
        return RawFile(items=[text], newline="", final_newline=False)
    return raw


def parse(data: bytes) -> RawFile:
    return parse_text(data.decode(ENCODING))


def read(path) -> RawFile:
    with open(path, "rb") as f:
        return parse(f.read())
