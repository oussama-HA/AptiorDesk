"""Versioned prompt templates.

Templates are Markdown files in ``aptiordesk/prompts/templates`` with YAML-ish
front matter::

    ---
    id: job_extraction
    version: 1
    ---
    template body with {placeholders}

Kept intentionally dependency-free (no YAML lib): front matter is simple
``key: value`` lines. Placeholders are filled with ``str.format_map``;
untrusted values must already be fenced via ``guards.wrap_untrusted``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: int
    body: str

    def render(self, **values: str) -> str:
        return self.body.format_map(_Safe(values))


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(f"Missing template variable: {key}")


@lru_cache(maxsize=1)
def _load_all() -> dict[str, PromptTemplate]:
    templates: dict[str, PromptTemplate] = {}
    package = resources.files("aptiordesk.ai.prompts.templates")
    for entry in package.iterdir():
        if not entry.name.endswith(".md"):
            continue
        meta, body = _parse(entry.read_text(encoding="utf-8"), entry.name)
        template = PromptTemplate(id=meta["id"], version=int(meta["version"]), body=body)
        if template.id in templates:
            raise ValueError(f"Duplicate template id: {template.id}")
        templates[template.id] = template
    return templates


def get_template(template_id: str) -> PromptTemplate:
    try:
        return _load_all()[template_id]
    except KeyError:
        raise KeyError(f"Unknown prompt template: {template_id}") from None


def _parse(text: str, filename: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        raise ValueError(f"{filename}: missing front matter")
    _, front, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in front.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    for required in ("id", "version"):
        if required not in meta:
            raise ValueError(f"{filename}: front matter missing '{required}'")
    return meta, body.strip()
