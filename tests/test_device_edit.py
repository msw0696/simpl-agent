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
        (("CEN-RGBHV8x4 (Ethernet)", "20"), "requires some pins"),
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
