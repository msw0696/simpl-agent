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
    """SIMPL's save also changed PrNm (the file name); nothing else may differ."""
    g = [ln for ln in got.split(b"\r\n") if not ln.startswith(b"PrNm=")]
    w = [ln for ln in want.split(b"\r\n") if not ln.startswith(b"PrNm=")]
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


def test_middle_and_last_addresses_split_the_range(libs) -> None:
    ed = editor(libs)
    ed.add_device(libs[1], 232, "0x10")
    ed.add_device(libs[1], "TSW-1070", "FE")
    ed.add_device(libs[1], 232, "05")
    prog = ed.prog
    slots = [(r.get("H"), r.get("Ad")) for r in prog.raw.of_type("Dv") if r.get("Nm") == "P4Ethernet"]
    assert [a.split(",")[0] for _, a in slots] == ["03", "05", "06", "10", "11", "FE"]
    assert slots[0][0] == "263.264" and slots[1] == ("265", "05") and slots[3] == ("276", "10")
    assert slots[-1] == ("514", "FE") and slots[-2][0] == "277.513"
    # The network's symbol lists its devices by address, not by when they were added.
    net = prog.symbols[7]
    addrs = [prog.devices[prog.symbols[c].device].address for c in net.children]
    assert addrs == ["05", "10", "FE"]
    assert structural_problems(prog) == set()
    assert len(list(prog.raw.of_type("Et"))) == 1  # only the TSW has a default IP


def test_refusals_change_nothing(libs) -> None:
    ed = editor(libs, "dev-step1.smw")
    before = ed.raw.to_bytes()
    cases = [
        (("TSW-1070", "03"), "already used"),
        (("TSW-1070", "02"), "no P4Ethernet slot"),        # 02 is a Not_Used slot
        (("TSW-1070", "1G"), "bad address"),
        (("TSW-770", "20"), "isn't proven"),
        (("No Such Device", "20"), "0 devices named"),
    ]
    for (dev, ad), msg in cases:
        with pytest.raises(EditError, match=msg):
            ed.add_device(libs[1], dev, ad)
        assert ed.raw.to_bytes() == before
    with pytest.raises(EditError, match="no P4Ethernet slot"):
        ed.add_device(libs[1], 232, "20", network="Cresnet Devices")


@pytest.mark.parametrize("given,want", [("3", "03"), ("03", "03"), ("0x1a", "1A"), (254, "FE"), ("fe", "FE")])
def test_addresses_are_normalised(given, want) -> None:
    assert normalise_address(given) == want


def test_unproven_devices_are_still_checked_for_shape(libs) -> None:
    """allow_unproven (tests only) still refuses shapes the builder can't make."""
    ed = editor(libs)
    tsw770 = libs[1].find("TSW-770")[0]
    ed.add_device(libs[1], tsw770.code, "07", allow_unproven=True)
    assert structural_problems(ed.prog) == set()


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
