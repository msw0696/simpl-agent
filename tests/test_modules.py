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


# ---------------------------------------------------------------- add_module
def module_editor(tmp_path: Path):
    from simpl_agent.smw.edit import Editor

    p, _ = program(tmp_path)
    (tmp_path / "fake_timer.usp").write_bytes(b"// SIMPL+ source placeholder\r\n")
    data = p.read_bytes().replace(b"Sgntr=SimplWindow", b"Sgntr=SimplWindow\r\nRelVrs=4.32.02")
    return Editor(rawfile.parse(data), None, program_path=p), p


UMC_FULL = (
    "[\r\nVersion=1\r\n]\r\n[\r\nObjTp=FSgntr\r\nSgntr=UserMacro\r\n]\r\n"
    "[\r\nObjTp=Symbol\r\nName=Fake Camera\r\nNumFixedInputs=3\r\nNumFixedOutputs=2\r\nNumFixedParams=1\r\n"
    "InputCue1=Power_On\r\nInputSigType1=Digital\r\nInputCue2=[~UNUSED~]\r\nInputCue3=Preset_1\r\n"
    "InputSigType3=Digital\r\nOutputCue1=Power_Fb\r\nOutputSigType1=Digital\r\nOutputCue2=Level\r\n"
    "OutputSigType2=Analog\r\nParamCue1=Camera_Id\r\nParamCue2=p2\r\n]\r\n"
)
USH_FULL = (
    "[BEGIN]\r\n  ObjTp=Symbol\r\n  Name=fake_timer\r\n  MinVariableInputs=2\r\n  MinVariableInputsList2=1\r\n"
    "  MinVariableOutputs=1\r\n  MinVariableOutputsList2=1\r\n  NumFixedParams=1\r\n  MinVariableParams=1\r\n"
    "  InputCue1=Trig\r\n  InputSigType1=Digital\r\n  InputCue2=[~UNUSED~]\r\n  InputList2Cue1=Hours\r\n"
    "  InputList2SigType1=Analog\r\n  OutputCue1=Done\r\n  OutputSigType1=Digital\r\n  OutputList2Cue1=Progress\r\n"
    "  OutputList2SigType1=Analog\r\n  ParamCue1=[Reference Name]\r\n  ParamCue2=Timeout\r\n[END]\r\n"
)


def test_add_macro_by_pin_names(tmp_path: Path) -> None:
    ed, p = module_editor(tmp_path)
    (tmp_path / "Fake Camera.umc").write_bytes(UMC_FULL.encode("latin-1"))
    h = ed.add_module("Fake Camera.umc", "Logic", connect={"Power_On": "cam_power", "Level": "cam_level"},
                      parameters=["7"], comment="Room camera")
    s = ed.prog.symbols[h]
    reserved = ed.find_signal("//__digital_reserved__")
    assert s.record.lines == [
        ("ObjTp", "Sm"), ("H", "7"), ("SmC", "155"), ("Nm", "Fake Camera.umc"), ("ObjVer", "1"), ("PrH", "4"),
        ("CF", "2"), ("n1I", "3"), ("n1O", "2"), ("Cmn1", "Room camera"), ("mI", "3"), ("I1", str(s.inputs[1])),
        ("I3", str(reserved)), ("mO", "2"), ("tO", "2"), ("O1", str(reserved)), ("O2", str(s.outputs[2])),
        ("mP", "1"), ("P1", "7"),
    ]
    assert ed.prog.signals[s.outputs[2]].type == "analog"  # new signal typed from the pin
    # Unused required pins (Preset_1, Power_Fb) got SIMPL's placeholder; the [~UNUSED~] slot stays empty.
    assert 2 not in s.inputs


