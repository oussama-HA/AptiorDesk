"""Adapter for AI command-line tools installed on the user's device.

Only reviewed, non-interactive argument templates are supported. Prompt text is
sent on stdin, never interpolated into a shell command, and every invocation
runs in a fresh temporary directory so an agentic CLI cannot inspect or modify
the AptiorDesk workspace as a side effect of an ordinary AI request.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from aptiordesk.ai.base import (
    AIProvider,
    Capabilities,
    ChatMessage,
    CompletionResult,
    HealthStatus,
    Role,
)
from aptiordesk.ai.errors import (
    AuthError,
    ProviderTimeout,
    ProviderUnavailable,
    UnsupportedFeature,
)
from aptiordesk.ai.prompts.parsing import JsonExtractionError, extract_json
from aptiordesk.database.models.provider import CLIAdapterKind

_DEFAULT_COMMANDS: dict[CLIAdapterKind, str] = {
    CLIAdapterKind.CODEX: "codex",
    CLIAdapterKind.CLAUDE: "claude",
    CLIAdapterKind.GEMINI: "gemini",
}

_ADAPTER_NAMES: dict[CLIAdapterKind, str] = {
    CLIAdapterKind.CODEX: "Codex CLI",
    CLIAdapterKind.CLAUDE: "Claude Code",
    CLIAdapterKind.GEMINI: "Gemini CLI",
}

_OUTPUT_LIMIT = 10_000_000


def adapter_display_name(adapter: CLIAdapterKind) -> str:
    return _ADAPTER_NAMES[adapter]


def detect_cli_executable(adapter: CLIAdapterKind) -> str:
    """Return the executable discoverable on PATH, or an empty string."""
    return shutil.which(_DEFAULT_COMMANDS[adapter]) or ""


def resolve_cli_executable(executable: str, adapter: CLIAdapterKind) -> str:
    candidate = os.path.expandvars(os.path.expanduser(executable.strip()))
    if candidate:
        has_directory = bool(Path(candidate).parent != Path("."))
        if has_directory or Path(candidate).is_absolute():
            path = Path(candidate)
            if path.is_file():
                return str(path.resolve())
            raise ProviderUnavailable(
                f"The selected {_ADAPTER_NAMES[adapter]} executable does not exist."
            )
        found = shutil.which(candidate)
    else:
        found = detect_cli_executable(adapter)
    if found:
        return found
    raise ProviderUnavailable(
        f"{_ADAPTER_NAMES[adapter]} was not found. Install it, then select its "
        "executable in Settings → AI providers."
    )


class CLIProvider(AIProvider):
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            streaming=False,
            json_mode=False,
            model_listing=False,
            # The process is local, but the configured CLI may use a cloud API.
            is_local=False,
        )

    def chat(self, messages: list[ChatMessage], **overrides) -> CompletionResult:
        request_timeout_s = overrides.pop("request_timeout_s", self.config.timeout_s)
        del overrides  # CLI-owned settings govern sampling and output limits.
        adapter = self.config.cli_adapter
        executable = resolve_cli_executable(self.config.cli_executable, adapter)
        prompt = _render_prompt(messages)
        args = _arguments(adapter, self.config.model)

        environment = os.environ.copy()
        environment.update({"NO_COLOR": "1", "TERM": "dumb", "CI": "1"})
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            with tempfile.TemporaryDirectory(prefix="aptiordesk-ai-") as workdir:
                completed = subprocess.run(  # noqa: S603 - argv is a reviewed preset
                    [executable, *args],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=request_timeout_s,
                    cwd=workdir,
                    env=environment,
                    shell=False,
                    creationflags=creationflags,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise ProviderTimeout(
                f"{_ADAPTER_NAMES[adapter]} did not respond within "
                f"{request_timeout_s:g} seconds. The model may still be loading or "
                "generating; you can increase its timeout in Settings → AI providers.",
                detail=str(exc),
            ) from exc
        except OSError as exc:
            raise ProviderUnavailable(
                f"AptiorDesk could not start {_ADAPTER_NAMES[adapter]}. "
                "Check the executable path and permissions.",
                detail=str(exc),
            ) from exc

        stdout = completed.stdout[:_OUTPUT_LIMIT].strip()
        stderr = completed.stderr[:_OUTPUT_LIMIT].strip()
        if completed.returncode != 0:
            _raise_cli_failure(adapter, completed.returncode, stderr or stdout)
        if not stdout:
            raise ProviderUnavailable(
                f"{_ADAPTER_NAMES[adapter]} finished without returning a response.",
                detail=stderr,
            )

        text, reported_model = _parse_output(adapter, stdout)
        if not text.strip():
            raise ProviderUnavailable(
                f"{_ADAPTER_NAMES[adapter]} returned an empty response.", detail=stdout[:1000]
            )
        return CompletionResult(
            text=text.strip(),
            model=reported_model or self.config.model or adapter.value,
            finish_reason="stop",
        )

    def chat_stream(self, messages: list[ChatMessage], **overrides) -> Iterator[str]:
        del messages, overrides
        raise UnsupportedFeature("Device CLI providers do not support streaming yet.")

    def list_models(self) -> list[str]:
        # These CLIs do not share a stable, machine-readable model-list command.
        return [self.config.model] if self.config.model else []

    def health_check(self) -> HealthStatus:
        try:
            executable = resolve_cli_executable(self.config.cli_executable, self.config.cli_adapter)
            result = self.chat([ChatMessage(role=Role.USER, content="Reply with exactly OK.")])
            return HealthStatus(
                ok=True,
                message=f"CLI responded via {Path(executable).name}: {result.text[:80]}",
                models=self.list_models(),
            )
        except Exception as exc:
            return HealthStatus(ok=False, message=getattr(exc, "user_message", str(exc)))


def _arguments(adapter: CLIAdapterKind, model: str) -> list[str]:
    if adapter == CLIAdapterKind.CODEX:
        args = [
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
        ]
        if model:
            args.extend(["--model", model])
        return [*args, "-"]
    if adapter == CLIAdapterKind.CLAUDE:
        args = [
            "--print",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--permission-mode",
            "plan",
        ]
        if model:
            args.extend(["--model", model])
        return args
    args = [
        "--prompt",
        "",
        "--output-format",
        "json",
        "--approval-mode",
        "plan",
        "--skip-trust",
    ]
    if model:
        args.extend(["--model", model])
    return args


def _render_prompt(messages: list[ChatMessage]) -> str:
    sections = [
        "You are responding inside AptiorDesk. Complete the requested career task and "
        "return only the requested answer. Do not inspect files or run tools."
    ]
    for message in messages:
        sections.append(f"\n[{message.role.value.upper()}]\n{message.content}")
    return "\n".join(sections).strip() + "\n"


def _parse_output(adapter: CLIAdapterKind, stdout: str) -> tuple[str, str]:
    if adapter == CLIAdapterKind.CODEX:
        return stdout, ""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        try:
            payload = extract_json(stdout)
        except JsonExtractionError as exc:
            raise ProviderUnavailable(
                f"{_ADAPTER_NAMES[adapter]} returned output AptiorDesk could not read.",
                detail=stdout[:1000],
            ) from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailable(
            f"{_ADAPTER_NAMES[adapter]} returned an unexpected response format."
        )
    if adapter == CLIAdapterKind.CLAUDE:
        if payload.get("is_error"):
            raise ProviderUnavailable(
                "Claude Code reported an error.", detail=str(payload.get("result", ""))
            )
        return str(payload.get("result", "")), str(payload.get("model", ""))
    error = payload.get("error")
    if error:
        raise ProviderUnavailable("Gemini CLI reported an error.", detail=str(error))
    return str(payload.get("response", "")), str(payload.get("model", ""))


def _raise_cli_failure(adapter: CLIAdapterKind, returncode: int, detail: str) -> None:
    lowered = detail.lower()
    if any(term in lowered for term in ("not logged in", "authentication", "api key", "login")):
        raise AuthError(
            f"{_ADAPTER_NAMES[adapter]} is not authenticated. Sign in through the CLI, "
            "then test it again.",
            detail=detail[:2000],
        )
    raise ProviderUnavailable(
        f"{_ADAPTER_NAMES[adapter]} exited with code {returncode}.", detail=detail[:2000]
    )
