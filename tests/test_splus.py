from __future__ import annotations

from pathlib import Path

import pytest

from simpl_agent.splus import SPLUSCC, compile_module, parse_output

SAMPLE = """Compiling for 3-Series Output: 'C:\\x\\Broken.usp'...
[C:\\x\\Broken.usp] Error  (Line 50) - The  archive does not contain a valid SIMPL# assembly.
Total Error(s): 1
Total Warning(s): 0
Compiling for 4-Series Output: 'C:\\x\\Broken.usp'...
[C:\\x\\Broken.usp] * WARNING  * (Line 50) - The  archive does not contain a valid SIMPL# assembly.
Compiling Library for 4-Series Control System: 'LibrarySystem.dll'...
Total Error(s): 0
Total Warning(s): 1
"""


def test_parse_output_per_target() -> None:
    t = parse_output(SAMPLE)
    assert set(t) == {"3-Series", "4-Series"}
    assert t["3-Series"]["errors"] == 1 and t["3-Series"]["messages"][0] == {
        "severity": "error", "line": 50, "file": "Broken.usp",
        "message": "The  archive does not contain a valid SIMPL# assembly."}
    assert t["4-Series"]["warnings"] == 1 and t["4-Series"]["messages"][0]["severity"] == "warning"


@pytest.mark.skipif(not SPLUSCC.exists(), reason="SIMPL+ compiler not installed")
def test_compile_a_real_module(tmp_path: Path) -> None:
    usp = tmp_path / "Tiny.usp"
    usp.write_text("#SYMBOL_NAME \"Tiny\"\r\nDIGITAL_INPUT go;\r\nDIGITAL_OUTPUT done;\r\n"
                   "PUSH go\r\n{\r\n    done = 1;\r\n}\r\n", encoding="latin-1")
    res = compile_module(usp, ["series4"])
    assert res["compiled"] and res["errors"] == 0 and res["ush_written"], res
    bad = tmp_path / "Bad.usp"
    bad.write_text("#SYMBOL_NAME \"Bad\"\r\nDIGITAL_INPUT go;\r\nPUSH go\r\n{\r\n    nothere = 1;\r\n}\r\n",
                   encoding="latin-1")
    res = compile_module(bad, ["series4"])
    assert not res["compiled"] and res["errors"] >= 1, res
    msgs = res["targets"]["4-Series"]["messages"]
    assert any(m.get("code") == 1001 and "NOTHERE" in m["message"] for m in msgs), res


def test_fix_line_endings(tmp_path: Path) -> None:
    from simpl_agent.splus import fix_line_endings

    p = tmp_path / "x.usp"
    p.write_bytes(b"#SYMBOL_NAME \"X\" // name\nDIGITAL_INPUT a;\r\nDIGITAL_OUTPUT b;\n")
    assert fix_line_endings(p)
    assert p.read_bytes() == b"#SYMBOL_NAME \"X\" // name\r\nDIGITAL_INPUT a;\r\nDIGITAL_OUTPUT b;\r\n"
    assert not fix_line_endings(p)


@pytest.mark.skipif(not SPLUSCC.exists(), reason="SIMPL+ compiler not installed")
def test_lf_module_with_comments_keeps_its_pins(tmp_path: Path) -> None:
    # Found placing a module written with LF line endings: SPlusCC dropped everything after the
    # first // comment and reported a clean compile of an empty module.
    usp = tmp_path / "Lf.usp"
    usp.write_bytes(b"#SYMBOL_NAME \"Lf\" // the name\nBUFFER_INPUT rx$[100];\nDIGITAL_OUTPUT is_on, is_off;\n"
                    b"CHANGE rx$\n{\n    if (Find(\"ON\", rx$)) is_on = 1; // reply\n}\n")
    res = compile_module(usp, ["series4"])
    assert res["compiled"] and res["line_endings_fixed"], res
    m = res["module"]
    assert m["symbol_name"] == "Lf"
    assert [p["name"] for p in m["inputs"]] == ["rx$"] and m["inputs"][0]["type"] == "Serial"
    assert [p["name"] for p in m["outputs"]] == ["is_on", "is_off"]


@pytest.mark.skipif(not SPLUSCC.exists(), reason="SIMPL+ compiler not installed")
def test_stale_module_builds_are_found(tmp_path: Path, tiny: bytes) -> None:
    # A SIMPL started before a module's .ush was rewritten keeps the old build; compile_program
    # restarts it. _stale_splus finds those modules from the SIMPL process's start time.
    import time

    from simpl_agent.server import Tools
    from simpl_agent.smw import rawfile
    from simpl_agent.smw.edit import Editor

    usp = tmp_path / "Fb.usp"
    usp.write_bytes(b"#SYMBOL_NAME \"Fb\"\r\nDIGITAL_INPUT go;\r\nDIGITAL_OUTPUT done;\r\n"
                    b"PUSH go\r\n{\r\n    done = 1;\r\n}\r\n")
    assert compile_module(usp, ["series4"])["compiled"]
    prog = tmp_path / "x.smw"
    ed = Editor(rawfile.parse(tiny), None, program_path=prog)
    ed.add_module("Fb.usp", "Logic", connect={"go": "room_enable", "done": "fb_done"})
    prog.write_bytes(ed.raw.to_bytes())

    class Live:
        start = 0.0

        def process_start(self, pid):
            return self.start

    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    t.live = Live()
    t.live.start = time.time() - 3600  # SIMPL started before the compile
    assert t._stale_splus(prog, 123) == ["Fb.ush"]
    t.live.start = time.time() + 5  # started after it
    assert t._stale_splus(prog, 123) == []


def test_compare_pins() -> None:
    from simpl_agent.splus import compare_pins

    def pins(*names: str, kind: str = "Digital") -> dict:
        return {"inputs": [{"pin": i, "name": n, "type": kind} for i, n in enumerate(names, 1)], "outputs": []}

    assert compare_pins(pins("a", "b"), pins("a", "b")) is None
    swap = compare_pins(pins("a", "b"), pins("b", "a"))
    assert swap == {"inputs": {"before": ["a", "b"], "after": ["b", "a"], "moved": ["a", "b"]}, "wires_stay": False}
    assert compare_pins(pins("a", "b"), pins("a", "bee"))["wires_stay"] is True
    gone = compare_pins(pins("a", "b"), pins("b"))["inputs"]
    assert gone["removed"] == ["a"] and gone["moved"] == ["b"]
    assert compare_pins(pins("a"), pins("a", kind="Analog"))["inputs"]["type_changed"] == ["a"]
