"""Minimal JSON-pointer (RFC 6901 subset) for addressing string fields inside
resume content, e.g. "/experiences/0/highlights/1" or "/summary"."""

from __future__ import annotations

from typing import Any


class PointerError(KeyError):
    pass


def _tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise PointerError(f"Pointer must start with '/': {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def get(document: Any, pointer: str) -> Any:
    node = document
    for token in _tokens(pointer):
        try:
            if isinstance(node, list):
                node = node[int(token)]
            elif isinstance(node, dict):
                node = node[token]
            else:
                raise PointerError(f"Cannot descend into {type(node).__name__} at {token!r}")
        except (KeyError, IndexError, ValueError) as exc:
            raise PointerError(f"Path not found: {pointer!r} (at {token!r})") from exc
    return node


def set_(document: Any, pointer: str, value: Any) -> None:
    """Replace an existing value in place. Never creates new keys/indices —
    a tailoring suggestion may only rewrite content that already exists."""
    tokens = _tokens(pointer)
    parent = get(document, "/" + "/".join(tokens[:-1])) if len(tokens) > 1 else document
    last = tokens[-1]
    try:
        if isinstance(parent, list):
            index = int(last)
            parent[index]  # noqa: B018 — bounds check
            parent[index] = value
        elif isinstance(parent, dict):
            if last not in parent:
                raise PointerError(f"Key does not exist: {pointer!r}")
            parent[last] = value
        else:
            raise PointerError(f"Cannot set on {type(parent).__name__}")
    except (IndexError, ValueError) as exc:
        raise PointerError(f"Path not found: {pointer!r}") from exc
