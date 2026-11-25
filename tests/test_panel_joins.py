"""M7: reading a panel's joins and checking them against CH5 Agent's joins.json."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simpl_agent.smw import rawfile
from simpl_agent.smw.edit import EditError
from simpl_agent.smw.joins import is_join_symbol, numbered, read_joins
from test_device_edit import _wired_panel, libs  # noqa: F401 - pytest fixture

pytestmark = pytest.mark.skipif(not (Path(__file__).parent / "data" / "dev-step0.smw").exists(),
                                reason="device test files not present")


def names(ed, joins):
    return {k: {d: ed.prog.signals[h].name for d, h in v.items()} for k, v in joins.items()}


def test_read_joins_is_the_inverse_of_wire_joins(libs) -> None:  # noqa: F811
    ed, sym = _wired_panel(libs)
    assert names(ed, read_joins(ed.prog.symbols[sym].record)) == {
        ("digital", 10): {"in": "Power_On_Fb", "out": "Power_On_Press"},
        ("digital", 40): {"out": "Page_40_Press"},
        ("analog", 2): {"in": "Volume_Fb", "out": "Volume_Set"},
        ("analog", 35): {"in": "Level_35"},
        ("serial", 1): {"in": "Room_Name_Fb"},
    }


def test_wiring_the_same_joins_again_changes_nothing(libs) -> None:  # noqa: F811
    ed, sym = _wired_panel(libs)
    before = ed.raw.to_bytes()
    same = [{"type": "digital", "join": 10, "in": "power_on_fb", "out": "Power_On_Press"},
            {"type": "analog", "join": 2, "in": "Volume_Fb", "out": "Volume_Set"}]
    ed.wire_joins(f"#{sym}", same, keep_existing=True)  # a digital press driving its own signal again is fine
    assert ed.raw.to_bytes() == before


def test_join_map_never_replaces_a_different_signal(libs) -> None:  # noqa: F811
    ed, sym = _wired_panel(libs)
    before = ed.raw.to_bytes()
    with pytest.raises(EditError, match="digital 10 out: Power_On_Press \\(file: Power_Toggle\\)"):
        ed.wire_joins(f"#{sym}", [{"type": "digital", "join": 10, "out": "Power_Toggle"}], keep_existing=True)
    assert ed.raw.to_bytes() == before
    ed.wire_joins(f"#{sym}", [{"type": "digital", "join": 10, "out": "Power_Toggle"}])  # explicit: replaced
    assert names(ed, read_joins(ed.prog.symbols[sym].record))[("digital", 10)]["out"] == "Power_Toggle"
    # The replaced signal is used nowhere else, so it goes at the end of the edit, as SIMPL drops
    # unused signals on its next save (seen live, 2026-11-25).
    assert ed.finish() == ["Power_On_Press"]
    with pytest.raises(EditError, match="no signal named"):
        ed.find_signal("Power_On_Press")


def write_map(tmp_path: Path, joins, unnamed=(), ip="03") -> Path:
    p = tmp_path / "joins.json"
    p.write_text(json.dumps({"note": "test", "xpanel_ip_id": ip, "joins": list(joins),
                             "joins_without_simpl_signals": list(unnamed)}), "utf-8")
    return p


def test_check_against_a_join_map(libs, tmp_path: Path) -> None:  # noqa: F811
    from simpl_agent import panel_joins as pj

    ed, sym = _wired_panel(libs)
    jm = pj.load_join_map(write_map(tmp_path, [
        {"type": "digital", "join": 10, "out": "Power_On_Press", "in": "POWER_ON_FB"},  # ok (case)
        {"type": "analog", "join": 2, "out": "Volume_Set", "in": "Volume_Level"},      # in differs
        {"type": "digital", "join": 11, "out": "Mute_Press"},                           # missing
    ], unnamed=[{"type": "serial", "join": 1}, {"type": "digital", "join": 12}]))
    panel, notes = pj.find_panel(ed.prog, libs[0], "3", None)  # hex IDs compare by value
    assert panel["handle"] == sym and notes == []
    r = pj.check(ed.prog, sym, jm)
    assert r["counts"] == {"ok": 3, "missing": 1, "different": 1, "panel_joins_without_signal_names": 2,
                           "wired_but_not_on_panel": 2}
    assert r["different"] == [{"type": "analog", "join": 2, "direction": "in", "panel_map": "Volume_Level",
                               "program": "Volume_Fb"}]
    assert r["wire_joins_for_missing"] == [{"type": "digital", "join": 11, "out": "Mute_Press"}]
    assert r["panel_joins_without_signal_names"] == [
        {"type": "serial", "join": 1, "program": {"in": "Room_Name_Fb"}}, {"type": "digital", "join": 12, "program": None}]
    assert [(x["type"], x["join"]) for x in r["wired_but_not_on_panel"]] == [("digital", 40), ("analog", 35)]
    assert not r["matches"]
    with pytest.raises(pj.JoinMapError, match="no panel, XPanel or EISC at IP ID 04"):
        pj.find_panel(ed.prog, libs[0], "04", None)


def test_bad_join_maps_are_refused(tmp_path: Path) -> None:
    from simpl_agent import panel_joins as pj

    for joins, msg in [([{"type": "video", "join": 1, "in": "x"}], "bad join"),
                       ([{"type": "digital", "join": 1}], "no 'in' or 'out'"),
                       ([{"type": "digital", "join": 1, "in": "a"}, {"type": "digital", "join": 1, "out": "b"}],
                        "listed twice")]:
        with pytest.raises(pj.JoinMapError, match=msg):
            pj.load_join_map(write_map(tmp_path, joins))


def test_apply_edits_with_a_join_map_file(libs, tmp_path: Path) -> None:  # noqa: F811
    from simpl_agent.server import Tools

    ed, sym = _wired_panel(libs)
    prog = tmp_path / "panel.smw"
    prog.write_bytes(ed.raw.to_bytes())
    t = Tools(home=tmp_path / "home")
    t.windows = lambda: []
    jf = write_map(tmp_path, [{"type": "digital", "join": 10, "out": "Power_On_Press", "in": "Power_On_Fb"},
                              {"type": "digital", "join": 11, "out": "Mute_Press", "in": "Mute_Fb"}])
    c = t.call("check_panel_joins", {"path": str(prog), "joins_file": str(jf)})
    assert c["ok"] and c["counts"]["missing"] == 2 and c["panel"]["symbol"] == f"#{sym}"
    r = t.call("apply_edits", {"path": str(prog), "revision": c["revision"], "summary": "wire from the map",
                               "edits": [{"op": "wire_joins", "joins_file": str(jf)}]})
    assert r["ok"], r
    c2 = t.call("check_panel_joins", {"path": str(prog), "joins_file": str(jf)})
    assert c2["counts"]["missing"] == 0 and c2["counts"]["ok"] == 4
    hist = t.call("edit_history", {"path": str(prog)})
    assert "Mute_Press" in json.dumps(hist)  # the joins themselves are in the history, not just the file name


@pytest.mark.corpus
def test_every_corpus_panel_reads_back_and_rewires_unchanged(libs) -> None:  # noqa: F811
    """Every wired pin on a panel-style symbol in a SIMPL 4.3x corpus file is one join, and
    wiring those joins again (as a join map would) leaves the file byte for byte."""
    from simpl_agent.corpus import GITHUB_CORPUS, iter_files
    from simpl_agent.smw.edit import Editor

    if not GITHUB_CORPUS.is_dir():
        pytest.skip("no corpus")
    lib = libs[0]
    panels = pins = 0
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        raw = rawfile.read(f)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        ed = Editor(raw, lib)
        for s in list(ed.prog.symbols.values()):
            ls = lib.get(s.code) if s.code is not None else None
            if ls is None or not is_join_symbol(ls) or not (s.inputs or s.outputs):
                continue
            joins = read_joins(s.record)
            got = sum(len(v) for v in joins.values())
            assert got == len(numbered(s.record, "I")) + len(numbered(s.record, "O")), (f.name, s.handle)
            if any(h not in ed.prog.signals for v in joins.values() for h in v.values()):
                continue
            before = ed.raw.to_bytes()
            ed.wire_joins(f"#{s.handle}", [{"type": t, "join": n, **{d: f"#{h}" for d, h in v.items()}}
                                           for (t, n), v in joins.items()], keep_existing=True)
            assert ed.raw.to_bytes() == before, (f.name, s.handle)
            panels += 1
            pins += got
    assert panels > 50, panels


def test_connect_types_new_signals_by_pin_list(libs) -> None:  # noqa: F811
    """connect on a multi-list device: a new signal takes its pin list's type (digital, analog,
    serial), and a signal of another type is refused (64,525 corpus pins, 2026-11-25)."""
    ed, sym = _wired_panel(libs)  # lists of 40 digital, 35 analog, 32 serial
    ed.connect(f"#{sym}", "I43", "Volume_Fb_2")  # analog join 3
    ed.connect(f"#{sym}", "O77", "Room_Name_Out")  # serial join 2
    ed.connect(f"#{sym}", "I5", "Mute_Fb")  # digital join 5
    assert ed.prog.signals[ed.find_signal("Volume_Fb_2")].type == "analog"
    assert ed.prog.signals[ed.find_signal("Room_Name_Out")].type == "serial"
    assert ed.prog.signals[ed.find_signal("Mute_Fb")].type == "digital"
    with pytest.raises(EditError, match="takes analog signals"):
        ed.connect(f"#{sym}", "I44", "Power_On_Fb")