def test_required_pin_of_any_type_must_be_given(tmp_path: Path) -> None:
    import pytest

    from simpl_agent.smw.edit import EditError

    ed, p = module_editor(tmp_path)
    umc = UMC_FULL.replace("InputSigType3=Digital\r\n", "InputSigType3=Digital|Analog|Serial\r\n")
    (tmp_path / "Fake Camera.umc").write_bytes(umc.encode("latin-1"))
    with pytest.raises(EditError, match="Preset_1.*any signal"):
        ed.add_module("Fake Camera.umc", "Logic", connect={"Power_On": "cam_power"}, parameters=["7"])
    ed.add_module("Fake Camera.umc", "Logic", connect={"Power_On": "cam_power", "Preset_1": "cam_preset"},
                  parameters=["7"], new_signal_type="digital")


def test_add_splus_lists_and_placeholders(tmp_path: Path) -> None:
    ed, p = module_editor(tmp_path)
    (tmp_path / "fake_timer.ush").write_bytes(USH_FULL.encode("latin-1"))
    h = ed.add_module("fake_timer.usp", "Logic", connect={"Hours": "hours", "Progress": "progress"},
                      parameters={"Timeout": "30d"})
    r = ed.prog.symbols[h].record
    assert [r.get(k) for k in ("n1I", "n2I", "n1O", "n2O", "mI", "mO", "tO", "mP")] == ["2", "1", "1", None, "3", "2", "2", "2"]
    assert r.get("I3") == "9" and r.get("O2") == "10"  # existing analog signals on list-2 pins
    assert r.get("P1") == "" and r.get("P2") == "30d"  # [Reference Name] stays empty


def test_add_module_refusals(tmp_path: Path) -> None:
    import pytest

    from simpl_agent.smw.edit import EditError

    ed, p = module_editor(tmp_path)
    (tmp_path / "Fake Camera.umc").write_bytes(UMC_FULL.encode("latin-1"))
    (tmp_path / "fake_timer.ush").write_bytes(USH_FULL.encode("latin-1"))
    before = ed.raw.to_bytes()
    with pytest.raises(EditError, match="no pin"):
        ed.add_module("Fake Camera.umc", "Logic", connect={"Zoom": "x"}, parameters=["1"])
    with pytest.raises(EditError, match="placeholder"):
        ed.add_module("Fake Camera.umc", "Logic", connect={"I2": "x"}, parameters=["1"])
    with pytest.raises(EditError, match="missing"):
        ed.add_module("Fake Camera.umc", "Logic", connect={})
    with pytest.raises(EditError, match="takes digital"):
        ed.add_module("Fake Camera.umc", "Logic", connect={"Power_On": "hours"}, parameters=["1"])  # analog
    with pytest.raises(EditError, match="can't find"):
        ed.add_module("Missing.umc", "Logic")
    with pytest.raises(EditError, match="file name only"):
        ed.add_module(r"C:\elsewhere\Fake Camera.umc", "Logic")
    (tmp_path / "fake_timer.usp").unlink()
    with pytest.raises(EditError, match="next to the program"):
        ed.add_module("fake_timer.usp", "Logic", parameters=["1d"])
    assert ed.raw.to_bytes() == before


def test_parameter_dropdown(tmp_path: Path) -> None:
    """A drop-down parameter takes a listed value or its label; SIMPL's Plb label follows P<n>
    (live-checked: SIMPL 4.32 re-saved and compiled a module placed this way, 2026-11-25)."""
    import pytest

    from simpl_agent import analysis as an
    from simpl_agent.smw.edit import EditError

    ed, p = module_editor(tmp_path)
    ush = USH_FULL.replace("  ParamCue2=Timeout\r\n", "  ParamCue2=Timeout,0d,1d\r\n  ParamSigType2=List\r\n")
    ush += ("[BEGIN]\r\n  ObjTp=Dp\r\n  H=2\r\n  Tp=1\r\n  DV=0d\r\n  VVS=2\r\n  VN=2\r\n  Val1=0d\r\n"
            "  Lbl1=Off\r\n  Val2=1d\r\n  Lbl2=Long wait\r\n[END]\r\n")
    (tmp_path / "fake_timer.ush").write_bytes(ush.encode("latin-1"))
    assert an.splus_parameter_lists(p, "fake_timer.usp") == {
        2: {"default": "0d", "options": [("0d", "Off"), ("1d", "Long wait")]}}
    _, _, lay = ed.module_definition("fake_timer.usp")
    assert lay["parameters"][1][1:] == ("Timeout", "List")  # the values are cut from the name
    for given in ("long WAIT", "1d"):
        h = ed.add_module("fake_timer.usp", "Logic", parameters={"Timeout": given})
        lines = ed.prog.symbols[h].record.lines
        assert lines[-3:] == [("P1", ""), ("P2", "1d"), ("Plb2", "Long wait")]
    with pytest.raises(EditError, match=r"drop-down.*0d \(Off\), 1d \(Long wait\)"):
        ed.add_module("fake_timer.usp", "Logic", parameters=["5d"])


