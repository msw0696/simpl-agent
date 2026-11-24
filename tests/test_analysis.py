from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from simpl_agent import analysis as an
from simpl_agent.catalog.symlib import LibSymbol, SymbolLibrary
from simpl_agent.smw import rawfile
from simpl_agent.smw.edit import Editor
from simpl_agent.smw.model import load


def lib() -> SymbolLibrary:
    """Invented definitions in the library's shape."""
    out = SymbolLibrary()
    defs = {
        3: ("OR", {"Smpl-C": "1", "DeviceCode": "0", "MaxVariableInputs": "999", "NumFixedOutputs": "1",
                   "OutputCue1": "out"}),
        20: ("Buffer", {"Smpl-C": "1", "DeviceCode": "0", "NumFixedInputs": "1", "MaxVariableInputs": "4000",
                        "MaxVariableOutputs": "4000", "Expand": "expand_inputs_with_outputs",
                        "SymJam": "NonExclusive", "InputCue1": "enable", "InputCue2": "i#"}),
        21: ("Pulse", {"Smpl-C": "1", "DeviceCode": "0", "NumFixedInputs": "1", "NumFixedOutputs": "1",
                       "InputCue1": "trig", "OutputCue1": "out", "ParamCue1": "time"}),
    }
    for code, (name, f) in defs.items():
        out.symbols[code] = LibSymbol(code=code, name=name, fields={"Name": name, "Code": str(code), **f})
    return out


def counts(prog) -> Counter:
    return Counter(p.code for p in an.find_problems(prog, lib()))


def test_tiny_problems(tiny: bytes) -> None:
    probs = an.find_problems(load(rawfile.parse(tiny)), lib())
    got = [(p.code, p.signal) for p in probs]
    # room_enable and room_level go into the Buffer but nothing drives them;
    # room_text$ is driven by the Pulse but goes nowhere.
    assert got == [("LGCMCVT102", "room_enable"), ("LGCMCVT102", "room_level"), ("LGCMCVT103", "room_text$")]


def test_second_driver_warns_unless_shared(tiny: bytes) -> None:
    ed = Editor(rawfile.parse(tiny), lib(), verified_codes={3, 20})
    ed.add_symbol(3, "Logic", inputs=["room_enable", "room_enable"], outputs=["room_out"], allow_second_driver=True)
    probs = [p for p in an.find_problems(ed.prog, lib()) if p.code == "LGCMCVT220"]
    assert len(probs) == 1 and probs[0].signal == "room_out" and probs[0].confirmed
    assert "S-3" in probs[0].message  # third symbol in Logic

    ed2 = Editor(rawfile.parse(tiny), lib(), verified_codes={3, 20})
    ed2.add_symbol(20, "Logic", inputs=["room_enable", "room_level"], outputs=["room_out"])
    # Pulse (#6) reads room_out and Buffer #5 already drives it; two Buffers may share.
    assert "LGCMCVT220" not in counts(ed2.prog)


def test_placeholders_and_builtins_exempt(tiny: bytes) -> None:
    data = tiny.replace(b"Nm=room_text$", b"Nm=//__serial_reserved__")
    assert "LGCMCVT103" not in counts(load(rawfile.parse(data)))
    data = tiny.replace(b"I1=4\r\nI2=5", b"I1=1\r\nI2=2")  # wire the Buffer to built-ins 0 and 1
    assert counts(load(rawfile.parse(data)))["LGCMCVT102"] == 0


def test_errors(tiny: bytes) -> None:
    dup = tiny.replace(b"Nm=room_level", b"Nm=ROOM_ENABLE")
    assert counts(load(rawfile.parse(dup)))["SA-DUPLICATE-NAME"] == 1
    broken = tiny.replace(b"O1=7", b"O1=99")
    assert counts(load(rawfile.parse(broken)))["SA-MISSING-SIGNAL"] == 1


def test_incomplete_reports_only_the_leaf(tiny: bytes) -> None:
    data = tiny.replace(b"H=6\r\nSmC=21\r\n", b"H=6\r\nSmC=21\r\nCF=1\r\n")
    data = data.replace(b"Nm=Logic\r\nCF=2", b"Nm=Logic\r\nCF=1")
    probs = [p for p in an.find_problems(load(rawfile.parse(data)), lib()) if p.code == "SA-INCOMPLETE"]
    assert [p.symbols for p in probs] == [[6]]


@pytest.mark.parametrize(
    "code,letter,n,expected",
    [(20, "I", 1, "enable"), (20, "I", 2, "i1"), (20, "I", 3, "i2"), (20, "O", 1, "o1"),
     (3, "I", 4, "i4"), (3, "O", 1, "out"), (21, "P", 1, "time")],
)
def test_pin_labels(tiny: bytes, code: int, letter: str, n: int, expected: str) -> None:
    prog = load(rawfile.parse(tiny))
    assert an.pin_label(lib().get(code), prog.symbols[5], letter, n) == expected


def test_folder_path_and_position(tiny: bytes) -> None:
    prog = load(rawfile.parse(tiny))
    assert an.folder_path(prog, 6) == "Logic"
    assert an.position_in_folder(prog, 6) == 2


# ---------------------------------------------------------------- ground truth
def _f12_dir() -> Path | None:
    for c in (os.environ.get("SIMPL_F12_DIR"), Path.home() / "simpl-f12-test",
              Path.home() / "OneDrive" / "Documents" / "SIMPL" / "f12-test"):
        if c and Path(c, "03-two-drivers").is_dir():
            return Path(c)
    return None


# What SIMPL 4.32 reported when Matthew compiled each file (2026-11-24).
SIMPL_SAID = {
    "00-control-empty/test00.smw": (0, 0),
    "01-add-or/test01.smw": (2, 1),
    "02-rename/test02.smw": (2, 1),
    "03-two-drivers/test03.smw": (3, 1),
    "10-control-real/demo10.smw": (0, 0),
    "11-rename-real/demo11.smw": (0, 0),
}


@pytest.mark.corpus
@pytest.mark.skipif(_f12_dir() is None, reason="F12 test set not on this PC")
@pytest.mark.parametrize("rel,expected", sorted(SIMPL_SAID.items()))
def test_matches_simpl_compiler(rel: str, expected: tuple[int, int]) -> None:
    from simpl_agent.catalog.index import load_index

    prog = load(rawfile.read(_f12_dir() / rel))
    c = Counter(p.severity for p in an.find_problems(prog, load_index().library))
    assert (c["warning"], c["notice"]) == expected
    assert c["error"] == 0
