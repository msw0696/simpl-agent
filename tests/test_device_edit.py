"""add_device: rebuild SIMPL 4.32's own saves byte for byte, and keep the format rules."""
from __future__ import annotations

from pathlib import Path

import pytest

from simpl_agent.catalog.devices import DEFAULT_IODEV
from simpl_agent.catalog.symlib import DEFAULT_SYMLIB
from simpl_agent.checks import structural_problems
from simpl_agent.smw import rawfile
from simpl_agent.smw.device_edit import normalise_address, symbol_counts
from simpl_agent.smw.edit import EditError, Editor
from simpl_agent.smw.model import load

# SIMPL 4.32's own saves of an empty CP4N, + TSW-1070 at 03, + EISC at 04. Real SIMPL files stay
# out of the repo (.gitignore), so these tests run only where the files are (copy them from
# Documents\SIMPL12-round5).
DATA = Path(__file__).parent / "data"
pytestmark = pytest.mark.skipif(
    not (DEFAULT_SYMLIB.exists() and DEFAULT_IODEV.exists() and (DATA / "dev-step2.smw").exists()),
    reason="needs SIMPL's libraries and the local dev-step samples")


@pytest.fixture(scope="module")
def libs():
    from simpl_agent.catalog.devices import load_devices
    from simpl_agent.catalog.index import load_index

    return load_index().library, load_devices()  # the slim index, as apply_edits uses


def editor(libs, name: str = "dev-step0.smw") -> Editor:
    return Editor(rawfile.read(DATA / name), libs[0])


def same_except_name(got: bytes, want: bytes) -> bool:
    """SIMPL's save also changed PrNm (the file name); nothing else may differ. Pin=True on a
    logic symbol is display state SIMPL keeps or drops on its own (round 6: dropped in one
    re-save of the same program, kept in the other), unrelated to devices."""
    skip = (b"PrNm=", b"Pin=")
    g = [ln for ln in got.split(b"\r\n") if not ln.startswith(skip)]
    w = [ln for ln in want.split(b"\r\n") if not ln.startswith(skip)]
    return g == w


@pytest.mark.parametrize("start,steps,want", [
    ("dev-step0.smw", [("TSW-1070", "03")], "dev-step1.smw"),
    ("dev-step1.smw", [("Ethernet Intersystem Communications", "04")], "dev-step2.smw"),
    ("dev-step0.smw", [("TSW-1070", "3"), (232, 4)], "dev-step2.smw"),
])
def test_rebuilds_simpls_own_saves(libs, start, steps, want) -> None:
    ed = editor(libs, start)
    for dev, ad in steps:
        ed.add_device(libs[1], dev, ad)
    assert same_except_name(ed.raw.to_bytes(), (DATA / want).read_bytes())


def test_symbol_counts_match_the_built_in_device_symbols(libs) -> None:
    """The count rule also reproduces every list-sized device symbol SIMPL wrote in step 0."""
    prog = load(rawfile.read(DATA / "dev-step0.smw"))
    checked = 0
    for s in prog.symbols.values():
        ls = libs[0].get(s.code)
        if s.record.get("DvH") is None or ls is None or ls.fields.get("NumFixedInputs"):
            continue
        got = {k: v for k, v in symbol_counts(ls).items() if v}
        want = {k: int(s.record.get(k)) for k in ("n1I", "n2I", "n1O", "mI", "mO", "tO") if s.record.get(k)}
        assert got == want, (s.handle, s.code)
        checked += 1
    assert checked >= 8


@pytest.mark.parametrize("start,steps,want", [
    # Round 6: SIMPL 4.32 re-saved our files. Middle, first and last addresses, several devices.
    ("dev-step0.smw", [("TSW-1070", "10"), (232, "FE"), (232, "05"), ("TSW-1070", "03")], "dev-a-saved.smw"),
    # A public program whose free IP IDs already had a gap (263,265.514); SIMPL's save of the
    # untouched program is the starting point, so its unrelated tidying cancels out.
    ("lib-orig-saved.smw", [(232, "0A")], "lib-edit-saved.smw"),
])
def test_matches_simpls_resave(libs, start, steps, want) -> None:
    if not (DATA / want).exists():
        pytest.skip("round 6 saves not copied here")
    ed = editor(libs, start)
    for dev, ad in steps:
        ed.add_device(libs[1], dev, ad)
    assert same_except_name(ed.raw.to_bytes(), (DATA / want).read_bytes())


