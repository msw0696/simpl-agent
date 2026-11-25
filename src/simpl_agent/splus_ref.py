"""SIMPL+ Language Reference lookups, from the help file SIMPL installs (``Simpl+lr.chm``).

The help file is unpacked with Windows' own ``hh.exe -decompile`` into SIMPL Agent's cache on first
use (keyed on the file's size and date) and turned into plain-text topics: functions, declarations,
compiler directives, events, and one page per compiler error and warning. Nothing from it is ever
copied into this repo.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SPLUS_CHM = Path(r"C:\Program Files (x86)\Crestron\Simpl\Simpl+lr.chm")
INDEX_VERSION = 3


@dataclass
class Topic:
    path: str       # relative to the unpacked help, e.g. "Language_Constructs_&_Functions/.../FIND.htm"
    title: str
    category: str   # the folder, readable: "Language Constructs & Functions > String Parsing ..."
    text: str


def html_to_text(page: str) -> tuple[str | None, str]:
    """(title, plain text) of one help page."""
    m = re.search(r"(?is)<title>(.*?)</title>", page)
    title = html.unescape(m.group(1)).strip() if m else None
    t = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", page)
    t = re.sub(r"(?i)</p>|</h\d>|</pre>|</div>", "\n\n", t)  # paragraphs
    t = re.sub(r"(?i)<br\s*/?>|</tr>|</li>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\r", "")
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return title, t


def _category(rel: Path) -> str:
    return " > ".join(part.replace("_", " ") for part in rel.parent.parts)


def unpack(chm: Path, dest: Path, timeout_s: int = 180) -> Path:
    """Decompile ``chm`` into ``dest/out`` with hh.exe; returns the folder. hh.exe fails silently on
    paths with spaces, so it gets a copy under a plain name and relative arguments."""
    out = dest / "out"
    if (dest / "ok").exists():
        return out
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copy2(chm, dest / "lr.chm")
    subprocess.run(["hh.exe", "-decompile", "out", "lr.chm"], cwd=dest, timeout=timeout_s,
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    pages = list(out.rglob("*.htm")) if out.is_dir() else []
    if not pages:
        raise RuntimeError(f"couldn't unpack the SIMPL+ Language Reference ({chm}) with hh.exe")
    (dest / "lr.chm").unlink(missing_ok=True)
    (dest / "ok").write_text("ok")
    return out


def build_topics(out: Path) -> list[Topic]:
    topics = []
    for p in sorted(out.rglob("*.htm")):
        rel = p.relative_to(out)
        title, text = html_to_text(p.read_bytes().decode("cp1252", errors="replace"))
        if not text:
            continue
        topics.append(Topic(path=rel.as_posix(), title=title or p.stem.replace("_", " "),
                            category=_category(rel), text=text))
    return topics


class Reference:
    def __init__(self, topics: list[Topic]):
        self.topics = topics
        self._by_key: dict[str, list[Topic]] = {}
        for t in topics:
            for k in {t.title.lower(), Path(t.path).stem.lower(), Path(t.path).stem.replace("_", " ").lower()}:
                self._by_key.setdefault(k, []).append(t)

    @classmethod
    def load(cls, cache: Path, chm: Path = SPLUS_CHM) -> Reference:
        """From the cache, unpacking and indexing the installed help file the first time."""
        if not chm.exists():
            raise FileNotFoundError(f"the SIMPL+ Language Reference isn't installed ({chm})")
        st = chm.stat()
        key = f"v{INDEX_VERSION}-{st.st_size}-{int(st.st_mtime)}"
        base = cache / "splus_ref"
        index = base / f"{key}.json"
        if index.exists():
            return cls([Topic(**t) for t in json.loads(index.read_text("utf-8"))])
        topics = build_topics(unpack(chm, base / key))
        index.write_text(json.dumps([t.__dict__ for t in topics]), "utf-8")
        return cls(topics)

    def error(self, code: int) -> Topic | None:
        for kind in ("error", "warning"):
            hit = self._by_key.get(f"compiler {kind} {code}")
            if hit:
                return hit[0]
        return None

    def explain(self, code: int, limit: int = 400) -> str | None:
        """The help's explanation of a compiler error or warning: its first plain paragraphs, after
        the message lines (which hold placeholders like '<identifier>')."""
        t = self.error(code)
        if t is None:
            return None
        out: list[str] = []
        for para in t.text.split("\n\n")[1:]:
            para = para.strip()
            if not para or "<" in para or para.lower().startswith(("syntax error", "compiler error", "warning",
                                                                     "note:")):
                continue
            if not para.endswith((".", ":")) or para.lower().startswith("the following are examples"):
                if out:
                    break
                continue
            out.append(para)
            if sum(map(len, out)) >= limit // 2:
                break
        text = " ".join(out)
        return (text[:limit].rsplit(" ", 1)[0] + "...") if len(text) > limit else (text or None)

    def search(self, query: str, limit: int = 5) -> list[Topic]:
        """Exact names first (a function, directive or 'compiler error 1001'), then pages whose
        title, then text, mention every word of the query."""
        q = query.strip().lower()
        if not q:
            return []
        if q.isdigit():
            t = self.error(int(q))
            return [t] if t else []
        exact = self._by_key.get(q) or self._by_key.get(q.lstrip("#")) or []
        words = [w for w in re.split(r"[^\w#$]+", q) if w]
        scored = []
        for t in self.topics:
            if t in exact:
                continue
            title, text = t.title.lower(), t.text.lower()
            if not all(w in title or w in text for w in words):
                continue
            score = sum(10 for w in words if w in title) + sum(min(text.count(w), 5) for w in words)
            if "compiler error" in title or "compiler warning" in title:
                score -= 5  # error pages mention everything; prefer the topic itself
            scored.append((score, t.title, t))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out, seen = [], set()
        for t in exact + [t for _, _, t in scored]:
            if (t.title, t.text) not in seen:  # some pages appear twice in the help
                seen.add((t.title, t.text))
                out.append(t)
        return out[:limit]
