"""Provider adapter tests against mocked HTTP. No real network, no paid APIs."""

import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import BaseModel

from aptiordesk.ai.base import AIProvider, Capabilities, ChatMessage, CompletionResult, Role
from aptiordesk.ai.errors import (
    AuthError,
    OutputParseError,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
)
from aptiordesk.ai.providers import (
    AnthropicProvider,
    CLIProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatProvider,
)
from aptiordesk.database.models.provider import CLIAdapterKind, ProviderConfig, ProviderKind

MSGS = [ChatMessage(Role.SYSTEM, "You are helpful."), ChatMessage(Role.USER, "Hi")]


def ollama_provider() -> OllamaProvider:
    return OllamaProvider(ProviderConfig(kind=ProviderKind.OLLAMA, model="gemma3"))


def openai_provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        ProviderConfig(kind=ProviderKind.OPENAI_COMPAT, model="gpt-x"), api_key="test-key"
    )


class TestOllama:
    @respx.mock
    def test_chat_success(self):
        respx.post("http://localhost:11434/api/chat").respond(
            json={
                "model": "gemma3",
                "message": {"role": "assistant", "content": "Hello!"},
                "prompt_eval_count": 10,
                "eval_count": 5,
                "done_reason": "stop",
            }
        )
        result = ollama_provider().chat(MSGS)
        assert result.text == "Hello!"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @respx.mock
    def test_json_mode_sends_format(self):
        route = respx.post("http://localhost:11434/api/chat").respond(
            json={"message": {"content": "{}"}}
        )
        ollama_provider().chat(MSGS, json_mode=True)
        import json

        sent = json.loads(route.calls.last.request.content)
        assert sent["format"] == "json"

    @respx.mock
    def test_connection_refused_maps_to_unavailable(self):
        respx.post("http://localhost:11434/api/chat").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(ProviderUnavailable):
            ollama_provider().chat(MSGS)

    @respx.mock
    def test_list_models(self):
        respx.get("http://localhost:11434/api/tags").respond(
            json={"models": [{"name": "gemma3"}, {"name": "llama3"}]}
        )
        assert ollama_provider().list_models() == ["gemma3", "llama3"]


