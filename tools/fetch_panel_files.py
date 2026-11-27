"""Download the panel extension files (.chd contracts, .sgd Smart Graphics) corpus programs point to.

A program's VTP record names the file a panel's extender symbols (SmC 2942) come from, by a path
relative to the program (``SGDFile=..\\Contract\\output\\X\\programming\\SIMPL\\X.chd``). This fetches
that file from the same GitHub repo and saves it at the same relative place beside the corpus copy,
so extender records can be checked against their definitions. Files land in the corpus (outside the
repo) and never leave the repo folder they came from. Uses the `gh` CLI. Untrusted data: saved as
bytes, read only by SIMPL Agent's text parser.

Usage:  python -I tools/fetch_panel_files.py
"""
from __future__ import annotations

import json
import posixpath
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_module_files import gh  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402

EXTS = (".chd", ".sgd")


def main() -> int:
    manifest = [json.loads(line) for line in (GITHUB_CORPUS / "manifest-smw.jsonl").read_text("utf-8").splitlines()]
    trees: dict[tuple[str, str], set[str]] = {}
    got = skipped = missing = failed = 0
    for m in manifest:
        local = GITHUB_CORPUS / m["local"]
        if not local.exists():
            continue
        refs = {r.get("SGDFile") for r in rawfile.read(local).of_type("VTP") if r.get("SGDFile")}
        refs = {r for r in refs if r.lower().endswith(EXTS)}
        if not refs:
            continue
        key = (m["repo"], m["ref"])
        if key not in trees:
            data = json.loads(gh(f"repos/{m['repo']}/git/trees/{m['ref']}?recursive=1"))
            trees[key] = {t["path"] for t in data.get("tree", []) if t.get("type") == "blob"}
        folder = posixpath.dirname(m["path"])
        for ref in sorted(refs):
            rel = ref.replace("\\", "/")
            if ":" in rel or rel.startswith("/"):
                missing += 1  # an absolute path on the author's PC: not in the repo
                continue
            path = posixpath.normpath(posixpath.join(folder, rel))
            if path not in trees[key]:  # Windows paths ignore case
                path = next((t for t in trees[key] if t.lower() == path.lower()), path)
            if path.startswith("../") or path not in trees[key]:
                missing += 1
                continue
            dest = (local.parent / rel).resolve()
            root = (GITHUB_CORPUS / Path(m["local"].replace("\\", "/")).parts[0]).resolve()
            if root not in dest.parents:
                missing += 1  # would land outside this repo's corpus folder
                continue
            if dest.exists():
                skipped += 1
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(gh("-H", "Accept: application/vnd.github.raw",
                                    f"repos/{m['repo']}/contents/{quote(path)}?ref={m['ref']}"))
                got += 1
            except RuntimeError as e:
                print(f"  failed {m['repo']}/{path}: {e}")
                failed += 1
    print(f"downloaded {got}, already had {skipped}, not in the repo {missing}, failed {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
