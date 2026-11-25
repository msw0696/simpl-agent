from __future__ import annotations

import pytest

from simpl_agent.corpus import default_roots, iter_files
from simpl_agent.smw import rawfile
from simpl_agent.smw.edit import EditError, Editor
from simpl_agent.smw.model import load
from simpl_agent.smw.rawfile import Record
from test_edit import fake_library


@pytest.fixture
def ed(tiny: bytes) -> Editor:
    return Editor(rawfile.parse(tiny), fake_library(), verified_codes={3, 9, 20})


# ---------------------------------------------------------------- connect
def test_connect_existing_pin_and_new_signal(ed: Editor) -> None:
    ed.connect("#5", "I2", "room_enable")
    assert ed.prog.symbols[5].inputs == {1: 4, 2: 4}
    ed.connect("#6", "O1", "fresh_text", new_signal_type="serial")
    assert ed.prog.signals[ed.find_signal("fresh_text")].type == "serial"


def test_disconnect_and_reconnect_keeps_key_order(ed: Editor, tiny: bytes) -> None:
    ed.connect("#5", "I1", None)
    assert "I1" not in ed.prog.symbols[5].record
    ed.connect("#5", "I1", "#4")
    assert ed.raw.to_bytes() == tiny  # back exactly where SIMPL had it


def test_connect_refusals(ed: Editor, tiny: bytes) -> None:
    with pytest.raises(EditError, match="no pin I3"):
        ed.connect("#5", "I3", "room_enable")
    with pytest.raises(EditError, match="pin must look like"):
        ed.connect("#5", "X1", "room_enable")
    with pytest.raises(EditError, match="folder"):
        ed.connect("#4", "I1", "room_enable")
    with pytest.raises(EditError, match="already has a driver"):
        ed.connect("#6", "O1", "room_out")  # room_out is driven by Buffer #5; Pulse doesn't share
    with pytest.raises(EditError, match="built-in"):
        ed.connect("#6", "O1", "1")
    assert ed.raw.to_bytes() == tiny


def test_analog_and_placeholder_may_have_two_drivers(ed: Editor) -> None:
    # SIMPL 4.32 allows several drivers on analog signals and // placeholders (F12 round 2).
    ed.connect("#6", "O1", "room_level")  # analog, no driver yet
    ed.add_symbol(3, "Logic", inputs=["room_enable", "room_out"], outputs=["//spare"])
    ed.connect("#6", "O1", "//spare")


# ---------------------------------------------------------------- parameters and comments
def test_set_parameter(ed: Editor) -> None:
    ed.set_parameter("#6", "P1", "2.5s")
    assert ed.prog.symbols[6].params == {1: "2.5s"}
    with pytest.raises(EditError, match="no parameter P2"):
        ed.set_parameter("#6", "P2", "1s")
    with pytest.raises(EditError, match="one line"):
        ed.set_parameter("#6", "P1", "1s\n2s")


def test_set_comment_replaces_every_comment_key(ed: Editor) -> None:
    rec = ed.prog.symbols[6].record
    rec.set("Cmn2", "more text", after="Cmn1")
    ed.set_comment("#6", "new note")
    assert [k for k in ed.prog.symbols[6].record.keys() if k.startswith("Cmn")] == ["Cmn1"]


# ---------------------------------------------------------------- folders and structure
def test_rename_folder(ed: Editor) -> None:
    f = ed.add_folder("Lobby")
    ed.rename_folder("Lobby", "Reception")
    assert ed.prog.symbols[f].record.get("Cmn1") == "Reception"
    ed.add_folder("Other")
    with pytest.raises(EditError, match="already there"):
        ed.rename_folder("Other", "reception")
    with pytest.raises(EditError, match="Logic"):
        ed.rename_folder("Logic", "Main")


def test_rename_folder_keeps_extra_comment_lines(ed: Editor) -> None:
    f = ed.add_folder("Lobby")
    ed.prog.symbols[f].record.set("Cmn1", "Lobby" + "\\" * 2 + "second line")
    ed._reload()
    ed.rename_folder(f"#{f}", "Reception")
    assert ed.prog.symbols[f].record.get("Cmn1") == "Reception" + "\\" * 2 + "second line"


