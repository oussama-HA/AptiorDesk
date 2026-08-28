"""Builds AIProvider instances from stored configuration + keyring."""

from __future__ import annotations

import sqlite3

from aptiordesk.ai import keystore
from aptiordesk.ai.base import AIProvider
from aptiordesk.ai.errors import AIError
from aptiordesk.ai.providers import (
    AnthropicProvider,
    CLIProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatProvider,
)
from aptiordesk.database.models.provider import KEYLESS_KINDS, ProviderConfig, ProviderKind
from aptiordesk.database.repositories.provider_repo import ProviderRepository

_ADAPTERS: dict[ProviderKind, type[AIProvider]] = {
    ProviderKind.OLLAMA: OllamaProvider,
    ProviderKind.OPENAI_COMPAT: OpenAICompatProvider,
    ProviderKind.ANTHROPIC: AnthropicProvider,
    ProviderKind.GEMINI: GeminiProvider,
    ProviderKind.CLI: CLIProvider,
}


class NoActiveProvider(AIError):
    pass


def build_provider(config: ProviderConfig, api_key: str | None = None) -> AIProvider:
    if api_key is None and config.id is not None and config.kind not in KEYLESS_KINDS:
        api_key = keystore.get_key(config.id)
    return _ADAPTERS[config.kind](config, api_key)


def get_active_provider(conn: sqlite3.Connection) -> AIProvider:
    config = ProviderRepository(conn).get_active()
    if config is None:
        raise NoActiveProvider("No AI provider is configured. Add one in Settings → AI Providers.")
    return build_provider(config)
