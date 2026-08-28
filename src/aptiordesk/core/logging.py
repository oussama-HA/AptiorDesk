"""Logging setup with secret redaction.

Rules:
- API keys and credential-like strings must never reach the log file.
- Document bodies (resumes, job descriptions, answers) are never logged at
  INFO or above; services must log lengths/ids, not content.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re

from aptiordesk.core import paths
from aptiordesk.core.identity import LEGACY_LOG_LEVEL_ENV, LOG_LEVEL_ENV, LOG_NAME

# Common API key shapes plus explicit key=value leaks.
_REDACT_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI-style
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),  # Anthropic
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),  # Google
    re.compile(
        r"(?i)(api[_-]?key|authorization|x-goog-api-key|x-api-key)"
        r"([\"':=\s]+)([A-Za-z0-9_\-\.]{8,})"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = _redact(msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def _redact(text: str) -> str:
    for pat in _REDACT_PATTERNS:
        if pat.groups >= 3:
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


def setup_logging(level: int | None = None) -> None:
    if level is None:
        configured = os.getenv(LOG_LEVEL_ENV) or os.getenv(LEGACY_LOG_LEVEL_ENV) or "INFO"
        level = getattr(logging, configured.upper(), logging.INFO)
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return  # already configured
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redaction = RedactionFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        paths.logs_dir() / LOG_NAME, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(redaction)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redaction)
    root.addHandler(console)
