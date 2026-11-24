"""Build F12 round 4: prove add_module (macros and SIMPL+) against SIMPL 4.32.

40-hue-control   the public Philips Hue test program (4-Series), unchanged: control
41-hue-bridge    the same, plus a second Philips Hue Bridge macro placed by SIMPL Agent.
                 That macro groups its pins, so SIMPL normally stores GrpStI/GrpStO;
                 we place it WITHOUT them to see whether SIMPL fills them in itself.
42-classroom     the edited classroom copy (real-test/gpc-edit), plus a folder holding
                 the tcnj_wolfvision macro and the PTZCameraCalMod SIMPL+ module, both
                 placed by SIMPL Agent.

Predictions (find_problems) go in each folder's PREDICTED.txt. SIMPL writes its own
messages to logfile.txt beside each program when it compiles, so the comparison can
be read straight from disk.

Usage:  python -I tools/make_f12_round4.py --out DIR --classroom DIR
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simpl_agent.analysis import find_problems  # noqa: E402
from simpl_agent.catalog.index import load_index  # noqa: E402
from simpl_agent.corpus import GITHUB_CORPUS, INSTALLED_MODULES  # noqa: E402
from simpl_agent.smw import rawfile, save  # noqa: E402
from simpl_agent.smw.edit import Editor  # noqa: E402
from simpl_agent.smw.model import load  # noqa: E402

SKIP = {"SPlsWork", ".simpl-agent", "logfile.txt"}
SKIP_SUFFIX = (".lpz", ".hash", ".sig", ".smft", "_archive.zip", "_compiled.zip", ".ASV", ".sm2")


def copy_job(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True)
    for f in src.iterdir():
        if f.name in SKIP or f.name.endswith(SKIP_SUFFIX) or f.is_dir():
            continue
        shutil.copy2(f, dst / f.name)


def predict(prog_path: Path, lib) -> None:
    probs = find_problems(load(rawfile.read(prog_path)), lib)
    lines = [f"{p.severity.upper():7} {p.code}  {p.message}" for p in probs]
    (prog_path.parent / "PREDICTED.txt").write_text(
        f"{len(probs)} messages predicted by SIMPL Agent's find_problems\n" + "\n".join(lines) + "\n", "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--classroom", required=True, help="folder of the classroom test copy (gpc-edit)")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty", file=sys.stderr)
        return 1
    lib = load_index().library
    hue_src = next(GITHUB_CORPUS.rglob("PhilipsHueTest.smw")).parent

    copy_job(hue_src, out / "40-hue-control")
    predict(out / "40-hue-control" / "PhilipsHueTest.smw", lib)

    copy_job(hue_src, out / "41-hue-bridge")
    p = out / "41-hue-bridge" / "PhilipsHueTest.smw"
    ed = Editor(rawfile.read(p), lib, program_path=p, installed_modules=INSTALLED_MODULES)
    ed.add_folder("Second Bridge")
    ed.add_module("Philips Hue Bridge v2.0.0.umc", "Second Bridge",
                  connect={"Link": "bridge2_link", "Get_Lights": "bridge2_get_lights", "Is_Linked": "bridge2_linked",
                           "Status": "bridge2_status$"},
                  parameters=["192.168.2.51", "crestron"], comment="Placed by SIMPL Agent (round 4)",
                  new_signal_type="digital")
    save.write(ed.raw, p, make_backup=False)
    predict(p, lib)

    copy_job(Path(a.classroom), out / "42-classroom")
    p = out / "42-classroom" / "dmps3_4k_150_standard.smw"
    ed = Editor(rawfile.read(p), lib, program_path=p, installed_modules=INSTALLED_MODULES)
    ed.add_folder("Module Test")
    ed.add_module("tcnj_wolfvision_v1.umc", "Module Test",
                  connect={"Power_On": "Wolf.Power.On", "Power_Off": "Wolf.Power.Off",
                           "From_Camera$": "Wolf.RX$", "To_Camera$": "Wolf.TX$", "Power_On_Fb": "Wolf.Power.On.Fb"},
                  comment="Placed by SIMPL Agent (round 4)")
    ed.add_module("PTZCameraCalMod.usp", "Module Test",
                  connect={"Input/1": "WebCam.Presets", "Output_1/1": "PTZ.Cal.Out1"},
                  comment="Placed by SIMPL Agent (round 4)")
    save.write(ed.raw, p, make_backup=False)
    predict(p, lib)
    for d in sorted(out.iterdir()):
        print(d.name, "->", (d / "PREDICTED.txt").read_text("utf-8").splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
