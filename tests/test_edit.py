from __future__ import annotations

import pytest

from simpl_agent.catalog.symlib import LibSymbol, SymbolLibrary
from simpl_agent.smw import rawfile, save
from simpl_agent.smw.edit import EditError, Editor


def fake_library() -> SymbolLibrary:
    """Invented definitions shaped like simple library symbols."""
    lib = SymbolLibrary()
    defs = {
        3: ("OR", {"Smpl-C": "1", "DeviceCode": "0", "MaxVariableInputs": "999", "NumFixedOutputs": "1"}),
        20: ("Buffer", {"Smpl-C": "1", "DeviceCode": "0", "NumFixedInputs": "1", "MaxVariableInputs": "4000",
                        "MaxVariableOutputs": "4000", "Expand": "expand_inputs_with_outputs",
                        "SymJam": "NonExclusive"}),
        9: ("One Shot", {"Smpl-C": "1", "DeviceCode": "0", "NumFixedInputs": "3", "NumFixedOutputs": "2",
                         "NumFixedParams": "1", "ParamCue1": "pulse_time"}),
        999: ("Some Device", {"Smpl-C": "17", "DeviceCode": "42"}),
    }
    for code, (name, fields) in defs.items():
        lib.symbols[code] = LibSymbol(code=code, name=name, fields={"Code": str(code), "Name": name, **fields})
    return lib


@pytest.fixture
def ed(tiny: bytes) -> Editor:
    return Editor(rawfile.parse(tiny), fake_library(), verified_codes={3, 9, 20})


def test_rename_signal_changes_one_line(ed: Editor, tiny: bytes) -> None:
    ed.rename_signal("room_out", "room_output")
    out = ed.raw.to_bytes()
    assert out == tiny.replace(b"Nm=room_out\r\n", b"Nm=room_output\r\n")
    assert ed.prog.symbols[5].outputs == {1: 6}  # wiring is by handle, untouched


@pytest.mark.parametrize("bad", ["room_level", "ROOM_LEVEL", "", " x", "x ", "9lives", "Local", "a\r\nb"])
def test_rename_rejects_bad_names(ed: Editor, tiny: bytes, bad: str) -> None:
    with pytest.raises(EditError):
        ed.rename_signal("room_out", bad)
    assert ed.raw.to_bytes() == tiny


def test_rename_builtin_refused(ed: Editor) -> None:
    with pytest.raises(EditError):
        ed.rename_signal("#1", "zero")


def test_add_signal_appends_sorted(ed: Editor) -> None:
    h = ed.add_signal("room_volume", "analog")
    assert h == 8
    sg = list(ed.raw.of_type("Sg"))
    assert [r.get("H") for r in sg] == ["4", "5", "6", "7", "8"]
    assert sg[-1].lines == [("ObjTp", "Sg"), ("H", "8"), ("Nm", "room_volume"), ("SgTp", "2")]
    assert ed.raw.to_bytes().endswith(b"[\r\nObjTp=Sg\r\nH=8\r\nNm=room_volume\r\nSgTp=2\r\n]\r\n")


def test_add_symbol_or_with_new_output(ed: Editor) -> None:
    h = ed.add_symbol(3, "Logic", inputs=["room_enable", "room_out"], outputs=["room_any"])
    assert h == 7
    s = ed.prog.symbols[h]
    assert s.parent == 4 and h in ed.prog.symbols[4].children
    assert ed.prog.symbols[4].record.get("mC") == "3"
    assert s.inputs == {1: 4, 2: 6}
    assert ed.prog.signals[s.outputs[1]].name == "room_any"
    keys = s.record.keys()
    assert keys == ["ObjTp", "H", "SmC", "Nm", "ObjVer", "PrH", "CF", "n1I", "n1O", "mI", "I1", "I2", "mO", "tO", "O1"]
    # Round trip of the edited file is stable.
    data = ed.raw.to_bytes()
    assert rawfile.parse(data).to_bytes() == data


def test_add_symbol_refuses_second_driver(ed: Editor, tiny: bytes) -> None:
    with pytest.raises(EditError, match="already has a driver"):
        ed.add_symbol(3, "Logic", inputs=["room_enable", "brand_new"], outputs=["room_out"])
    assert ed.raw.to_bytes() == tiny  # the new input signal was rolled back too


def test_buffer_may_share_outputs(ed: Editor) -> None:
    ed.add_symbol(20, "Logic", inputs=["room_enable", "room_enable"], outputs=["room_out"])


def test_add_symbol_pin_counts_and_params(ed: Editor) -> None:
    with pytest.raises(EditError, match="each extra input"):
        ed.add_symbol(20, "Logic", inputs=["room_enable", "a", "b"], outputs=["c"])
    with pytest.raises(EditError, match="parameter"):
        ed.add_symbol(9, "Logic", inputs=["a", None, None], outputs=["b", None])
    h = ed.add_symbol(9, "Logic", inputs=["trig", None, None], outputs=["pulse", None], params=["2s"])
    assert ed.prog.symbols[h].params == {1: "2s"}
    assert ed.prog.symbols[h].inputs == {1: ed.find_signal("trig")}


def test_add_symbol_refuses_complex_and_unknown(ed: Editor) -> None:
    with pytest.raises(EditError, match="simple logic"):
        ed.add_symbol(999, "Logic", inputs=[], outputs=[])
    with pytest.raises(EditError, match="not in the installed library"):
        ed.add_symbol(12345, "Logic", inputs=[], outputs=[])
    with pytest.raises(EditError, match="folder"):
        ed.add_symbol(3, "Nowhere", inputs=["a", "b"], outputs=["c"])


def test_set_comment(ed: Editor) -> None:
    ed.set_comment("#5", "drives room_out")
    assert ed.prog.symbols[5].comment == "drives room_out"
    with pytest.raises(EditError):
        ed.set_comment("#5", "two\nlines")


def test_save_backs_up_and_writes(tmp_path, ed: Editor, tiny: bytes) -> None:
    target = tmp_path / "prog.smw"
    target.write_bytes(tiny)
    ed.rename_signal("room_out", "room_output")
    b = save.write(ed.raw, target)
    assert b is not None and b.read_bytes() == tiny
    assert b.parent == tmp_path / ".simpl-agent" / "backups"
    assert b"room_output" in target.read_bytes()
    assert not list(tmp_path.glob("*.tmp"))


def test_unverified_symbol_refused(tiny: bytes) -> None:
    ed = Editor(rawfile.parse(tiny), fake_library(), verified_codes={20})
    with pytest.raises(EditError, match="unproven"):
        ed.add_symbol(3, "Logic", inputs=["a", "b"], outputs=["c"])
    assert ed.raw.to_bytes() == tiny


def test_shipped_verified_list_loads() -> None:
    from simpl_agent.smw.edit import load_verified_codes

    codes = load_verified_codes()
    assert codes is not None and {1, 3, 20} <= codes  # AND, OR, Buffer
