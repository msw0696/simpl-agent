from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from simpl_agent.catalog.index import LibraryIndex
from simpl_agent.catalog.symlib import LibSymbol, SymbolLibrary
from simpl_agent.server import INSTRUCTIONS, TOOL_NAMES, Tools, parse_simpl_title


def fake_index() -> LibraryIndex:
    lib = SymbolLibrary()
    for code, name, extra in (
        (3, "OR", {"Smpl-C": "1", "DeviceCode": "0", "MaxVariableInputs": "999", "NumFixedOutputs": "1",
                   "SymbolTree": "2", "OutputCue1": "out"}),
        (9, "One Shot", {"Smpl-C": "1", "DeviceCode": "0", "NumFixedInputs": "3", "NumFixedOutputs": "2",
                         "NumFixedParams": "1", "InputCue1": "trig", "InputCue2": "hold", "InputCue3": "clear",
                         "OutputCue1": "out", "OutputCue2": "out*", "ParamCue1": "pulse_time",
                         "ParamSigType1": "Time", "SymbolTree": "13"}),
        (9999, "Made-up Panel", {"Smpl-C": "17", "DeviceCode": "12"}),
    ):
        lib.symbols[code] = LibSymbol(code=code, name=name, fields={"Name": name, "Code": str(code), **extra})
    return LibraryIndex(source="fake", library=lib, trees={2: "Logic", 13: "Timers"})


@pytest.fixture
def tools(tmp_path: Path) -> Tools:
    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    t._index = fake_index()
    t.verified = {3}
    return t


@pytest.fixture
def program(tmp_path: Path, tiny: bytes) -> Path:
    p = tmp_path / "tiny.smw"
    p.write_bytes(tiny)
    return p


def audit(t: Tools) -> list[dict]:
    return [json.loads(line) for line in t.audit_path.read_text("utf-8").splitlines()]


def test_instructions_are_short() -> None:
    assert len(INSTRUCTIONS.encode("utf-8")) < 2048


def test_describe_program(tools: Tools, program: Path) -> None:
    r = tools.call("describe_program", {"path": str(program)})
    assert r["ok"], r
    assert r["kind"] == "program"
    assert r["processor"] == "TestProc"
    assert len(r["revision"]) == 64
    assert r["counts"]["signals"] == 4
    assert r["counts"]["signals_by_type"] == {"digital": 2, "analog": 1, "serial": 1}
    assert r["counts"]["logic_symbols"] == 2
    assert [x["handle"] for x in r["logic_top_level"]] == [5, 6]
    assert program.read_bytes() == program.read_bytes()  # untouched
    assert audit(tools)[-1]["outcome"] == "ok"


@pytest.mark.parametrize(
    "content,name,msg",
    [
        (b"not a simpl file", "x.smw", "isn't a readable SIMPL program"),
        (b"[\r\nVersion=1\r\n]\r\n", "y.smw", "isn't a readable SIMPL program"),
        (b"", "z.txt", "only .smw"),
    ],
)
def test_describe_refuses_bad_files(tools: Tools, tmp_path: Path, content: bytes, name: str, msg: str) -> None:
    p = tmp_path / name
    p.write_bytes(content)
    r = tools.call("describe_program", {"path": str(p)})
    assert not r["ok"] and msg in r["error"]
    assert audit(tools)[-1]["outcome"] == "refused"


def test_missing_file_and_unknown_tool(tools: Tools, tmp_path: Path) -> None:
    assert "no such file" in tools.call("describe_program", {"path": str(tmp_path / "nope.smw")})["error"]
    assert not tools.call("rm_rf", {})["ok"]
    assert audit(tools)[-1]["tool"] == "rm_rf"


def test_revision_changes_with_content(tools: Tools, program: Path) -> None:
    a = tools.call("describe_program", {"path": str(program)})["revision"]
    program.write_bytes(program.read_bytes().replace(b"room_out", b"room_output"))
    assert tools.call("describe_program", {"path": str(program)})["revision"] != a


def test_library_search_and_details(tools: Tools) -> None:
    r = tools.call("find_library_symbols", {"query": "one shot"})
    assert r["ok"] and r["results"][0]["name"] == "One Shot"
    assert r["results"][0]["library_folder"] == "Timers"
    assert r["results"][0]["add_symbol_supported"] is False
    d = tools.call("library_symbol_details", {"symbol": "one shot"})
    assert [p["name"] for p in d["inputs"]] == ["trig", "hold", "clear"]
    assert d["parameters"] == [{"pin": 1, "name": "pulse_time", "type": "Time"}]
    assert d["rules"]["fixed_inputs"] == 3
    assert tools.call("library_symbol_details", {"symbol": "3"})["add_symbol_supported"] is True
    assert tools.call("library_symbol_details", {"symbol": "9999"})["kind"] == "device"
    assert not tools.call("library_symbol_details", {"symbol": "nonsense"})["ok"]
    assert not tools.call("find_library_symbols", {"query": "  "})["ok"]


