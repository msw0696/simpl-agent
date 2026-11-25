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
