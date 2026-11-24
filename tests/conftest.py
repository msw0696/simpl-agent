from __future__ import annotations

import pytest

# A tiny hand-written program in SIMPL's shape. Every name and value is
# invented for tests; nothing is copied from Crestron or third-party files.
TINY_LINES = [
    "[", "Version=1", "]",
    "[", "ObjTp=FSgntr", "Sgntr=SimplWindow", "RelVrs=9.99.01", "SavedBy=TEST9.99", "]",
    "[", "ObjTp=Hd", "CnC=9001", "CnH=2", "S0Nd=1", "S1Nd=2", "SLNd=3", "PrNm=tiny.smw", "]",
    "[", "ObjTp=Dv", "Nm=TestProc", "H=2", "PrH=1", "DvC=9001", "Ad=00", "mC=2", "C1=3", "C2=4", "]",
    "[", "ObjTp=Dv", "Nm=EmptySlot", "H=3.4", "PrH=2", "Ad=01,02", "]",
    "[", "ObjTp=Sm", "H=1", "SmC=157", "Nm=Central", "CF=2", "]",
    "[", "ObjTp=Sm", "H=4", "SmC=156", "Nm=Logic", "CF=2", "mC=2", "C1=5", "C2=6", "]",
    "[", "ObjTp=Sm", "H=5", "SmC=20", "PrH=4", "mI=2", "I1=4", "I2=5", "mO=1", "tO=1", "O1=6", "]",
    "[", "ObjTp=Sm", "H=6", "SmC=21", "PrH=4", "Cmn1=a note", "mI=1", "I1=6", "mO=1", "tO=1", "O1=7",
    "mP=1", "P1=5s", "]",
    "[", "ObjTp=Sg", "H=4", "Nm=room_enable", "]",
    "[", "ObjTp=Sg", "H=5", "Nm=room_level", "SgTp=2", "]",
    "[", "ObjTp=Sg", "H=6", "Nm=room_out", "]",
    "[", "ObjTp=Sg", "H=7", "Nm=room_text$", "SgTp=4", "]",
]


def tiny_bytes(newline: str = "\r\n", final: bool = True) -> bytes:
    text = newline.join(TINY_LINES) + (newline if final else "")
    return text.encode("latin-1")


@pytest.fixture
def tiny() -> bytes:
    return tiny_bytes()
