"""Pin names for macros (.umc/.cmc) and SIMPL+ modules (.ush), read from their own files."""
from __future__ import annotations

from pathlib import Path

from simpl_agent import analysis as an
from simpl_agent.smw import rawfile
from simpl_agent.smw.model import load

# Invented module files in the real formats: .umc is .smw-style, .ush is .tio-style.
UMC = (
    "[\r\nVersion=1\r\n]\r\n[\r\nObjTp=FSgntr\r\nSgntr=UserMacro\r\n]\r\n"
    "[\r\nObjTp=Symbol\r\nName=Fake Camera\r\nInputCue1=Power_On\r\nInputCue2=Show_Id/#\r\n"
    "InputCue3=Preset_1\r\nOutputCue1=Power_Fb\r\nOutputCue2=Preset_1_Fb\r\n]\r\n"
)
USH = (
    "[BEGIN]\r\n  ObjTp=FSgntr\r\n  Sgntr=UserSPlus\r\n[END]\r\n"
    "[BEGIN]\r\n  ObjTp=Symbol\r\n  Name=fake_timer\r\n  InputCue1=Trig\r\n  InputCue2=[~UNUSED~]\r\n"
    "  InputList2Cue1=Hours\r\n  OutputCue1=Done\r\n  OutputList2Cue1=Progress\r\n[END]\r\n"
)


def program(tmp_path: Path) -> tuple[Path, object]:
    smw = (
        "[\r\nVersion=1\r\n]\r\n[\r\nObjTp=FSgntr\r\nSgntr=SimplWindow\r\n]\r\n"
        "[\r\nObjTp=Hd\r\nS0Nd=1\r\nS1Nd=2\r\nSLNd=3\r\n]\r\n"
        "[\r\nObjTp=Sm\r\nH=4\r\nSmC=156\r\nNm=Logic\r\nmC=2\r\nC1=5\r\nC2=6\r\n]\r\n"
        "[\r\nObjTp=Sm\r\nH=5\r\nSmC=155\r\nNm=Fake Camera.umc\r\nPrH=4\r\nn1I=3\r\nmI=3\r\nI3=7\r\n"
        "n1O=2\r\nmO=2\r\ntO=2\r\nO2=8\r\n]\r\n"
        "[\r\nObjTp=Sm\r\nH=6\r\nSmC=103\r\nNm=fake_timer.usp\r\nPrH=4\r\nn1I=2\r\nn2I=1\r\nmI=3\r\nI3=9\r\n"
        "n1O=1\r\nn2O=1\r\nmO=2\r\ntO=2\r\nO2=10\r\n]\r\n"
        "[\r\nObjTp=Sg\r\nH=7\r\nNm=cam_preset\r\n]\r\n[\r\nObjTp=Sg\r\nH=8\r\nNm=cam_preset_fb\r\n]\r\n"
        "[\r\nObjTp=Sg\r\nH=9\r\nNm=hours\r\nSgTp=2\r\n]\r\n[\r\nObjTp=Sg\r\nH=10\r\nNm=progress\r\nSgTp=2\r\n]\r\n"
    )
    (tmp_path / "Fake Camera.umc").write_bytes(UMC.encode("latin-1"))
    (tmp_path / "fake_timer.ush").write_bytes(USH.encode("latin-1"))
    p = tmp_path / "job.smw"
    p.write_bytes(smw.encode("latin-1"))
    return p, load(rawfile.read(p))


def test_macro_pin_names_from_umc(tmp_path: Path) -> None:
    p, prog = program(tmp_path)
    cam = prog.symbols[5]
    d = an.module_definition(p, cam)
    assert d is not None and d.name == "Fake Camera"
    # A name ending in '#' that is a real pin name doesn't renumber the pins after it.
    assert an.pin_label(d, cam, "I", 3) == "Preset_1"
    assert an.pin_label(d, cam, "I", 2) == "Show_Id/1"
    assert an.pin_label(d, cam, "O", 2) == "Preset_1_Fb"


def test_splus_pin_names_from_ush_including_list2(tmp_path: Path) -> None:
    p, prog = program(tmp_path)
    timer = prog.symbols[6]
    d = an.module_definition(p, timer)
    assert d is not None
    assert an.pin_label(d, timer, "I", 1) == "Trig"
    assert an.pin_label(d, timer, "I", 3) == "Hours"  # first pin of list 2
    assert an.pin_label(d, timer, "O", 2) == "Progress"


def test_missing_module_file_falls_back(tmp_path: Path) -> None:
    p, prog = program(tmp_path)
    (tmp_path / "fake_timer.ush").unlink()
    assert an.module_definition(p, prog.symbols[6]) is None
    assert an.pin_label(None, prog.symbols[6], "I", 3) == "i3"


def test_umc_files_can_be_described(tmp_path: Path) -> None:
    from simpl_agent.server import Tools

    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    t.windows = lambda: []
    (tmp_path / "m.umc").write_bytes(
        b"[\r\nVersion=1\r\n]\r\n[\r\nObjTp=FSgntr\r\nSgntr=UserMacro\r\n]\r\n"
        b"[\r\nObjTp=Hd\r\nS0Nd=1\r\nS1Nd=2\r\nSLNd=3\r\n]\r\n")
    r = t.call("describe_program", {"path": str(tmp_path / "m.umc")})
    assert r["ok"] and r["kind"] == "macro"
