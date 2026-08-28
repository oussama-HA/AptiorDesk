"""Read AptiorDesk's canonical desktop design-token source."""

from __future__ import annotations

import re
from pathlib import Path

TOKEN_FILE = Path(__file__).with_name("brand_tokens.css")


def _read_tokens() -> dict[str, str]:
    text = TOKEN_FILE.read_text(encoding="utf-8")
    return {
        name: value.strip() for name, value in re.findall(r"--ad-([a-z0-9-]+)\s*:\s*([^;]+);", text)
    }


TOKENS = _read_tokens()


def token(name: str) -> str:
    try:
        return TOKENS[name]
    except KeyError as exc:
        raise RuntimeError(f"Shared design token --ad-{name} is missing") from exc


def number(name: str) -> float:
    value = token(name)
    match = re.match(r"-?[\d.]+", value)
    if not match:
        raise RuntimeError(f"Shared design token --ad-{name} is not numeric: {value}")
    return float(match.group(0))


__all__ = ["TOKENS", "TOKEN_FILE", "number", "token"]
