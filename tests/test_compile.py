from __future__ import annotations

from pathlib import Path

import pytest

from simpl_agent import compile as cmp

# Shaped like smpc v0.2.0's real output (F12 round 4, 2026-11-24).
SAMPLE = """SIMPL Windows process started pid=28752
Compiling program...
Gathering details...

Error messages:
  1. ERROR\t(LGCMCVT190) Symbol S-2 (Bridge.USH) in module S-2 cannot be opened.

Warning messages:
  1. WARNING\t(108) Cannot locate the .ush compiled header file for User Simpl Plus symbol [X.usp] at [S-2].
  2. WARNING\t(LGCMCVT102) ** Signal "Wolf.Power.On" has no driving source.

Notice messages:
  1. NOTICE\t(LGCMCVT103) ** Signal "Wolf.TX$" has no destination.
"""


def test_parse_output() -> None:
    r = cmp.parse_output(SAMPLE)
    assert r["counts"] == {"errors": 1, "warnings": 2, "notices": 1}
    assert r["messages"][2] == {"severity": "warning", "code": "LGCMCVT102",
                                "message": 'Signal "Wolf.Power.On" has no driving source.'}
    assert r["messages"][3]["code"] == "LGCMCVT103" and r["messages"][1]["code"] == "108"


class NoLiveSimpl:
    """Tests never start a real SIMPL: the live link reports no SIMPL and can't launch one."""

    @staticmethod
    def status(p):
        return {"open": False, "controllable": False}

    @staticmethod
    def find(p):
        return None

    @staticmethod
    def launch(p):
        raise RuntimeError("no SIMPL in tests")


def test_compile_tool_refusals(tmp_path: Path, tiny: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    from simpl_agent.server import Tools

    p = tmp_path / "x.smw"
    p.write_bytes(tiny)
    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    t.live = NoLiveSimpl()
    monkeypatch.setattr(cmp, "installed", lambda: False)
    t.windows = lambda: []
    assert "couldn't compile through SIMPL" in t.call("compile_program", {"path": str(p)})["error"]
    monkeypatch.setattr(cmp, "installed", lambda: True)
    t.windows = lambda: ["SIMPL Windows - other.smw ( C:\\x\\other.smw)"]
    assert "Ask the user to close it" in t.call("compile_program", {"path": str(p)})["error"]


def test_compile_tool_compares_with_find_problems(tmp_path: Path, tiny: bytes,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from simpl_agent.server import Tools

    p = tmp_path / "x.smw"
    p.write_bytes(tiny)
    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    t.live = NoLiveSimpl()  # falls back to the (faked) smpc task
    t.windows = lambda: []
    monkeypatch.setattr(cmp, "installed", lambda: True)
    fake = ('Warning messages:\n  1. WARNING\t(LGCMCVT102) ** Signal "room_enable" has no driving source.\n'
            '  2. WARNING\t(LGCMCVT102) ** Signal "room_level" has no driving source.\n'
            'Notice messages:\n  1. NOTICE\t(LGCMCVT103) ** Signal "room_text$" has no destination.\n')
    monkeypatch.setattr(cmp, "compile_program", lambda path, timeout_s: {"exit_code": 0, "output": fake,
                                                                         **cmp.parse_output(fake)})
    r = t.call("compile_program", {"path": str(p)})
    assert r["ok"] and r["compiled"] and r["matches_find_problems"] and not r["file_changed_by_simpl"]
