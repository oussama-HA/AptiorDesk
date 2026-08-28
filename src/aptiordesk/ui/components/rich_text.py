"""Consistent document spacing for HTML shown inside Qt text browsers."""

from __future__ import annotations

_DOCUMENT_CSS = """
<style>
  html, body { margin: 0; padding: 0; font-size: 15px; line-height: 1.55; }
  h1 { font-size: 25px; line-height: 1.22; margin: 0 0 17px 0; }
  h2 { font-size: 20px; line-height: 1.28; margin: 2px 0 14px 0; }
  h3 { font-size: 16px; line-height: 1.35; margin: 21px 0 8px 0; }
  p { margin: 0 0 13px 0; }
  ul, ol { margin: 6px 0 14px 20px; padding: 0; }
  li { margin-bottom: 7px; }
  table { margin: 8px 0 16px 0; }
  td, th { padding: 5px 14px 5px 0; }
  blockquote { margin: 12px 0; padding-left: 14px; }
  code { font-family: "Cascadia Code", Consolas, monospace; }
</style>
"""


def rich_document(body: str) -> str:
    """Wrap a trusted HTML fragment in the application's document rhythm."""
    return f"<html><head>{_DOCUMENT_CSS}</head><body>{body}</body></html>"


__all__ = ["rich_document"]
