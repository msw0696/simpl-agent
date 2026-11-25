from __future__ import annotations

import pytest

from simpl_agent import devices as dv
from simpl_agent.checks import device_problems
from simpl_agent.corpus import GITHUB_CORPUS, iter_files
from simpl_agent.smw import rawfile
from simpl_agent.smw.model import format_handles, load, parse_handles


@pytest.mark.parametrize("hs,text", [([7], "7"), ([7, 8, 9], "7.9"), ([515, 551, 552, 553], "515,551.553"),
                                     ([3, 5], "3,5")])
def test_format_handles_round_trips(hs, text) -> None:
    assert format_handles(hs) == text
    assert parse_handles(text) == hs


def test_tiny_device_views(tiny: bytes) -> None:
    prog = load(rawfile.parse(tiny.replace(b"Nm=EmptySlot\r\n", b"Nm=EmptySlot\r\nDvF=Sl\r\n")))
    rows = dv.device_rows(prog)
    assert [r["name"] for r in rows] == ["TestProc"]
    nets = dv.networks(prog, None)
    assert nets[0]["network"] == "TestProc" and nets[0]["free_ids"] == ["01", "02"]
    assert device_problems(prog) == set()


def test_device_checks_catch_breakage(tiny: bytes) -> None:
    broken = tiny.replace(b"Ad=01,02", b"Ad=01")  # range of 2 handles, 1 address
    assert any("address count" in p for p in device_problems(load(rawfile.parse(broken))))
    unlisted = tiny.replace(b"C2=4\r\n]", b"]").replace(b"mC=2\r\nC1=3", b"mC=1\r\nC1=5")
    assert any("isn't listed" in p for p in device_problems(load(rawfile.parse(unlisted))))


@pytest.mark.corpus
@pytest.mark.skipif(not GITHUB_CORPUS.is_dir(), reason="no corpus")
def test_device_rules_hold_in_every_public_program() -> None:
    bad = []
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        ps = device_problems(load(rawfile.read(f)))
        if ps:
            bad.append((f.name, sorted(ps)[:2]))
    assert not bad, bad[:5]

@pytest.mark.corpus
@pytest.mark.skipif(not GITHUB_CORPUS.is_dir(), reason="no corpus")
def test_pin_types_match_every_public_program() -> None:
    # add_symbol/connect type new signals and refuse wrong-typed ones from Editor.pin_types,
    # so it must agree with every wired pin SIMPL saved (13,514 logic + 1,239 single-list device
    # pins, and since 2026-11-25 the 64,525 pins of multi-list devices: panels, EISCs, dimmers).
    from simpl_agent.catalog.symlib import DEFAULT_SYMLIB, load_symlib
    from simpl_agent.smw.edit import Editor

    if not DEFAULT_SYMLIB.exists():
        pytest.skip("SIMPL isn't installed")
    lib = load_symlib()
    checked, bad = 0, []
    for f in iter_files(GITHUB_CORPUS, exts={".smw"}):
        try:
            prog = load(rawfile.read(f))
        except Exception:
            continue
        builtin = set(prog.builtin_signals.values())
        for s in prog.symbols.values():
            ls = lib.get(s.code)
            for letter, pins in (("I", s.inputs), ("O", s.outputs)):
                for n, h in pins.items():
                    sg = prog.signals.get(h)
                    if sg is None or h in builtin or sg.name.startswith("//"):
                        continue
                    types = Editor.pin_types(ls, letter, n, s.record)
                    if types:
                        checked += 1
                        if sg.type not in types:
                            bad.append((f.name, s.code, f"{letter}{n}", sg.name, sg.type, types))
    assert checked > 70000 and not bad, bad[:5]
