"""Signals through placed macros, as SIMPL's compiler sees them (one circuit with the program).
The macro and program are invented; the rules come from a SIMPL 4.32 compile of a public program
(docs/format.md "Signals inside macros")."""
from __future__ import annotations

from pathlib import Path

from simpl_agent import analysis as an
from simpl_agent.smw import rawfile
from simpl_agent.smw.model import load


def rec(**kv) -> str:
    return "[\r\n" + "".join(f"{k}={v}\r\n" for k, v in kv.items()) + "]\r\n"


HEAD = rec(Version=1) + rec(ObjTp="FSgntr", Sgntr="UserMacro") + rec(ObjTp="Hd", S0Nd=1, S1Nd=2, SLNd=3)

# Inside the macro: in_a -> OR -> mid -> OR -> out_a; in_b goes nowhere; out_b is read inside but
# never driven; lonely_in is read but never driven; lonely_out is driven but never read; only_forced
# sits on a Serial Force alone.
UMC = (HEAD
       + rec(ObjTp="Symbol", Name="Relay", InputCue1="A", InputCue2="B", OutputCue1="A_Out", OutputCue2="B_Out")
       + rec(ObjTp="Sm", H=4, SmC=156, Nm="Logic", mC=5, C1=5, C2=6, C3=7, C4=8, C5=9)
       + rec(ObjTp="Sm", H=5, SmC=55, Nm="Argument Definition", PrH=4, mI=2, I1=10, I2=11, mO=2, tO=2, O1=12, O2=13)
       + rec(ObjTp="Sm", H=6, SmC=3, PrH=4, mI=1, I1=10, mO=1, tO=1, O1=14)
       + rec(ObjTp="Sm", H=7, SmC=3, PrH=4, mI=1, I1=14, mO=1, tO=1, O1=12)
       + rec(ObjTp="Sm", H=8, SmC=3, PrH=4, mI=2, I1=15, I2=13, mO=1, tO=1, O1=16)
       + rec(ObjTp="Sm", H=9, SmC=470, PrH=4, mI=1, I1=17)
       + "".join(rec(ObjTp="Sg", H=h, Nm=n) for h, n in (
           (10, "in_a"), (11, "in_b"), (12, "out_a"), (13, "out_b"), (14, "mid"), (15, "lonely_in"),
           (16, "lonely_out"), (17, "only_forced"))))


def program(tmp_path: Path, second_copy: bool = True) -> Path:
    kids = {"mC": 2, "C1": 5, "C2": 6} if second_copy else {"mC": 1, "C1": 5}
    smw = (rec(Version=1) + rec(ObjTp="FSgntr", Sgntr="SimplWindow") + rec(ObjTp="Hd", S0Nd=1, S1Nd=2, SLNd=3)
           + rec(ObjTp="Sm", H=4, SmC=156, Nm="Logic", **kids)
           + rec(ObjTp="Sm", H=5, SmC=155, Nm="Relay.umc", PrH=4, n1I=2, mI=2, I1=7, I2=8, n1O=2, mO=2, tO=2,
                 O1=9, O2=10)
           + (rec(ObjTp="Sm", H=6, SmC=155, Nm="Relay.umc", PrH=4, n1I=2, mI=2, n1O=2, mO=2, tO=2)
              if second_copy else "")
           + "".join(rec(ObjTp="Sg", H=h, Nm=n) for h, n in (
               (7, "top_a"), (8, "top_b"), (9, "top_out_a"), (10, "top_out_b"))))
    (tmp_path / "Relay.umc").write_bytes(UMC.encode("latin-1"))
    p = tmp_path / "job.smw"
    p.write_bytes(smw.encode("latin-1"))
    return p


def found(p: Path) -> set[tuple[str, str]]:
    prog = load(rawfile.read(p))
    return {(x.code, x.message) for x in an.find_problems(prog, None, p)
            if x.code in ("LGCMCVT102", "LGCMCVT103", "LGCMCVT126", "LGCMCVT127")}


def test_signals_are_judged_through_the_macro(tmp_path: Path) -> None:
    p = program(tmp_path)
    umc = tmp_path / "Relay.umc"
    assert found(p) == {
        # Read inside the macro, driven by nothing: reported once, by the outer name.
        ("LGCMCVT102", 'Signal "top_a" has no driving source.'),
        ("LGCMCVT102", 'Signal "top_out_b" has no driving source.'),
        # Driven inside, read by nothing outside.
        ("LGCMCVT103", 'Signal "top_out_a" has no destination.'),
        # Wholly inside: once per placed copy, with the copy's symbol number and file.
        ("LGCMCVT126", f'Signal "lonely_in" in S-1 (Module name {umc}) has no driving source.'),
        ("LGCMCVT127", f'Signal "lonely_out" in S-1 (Module name {umc}) has no destination.'),
        ("LGCMCVT126", f'Signal "lonely_in" in S-2 (Module name {umc}) has no driving source.'),
        ("LGCMCVT127", f'Signal "lonely_out" in S-2 (Module name {umc}) has no destination.'),
        # The second copy's B_Out isn't wired, so out_b there is read inside and driven by nothing.
        ("LGCMCVT126", f'Signal "out_b" in S-2 (Module name {umc}) has no driving source.'),
    }
    # top_b goes into the macro and nothing reads it there: no message (nothing reads or drives it).
    # The second copy's unwired input (held at 0) gives no message, and only_forced (on a Serial
    # Force alone) isn't a destination.


def test_without_the_macro_file_its_pins_count(tmp_path: Path) -> None:
    p = program(tmp_path, second_copy=False)
    (tmp_path / "Relay.umc").unlink()
    assert found(p) == {("LGCMCVT102", 'Signal "top_a" has no driving source.'),
                        ("LGCMCVT102", 'Signal "top_b" has no driving source.'),
                        ("LGCMCVT103", 'Signal "top_out_a" has no destination.'),
                        ("LGCMCVT103", 'Signal "top_out_b" has no destination.')}


def test_a_macro_file_on_its_own_counts_its_pins_as_outside(tmp_path: Path) -> None:
    program(tmp_path)
    umc = tmp_path / "Relay.umc"
    assert found(umc) == {("LGCMCVT102", 'Signal "lonely_in" has no driving source.'),
                          ("LGCMCVT103", 'Signal "lonely_out" has no destination.'),
                          ("LGCMCVT102", 'Signal "out_b" has no driving source.')}
