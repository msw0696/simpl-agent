"""Build the M0 reload/compile test set from public corpus files.

Writes numbered test programs for Matthew to open in SIMPL 4.32 and compile (F12),
plus untouched control copies, so a failure can be pinned on our edit. A copy of
every file as we wrote it is kept in <out>/_as_written for diffing against SIMPL's
re-save.

Usage:  python -I tools/make_f12_samples.py [--out DIR]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.catalog import load_symlib  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.edit import Editor  # noqa: E402
from simpl_agent.smw.rawfile import RawFile  # noqa: E402

EMPTY = GITHUB_CORPUS / "Norgate-AV__smpc/test/integration/fixtures/simple.smw"
REAL = GITHUB_CORPUS / "JayLiaProgramming__Crestron-Angular-Html/Crestron/Demo.smw"
OR, AND = 3, 1

README = """SIMPL Agent - M0 reload and compile test ({n} programs)
==========================================================

For each folder, in order:
  1. Open the .smw in SIMPL Windows 4.32 (File > Open). These were saved by
     SIMPL 4.30, so SIMPL may offer to convert or upgrade them: say yes, and
     note the message.
  2. Note any other message or warning shown while it loads.
  3. Compile (F12). Note the error, warning and notice counts and their text.
  4. File > Save (leave the file where it is) and close it.

Then tell Claude it's done, with what you noted. Don't touch _as_written.

How each one is judged: an edited file passes if it shows its control's
messages plus ONLY the ones predicted below. Folders "00" and "10" are the
untouched controls; if a control fails, the edits after it can't be judged.

{lines}
"""


def crlf(raw: RawFile) -> RawFile:
    """Files from git may have LF endings; SIMPL writes CRLF. Restore it."""
    if raw.newline == "\r\n":
        return raw
    return rawfile.parse(raw.to_text().replace(raw.newline, "\r\n").encode("latin-1"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Users\matth\OneDrive\Documents\SIMPL\f12-test")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty; move it aside first", file=sys.stderr)
        return 1
    lib = load_symlib()
    made: list[tuple[str, list[str]]] = []

    def emit(folder: str, name: str, raw: RawFile, *what: str) -> None:
        for d in (out / folder, out / "_as_written" / folder):
            d.mkdir(parents=True)
            (d / name).write_bytes(raw.to_bytes())
        made.append((folder, list(what)))

    emit("00-control-empty", "test00.smw", crlf(rawfile.read(EMPTY)),
         "Control: an empty CP4N program, unchanged.",
         "Predicted: compiles with 0 errors (the smpc project's own test says so).")

    ed = Editor(crlf(rawfile.read(EMPTY)), lib)
    ed.add_symbol(OR, "Logic", inputs=["test_a", "test_b"], outputs=["test_or"])
    emit("01-add-or", "test01.smw", ed.raw,
         "Adds an OR in Logic: test_a + test_b -> test_or (three new signals).",
         "Predicted: 0 errors; 2 warnings (test_a and test_b have no source);",
         "1 notice (test_or isn't used). Nothing else beyond the control's messages.")

    ed.rename_signal("test_or", "room_a_any")
    emit("02-rename", "test02.smw", ed.raw,
         "Same as 01, then renames test_or to room_a_any.",
         "Predicted: exactly 01's messages, with room_a_any in place of test_or.")

    ed2 = Editor(crlf(rawfile.read(EMPTY)), lib)
    ed2.add_symbol(OR, "Logic", inputs=["test_a", "test_b"], outputs=["test_out"])
    ed2.add_symbol(AND, "Logic", inputs=["test_a", "test_b"], outputs=["test_out"], allow_second_driver=True)
    ed2.set_comment(f"#{max(ed2.prog.symbols)}", "experiment: second driver on test_out")
    emit("03-two-drivers", "test03.smw", ed2.raw,
         "EXPERIMENT: an OR and an AND both drive test_out.",
         "No prediction: this settles whether SIMPL allows two drivers. Note exactly",
         "what it says on load and on compile, even if it's nothing.")

    emit("10-control-real", "demo10.smw", crlf(rawfile.read(REAL)),
         "Control: a small public PRO3 program, unchanged.",
         "Predicted: none; whatever it shows is the baseline for 11.")

    ed3 = Editor(crlf(rawfile.read(REAL)), lib)
    sigs = [s for s in ed3.prog.signals.values() if s.record is not None and not s.name.startswith("//")]
    victim = sigs[0]
    new = victim.name + "_renamed"
    ed3.rename_signal(f"#{victim.handle}", new)
    emit("11-rename-real", "demo11.smw", ed3.raw,
         f"The same program with signal '{victim.name}' renamed to '{new}'.",
         f"Predicted: exactly 10's messages; any that named {victim.name} now say {new}.",
         "THIS IS THE MAIN TEST.")

    lines = "\n".join(f"{f}\n" + "".join(f"     {w}\n" for w in what) for f, what in made)
    (out / "README.txt").write_text(README.format(n=len(made), lines=lines), encoding="utf-8")
    shutil.copy2(Path(__file__), out / "_as_written" / "make_f12_samples.py")
    print(f"Wrote {len(made)} test programs to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
