"""Parameter values: SIMPL's escapes in strings (help: Compiler Errors 105-107, 125) and the forms of
numeric values. The corpus test checks that no value in the public programs is flagged."""
from __future__ import annotations

import pytest

from simpl_agent import analysis as an
from simpl_agent.smw import rawfile
from simpl_agent.smw.edit import EditError, Editor
from simpl_agent.smw.model import load
from test_edit import ed, fake_library  # noqa: F401 - pytest fixture


@pytest.mark.parametrize("value", [
    "PWR ON\\x0D", "\\x02POWR\\x03", "Command 1\\r\\n", "\\\\USER\\\\config.json", "\\a\\b\\f\\t\\v",
    '"GF Party Room"', "CS 00033 00000\\x0d", "", "plain text",
])
def test_good_string_values(value: str) -> None:
    assert an.parameter_value_issue(value, "string") is None


@pytest.mark.parametrize(("value", "code"), [
    ("PWR\\x0", "LGCMCVT105"),       # ends before two hex digits
    ("PWR\\x", "LGCMCVT105"),
    ("\\x5\\x6", "LGCMCVT125"),      # the help's own example
    ("A\\xG1", "LGCMCVT125"),
    ("path\\", "LGCMCVT107"),        # lone backslash at the end
    ("\\q", "LGCMCVT106"),           # the help's invalid escape
    ("\\user\\", "LGCMCVT236"),      # seen in SIMPL 4.32 with a drop-down value
])
def test_bad_string_values(value: str, code: str) -> None:
    issue = an.parameter_value_issue(value, "string")
    assert issue is not None and issue[0] == code


@pytest.mark.parametrize(("value", "ptype"), [
    ("10d", "constant"), ("-5d", "constant"), ("0", "constant"), ("1Fh", "constant"), ("'2'", "constant"),
    ("99999d", "constant"), ("50%", "percent"), ("33.3%", "percent"), ("2s", "time"), (".01s", "time"),
    ("0.05s", "time"), ("1t", "time"), ("07.50.00.00s", "time"), ("5.00.00s", "time"), ("655.35s", "time"),
    ("1S", "time"), ("013Ch", "hexaddress"), ("", "time"),
])
def test_good_numeric_values(value: str, ptype: str) -> None:
    assert an.parameter_value_issue(value, ptype) is None


@pytest.mark.parametrize(("value", "ptype"), [
    ("2 seconds", "time"), ("5 sec", "time"), ("fifty", "percent"), ("10 d", "constant"), ("1.2.3", "time"),
])
def test_bad_numeric_values(value: str, ptype: str) -> None:
    issue = an.parameter_value_issue(value, ptype)
    assert issue is not None and issue[0] == "SA-PARAM-FORM"


def test_read_only_device_text_is_not_checked() -> None:
    assert an.parameter_value_issue("C:\\odd\\path", "ui_ro_string") is None


def test_variable_parameters_take_the_first_type() -> None:
    lib = fake_library()
    assert an.parameter_type(lib.get(89), 1) == "string"
    assert an.parameter_type(lib.get(89), 5) == "string"
    assert an.parameter_type(None, 1) == ""


def test_add_symbol_refuses_bad_values(ed: Editor) -> None:  # noqa: F811
    with pytest.raises(EditError, match="LGCMCVT125"):
        ed.add_symbol(89, "Logic", inputs=["go"], outputs=["tx$"], params=["\\x5\\x6"], new_signal_type="serial")
    with pytest.raises(EditError, match="SA-PARAM-FORM"):
        ed.add_symbol(9, "Logic", inputs=["trig", "0", "0"], outputs=["p", "pn"], params=["2 seconds"])
    h = ed.add_symbol(89, "Logic", inputs=["go"], outputs=["tx$"], params=["PWR\\x0D"])
    assert ed.prog.symbols[h].params == {1: "PWR\\x0D"}


def test_set_parameter_refuses_bad_values(ed: Editor) -> None:  # noqa: F811
    h = ed.add_symbol(9, "Logic", inputs=["trig", "0", "0"], outputs=["p", "pn"], params=["2s"])
    with pytest.raises(EditError, match="pulse_time"):
        ed.set_parameter(f"#{h}", "P1", "2 sec")
    ed.set_parameter(f"#{h}", "P1", "0.5s")
    assert ed.prog.symbols[h].params == {1: "0.5s"}


def test_find_problems_reports_existing_bad_values(ed: Editor) -> None:  # noqa: F811
    h = ed.add_symbol(89, "Logic", inputs=["go"], outputs=["tx$"], params=["ok"])
    ed.prog.symbols[h].record.set("P1", "C:\\data")  # as if edited elsewhere; \d isn't an escape
    probs = an.find_problems(load(rawfile.parse(ed.raw.to_bytes())), fake_library())
    hits = [p for p in probs if p.code == "LGCMCVT106"]
    assert len(hits) == 1 and hits[0].symbols == [h] and hits[0].severity == "notice"


@pytest.mark.corpus
def test_no_corpus_parameter_is_flagged() -> None:
    from simpl_agent.catalog.symlib import DEFAULT_SYMLIB, load_symlib
    from simpl_agent.corpus import default_roots, iter_files

    roots = default_roots()
    if not roots or not DEFAULT_SYMLIB.exists():
        pytest.skip("needs the corpus and SIMPL's library")
    lib = load_symlib()
    flagged, n = [], 0
    for p in iter_files(*roots):
        if p.suffix.lower() != ".smw":
            continue
        n += 1
        prog = load(rawfile.parse(p.read_bytes()))
        flagged += [(p.name, x.code, x.message) for x in an.parameter_problems(prog, lib, p)]
    assert n > 300
    assert not flagged, flagged[:10]
