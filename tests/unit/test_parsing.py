import pytest

from aptiordesk.ai.prompts.parsing import JsonExtractionError, extract_json


def test_plain_json_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_nested_json_is_not_truncated():
    # The legacy regex \{.*?\} failed exactly this case.
    text = 'Here you go: {"outer": {"inner": [1, 2, {"deep": true}]}, "b": 2} thanks!'
    assert extract_json(text) == {"outer": {"inner": [1, 2, {"deep": True}]}, "b": 2}


def test_json_inside_code_fence():
    text = 'Sure!\n```json\n{"skills": ["python", "sql"]}\n```\nDone.'
    assert extract_json(text) == {"skills": ["python", "sql"]}


def test_json_array():
    text = 'Questions: [{"q": "Why us?"}, {"q": "Tell me about a conflict"}]'
    assert extract_json(text) == [{"q": "Why us?"}, {"q": "Tell me about a conflict"}]


def test_trailing_comma_repair():
    assert extract_json('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}


def test_braces_inside_strings_do_not_confuse_scanner():
    text = 'prefix {"text": "a { tricky } value", "n": 3} suffix'
    assert extract_json(text) == {"text": "a { tricky } value", "n": 3}


def test_garbage_raises_with_raw_text():
    with pytest.raises(JsonExtractionError) as excinfo:
        extract_json("I am sorry, I cannot produce JSON today.")
    assert "cannot produce" in excinfo.value.raw_text


def test_empty_raises():
    with pytest.raises(JsonExtractionError):
        extract_json("   ")
