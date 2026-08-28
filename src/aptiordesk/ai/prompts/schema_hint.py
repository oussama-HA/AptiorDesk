"""Turn a pydantic model into something a small local model can actually follow.

``model_json_schema()`` produces ``$ref``/``$defs`` indirection: for
``ResumeContent`` that is ~4 KB and ~1000 tokens of JSON Schema in which every
nested type is a pointer. Small models (the 3B-8B range AptiorDesk recommends for
local use) resolve those pointers badly and invent flattened key names instead,
which then validate as an empty object because every field has a default.

A concrete example object works far better: it is shorter, it shows the exact
key names and nesting, and there is nothing to dereference. This module builds
one from the model's own field types, so it cannot drift from the schema.
"""

from __future__ import annotations

import json
import types
import typing
from enum import Enum

from pydantic import BaseModel
from pydantic.fields import FieldInfo

_MAX_DEPTH = 5


def example_for(model: type[BaseModel], *, depth: int = 0) -> dict:
    """Build a nested example object showing every field of `model`."""
    example: dict[str, object] = {}
    for name, field in model.model_fields.items():
        example[name] = _example_value(field.annotation, field, depth)
    return example


def schema_hint(model: type[BaseModel], *, list_items: int = 2) -> str:
    """A prompt fragment: the exact JSON shape expected, as an example.

    `list_items` controls how many placeholder entries each list gets — two is
    enough to show that repetition is expected without wasting tokens.
    """
    example = example_for(model)
    example = _expand_lists(example, list_items)
    rendered = json.dumps(example, indent=2, ensure_ascii=False)
    return (
        "Return a single JSON object with exactly this shape. Use these key "
        'names exactly. Keep a key with an empty value ("" or []) when the '
        "information is not present — never omit a key, never add new ones.\n\n"
        f"{rendered}"
    )


def describe_fields(model: type[BaseModel]) -> str:
    """One line per field, using each field's description where it has one."""
    lines = []
    for name, field in model.model_fields.items():
        description = field.description or ""
        lines.append(f"- {name}: {description}" if description else f"- {name}")
    return "\n".join(lines)


# --- internals ----------------------------------------------------------------


def _example_value(annotation: object, field: FieldInfo | None, depth: int) -> object:
    if depth > _MAX_DEPTH:
        return ""
    origin = typing.get_origin(annotation)

    # Optional[X] / X | None -> use X; the example shows the populated shape.
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if args:
            return _example_value(args[0], field, depth)
        return ""

    if origin in (list, set, tuple):
        args = typing.get_args(annotation)
        inner = _example_value(args[0], None, depth + 1) if args else ""
        return [inner]

    if origin is dict:
        return {}

    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return example_for(annotation, depth=depth + 1)
        if issubclass(annotation, Enum):
            return next(iter(annotation)).value
        if annotation is bool:
            return False
        if annotation is int:
            return 0
        if annotation is float:
            return 0.0

    # Strings (and anything unrecognised) show the field's own guidance, which
    # is where the per-field instructions actually land in the prompt.
    if field is not None and field.description:
        return f"<{field.description}>"
    return ""


def _expand_lists(value: object, count: int) -> object:
    """Repeat single-element example lists so repetition is obvious."""
    if isinstance(value, list) and value:
        item = _expand_lists(value[0], count)
        if isinstance(item, dict):
            return [item] * max(1, count)
        return [item, item] if count > 1 else [item]
    if isinstance(value, dict):
        return {k: _expand_lists(v, count) for k, v in value.items()}
    return value