def test_status_without_library(tmp_path: Path) -> None:
    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    r = t.call("simpl_agent_status", {})
    assert r["ok"] and r["symbol_library"]["found"] is False
    assert isinstance(r["simpl_windows_open"], list)


@pytest.mark.parametrize(
    "title,file,unsaved",
    [
        ("SIMPL Windows - a.smw ( C:\\x\\a.smw)", "C:\\x\\a.smw", False),
        ("SIMPL Windows - a.smw* ( C:\\x\\a.smw)", "C:\\x\\a.smw", True),
        ("SIMPL Windows", None, None),
    ],
)
def test_parse_simpl_title(title: str, file, unsaved) -> None:
    r = parse_simpl_title(title)
    assert r["file"] == file and r["unsaved_changes"] == unsaved


def test_stdio_round_trip(tmp_path: Path, program: Path) -> None:
    """Spawn the real server over stdio: initialize, list tools, call one."""
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run() -> tuple[set[str], dict, str | None]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "simpl_agent.server"],
            env={"SIMPL_AGENT_HOME": str(tmp_path / "home"), "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            res = await session.call_tool("describe_program", {"path": str(program)})
            payload = json.loads(res.content[0].text)
            # Every other tool answers over the wire too.
            calls = {
                "simpl_agent_status": {}, "folder_tree": {"path": str(program)},
                "list_folder": {"path": str(program)}, "show_symbol": {"path": str(program), "symbol": "#5"},
                "find_signals": {"path": str(program)},
                "follow_signal": {"path": str(program), "signal": "room_out"},
                "find_problems": {"path": str(program)},
                "find_library_symbols": {"query": "or"}, "library_symbol_details": {"symbol": "3"},
            }
            for name, args in calls.items():
                r = json.loads((await session.call_tool(name, args)).content[0].text)
                # No library is installed in this test's home, so library tools refuse cleanly.
                assert r["ok"] or name.startswith(("find_library", "library_")), (name, r)
            return {t.name for t in listed.tools}, payload, init.instructions

    names, payload, instructions = anyio.run(run)
    assert names == set(TOOL_NAMES) and len(names) == 10
    assert payload["ok"] and payload["processor"] == "TestProc"
    assert instructions == INSTRUCTIONS
    log = (tmp_path / "home" / "audit.jsonl").read_text("utf-8")
    assert '"describe_program"' in log


# ---------------------------------------------------------------- M2 tools
def test_folder_tree_and_list_folder(tools: Tools, program: Path) -> None:
    t = tools.call("folder_tree", {"path": str(program)})
    assert t["ok"] and t["root"] == "#4" and t["logic_symbols"] == 2 and t["folders"] == []
    f = tools.call("list_folder", {"path": str(program)})
    assert [(r["symbol"], r["simpl_number"]) for r in f["symbols"]] == [("#5", "S-1"), ("#6", "S-2")]
    assert f["symbols"][1]["comment"] == "a note"
    assert not tools.call("list_folder", {"path": str(program), "folder": "#5"})["ok"]
    assert not tools.call("list_folder", {"path": str(program), "folder": "Nowhere"})["ok"]


def test_show_symbol(tools: Tools, program: Path) -> None:
    r = tools.call("show_symbol", {"path": str(program), "symbol": "#6"})
    assert r["ok"] and r["simpl_number"] == "S-2" and r["comment"] == "a note"
    assert r["inputs"] == [{"pin": 1, "name": "i1", "signal": "room_out", "type": "digital"}]
    assert r["outputs"][0]["signal"] == "room_text$" and r["parameters"][0]["value"] == "5s"
    assert not tools.call("show_symbol", {"path": str(program), "symbol": "#99"})["ok"]


def test_find_and_follow_signals(tools: Tools, program: Path) -> None:
    r = tools.call("find_signals", {"path": str(program), "query": "room"})
    assert [s["signal"] for s in r["signals"]] == ["room_enable", "room_level", "room_out", "room_text$"]
    assert tools.call("find_signals", {"path": str(program), "signal_type": "analog"})["signals"][0]["signal"] == "room_level"
    f = tools.call("follow_signal", {"path": str(program), "signal": "ROOM_OUT"})
    assert f["driven_by"][0]["symbol"] == "#5" and f["goes_to"][0]["symbol"] == "#6"
    assert f["driven_by"][0]["folder"] == "Logic"
    assert not tools.call("follow_signal", {"path": str(program), "signal": "nope"})["ok"]


def test_find_problems_tool(tools: Tools, program: Path) -> None:
    r = tools.call("find_problems", {"path": str(program)})
    assert r["ok"] and r["counts"] == {"warning": 2, "notice": 1}
    assert {p["code"] for p in r["problems"]} == {"LGCMCVT102", "LGCMCVT103"}
