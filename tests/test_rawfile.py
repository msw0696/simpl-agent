from __future__ import annotations

import pytest

from conftest import tiny_bytes
from simpl_agent.smw import rawfile


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
@pytest.mark.parametrize("final", [True, False])
def test_roundtrip_exact(newline: str, final: bool) -> None:
    data = tiny_bytes(newline, final)
    raw = rawfile.parse(data)
    assert raw.newline == newline
    assert raw.final_newline is final
    assert raw.to_bytes() == data


def test_records_and_types(tiny: bytes) -> None:
    raw = rawfile.parse(tiny)
    types = [r.type for r in raw.records]
    assert types[0] is None  # the leading Version record has no ObjTp
    assert types.count("Sg") == 4
    assert raw.first("Hd").get("CnH") == "2"


@pytest.mark.parametrize(
    "text",
    [
        "\r\n[\r\nVersion=1\r\n]\r\n",  # stray blank line before the first record
        "[\r\nObjTp=Sg\r\nno equals sign here\r\n]\r\n",  # raw line inside a record
        "[\r\nObjTp=Sg\r\nH=4\r\n",  # unclosed final record
        "[\r\nObjTp=Symbol\r\nA=1\r\nA=2\r\n]\r\n",  # repeated key
        "[\r\nObjTp=Sm\r\nP1=a=b\r\nP2=\r\n]\r\n",  # '=' in a value, empty value
        "[\r\nX=caf\xe9\r\n]\r\n",  # latin-1 byte
        "[\r\nA=1\n]\r\n",  # mixed line endings -> kept verbatim
        "",
    ],
)
def test_odd_inputs_roundtrip(text: str) -> None:
    data = text.encode("latin-1")
    assert rawfile.parse(data).to_bytes() == data


def test_value_with_equals_is_split_once() -> None:
    raw = rawfile.parse(b"[\r\nObjTp=Sm\r\nP1=a=b\r\n]\r\n")
    assert raw.first("Sm").get("P1") == "a=b"


def test_repeated_keys_kept_in_order() -> None:
    rec = rawfile.parse(b"[\r\nA=1\r\nB=x\r\nA=2\r\n]\r\n").items[0]
    assert rec.get_all("A") == ["1", "2"]
    assert rec.get("A") == "1"


def test_set_replaces_in_place(tiny: bytes) -> None:
    raw = rawfile.parse(tiny)
    sg = next(r for r in raw.of_type("Sg") if r.get("H") == "6")
    sg.set("Nm", "room_output")
    out = raw.to_bytes()
    assert b"Nm=room_output\r\n" in out
    # Only that one line changed.
    assert out.replace(b"room_output", b"room_out") == tiny


def test_set_inserts_after_key_and_delete() -> None:
    rec = rawfile.parse(b"[\r\nObjTp=Sg\r\nH=4\r\nNm=x\r\n]\r\n").items[0]
    rec.set("SgTp", "2", after="Nm")
    assert rec.keys() == ["ObjTp", "H", "Nm", "SgTp"]
    rec.set("Zz", "1", after="missing")
    assert rec.keys()[-1] == "Zz"
    assert rec.delete("Zz") == 1
    assert "Zz" not in rec
