"""Download public SIMPL Windows programs from GitHub into a local test corpus.

The corpus lives OUTSIDE the repo (default ~/simpl-corpus/github, or $SIMPL_CORPUS/github)
and is never committed. Files are untrusted data: this script only saves bytes,
it never opens or runs them. Uses the `gh` CLI for auth.

Usage:  python -I tools/fetch_github_corpus.py [--out DIR] [--ext smw]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from simpl_agent.corpus import GITHUB_CORPUS  # noqa: E402

QUERIES = ["SimplWindow", "ObjTp", "SavedBy", "Sgntr"]


def gh(*args: str) -> bytes:
    for attempt in range(5):
        p = subprocess.run(["gh", "api", *args], capture_output=True)
        if p.returncode == 0:
            return p.stdout
        err = p.stderr.decode("utf-8", "replace")
        if "rate limit" in err.lower() or "429" in err:
            time.sleep(30 * (attempt + 1))
            continue
        raise RuntimeError(f"gh api {' '.join(args)} failed: {err.strip()}")
    raise RuntimeError(f"gh api {' '.join(args)}: rate limited too often")


def search(ext: str) -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    for term in QUERIES:
        for page in range(1, 11):  # code search caps at 1000 results
            data = json.loads(gh("-X", "GET", "search/code", "-f", f"q={term} extension:{ext}",
                                 "-f", "per_page=100", "-f", f"page={page}"))
            items = data.get("items", [])
            for it in items:
                found[(it["repository"]["full_name"], it["path"])] = it
            print(f"  {term!r} page {page}: {len(items)} items, {len(found)} unique so far", flush=True)
            if len(items) < 100:
                break
            time.sleep(7)  # code search allows ~10 requests a minute
        time.sleep(7)
    return found


def safe(part: str) -> str:
    return re.sub(r'[<>:"|?*\x00-\x1f]', "_", part).rstrip(" .") or "_"


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(GITHUB_CORPUS))
    ap.add_argument("--ext", default="smw")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / f"manifest-{a.ext}.jsonl"
    done = set()
    if manifest_path.exists():
        for line in manifest_path.read_text("utf-8").splitlines():
            r = json.loads(line)
            done.add((r["repo"], r["path"]))

    print(f"Searching GitHub for .{a.ext} files...")
    found = search(a.ext)
    print(f"{len(found)} files found, {len(done)} already downloaded")

    ok = bad = 0
    with manifest_path.open("a", encoding="utf-8") as man:
        for (repo, path), it in sorted(found.items()):
            if (repo, path) in done:
                continue
            ref = it["url"].split("?ref=")[-1]
            try:
                data = gh("-H", "Accept: application/vnd.github.raw",
                          f"repos/{repo}/contents/{quote(path)}?ref={ref}")
            except RuntimeError as e:
                print(f"  SKIP {repo}/{path}: {e}")
                bad += 1
                continue
            verified = blob_sha(data) == it["sha"]
            dest = out / safe(repo.replace("/", "__")) / Path(*[safe(p) for p in path.split("/")])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            man.write(json.dumps({"repo": repo, "path": path, "ref": ref, "blob_sha": it["sha"],
                                  "verified": verified, "bytes": len(data),
                                  "html_url": it["html_url"],
                                  "local": str(dest.relative_to(out))}) + "\n")
            ok += 1
            if not verified:
                print(f"  WARN sha mismatch {repo}/{path}")
    print(f"Downloaded {ok}, failed {bad}. Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
