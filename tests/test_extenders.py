"""Panel extenders (SmC 2942): Smart Graphics objects (.sgd) and CH5 contract components (.chd).
The contract and program pieces here are invented; the corpus test reads public programs."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from simpl_agent import analysis as an
from simpl_agent.smw import rawfile
from simpl_agent.smw.model import load
from simpl_agent.smw.rawfile import Record
from test_device_edit import DATA, editor, libs  # noqa: F401 - pytest fixture

needs_samples = pytest.mark.skipif(not (DATA / "dev-step0.smw").exists(),
                                   reason="needs the local dev-step samples and SIMPL's libraries")

CHD = "\r\n".join([
    "[", "ObjTp=FSgntr", "Sgntr=CHD", "RelVrs=1", "]",
    "[", "ObjTp=Hd", "ProjectFile=Room", "ContractID=_test1", "]",
    "[", "ObjTp=Symbol", "Name=Room", "Hint=Room (Control Join Id 5)", "Code=1",
    "MinVariableInputs=1", "MaxVariableInputs=1", "MinVariableInputsList2=0", "MaxVariableInputsList2=0",
    "MinVariableInputsList3=2", "MaxVariableInputsList3=2",
    "MinVariableOutputs=1", "MaxVariableOutputs=1", "MinVariableOutputsList2=0", "MaxVariableOutputsList2=0",
    "MinVariableOutputsList3=1", "MaxVariableOutputsList3=1",
    "InputCue1=PowerFb", "InputSigType1=Digital",
    "InputList3Cue1=[~UNUSED3~]", "InputList3SigType1=Serial", "InputList3Cue2=Title", "InputList3SigType2=Serial",
    "OutputCue1=PowerPress", "OutputSigType1=Digital", "OutputList3Cue1=Debug", "OutputList3SigType1=Serial",
    "NumFixedParams=1", "ParamCue1=ControlJoinId", "]",
    "",
])


def contract_program(libs, tmp_path: Path):  # noqa: F811
    """A TSW-1070 at 03 with a CH5 contract and one placed component, written to tmp_path."""
    ed = editor(libs)
    sym = ed.add_device(libs[1], "TSW-1070", "03")
    dev = next(d for d in ed.prog.devices.values() if d.symbol == sym)
    ed._insert_record(Record(lines=[("ObjTp", "VTP"), ("H", "1"), ("DvH", str(dev.handles[0])), ("GuiExtType", "2"),
                                    ("SGDFile", ".\\contract\\Room.chd"), ("ContractID", "_test1")]), "VTP",
                      after_types=("Et",))
    dev.record.set("VtpH", "1")
    fb = ed.signal_for("Room_Power_Fb", create_type="digital")
    title = ed.signal_for("Room_Title$", create_type="serial")
    press = ed.signal_for("Room_Power_Press", create_type="digital")
    h = ed._next_handle("Sm")
    ed._insert_record(Record(lines=[
        ("ObjTp", "Sm"), ("H", str(h)), ("SmC", "2942"), ("Nm", "Room"), ("ObjVer", "1"), ("PrH", str(sym)),
        ("CF", "2"), ("n1I", "1"), ("n1O", "1"), ("mI", "3"), ("I1", str(fb)), ("I3", str(title)),
        ("mO", "1"), ("tO", "2"), ("O1", str(press)), ("mP", "1"), ("P1", "5d")]), "Sm", after_types=("Bw", "Bk"))
    ed._append_child(sym, h)
    ed._reload()
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "Room.chd").write_bytes(CHD.encode("latin-1"))
    prog_path = tmp_path / "panel.smw"
    prog_path.write_bytes(ed.raw.to_bytes())
    return prog_path, h, sym


@needs_samples
def test_contract_component_pin_names(libs, tmp_path: Path) -> None:  # noqa: F811
    p, h, sym = contract_program(libs, tmp_path)
    prog = load(rawfile.read(p))
    s = prog.symbols[h]
    assert an.panel_of(prog, h).symbol == sym
    ext = an.gui_extension(prog, an.panel_of(prog, h), p)
    assert ext["kind"] == "CH5 contract (.chd)" and ext["found"] and ext["contract_id"] == "_test1"
    d = an.extender_definition(prog, s, p)
    assert d is not None and d.name == "Room"
    assert [an.pin_label(d, s, "I", n) for n in (1, 2, 3)] == ["PowerFb", "[~UNUSED3~]", "Title"]
    assert [an.pin_label(d, s, "O", n) for n in (1, 2)] == ["PowerPress", "Debug"]
    (tmp_path / "contract" / "Room.chd").unlink()  # without its file, names are generic
    assert an.extender_definition(prog, s, p) is None


@needs_samples
def test_show_symbol_and_device_tree_report_the_contract(libs, tmp_path: Path) -> None:  # noqa: F811
    from simpl_agent.server import Tools

    p, h, sym = contract_program(libs, tmp_path)
    t = Tools(home=tmp_path / "home")
    t.windows = lambda: []
    r = t.call("show_symbol", {"path": str(p), "symbol": f"#{h}"})
    assert r["ok"], r
    assert [(x["name"], x.get("signal")) for x in r["inputs"]] == [
        ("PowerFb", "Room_Power_Fb"), ("[~UNUSED3~]", None), ("Title", "Room_Title$")]
    assert r["panel_extender"]["smart_object_id"] == "5" and r["panel_extender"]["defined"]
    dt = t.call("device_tree", {"path": str(p)})
    (panel,) = [d for d in dt["devices"] if d.get("gui_extension")]
    assert panel["gui_extension"]["file"] == ".\\contract\\Room.chd"


@pytest.mark.corpus
def test_corpus_extenders_get_their_definitions() -> None:
    """Every placed extender whose .chd/.sgd is in its repo (tools/fetch_panel_files.py) finds its
    definition, fits its pin counts and gets a real name on every wired pin."""
    from simpl_agent.corpus import GITHUB_CORPUS, iter_files

    if not GITHUB_CORPUS.is_dir():
        pytest.skip("no corpus")
    generic = re.compile(r"^(i|o)\d+$|^list \d pin \d+$")
    defined = 0
    bad = []
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        raw = rawfile.read(f)
        if not any(r.get("SmC") == "2942" for r in raw.of_type("Sm")):
            continue
        prog = load(raw)
        for s in prog.symbols.values():
            if s.code != an.EXTENDER_CODE:
                continue
            d = an.extender_definition(prog, s, f)
            if d is None:
                continue
            defined += 1
            for letter, pins in (("I", s.inputs), ("O", s.outputs)):
                for n in pins:
                    if generic.match(an.pin_label(d, s, letter, n)):
                        bad.append((f.name, s.handle, f"{letter}{n}"))
    if defined == 0:
        pytest.skip("no panel files in the corpus (run tools/fetch_panel_files.py)")
    assert defined >= 200 and not bad, bad[:5]


@needs_samples
def test_simpls_copy_of_the_file_and_missing_or_changed_files(libs, tmp_path: Path) -> None:  # noqa: F811
    """SIMPL opens a program from its own copy of the imported file (<name>.chd_ in the program
    folder); without either it reports problems loading; a changed source means a sync."""
    p, h, sym = contract_program(libs, tmp_path)
    prog = load(rawfile.read(p))
    assert an.gui_extension_problems(prog, p) == []
    src = tmp_path / "contract" / "Room.chd"
    copy = tmp_path / "Room.chd_"
    copy.write_bytes(src.read_bytes())
    ext = an.gui_extension(prog, an.panel_of(prog, h), p)
    assert ext["simpl_copy"] == str(copy) and ext["path"] == str(copy) and "source_changed" not in ext
    src.write_bytes(src.read_bytes().replace(b"Title", b"Heading"))
    assert [x.code for x in an.gui_extension_problems(prog, p)] == ["SA-GUI-FILE-CHANGED"]
    assert an.pin_label(an.extender_definition(prog, prog.symbols[h], p), prog.symbols[h], "I", 3) == "Title"
    src.unlink()
    copy.unlink()
    (probs,) = [an.gui_extension_problems(prog, p)]
    assert [x.code for x in probs] == ["SA-GUI-FILE-MISSING"] and probs[0].symbols == [sym]
