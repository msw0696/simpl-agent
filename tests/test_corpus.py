"""Opt-in tests over the real corpus. Skipped when the corpus isn't on this PC.

Run them with:  pytest -m corpus
"""
from __future__ import annotations

import pytest

from simpl_agent.catalog.symlib import DEFAULT_SYMLIB, load_symlib
from simpl_agent.corpus import default_roots, iter_files
from simpl_agent.smw import rawfile
from simpl_agent.smw.model import load

pytestmark = pytest.mark.corpus

ROOTS = default_roots()
needs_corpus = pytest.mark.skipif(not ROOTS, reason="no SIMPL corpus on this PC")


@needs_corpus
def test_every_corpus_file_roundtrips_and_loads() -> None:
    failures = []
    n = 0
    for path in iter_files(*ROOTS):
        data = path.read_bytes()
        raw = rawfile.parse(data)
        if raw.to_bytes() != data:
            failures.append(f"roundtrip: {path}")
        try:
            load(raw)
        except Exception as e:  # noqa: BLE001
            failures.append(f"load: {path}: {e}")
        n += 1
    assert n > 0
    assert not failures, failures[:10]


@pytest.mark.skipif(not DEFAULT_SYMLIB.exists(), reason="SIMPL not installed")
def test_symlib_loads() -> None:
    lib = load_symlib()
    assert len(lib.symbols) > 1000
    buf = lib.by_name["buffer"][0]
    assert buf.shares_outputs


@needs_corpus
@pytest.mark.skipif(not DEFAULT_SYMLIB.exists(), reason="SIMPL not installed")
def test_simple_symbols_regenerate_exactly() -> None:
    """Every simple logic symbol saved by SIMPL 4.3x rebuilds byte-for-byte from the model.

    Window-state flags (OpF, PropF, HandF) are ignored: new symbols don't have them.
    """
    from simpl_agent.smw.edit import simple_symbol_lines

    lib = load_symlib()
    ui = {"OpF", "PropF", "HandF"}
    checked = 0
    bad = []
    for path in iter_files(*ROOTS):
        raw = rawfile.read(path)
        sig = raw.first("FSgntr")
        if sig is None or not (sig.get("SavedBy") or "").startswith("SMW4.3"):
            continue
        p = load(raw)
        for s in p.symbols.values():
            ls = lib.get(s.code)
            f = ls.fields if ls else {}
            if not ls or f.get("Smpl-C") != "1" or f.get("DeviceCode", "0") != "0" or any(
                k.startswith(("InputList2", "OutputList2", "InputList3", "OutputList3")) for k in f
            ):
                continue
            r = s.record
            mi, mo, mp = (int(r.get(k) or 0) for k in ("mI", "mO", "mP"))
            gen = simple_symbol_lines(
                handle=s.handle, code=s.code, name=ls.name,
                # SmVr is per symbol (older symbols keep an older value or none);
                # new symbols get the header's SmVr, as freshly placed ones do.
                smvr=r.get("SmVr"), parent=s.parent,
                inputs=[s.inputs.get(i) for i in range(1, mi + 1)],
                outputs=[s.outputs.get(i) for i in range(1, mo + 1)],
                params=[s.params.get(i, "") for i in range(1, mp + 1)],
                comment=[v for k, v in r.lines if k and k.startswith("Cmn")],
            )
            checked += 1
            if gen != [kv for kv in r.lines if kv[0] not in ui]:
                bad.append(f"{path.name} Sm#{s.handle}")
    assert checked > 500
    assert not bad, bad[:10]