class TestOpenAICompat:
    @respx.mock
    def test_chat_success_and_auth_header(self):
        route = respx.post("https://api.openai.com/v1/chat/completions").respond(
            json={
                "model": "gpt-x",
                "choices": [{"message": {"content": "Hi there"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }
        )
        result = openai_provider().chat(MSGS)
        assert result.text == "Hi there"
        assert route.calls.last.request.headers["authorization"] == "Bearer test-key"

    @respx.mock
    def test_401_maps_to_auth_error(self):
        respx.post("https://api.openai.com/v1/chat/completions").respond(
            status_code=401, json={"error": "bad key"}
        )
        with pytest.raises(AuthError):
            openai_provider().chat(MSGS)

    @respx.mock
    def test_429_maps_to_rate_limit_with_retry_after(self):
        respx.post("https://api.openai.com/v1/chat/completions").respond(
            status_code=429, headers={"retry-after": "30"}, json={}
        )
        with pytest.raises(RateLimitError) as excinfo:
            openai_provider().chat(MSGS)
        assert excinfo.value.retry_after_s == 30.0

    @respx.mock
    def test_timeout_maps_to_provider_timeout(self):
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        with pytest.raises(ProviderTimeout):
            openai_provider().chat(MSGS)

    @respx.mock
    def test_operation_timeout_override_is_used_and_reported(self):
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        with pytest.raises(ProviderTimeout, match="300 seconds"):
            openai_provider().chat(MSGS, request_timeout_s=300)
        timeout = openai_provider()._client(300).timeout
        assert timeout.connect == 10
        assert timeout.read == 300

    @respx.mock
    def test_custom_base_url(self):
        provider = OpenAICompatProvider(
            ProviderConfig(
                kind=ProviderKind.OPENAI_COMPAT,
                base_url="http://localhost:1234/v1",
                model="local-model",
            )
        )
        respx.post("http://localhost:1234/v1/chat/completions").respond(
            json={"choices": [{"message": {"content": "ok"}}]}
        )
        assert provider.chat(MSGS).text == "ok"


class TestAnthropic:
    @respx.mock
    def test_chat_success_system_separated(self):
        route = respx.post("https://api.anthropic.com/v1/messages").respond(
            json={
                "model": "claude-x",
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {"input_tokens": 12, "output_tokens": 4},
                "stop_reason": "end_turn",
            }
        )
        provider = AnthropicProvider(
            ProviderConfig(kind=ProviderKind.ANTHROPIC, model="claude-x"), api_key="k"
        )
        result = provider.chat(MSGS)
        assert result.text == "Hello"
        import json

        sent = json.loads(route.calls.last.request.content)
        assert sent["system"] == "You are helpful."
        assert all(m["role"] != "system" for m in sent["messages"])
        assert route.calls.last.request.headers["x-api-key"] == "k"


class TestGemini:
    @respx.mock
    def test_chat_success_key_in_header_not_url(self):
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
        route = respx.post(url).respond(
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Hi from Gemini"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            }
        )
        provider = GeminiProvider(
            ProviderConfig(kind=ProviderKind.GEMINI, model="gemini-x"), api_key="secret"
        )
        result = provider.chat(MSGS)
        assert result.text == "Hi from Gemini"
        request = route.calls.last.request
        assert "secret" not in str(request.url)
        assert request.headers["x-goog-api-key"] == "secret"


class TestDeviceCLI:
    def _provider(self, executable, adapter=CLIAdapterKind.CODEX, model=""):
        return CLIProvider(
            ProviderConfig(
                kind=ProviderKind.CLI,
                cli_adapter=adapter,
                cli_executable=str(executable),
                model=model,
            )
        )

    def test_codex_uses_reviewed_argv_stdin_and_isolated_directory(self, monkeypatch, tmp_path):
        executable = tmp_path / "codex.exe"
        executable.touch()
        observed = {}

        def fake_run(argv, **kwargs):
            observed["argv"] = argv
            observed.update(kwargs)
            assert kwargs["cwd"] != str(tmp_path)
            assert Path(kwargs["cwd"]).is_dir()
            return subprocess.CompletedProcess(argv, 0, "A focused answer", "")

        monkeypatch.setattr("aptiordesk.ai.providers.cli.subprocess.run", fake_run)
        result = self._provider(executable, model="gpt-test").chat(MSGS)

        assert result.text == "A focused answer"
        assert observed["argv"][0] == str(executable.resolve())
        assert observed["argv"][-1] == "-"
        assert "--model" in observed["argv"]
        assert observed["shell"] is False
        assert "[SYSTEM]\nYou are helpful." in observed["input"]

    def test_cli_uses_operation_timeout_override(self, monkeypatch, tmp_path):
        executable = tmp_path / "codex.exe"
        executable.touch()
        observed = {}

        def fake_run(argv, **kwargs):
            observed.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, "A focused answer", "")

        monkeypatch.setattr("aptiordesk.ai.providers.cli.subprocess.run", fake_run)
        self._provider(executable).chat(MSGS, request_timeout_s=300)
        assert observed["timeout"] == 300

    def test_claude_json_result_is_unwrapped(self, monkeypatch, tmp_path):
        executable = tmp_path / "claude.exe"
        executable.touch()

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, '{"result":"Hello from Claude","model":"sonnet"}', ""
            )

        monkeypatch.setattr("aptiordesk.ai.providers.cli.subprocess.run", fake_run)
        result = self._provider(executable, CLIAdapterKind.CLAUDE).chat(MSGS)
        assert result.text == "Hello from Claude"
        assert result.model == "sonnet"

    def test_cli_auth_failure_is_mapped(self, monkeypatch, tmp_path):
        executable = tmp_path / "gemini.cmd"
        executable.touch()

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, "", "Not logged in. Run login first.")

        monkeypatch.setattr("aptiordesk.ai.providers.cli.subprocess.run", fake_run)
        with pytest.raises(AuthError):
            self._provider(executable, CLIAdapterKind.GEMINI).chat(MSGS)

    def test_cli_is_not_claimed_as_local(self, tmp_path):
        executable = tmp_path / "codex.exe"
        executable.touch()
        provider = self._provider(executable)
        assert not provider.config.is_local
        assert not provider.capabilities.is_local


# --- structured() -------------------------------------------------------------


class Answer(BaseModel):
    city: str
    population: int


class ScriptedProvider(AIProvider):
    """Deterministic provider for exercising the structured-output flow."""

    def __init__(self, responses: list[str]):
        super().__init__(ProviderConfig(kind=ProviderKind.OLLAMA, model="fake"))
        self._responses = list(responses)
        self.calls = 0

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(streaming=False, json_mode=False, model_listing=False, is_local=True)

    def chat(self, messages, **overrides) -> CompletionResult:
        self.calls += 1
        return CompletionResult(text=self._responses.pop(0), model="fake")

    def chat_stream(self, messages, **overrides):
        raise NotImplementedError

    def list_models(self):
        return []


class TestStructured:
    def test_valid_first_try(self):
        provider = ScriptedProvider(['{"city": "Lisbon", "population": 500000}'])
        result = provider.structured([ChatMessage(Role.USER, "q")], Answer)
        assert result.city == "Lisbon"
        assert provider.calls == 1

    def test_repair_round_trip_fixes_output(self):
        provider = ScriptedProvider(
            ["Sorry, here it is: city Lisbon", '{"city": "Lisbon", "population": 500000}']
        )
        result = provider.structured([ChatMessage(Role.USER, "q")], Answer)
        assert result.population == 500000
        assert provider.calls == 2

    def test_gives_up_with_output_parse_error(self):
        provider = ScriptedProvider(["nope", "still nope"])
        with pytest.raises(OutputParseError) as excinfo:
            provider.structured([ChatMessage(Role.USER, "q")], Answer)
        assert excinfo.value.raw_output == "still nope"

    def test_validation_error_triggers_repair(self):
        provider = ScriptedProvider(
            ['{"city": "Lisbon", "population": "lots"}', '{"city": "Lisbon", "population": 1}']
        )
        result = provider.structured([ChatMessage(Role.USER, "q")], Answer)
        assert result.population == 1
        assert provider.calls == 2
