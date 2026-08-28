"""AI provider configuration model. The API key is never part of this model —
it is stored in the OS keyring, addressed by provider id."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProviderKind(StrEnum):
    OLLAMA = "ollama"
    OPENAI_COMPAT = "openai_compat"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    CLI = "cli"


class CLIAdapterKind(StrEnum):
    """Supported non-interactive command-line interfaces.

    AptiorDesk owns the argument templates. Users select an executable rather
    than entering an arbitrary shell command, which keeps prompt content out of
    command-line parsing and avoids a command-injection surface.
    """

    CODEX = "codex"
    CLAUDE = "claude"
    GEMINI = "gemini"


DEFAULT_BASE_URLS: dict[ProviderKind, str] = {
    ProviderKind.OLLAMA: "http://localhost:11434",
    ProviderKind.OPENAI_COMPAT: "https://api.openai.com/v1",
    ProviderKind.ANTHROPIC: "https://api.anthropic.com",
    ProviderKind.GEMINI: "https://generativelanguage.googleapis.com",
    ProviderKind.CLI: "",
}

# Kinds that work without an API key (local endpoints).
KEYLESS_KINDS = {ProviderKind.OLLAMA, ProviderKind.CLI}


class ProviderConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: int | None = None
    name: str = ""
    kind: ProviderKind = ProviderKind.OLLAMA
    base_url: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_s: int = 60
    is_active: bool = False
    cli_adapter: CLIAdapterKind = CLIAdapterKind.CODEX
    cli_executable: str = ""

    def effective_base_url(self) -> str:
        return (self.base_url or DEFAULT_BASE_URLS[self.kind]).rstrip("/")

    @property
    def is_local(self) -> bool:
        # A CLI process starts locally, but Codex/Claude/Gemini may send the
        # prompt to the service configured by that CLI. Do not present it as a
        # local/private model merely because its executable is on this device.
        if self.kind == ProviderKind.CLI:
            return False
        url = self.effective_base_url()
        return "localhost" in url or "127.0.0.1" in url
