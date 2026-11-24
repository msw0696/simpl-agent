from __future__ import annotations

import pytest

from simpl_agent.smw import rawfile
from simpl_agent.smw.model import load, parse_handles


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7", [7]),
        ("7.10", [7, 8, 9, 10]),
        ("515,551.553", [515, 551, 552, 553]),
        ("", []),
        (None, []),
    ],
)
def test_parse_handles(text, expected) -> None:
    assert parse_handles(text) == expected


def test_load_tiny(tiny: bytes) -> None:
    p = load(rawfile.parse(tiny))
    assert p.kind == "SimplWindow"
    assert p.builtin_signals == {"0": 1, "1": 2, "Local": 3}
    assert p.signals[1].name == "0" and p.signals[1].record is None
    assert p.signals[5].type == "analog"
    assert p.signals[7].type == "serial"
    assert p.signals[6].type == "digital"

    logic = p.symbols[4]
    assert logic.children == [5, 6]
    buf = p.symbols[5]
    assert buf.parent == 4
    assert buf.inputs == {1: 4, 2: 5}
    assert buf.outputs == {1: 6}
    pulse = p.symbols[6]
    assert pulse.params == {1: "5s"}
    assert pulse.comment == "a note"

    assert p.devices[3] is p.devices[4]  # one record covering 3.4
    assert p.devices[2].children == [3, 4]
    assert p.signal_name(99) == "#99?"


def test_sparse_pins(tiny: bytes) -> None:
    text = tiny.replace(b"I1=4\r\nI2=5", b"I2=5")
    p = load(rawfile.parse(text))
    assert p.symbols[5].inputs == {2: 5}  # pin 1 unconnected
