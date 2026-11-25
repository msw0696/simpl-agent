"""M8: saved SIMPL Debugger traces. Every trace line here is invented in the layout taken from
the Debugger's own format strings; no real log has been seen yet."""
from __future__ import annotations

from pathlib import Path

from simpl_agent.trace import parse_trace, read_trace_file


def kinds(res):
    return [(e.kind, e.time, e.signal or e.event_type or e.message, e.value) for e in res["entries"]]


def test_line_shapes() -> None:
    res = parse_trace([
        "12:55:25 - 01-16-2015: room_enable -> 1",
        "12:55:26 - 01-16-2015: room_level -> 0400h",
        "12:55:27 - 01-16-2015: room_text$ -> POWR1\\x0D",
        "12:55:28 - 01-16-2015: [SIMPL+ Trace] : got reply 7",
        "12:55:29 - 01-16-2015: *** Timestamp 3",
        "12:55:30 - 01-16-2015: room_empty$ -> ",
        "this is not a trace line",
    ])
    assert kinds(res) == [
        ("signal", "12:55:25 - 01-16-2015", "room_enable", "1"),
        ("signal", "12:55:26 - 01-16-2015", "room_level", "0400h"),
        ("signal", "12:55:27 - 01-16-2015", "room_text$", "POWR1\\x0D"),
        ("event", "12:55:28 - 01-16-2015", "SIMPL+ Trace", None),
        ("timestamp", "12:55:29 - 01-16-2015", "Timestamp 3", None),
        ("signal", "12:55:30 - 01-16-2015", "room_empty$", ""),
    ]
    assert res["entries"][3].message == "got reply 7"
    assert res["unparsed"] == [(7, "this is not a trace line")]
    assert res["time_formats"] == {"time of day": 6}


def test_time_formats_and_relative_times() -> None:
    res = parse_trace(["00:10:54.019: a -> 0", "1 day, 00:00:01.500: a -> 1", "250 ms: a -> 0", "750 ms: a -> 1",
                       "00:10:58\t1\tS-2_out", "00:10:58.028\t1\tS-2_out"])
    assert [e.seconds for e in res["entries"]] == [654.019, 86401.5, 86401.75, 86402.5, 658, 658.028]
    assert res["entries"][-1].signal == "S-2_out"  # the Trace window's copy: time, value, name
    assert set(res["time_formats"]) == {"time with milliseconds", "days and time",
                                        "milliseconds since previous event", "time (copied)",
                                        "time with milliseconds (copied)"}


def test_arrow_inside_names_and_values() -> None:
    res = parse_trace(["10:00:00.000: a -> b -> c"])
    assert (res["entries"][0].signal, res["entries"][0].value) == ("a", "b -> c")
    res = parse_trace(["10:00:00.000: a -> b -> c"], names={"a -> b"})
    assert (res["entries"][0].signal, res["entries"][0].value) == ("a -> b", "c")


def test_read_trace_tool(tmp_path: Path, tiny: bytes) -> None:
    from simpl_agent.server import Tools

    prog = tmp_path / "tiny.smw"
    prog.write_bytes(tiny)
    log = tmp_path / "trace.txt"
    log.write_bytes("\r\n".join([
        "08:00:00.000: room_enable -> 0",
        "08:00:01.000: room_level -> 50.000%",
        "08:00:02.000: room_enable -> 1",
        "08:00:02.010: room_out -> 1",
        "08:00:03.000: ::module_sig -> 1",
        "08:00:04.000: old_name -> 1",
        "08:00:05.000: [User Stimulus] : User set room_enable to 0",
        "",
    ]).encode("cp1252"))
    t = Tools(home=tmp_path / "home")
    t.windows = lambda: []
    r = t.call("read_trace", {"path": str(log), "program": str(prog), "signal": "room_out"})
    assert r["ok"], r
    assert r["counts"] == {"signal changes": 6, "events": 1, "timestamps": 0, "unparsed lines": 0}
    assert r["signals"][0] == {"signal": "room_enable", "changes": 2, "first": "08:00:00.000",
                               "last": "08:00:02.000", "last_value": "1", "type": "digital"}
    assert r["not_in_program"] == ["old_name"] and "inside modules" in r["note"]
    (change,) = r["what_drove"]["changes"]
    assert change["value"] == "1" and change["time"] == "08:00:02.010"
    (drv,) = change["drivers"]
    assert drv["symbol"] == "#5"
    assert [(i["signal"], i["last_seen"]) for i in drv["inputs"]] == [("room_enable", "1"), ("room_level", "50.000%")]
    q = t.call("read_trace", {"path": str(log), "query": "stimulus"})
    assert [e.get("event") for e in q["entries"]] == ["User Stimulus"]
    audit = (tmp_path / "home" / "audit.jsonl").read_text("utf-8")
    assert "trace.txt" in audit and "50.000%" not in audit and "User set" not in audit  # paths, not trace text


def test_read_trace_file_limits(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        read_trace_file(tmp_path / "missing.txt")
