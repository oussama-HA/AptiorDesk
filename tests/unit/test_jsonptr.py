import pytest

from aptiordesk.core import jsonptr

DOC = {
    "summary": "hello",
    "experiences": [
        {"title": "Engineer", "highlights": ["built X", "led Y"]},
    ],
}


def test_get_top_level():
    assert jsonptr.get(DOC, "/summary") == "hello"


def test_get_nested_list():
    assert jsonptr.get(DOC, "/experiences/0/highlights/1") == "led Y"


def test_get_missing_raises():
    with pytest.raises(jsonptr.PointerError):
        jsonptr.get(DOC, "/experiences/5/title")
    with pytest.raises(jsonptr.PointerError):
        jsonptr.get(DOC, "/nope")


def test_set_replaces_existing():
    doc = {"summary": "old", "items": ["a", "b"]}
    jsonptr.set_(doc, "/summary", "new")
    jsonptr.set_(doc, "/items/1", "B")
    assert doc == {"summary": "new", "items": ["a", "B"]}


def test_set_never_creates_new_keys():
    doc = {"summary": "x"}
    with pytest.raises(jsonptr.PointerError):
        jsonptr.set_(doc, "/invented_field", "value")
    with pytest.raises(jsonptr.PointerError):
        jsonptr.set_(doc, "/items/0", "value")


def test_bad_pointer_format():
    with pytest.raises(jsonptr.PointerError):
        jsonptr.get(DOC, "summary")