def test_remove_symbol_drops_unused_signals(ed: Editor) -> None:
    gone = ed.remove_symbol("#6")  # Pulse: room_out (still used by Buffer) in, room_text$ out
    assert gone == ["room_text$"]
    assert 6 not in ed.prog.symbols and ed.prog.symbols[4].children == [5]
    assert ed.prog.symbols[4].record.get("mC") == "1"
    data = ed.raw.to_bytes()
    assert rawfile.parse(data).to_bytes() == data


def test_remove_last_child_drops_mC(ed: Editor) -> None:
    f = ed.add_folder("Tmp")
    h = ed.add_symbol(3, "Tmp", inputs=["room_enable", "room_out"], outputs=["tmp_out"])
    ed.remove_symbol(f"#{h}")
    rec = ed.prog.symbols[f].record
    assert "mC" not in rec and "C1" not in rec
    ed.remove_symbol(f"#{f}")  # now empty, so removable
    assert f not in ed.prog.symbols


def test_removing_the_last_incomplete_symbol_clears_folder_marks(ed: Editor) -> None:
    """SIMPL marks the folders above an incomplete symbol (CF=1) and clears them once nothing
    incomplete is left inside (seen live in SIMPL 4.32, 2026-11-25)."""
    outer = ed.add_folder("Outer")
    inner = ed.add_folder("Inner", parent=f"#{outer}")
    a = ed.add_symbol(3, f"#{inner}", inputs=["room_enable", "room_out"], outputs=["a_out"])
    b = ed.add_symbol(3, f"#{inner}", inputs=["room_enable", "room_out"], outputs=["b_out"])
    for h in (a, b, inner, outer, 4):
        ed.prog.symbols[h].record.set("CF", "1")
    ed._reload()
    ed.remove_symbol(f"#{a}")  # b is still incomplete: the marks stay
    assert [ed.prog.symbols[h].record.get("CF") for h in (inner, outer, 4)] == ["1", "1", "1"]
    ed.remove_symbol(f"#{b}")
    assert [ed.prog.symbols[h].record.get("CF") for h in (inner, outer, 4)] == ["2", "2", "2"]


def test_remove_refusals(ed: Editor, tiny: bytes) -> None:
    f = ed.add_folder("Full")
    ed.add_symbol(3, "Full", inputs=["room_enable", "room_out"], outputs=["x"])
    with pytest.raises(EditError, match="isn't empty"):
        ed.remove_symbol(f"#{f}")
    with pytest.raises(EditError, match="top-level"):
        ed.remove_symbol("#4")


def test_move_symbol(ed: Editor) -> None:
    f = ed.add_folder("Room A")
    ed.move_symbol("#5", "Room A")
    assert ed.prog.symbols[5].parent == f
    assert ed.prog.symbols[4].children == [6, f] and ed.prog.symbols[f].children == [5]
    g = ed.add_folder("Inner", "Room A")
    with pytest.raises(EditError, match="into itself"):
        ed.move_symbol(f"#{f}", "Inner")
    ed.move_symbol(f"#{g}", "Logic")
    assert ed.prog.symbols[g].parent == 4


# ---------------------------------------------------------------- proof against SIMPL's own files
@pytest.mark.corpus
@pytest.mark.skipif(not default_roots(), reason="no corpus")
def test_pin_keys_reinsert_where_simpl_puts_them() -> None:
    """Strip each wired pin from every symbol SIMPL 4.3x saved, put it back with the
    editor's key placement, and require the identical record."""
    checked, bad = 0, []
    for path in iter_files(*default_roots()):
        raw = rawfile.read(path)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        for s in load(raw).symbols.values():
            for letter, pins in (("I", s.inputs), ("O", s.outputs)):
                for n, h in pins.items():
                    rec = Record(lines=list(s.record.lines))
                    rec.delete(f"{letter}{n}")
                    Editor._set_pin_key(rec, letter, n, str(h))
                    checked += 1
                    if rec.lines != s.record.lines:
                        bad.append(f"{path.name} Sm#{s.handle} {letter}{n}")
    assert checked > 10000
    assert not bad, (len(bad), bad[:10])
