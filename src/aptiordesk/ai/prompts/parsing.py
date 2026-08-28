"""Robust extraction of JSON from LLM output.

Replaces the legacy non-greedy regex approach (which truncated any nested
JSON). Strategy, in order:

1. Strip Markdown code fences.
2. ``json.loads`` on the whole text.
3. Balanced-delimiter scan: find the largest parseable JSON object/array.
4. Minor repairs (trailing commas) and retry.

Raises ``JsonExtractionError`` when nothing parseable is found — callers
decide whether to do a model repair round-trip.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([\]}])")


class JsonExtractionError(ValueError):
    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


def extract_json(text: str) -> Any:
    """Return the first JSON object or array found in `text`."""
    if not text or not text.strip():
        raise JsonExtractionError("Empty model output", text)

    candidates: list[str] = []
    for m in _FENCE.finditer(text):
        candidates.append(m.group(1))
    candidates.append(text)

    for candidate in candidates:
        candidate = candidate.strip()
        for attempt in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                pass
        found = _scan_balanced(candidate)
        if found is not None:
            return found

    raise JsonExtractionError("No valid JSON found in model output", text)


def _scan_balanced(text: str) -> Any | None:
    """Find the first balanced {...} or [...] region that parses as JSON."""
    for start, opener in _delimiter_positions(text):
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    fragment = text[start : i + 1]
                    for attempt in (fragment, _TRAILING_COMMA.sub(r"\1", fragment)):
                        try:
                            return json.loads(attempt)
                        except json.JSONDecodeError:
                            pass
                    break  # balanced but unparseable; try next start position
    return None


def _delimiter_positions(text: str) -> list[tuple[int, str]]:
    return [(i, ch) for i, ch in enumerate(text) if ch in "{["]
