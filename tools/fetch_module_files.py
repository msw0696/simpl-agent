"""Download the module files (.umc/.cmc/.usp/.ush/.clz) that sit next to corpus programs.

For each downloaded program saved by SIMPL 4.3x that uses macros or SIMPL+ modules,
fetch the module files in the same repo folder, so module records can be checked
against their definitions. Files land beside the program in the corpus (outside
the repo). Uses the `gh` CLI. Untrusted data: saved as bytes, never opened by tools
other than SIMPL Agent's text parser.

Usage:  python -I tools/fetch_module_files.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.corpus import GITHUB_CORPUS  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402

MODULE_EXTS = (".umc", ".cmc", ".usp", ".ush", ".clz")


def gh(*args: str) -> bytes:
    for attempt in range(4):
        p = subprocess.run(["gh", "api", *args], capture_output=True)
        if p.returncode == 0:
            return p.stdout
        if b"rate limit" in p.stderr.lower():
            time.sleep(30 * (attempt + 1))
            continue
        raise RuntimeError(p.stderr.decode("utf-8", "replace").strip()[:200])
    raise RuntimeError("rate limited")


def main() -> int:
    manifest = [json.loads(line) for line in (GITHUB_CORPUS / "manifest-smw.jsonl").read_text("utf-8").splitlines()]
    trees: dict[tuple[str, str], list[str]] = {}
    got = skipped = failed = 0
    for m in manifest:
        local = GITHUB_CORPUS / m["local"]
        raw = rawfile.read(local)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        names = {r.get("Nm") for r in raw.of_type("Sm") if r.get("SmC") in ("103", "155") and r.get("Nm")}
        if not names:
            continue
        key = (m["repo"], m["ref"])
        if key not in trees:
            data = json.loads(gh(f"repos/{m['repo']}/git/trees/{m['ref']}?recursive=1"))
            trees[key] = [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]
        folder = m["path"].rsplit("/", 1)[0] + "/" if "/" in m["path"] else ""
        for path in trees[key]:
            if not path.startswith(folder) or "/" in path[len(folder):]:
                continue
            if not path.lower().endswith(MODULE_EXTS):
                continue
            dest = local.parent / path[len(folder):]
            if dest.exists():
                skipped += 1
                continue
            try:
                dest.write_bytes(gh("-H", "Accept: application/vnd.github.raw",
                                    f"repos/{m['repo']}/contents/{quote(path)}?ref={m['ref']}"))
                got += 1
            except RuntimeError as e:
                print(f"  failed {m['repo']}/{path}: {e}")
                failed += 1
    print(f"downloaded {got}, already had {skipped}, failed {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