def test_free_addresses_stay_in_one_record(libs) -> None:
    ed = editor(libs)
    ed.add_device(libs[1], 232, "0x10")
    ed.add_device(libs[1], "TSW-1070", "FE")
    ed.add_device(libs[1], 232, "05")
    prog = ed.prog
    slots = [(r.get("H"), r.get("Ad")) for r in prog.raw.of_type("Dv") if r.get("Nm") == "P4Ethernet"]
    assert [h for h, _ in slots] == ["263.264,266.275,277.513", "265", "276", "514"]
    assert slots[0][1].startswith("03,04,06,") and ",0F,11," in slots[0][1] and slots[0][1].endswith(",FD")
    ed.add_device(libs[1], 232, "03")  # taking the first address moves the free record down
    hs = [r.get("H") for r in ed.raw.of_type("Dv") if r.get("Nm") == "P4Ethernet"]
    assert hs == ["263", "264,266.275,277.513", "265", "276", "514"]
    # The network's symbol lists its devices by address, not by when they were added.
    prog = ed.prog
    addrs = [prog.devices[prog.symbols[c].device].address for c in prog.symbols[7].children]
    assert addrs == ["03", "05", "10", "FE"]
    assert structural_problems(prog) == set()
    assert len(list(prog.raw.of_type("Et"))) == 1  # only the TSW has a default IP


def test_refusals_change_nothing(libs) -> None:
    ed = editor(libs, "dev-step1.smw")
    before = ed.raw.to_bytes()
    cases = [
        (("TSW-1070", "03"), "already used"),
        (("TSW-1070", "02"), "no .*slot at address 02"),   # 02 is a Not_Used slot
        (("TSW-1070", "1G"), "bad address"),
        (("Virtual Communication Port", "20"), "incomplete"),
        (("No Such Device", "20"), "0 devices named"),
    ]
    for (dev, ad), msg in cases:
        with pytest.raises(EditError, match=msg):
            ed.add_device(libs[1], dev, ad)
        assert ed.raw.to_bytes() == before
    with pytest.raises(EditError, match="no .*slot at address 20"):
        ed.add_device(libs[1], 232, "20", network="Cresnet Devices")


@pytest.mark.parametrize("given,want", [("3", "03"), ("03", "03"), ("0x1a", "1A"), (254, "FE"), ("fe", "FE")])
def test_addresses_are_normalised(given, want) -> None:
    assert normalise_address(given) == want


def test_frames_get_every_slot_and_fixed_device(libs) -> None:
    """A device with its own slots: each position in its own place, fixed devices inside, depth first."""
    from simpl_agent.smw.device_edit import slot_layout

    ed = editor(libs)
    st_io = libs[1].find("ST-IO")[0]
    ed.add_device(libs[1], st_io.code, "40", network="Cresnet Devices")
    prog = ed.prog
    assert structural_problems(prog) == set()
    dev = next(d for d in prog.devices.values() if d.code == st_io.code)
    lay = slot_layout(libs[1], st_io)
    slots = [prog.devices[h] for h in dict.fromkeys(dev.children)]
    assert [s.name for s in slots] == [t for _, t, _ in lay]
    assert [s.address for s in slots] == [f"{p:02d}" for p, _, _ in lay]
    # Depth first: slot, its device, next slot ...
    assert [h for s in slots for h in (s.handles[0], s.children[0])] == list(range(dev.handles[0] + 1, dev.handles[0] + 1 + 2 * len(lay)))
    assert all(prog.devices[s.children[0]].record.get("SlC") == s.record.get("SlC") for s in slots)