# ---------------------------------------------------------------- proof against SIMPL's own files
SPECIAL = ("GrpSt", "Pin")


@__import__("pytest").mark.corpus
def test_placed_modules_rebuild_exactly() -> None:
    """Every module SIMPL 4.3x placed in the corpus rebuilds byte-for-byte from its definition
    (window-state keys aside); drop-down labels (Plb) come from the record; group state is counted, not built."""
    import pytest

    from simpl_agent.corpus import GITHUB_CORPUS, INSTALLED_MODULES, iter_files
    from simpl_agent.smw.edit import module_lines

    if not GITHUB_CORPUS.is_dir():
        pytest.skip("no corpus")
    ui = {"OpF", "PropF", "HandF", "LogModDh"}
    checked, special, bad = 0, 0, []
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        raw = rawfile.read(f)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        for s in load(raw).symbols.values():
            if s.code not in (an.MACRO_CODE, an.SPLUS_CODE):
                continue
            d = an.module_definition(f, s, INSTALLED_MODULES)
            if d is None:
                continue
            r = s.record
            if any(k.startswith(SPECIAL) for k in r.keys()):
                special += 1
                continue
            lay = an.module_layout(s.code, d)
            num = an._int
            if s.code == an.SPLUS_CODE:  # arrays may be sized above the minimum when placed
                n1i, n2i, n1o = num(r.get("n1I")), num(r.get("n2I")), num(r.get("n1O"))
                n2o = num(r.get("mO")) - n1o
                npar = num(r.get("mP"))
            else:
                n1i, n2i, n1o, n2o, npar = lay["n1I"], 0, lay["n1O"], 0, len(lay["parameters"])
            gen = module_lines(handle=s.handle, code=s.code, name=s.name, objver=d.fields.get("ObjVer") or "1",
                               parent=s.parent, n1i=n1i, n2i=n2i, n1o=n1o, n2o=n2o, inputs=s.inputs,
                               outputs=s.outputs, params=[s.params.get(n, "") for n in range(1, npar + 1)],
                               param_labels={int(k[3:]): v for k, v in r.lines if k and k.startswith("Plb")},
                               comment=[v for k, v in r.lines if k and k.startswith("Cmn")])
            checked += 1
            if gen != [kv for kv in r.lines if kv[0] not in ui] or r.get("CF") != "2":
                bad.append(f"{f.name} {s.name}")
    if checked == 0:
        pytest.skip("no module files in the corpus (run tools/fetch_module_files.py)")
    assert checked > 500 and special < 30
    assert not bad, (len(bad), bad[:8])


# ---------------------------------------------------------------- changed modules
def placed_timer(tmp_path: Path):
    ed, p = module_editor(tmp_path)
    (tmp_path / "fake_timer.ush").write_bytes(USH_FULL.encode("latin-1"))
    h = ed.add_module("fake_timer.usp", "Logic", connect={"Trig": "t_trig", "Hours": "t_hours", "Done": "t_done",
                                                         "Progress": "t_progress"}, parameters={"Timeout": "5s"})
    p.write_bytes(ed.raw.to_bytes())
    return ed, p, h


