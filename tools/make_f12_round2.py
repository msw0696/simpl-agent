"""Build F12 round 2: settle the find_problems rules SIMPL hasn't confirmed yet.

Each file starts from the same empty CP4N program as round 1 (its control,
00-control-empty, already compiled clean). Predictions in the README are what
SIMPL Agent's find_problems says; SIMPL's compile tells us where it's wrong.

Usage:  python -I tools/make_f12_round2.py [--out DIR]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.analysis import find_problems  # noqa: E402
from simpl_agent.catalog.index import load_index  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS  # noqa: E402
from simpl_agent.smw import rawfile  # noqa: E402
from simpl_agent.smw.edit import Editor  # noqa: E402
from simpl_agent.smw.rawfile import RawFile  # noqa: E402

EMPTY = GITHUB_CORPUS / "Norgate-AV__smpc/test/integration/fixtures/simple.smw"
AND, OR, BUFFER, ANALOG_INIT = 1, 3, 20, 32

README = """SIMPL Agent - F12 round 2 ({n} programs)
==========================================

For each folder, in order: open the .smw in SIMPL 4.32, press F12, then
Ctrl+S. Tell Claude the warnings and notices for each, word for word if you
can (copy/paste from the compile window is perfect).

Each "We predict" is what SIMPL Agent's checker says. A difference is useful:
it tells us which rule is wrong.

{lines}
"""


def crlf(raw: RawFile) -> RawFile:
    if raw.newline == "\r\n":
        return raw
    return rawfile.parse(raw.to_text().replace(raw.newline, "\r\n").encode("latin-1"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "simpl-f12-round2"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty; move it aside first", file=sys.stderr)
        return 1
    lib = load_index().library
    made: list[tuple[str, list[str]]] = []

    def fresh() -> Editor:
        return Editor(crlf(rawfile.read(EMPTY)), lib)

    def emit(folder: str, name: str, ed: Editor, question: str) -> None:
        for d in (out / folder, out / "_as_written" / folder):
            d.mkdir(parents=True)
            (d / name).write_bytes(ed.raw.to_bytes())
        probs = find_problems(ed.prog, lib)
        c = Counter(p.severity for p in probs)
        pred = [f"We predict: {c['error']} errors, {c['warning']} warnings, {c['notice']} notices"]
        pred += [f"  {p.severity.upper():7} {p.code}  {p.message}" for p in probs]
        made.append((folder, [question, *pred]))

    # 21: two Buffers drive one digital signal. Buffers are meant to share outputs.
    ed = fresh()
    ed.add_symbol(BUFFER, "Logic", inputs=["test_en1", "test_a"], outputs=["test_out"])
    ed.add_symbol(BUFFER, "Logic", inputs=["test_en2", "test_b"], outputs=["test_out"])
    emit("21-two-buffers", "test21.smw", ed,
         "Two Buffers both drive test_out. Question: does SIMPL warn (LGCMCVT220)?")

    # 22: two Analog Initialize symbols drive one analog signal.
    ed = fresh()
    ed.add_signal("test_level", "analog")
    ed.add_symbol(ANALOG_INIT, "Logic", inputs=["test_t1"], outputs=["test_level"], params=["10d"])
    ed.add_symbol(ANALOG_INIT, "Logic", inputs=["test_t2"], outputs=["test_level"], params=["20d"],
                  allow_second_driver=True)
    emit("22-two-analog", "test22.smw", ed,
         "Two Analog Initialize symbols both drive the analog signal test_level. Question: does SIMPL warn?")

    # 23: signals named with // (placeholders).
    ed = fresh()
    ed.add_symbol(OR, "Logic", inputs=["test_a", "test_b"], outputs=["//spare_out"])
    ed.add_symbol(AND, "Logic", inputs=["//spare_in", "test_a"], outputs=["test_and"])
    emit("23-placeholders", "test23.smw", ed,
         "//spare_out goes nowhere and //spare_in has no source. Question: does SIMPL report the // ones?")

    # 24: a second driver inside a subfolder, to learn how SIMPL numbers symbols (S-n).
    ed = fresh()
    ed.add_symbol(OR, "Logic", inputs=["test_a", "test_b"], outputs=["test_out"])
    ed.add_folder("Sub", "Logic")
    ed.add_symbol(OR, "Sub", inputs=["test_c", "test_d"], outputs=["test_x"])
    ed.add_symbol(OR, "Sub", inputs=["test_c", "test_d"], outputs=["test_y"])
    ed.add_symbol(AND, "Sub", inputs=["test_a", "test_b"], outputs=["test_out"], allow_second_driver=True)
    emit("24-subfolder", "test24.smw", ed,
         "Logic holds an OR (S-1) and folder 'Sub' (S-2). In Sub: OR, OR, then an AND that is a second\n"
         "     driver of test_out. Question: which S-number does SIMPL give the AND? (S-3 = position in\n"
         "     its folder; something else, like S-5 or S-2.3, tells us SIMPL numbers differently.)\n"
         "     Also check the folder 'Sub' appears under Logic in the Program View.")

    lines = "\n".join(f"{f}\n" + "".join(f"     {w}\n" for w in what) for f, what in made)
    (out / "README.txt").write_text(README.format(n=len(made), lines=lines), encoding="utf-8")
    print(f"Wrote {len(made)} test programs to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
