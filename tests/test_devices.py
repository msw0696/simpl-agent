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
