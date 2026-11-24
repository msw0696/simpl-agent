from __future__ import annotations

import pytest

from simpl_agent.catalog.symlib import DEFAULT_SYMLIB
from simpl_agent.corpus import default_roots, iter_files
from simpl_agent.smw import rawfile
from simpl_agent.smw.edit import Editor, EditError, folder_lines
from simpl_agent.smw.model import load


def test_add_folder_and_put_a_symbol_in_it(tiny: bytes) -> None:
    from test_edit import fake_library

    ed = Editor(rawfile.parse(tiny), fake_library(), verified_codes={3})
    f = ed.add_folder("Room A")
    assert f == 7
    rec = ed.prog.symbols[f].record
    assert rec.lines == [("ObjTp", "Sm"), ("H", "7"), ("SmC", "156"), ("Nm", "SUBSYSTEM"), ("ObjVer", "1"),
                         ("PrH", "4"), ("CF", "2"), ("Cmn1", "Room A")]
    assert ed.prog.symbols[4].children == [5, 6, 7]
    h = ed.add_symbol(3, "Room A", inputs=["room_enable", "room_out"], outputs=["room_any"])
    assert ed.prog.symbols[f].children == [h]
    assert ed.prog.symbols[f].record.keys()[-2:] == ["mC", "C1"]
    data = ed.raw.to_bytes()
    assert rawfile.parse(data).to_bytes() == data


@pytest.mark.parametrize("bad", ["", " x", "a\\b", "two\nlines"])
def test_add_folder_rejects_bad_names(tiny: bytes, bad: str) -> None:
    ed = Editor(rawfile.parse(tiny))
    with pytest.raises(EditError):
        ed.add_folder(bad)
    assert ed.raw.to_bytes() == tiny


def test_add_folder_refuses_duplicate(tiny: bytes) -> None:
    ed = Editor(rawfile.parse(tiny))
    ed.add_folder("Room A")
    with pytest.raises(EditError, match="already exists"):
        ed.add_folder("room a")


@pytest.mark.corpus
@pytest.mark.skipif(not default_roots() or not DEFAULT_SYMLIB.exists(), reason="no corpus")
def test_folders_regenerate_exactly() -> None:
    """Every folder SIMPL 4.3x saved rebuilds byte-for-byte (window-state keys aside)."""
    ui = {"OpF", "PropF", "HandF", "LogModDh"}
    checked, bad = 0, []
    for path in iter_files(*default_roots()):
        raw = rawfile.read(path)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        for s in load(raw).symbols.values():
            if s.code != 156 or s.parent is None:
                continue
            r = s.record
            gen = folder_lines(handle=s.handle, smvr=r.get("SmVr"), parent=s.parent,
                               name=[v for k, v in r.lines if k and k.startswith("Cmn")], children=s.children)
            checked += 1
            if gen != [kv for kv in r.lines if kv[0] not in ui]:
                bad.append(f"{path.name} Sm#{s.handle}")
    assert checked > 300
    assert not bad, bad[:10]
