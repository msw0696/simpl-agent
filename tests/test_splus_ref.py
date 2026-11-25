from __future__ import annotations

from pathlib import Path

import pytest

from simpl_agent.splus_ref import SPLUS_CHM, Reference, Topic, html_to_text

# Invented pages shaped like the installed help's (no Crestron text in the repo).
FUNC = """<html><head><title>FOO</title><style>p{}</style></head><body>
<h1>Foo</h1><p>Name:</p><p>Foo</p><p>Syntax:</p><p>INTEGER Foo(STRING&nbsp;A);</p>
<p>Description:</p><p>Counts the widgets in A.</p></body></html>"""
ERR = """<html><head><title>Compiler Error 1234</title></head><body><h1>Compiler Error 1234</h1>
<p>syntax error: '&lt;identifier&gt;' is broken</p><p>The widget was declared twice.</p>
<p>NOTE: Scope is explained elsewhere.</p><p>Rename one of them.</p>
<p>The following are examples of this error:</p><p>INTEGER w;</p></body></html>"""


def ref() -> Reference:
    topics = []
    for path, page, cat in (("Funcs/FOO.htm", FUNC, "Funcs"), ("Errs/Compiler_Error_1234.htm", ERR, "Errs"),
                            ("Funcs/FooBar.htm", FUNC.replace("FOO", "FooBar"), "Funcs")):
        title, text = html_to_text(page)
        topics.append(Topic(path=path, title=title, category=cat, text=text))
    return Reference(topics)


def test_html_to_text() -> None:
    title, text = html_to_text(FUNC.replace("\n", "\r\n"))
    assert title == "FOO" and "\r" not in text and "p{}" not in text
    assert "INTEGER Foo(STRING A);" in text and "\n\n\n" not in text


def test_search_exact_then_words() -> None:
    r = ref()
    assert [t.title for t in r.search("foo")][:2] == ["FOO", "FooBar"]
    assert [t.title for t in r.search("1234")] == ["Compiler Error 1234"]
    assert r.search("widgets")[0].title in ("FOO", "FooBar")
    assert r.search("nothing like this") == []


def test_explain_skips_message_notes_and_examples() -> None:
    assert ref().explain(1234) == "The widget was declared twice. Rename one of them."
    assert ref().explain(9999) is None


@pytest.mark.skipif(not SPLUS_CHM.exists(), reason="SIMPL+ Language Reference not installed")
def test_installed_reference(tmp_path: Path) -> None:
    r = Reference.load(tmp_path)
    assert len(r.topics) > 400
    assert r.search("Find")[0].title.lower() == "find"
    assert r.explain(1001)
    assert len(Reference.load(tmp_path).topics) == len(r.topics)  # from the cache