def test_changed_module_is_reported(tmp_path: Path) -> None:
    """SIMPL keeps a placed module's wires by position (SIMPL 4.32, 2026-11-25): pin counts that
    no longer fit, or a signal of the wrong type on a pin, are SA-MODULE-CHANGED."""
    from simpl_agent.smw.model import load

    ed, p, h = placed_timer(tmp_path)
    prog = load(rawfile.read(p))
    assert [x for x in an.module_problems(prog, p) if h in x.symbols] == []  # (#6 was placed for another header)
    fields = dict(an._module_fields(str(tmp_path / "fake_timer.ush")))
    s = prog.symbols[h]
    assert an.module_fit_issues(prog, s, {**fields, "MinVariableInputs": "3"}) == [
        "2 digital inputs placed, the module now has 3"]
    assert an.module_fit_issues(prog, s, {**fields, "InputList2SigType1": "Serial"}) == [
        'pin I3 is now serial, but its signal "t_hours" is analog']
    (tmp_path / "fake_timer.ush").write_bytes(USH_FULL.replace("MinVariableInputs=2", "MinVariableInputs=1")
                                              .encode("latin-1"))
    import os

    os.utime(tmp_path / "fake_timer.ush", (1, 1))  # a new date, as a recompile gives (the header is cached by date)
    probs = [x for x in an.find_problems(prog, None, p) if h in x.symbols and x.code.startswith("SA-")]
    assert [x.code for x in probs] == ["SA-MODULE-CHANGED"]
    assert "2 digital inputs placed, the module now has 1" in probs[0].message


def test_placed_copies_named_from_the_previous_build(tmp_path: Path) -> None:
    from simpl_agent.splus import placed_copies

    ed, p, h = placed_timer(tmp_path)
    old = dict(an._module_fields(str(tmp_path / "fake_timer.ush")))
    new_pins = {"inputs": [{"name": "Trig"}, {"name": "Reset"}, {"name": "Hours"}],
                "outputs": [{"name": "Progress"}], "parameters": [{"name": "Timeout"}]}
    (c,) = [c for c in placed_copies(tmp_path / "fake_timer.usp", old, new_pins) if c["symbol"] == f"#{h}"]
    assert c["symbol"] == f"#{h}" and "already_out_of_date" not in c
    assert c["wiring_before"]["inputs"] == {"Trig": "t_trig", "Hours": "t_hours"}
    assert c["re_place_with"] == {"remove_symbol": f"#{h}", "add_module": {
        "module": "fake_timer.usp", "connect": {"Trig": "t_trig", "Hours": "t_hours", "Progress": "t_progress"},
        "parameters": {"Timeout": "5s"}}}
    assert c["signals_on_removed_pins"] == {"Done": "t_done"}


def test_splus_module_must_target_the_programs_processor(tmp_path: Path) -> None:
    """SIMPL only adds a SIMPL+ module built for the program's control system (Inclusions_CDS:
    6 = 3-Series, 7 = 4-Series; the processor's RackClass); all 365 corpus placements fit."""
    import pytest

    from simpl_agent.smw.edit import EditError

    ed, p = module_editor(tmp_path)
    for targets, cls, ok in (("7", "6", False), ("6,7", "6", True), ("7", "7", True), (None, "6", True)):
        ush = USH_FULL if targets is None else USH_FULL.replace("  Name=fake_timer\r\n",
                                                                 f"  Name=fake_timer\r\n  Inclusions_CDS={targets}\r\n")
        (tmp_path / "fake_timer.ush").write_bytes(ush.encode("latin-1"))
        import os

        os.utime(tmp_path / "fake_timer.ush", (len(ush) + int(cls), len(ush) + int(cls)))  # new date: no cached header
        ed.processor_class = cls
        if ok:
            ed.module_definition("fake_timer.usp")
        else:
            with pytest.raises(EditError, match="compiled for 4-Series only.*3-Series.*'3series'"):
                ed.module_definition("fake_timer.usp")