def test_other_devices_of_a_supported_shape(libs) -> None:
    """Any device the rules cover can be added, on Ethernet or Cresnet, named by InstanceName."""
    from simpl_agent.smw.device_edit import instance_name

    ed = editor(libs)
    ed.add_device(libs[1], "TSW-770", "07")
    cres = next(d for d in libs[1].devices.values() if "P4Cresnet" in d.occupies and d.symbol_code
                and not d.numbered("Expand") and d.fields.get("InstanceName")
                and libs[0].get(d.symbol_code) is not None
                and not __import__("simpl_agent.smw.device_edit", fromlist=["x"]).symbol_shape_problem(
                    libs[0].get(d.symbol_code)))
    ed.add_device(libs[1], cres.code, "25", network="Cresnet Devices")
    prog = ed.prog
    assert structural_problems(prog) == set()
    placed = [d for d in prog.devices.values() if d.code == cres.code]
    assert placed and placed[0].name == instance_name(cres) and placed[0].address == "25"
    assert prog.symbols[placed[0].symbol].record.get("Cmn1") == instance_name(cres)
    assert prog.devices[placed[0].parent].name == "P4Cresnet"


def test_apply_edits_adds_a_device_end_to_end(libs, tmp_path: Path) -> None:
    from simpl_agent.catalog.index import load_index
    from simpl_agent.server import Tools

    p = tmp_path / "room.smw"
    p.write_bytes((DATA / "dev-step0.smw").read_bytes())
    t = Tools(home=tmp_path / "home")
    t.windows = lambda: []
    t._index, t._devlib = load_index(), libs[1]
    rev = t.call("describe_program", {"path": str(p)})["revision"]
    r = t.call("apply_edits", {"path": str(p), "revision": rev, "summary": "add the touch panel",
                               "edits": [{"op": "add_device", "device": "TSW-1070", "address": "03"}]})
    assert r["ok"], r
    assert same_except_name(p.read_bytes(), (DATA / "dev-step1.smw").read_bytes())
    rows = t.call("device_tree", {"path": str(p)})["devices"]
    assert any(d["name"] == "TSW-1070" and d["address"] == "03" and d.get("ip_address") == "127.0.0.1" for d in rows)
    free = t.call("free_ids", {"path": str(p), "network": "Ethernet"})["networks"][0]
    assert "03" not in free["free_ids"] and free["used"]["03"] == "TSW-1070"
    bad = t.call("apply_edits", {"path": str(p), "revision": r["revision"], "summary": "again",
                                 "edits": [{"op": "add_device", "device": "TSW-1070", "address": "03"}]})
    assert not bad["ok"] and "already used" in bad["error"]


