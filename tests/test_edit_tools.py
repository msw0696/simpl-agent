"""apply_edits and history, end to end on a temp copy of the tiny program."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from simpl_agent.server import Tools
from test_server import fake_index


@pytest.fixture
def setup(tmp_path: Path, tiny: bytes):
    data = tiny.replace(b"RelVrs=9.99.01", b"RelVrs=4.32.02")  # a "SIMPL 4.3x" file
    p = tmp_path / "job" / "room.smw"
    p.parent.mkdir()
    p.write_bytes(data)
    t = Tools(library_path=tmp_path / "missing.tio", home=tmp_path / "home")
    t._index = fake_index()
    t.verified = {3, 9}
    t.windows = lambda: []
    return t, p


def rev(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def call(t: Tools, tool: str, **kw):
    return t.call(tool, kw)


def test_apply_edits_writes_backs_up_and_records(setup) -> None:
    t, p = setup
    before = p.read_bytes()
    r = call(t, "apply_edits", path=str(p), revision=rev(p), summary="Room A any-on OR",
             edits=[{"op": "add_folder", "name": "Room A"},
                    {"op": "add_symbol", "symbol": "OR", "folder": "Room A",
                     "inputs": ["room_enable", "room_out"], "outputs": ["room_any_on"]},
                    {"op": "rename_signal", "signal": "room_text$", "new_name": "room_status$"}])
    assert r["ok"], r
    assert r["written"] and r["history_id"] == 1 and r["revision"] == rev(p)
    assert len(r["changes"]) == 4  # folder, new signal, OR, rename
    assert [x["code"] for x in r["new_problems"]] == ["LGCMCVT103"]  # room_any_on goes nowhere yet
    backups = list((p.parent / ".simpl-agent" / "backups").iterdir())
    assert len(backups) == 1 and backups[0].read_bytes() == before
    h = call(t, "edit_history", path=str(p))
    assert h["total"] == 1 and h["entries"][0]["summary"] == "Room A any-on OR"
    assert h["changed_outside_simpl_agent"] is False


def test_apply_edits_is_all_or_nothing(setup) -> None:
    t, p = setup
    before = p.read_bytes()
    r = call(t, "apply_edits", path=str(p), revision=rev(p), summary="two things",
             edits=[{"op": "add_folder", "name": "Room A"},
                    {"op": "connect", "symbol": "#6", "pin": "O1", "signal": "room_out"}])  # second driver
    assert not r["ok"] and "edit 2 (connect) refused, nothing was changed" in r["error"]
    assert p.read_bytes() == before
    assert not (p.parent / ".simpl-agent").exists()


@pytest.mark.parametrize("bad,msg", [
    ({"op": "explode"}, "'op' must be one of"),
    ({"op": "connect", "symbol": "#5"}, "missing ['pin']"),
    ({"op": "add_folder", "name": "x", "allow_second_driver": True}, "unknown ['allow_second_driver']"),
])
def test_closed_op_schema(setup, bad, msg) -> None:
    t, p = setup
    r = call(t, "apply_edits", path=str(p), revision=rev(p), summary="s", edits=[bad])
    assert not r["ok"] and msg in r["error"]


def test_gate_refusals(setup, tmp_path: Path) -> None:
    t, p = setup
    ok = {"op": "set_comment", "symbol": "#5", "text": "hi"}
    assert "revision mismatch" in call(t, "apply_edits", path=str(p), revision="x" * 64, summary="s", edits=[ok])["error"]
    assert "one-line summary" in call(t, "apply_edits", path=str(p), revision=rev(p), summary="", edits=[ok])["error"]
    # Open in SIMPL: refused until the user has saved there and Claude says so.
    t.windows = lambda: [f"SIMPL Windows - room.smw ( {p})"]
    assert "Ask the user to save it in SIMPL" in call(
        t, "apply_edits", path=str(p), revision=rev(p), summary="s", edits=[ok])["error"]
    assert call(t, "apply_edits", path=str(p), revision=rev(p), summary="s", edits=[ok], dry_run=True)["ok"]
    t.windows = lambda: []
    lf = tmp_path / "job" / "lf.smw"
    lf.write_bytes(p.read_bytes().replace(b"\r\n", b"\n"))
    assert "CRLF" in call(t, "apply_edits", path=str(lf), revision=rev(lf), summary="s", edits=[ok])["error"]
    old = tmp_path / "job" / "old.smw"
    old.write_bytes(p.read_bytes().replace(b"RelVrs=4.32.02", b"RelVrs=4.03.01"))
    add = {"op": "add_folder", "name": "X"}
    assert "only proven for files saved by SIMPL 4.3x" in call(
        t, "apply_edits", path=str(old), revision=rev(old), summary="s", edits=[add])["error"]
    # Non-creating ops are fine on older files.
    assert call(t, "apply_edits", path=str(old), revision=rev(old), summary="s", edits=[ok])["ok"]


def test_dry_run_writes_nothing(setup) -> None:
    t, p = setup
    before = p.read_bytes()
    r = call(t, "apply_edits", path=str(p), revision=rev(p), summary="s", dry_run=True,
             edits=[{"op": "set_comment", "symbol": "#5", "text": "hi"}])
    assert r["ok"] and r["written"] is False and p.read_bytes() == before


def test_open_in_simpl_note(setup) -> None:
    t, p = setup
    t.windows = lambda: [f"SIMPL Windows - room.smw ( {p})"]
    r = call(t, "apply_edits", path=str(p), revision=rev(p), summary="s", user_confirmed_saved=True,
             edits=[{"op": "set_comment", "symbol": "#5", "text": "hi"}])
    assert r["ok"] and "offer to reload" in r["next_step"]


def test_undo_twice_back_to_start(setup) -> None:
    t, p = setup
    original = p.read_bytes()
    call(t, "apply_edits", path=str(p), revision=rev(p), summary="one",
         edits=[{"op": "set_comment", "symbol": "#5", "text": "one"}])
    after_one = p.read_bytes()
    call(t, "apply_edits", path=str(p), revision=rev(p), summary="two",
         edits=[{"op": "set_parameter", "symbol": "#6", "pin": "P1", "value": "9s"}])
    u = call(t, "undo_last_edit", path=str(p), revision=rev(p))
    assert u["ok"] and u["undid"]["summary"] == "two" and p.read_bytes() == after_one
    u = call(t, "undo_last_edit", path=str(p), revision=rev(p))
    assert u["ok"] and u["undid"]["summary"] == "one" and p.read_bytes() == original
    assert not call(t, "undo_last_edit", path=str(p), revision=rev(p))["ok"]  # nothing left


def test_undo_refuses_after_outside_change(setup) -> None:
    t, p = setup
    call(t, "apply_edits", path=str(p), revision=rev(p), summary="one",
         edits=[{"op": "set_comment", "symbol": "#5", "text": "one"}])
    p.write_bytes(p.read_bytes().replace(b"Nm=room_level", b"Nm=room_lvl"))  # "saved in SIMPL"
    r = call(t, "undo_last_edit", path=str(p), revision=rev(p))
    assert not r["ok"] and "restore_version" in r["error"]
    assert call(t, "edit_history", path=str(p))["changed_outside_simpl_agent"] is True


def test_restore_previews_then_restores(setup) -> None:
    t, p = setup
    original = p.read_bytes()
    for i in range(3):
        call(t, "apply_edits", path=str(p), revision=rev(p), summary=f"edit {i}",
             edits=[{"op": "set_comment", "symbol": "#5", "text": f"n{i}"}])
    p.write_bytes(p.read_bytes().replace(b"Nm=room_level", b"Nm=room_lvl"))  # outside change
    preview = call(t, "restore_version", path=str(p), revision=rev(p), before_entry="start")
    assert preview["ok"] and preview["written"] is False
    assert [x["id"] for x in preview["would_undo"]] == [1, 2, 3]
    assert preview["also_loses_changes_made_in_simpl"] is True
    done = call(t, "restore_version", path=str(p), revision=rev(p), before_entry="start", confirm=True)
    assert done["ok"] and done["written"] and p.read_bytes() == original


def test_tampered_backup_is_refused(setup) -> None:
    t, p = setup
    call(t, "apply_edits", path=str(p), revision=rev(p), summary="one",
         edits=[{"op": "set_comment", "symbol": "#5", "text": "one"}])
    b = next((p.parent / ".simpl-agent" / "backups").iterdir())
    b.write_bytes(b.read_bytes() + b"x")
    r = call(t, "undo_last_edit", path=str(p), revision=rev(p))
    assert not r["ok"] and "doesn't match" in r["error"]


def test_wait_for_simpl_save(setup) -> None:
    t, p = setup
    r = call(t, "wait_for_simpl_save", path=str(p), revision=rev(p), timeout_s=1)
    assert r["ok"] and r["saved"] is False
    old = rev(p)
    p.write_bytes(p.read_bytes() + b"")
    p.write_bytes(p.read_bytes().replace(b"Nm=room_level", b"Nm=room_lvl"))
    r = call(t, "wait_for_simpl_save", path=str(p), revision=old, timeout_s=1)
    assert r["saved"] is True and r["revision"] == rev(p)