@pytest.mark.corpus
def test_adding_a_device_keeps_every_public_program_valid(libs) -> None:
    from simpl_agent import devices as dv
    from simpl_agent.corpus import GITHUB_CORPUS, iter_files

    if not GITHUB_CORPUS.is_dir():
        pytest.skip("no corpus")
    tried, bad = 0, []
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        ed = Editor(rawfile.read(f), libs[0])
        nets = [n for n in dv.networks(ed.prog, libs[1]) if n["slot_type"] == "P4Ethernet" and n["free_ids"]]
        if not nets:
            continue
        before = structural_problems(ed.prog)
        try:
            ed.add_device(libs[1], 232, nets[0]["free_ids"][len(nets[0]["free_ids"]) // 2],
                          network=nets[0]["container"])
        except EditError as e:
            bad.append((f.name, str(e)))
            continue
        tried += 1
        new = structural_problems(ed.prog) - before
        if new:
            bad.append((f.name, sorted(new)[:2]))
    assert tried >= 10 and not bad, (tried, bad[:5])


def test_cards_go_into_a_frames_slots(libs) -> None:
    """A DM input card in a DM-MD8x8: no SlC, a Db record, symbol under the frame, Name parameter set."""
    ed = editor(libs)
    ed.add_device(libs[1], "DM-MD8x8", "10")
    frame = next(d for d in ed.prog.devices.values() if d.name == "DM-MD8x8")
    ed.add_device(libs[1], "DMC-4KZ-C", 1, network=f"#{frame.handles[0]}")
    prog = ed.prog
    assert structural_problems(prog) == set()
    card = next(d for d in prog.devices.values() if d.name == "DMC-4KZ-C")
    assert card.address == "01" and card.record.get("SlC") is None and card.record.get("DbH") is not None
    sym = prog.symbols[card.symbol]
    assert sym.parent == frame.symbol and sym.record.get("P1") == "DMC-4KZ-C"
    with pytest.raises(EditError, match="already used"):
        ed.add_device(libs[1], "DMC-4KZ-C", "01", network=f"#{frame.handles[0]}")
    # SIMPL drops its default "DM Outputs" into the output-card slots (DefDev17/21; f12-round8 save).
    outs = [prog.devices[prog.devices[h].children[0]] for h in dict.fromkeys(frame.children)
            if prog.devices[h].address in ("17", "21")]
    assert [d.name for d in outs] == ["DM Outputs", "DM Outputs"]
    assert prog.header.get("LabelOverrideStatus") == "2"
    with pytest.raises(EditError, match="already used"):
        ed.add_device(libs[1], "DMCO-22", 17, network=f"#{frame.handles[0]}")
    with pytest.raises(EditError, match="give network"):
        ed.add_device(libs[1], "DMC-4KZ-C", 2)


@pytest.mark.parametrize("start,steps,want", [
    # f12-round8, built in SIMPL 4.32 by SIMPL Agent driving SIMPL's own window (tools/simpl_gui.py).
    ("frames-step0.smw", [("DM-MD8x8", "03", None)], "frames-step1.smw"),
    ("frames-step1.smw", [("DMC-4KZ-C-DSP", 1, "#589"), ("DMC-4KZ-C", 2, "#589")], "frames-step2.smw"),
    ("frames-step2.smw", [("TSW-1070", "04", None), ("DM-NVX-36x", "05", None), ("CEN-IO-COM-102", "07", None),
                          ("XPanel 2.0 Smart Graphics", "08", None), ("TSW-770", "06", None)], "frames-step3.smw"),
])
def test_matches_simpls_frame_saves(libs, start, steps, want) -> None:
    """Frames, default devices (DefDev), cards, COM drivers with Cm records, Tpe, the header flag."""
    if not (DATA / want).exists():
        pytest.skip("round 8 saves not copied here")
    ed = editor(libs, start)
    for dev, ad, net in steps:
        ed.add_device(libs[1], dev, ad, network=net)
    assert same_except_name(ed.raw.to_bytes(), (DATA / want).read_bytes())


@pytest.mark.parametrize("start,device,want", [
    ("frames-step4.smw", "TSW-770", "frames-step5.smw"),      # a panel on an IP ID
    ("frames-step5.smw", "DMC-4KZ-C", "frames-step6.smw"),    # a card in a frame's slot
])
def test_remove_device_matches_simpls_delete(libs, start, device, want) -> None:
    if not (DATA / want).exists():
        pytest.skip("round 8 saves not copied here")
    ed = editor(libs, start)
    removed = ed.remove_device(libs[1], device)
    assert removed[0] == device and "FixedSlot" not in removed
    assert same_except_name(ed.raw.to_bytes(), (DATA / want).read_bytes())


def test_remove_device_refuses_built_in_parts(libs) -> None:
    ed = editor(libs)
    ed.add_device(libs[1], "TSW-1070", "03")
    before = ed.raw.to_bytes()
    with pytest.raises(EditError, match="built-in part"):
        ed.remove_device(libs[1], "TSW-1070 Buttons")
    with pytest.raises(EditError, match="can.t be removed"):
        ed.remove_device(libs[1], "#2")
    assert ed.raw.to_bytes() == before
    ed.remove_device(libs[1], "TSW-1070")
    assert same_except_name(ed.raw.to_bytes(), (DATA / "dev-step0.smw").read_bytes())



@pytest.mark.parametrize("name", ["new-cp4n", "new-cp3n", "new-rmc4", "new-mc4", "new-cp4", "new-pro4", "new-av4",
                                  "new-dinap4", "new-mc3", "new-rmc3", "new-cp3", "new-pro3", "new-mpc3302"])
def test_new_program_matches_simpls_file_new(libs, name) -> None:
    """SIMPL 4.32's File > New SIMPL program, made by driving SIMPL's window (f12-round8)."""
    from simpl_agent.smw.new_program import new_program

    want = DATA / f"{name}.smw"
    if not want.exists():
        pytest.skip("round 8 saves not copied here")
    hd = rawfile.read(want)
    fs, h = hd.first("FSgntr"), hd.first("Hd")
    versions = {"RelVrs": fs.get("RelVrs"), "SavedBy": fs.get("SavedBy"), "DbVr": h.get("DbVr"),
                "DvcDbVr": h.get("DvcDbVr")}
    raw = new_program(libs[1], libs[0], libs[1].get(int(h.get("CnC"))), file_name=f"{name}.smw",
                      system_name="New Test", versions=versions, lib_version=h.get("SmVr"))
    assert raw.to_bytes() == want.read_bytes()


def test_new_program_tool_never_overwrites(libs, tmp_path: Path) -> None:
    from simpl_agent.catalog.index import load_index
    from simpl_agent.server import Tools

    t = Tools(home=tmp_path / "home")
    t.windows = lambda: []
    t._index, t._devlib = load_index(), libs[1]
    p = tmp_path / "Job.smw"
    r = t.call("new_program", {"path": str(p), "processor": "CP4N", "system_name": "Job"})
    assert r["ok"] and p.exists(), r
    assert structural_problems(load(rawfile.read(p))) == set()
    again = t.call("new_program", {"path": str(p), "processor": "CP4N"})
    assert not again["ok"] and "already exists" in again["error"]
    bad = t.call("new_program", {"path": str(tmp_path / "x.smw"), "processor": "TSW-1070"})
    assert not bad["ok"] and "isn't a control processor" in bad["error"]
    unproven = t.call("new_program", {"path": str(tmp_path / "y.smw"), "processor": "CP2E"})
    assert not unproven["ok"] and "aren't proven yet" in unproven["error"]
    # A device can go straight onto the new program.
    r2 = t.call("apply_edits", {"path": str(p), "revision": r["revision"], "summary": "panel",
                                "edits": [{"op": "add_device", "device": "TSW-1070", "address": "03"}]})
    assert r2["ok"], r2


def _wired_panel(libs):
    ed = editor(libs)
    sym = ed.add_device(libs[1], "TSW-1070", "03")
    ed.wire_joins(f"#{sym}", [{"type": "serial", "join": 1, "in": "Room_Name_Fb"},
                              {"type": "analog", "join": 2, "in": "Volume_Fb", "out": "Volume_Set"},
                              {"type": "digital", "join": 10, "in": "Power_On_Fb", "out": "Power_On_Press"}])
    ed.wire_joins(f"#{sym}", [{"type": "digital", "join": 40, "out": "Page_40_Press"},
                              {"type": "analog", "join": 35, "in": "Level_35"}])
    return ed, sym


def test_wire_joins_grows_lists_and_moves_later_pins(libs) -> None:
    from simpl_agent.smw.joins import list_sizes

    ed, sym = _wired_panel(libs)
    r = ed.prog.symbols[sym].record
    assert list_sizes(r) == ([40, 35, 32], [40, 35, 32])
    names = {h: s.name for h, s in ed.prog.signals.items()}
    pins = {k: names[int(v)] for k, v in r.lines if k and k[0] in "IO" and k[1:].isdigit()}
    # Digital 40 / analog 35: analog join 2 is I42, serial join 1 is I76 (moved up from I34 and I65).
    assert pins == {"I10": "Power_On_Fb", "I42": "Volume_Fb", "I75": "Level_35", "I76": "Room_Name_Fb",
                    "O10": "Power_On_Press", "O40": "Page_40_Press", "O42": "Volume_Set"}
    assert structural_problems(ed.prog) == set()
    # SIMPL 4.32 opened this and re-saved it byte for byte (f12-round8).
    if (DATA / "joins-resaved.smw").exists():
        assert same_except_name(ed.raw.to_bytes(), (DATA / "joins-resaved.smw").read_bytes())


def test_wire_joins_refusals(libs) -> None:
    ed, sym = _wired_panel(libs)
    before = ed.raw.to_bytes()
    for joins, msg in [([{"type": "digital", "join": 3, "in": "Volume_Fb"}], "is analog"),
                       ([{"type": "video", "join": 1, "in": "x"}], "digital, analog or serial"),
                       ([{"type": "digital", "join": 0, "in": "x"}], "join number"),
                       ([{"type": "digital", "join": 5}], "in and/or out")]:
        with pytest.raises(EditError, match=msg):
            ed.wire_joins(f"#{sym}", joins)
        assert ed.raw.to_bytes() == before
    with pytest.raises(EditError, match="isn't a panel-style symbol"):
        ed.wire_joins("#9", [{"type": "digital", "join": 1, "in": "x"}])  # a COM driver



def test_output_cards_match_simpl(libs) -> None:
    """f12-round8 'outs': a DMC-4K-HDO into a DM Outputs holder, the default DM Outputs deleted, a DMCO-22
    in its place; SIMPL reused the freed handles (lowest unused first) for the DMCO-22 and its symbol."""
    if not (DATA / "outs-step3.smw").exists():
        pytest.skip("round 8 saves not copied here")
    ed = editor(libs, "outs-step0.smw")
    holders = sorted((d for d in ed.prog.devices.values() if d.name == "DM Outputs"), key=lambda d: d.handles[0])
    ed.add_device(libs[1], "DMC-4K-HDO", 1, network=f"#{holders[1].handles[0]}")
    assert same_except_name(ed.raw.to_bytes(), (DATA / "outs-step1.smw").read_bytes())
    ed.remove_device(libs[1], f"#{holders[0].handles[0]}")
    assert same_except_name(ed.raw.to_bytes(), (DATA / "outs-step2.smw").read_bytes())
    ed.add_device(libs[1], "DMCO-22", 17, network="#589")
    assert same_except_name(ed.raw.to_bytes(), (DATA / "outs-step3.smw").read_bytes())


def test_parameters_and_pins_by_name(libs) -> None:
    """A TCP/IP Client needs its Port; with it, SIMPL compiles it (round 8, compiled through SIMPL itself).
    Pins are wired by name across its digital/analog/serial lists."""
    ed = editor(libs)
    with pytest.raises(EditError, match="give its value in parameters"):
        ed.add_device(libs[1], "TCP/IP Client", "05")
    sym = ed.add_device(libs[1], "TCP/IP Client", "05", parameters={"Port": "23d"},
                        connect={"Connect": "Proj_Connect", "TX$": "Proj_TX$", "status": "Proj_Status"})
    r = ed.prog.symbols[sym].record
    names = {h: s for h, s in ed.prog.signals.items()}
    assert r.get("P1") == "23d" and r.get("SmC") == "3166"  # the 3/4-Series symbol (SymbolCode6)
    assert names[int(r.get("I1"))].name == "Proj_Connect" and names[int(r.get("I4"))].type == "serial"
    assert names[int(r.get("O2"))].type == "analog"
    assert structural_problems(ed.prog) == set()
    with pytest.raises(EditError, match="has no pin"):
        ed.add_device(libs[1], "TCP/IP Client", "06", parameters={"Port": "23d"}, connect={"Bogus": "x"})


def test_com_driver_remove_and_add_back_is_exact(libs) -> None:
    """A driver on a COM port is written like SIMPL's own default drivers; removing the CP4N's COM 1 driver
    and adding one back gives the original file (freed handles, Cm record included)."""
    ed = editor(libs)
    ed.remove_device(libs[1], "#518")
    ed.add_device(libs[1], "COM 2-Way Serial Driver", 1, network="#516")
    assert ed.raw.to_bytes() == (DATA / "dev-step0.smw").read_bytes()
