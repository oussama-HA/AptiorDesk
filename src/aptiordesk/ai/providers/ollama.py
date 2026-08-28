"""Ollama adapter (local, keyless). REST API: https://github.com/ollama/ollama/blob/main/docs/api.md"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from aptiordesk.ai.base import AIProvider, Capabilities, ChatMessage, CompletionResult
from aptiordesk.ai.errors import ProviderTimeout, ProviderUnavailable


class OllamaProvider(AIProvider):
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            streaming=True, json_mode=True, model_listing=True, is_local=self.config.is_local
        )

    def _payload(self, messages: list[ChatMessage], stream: bool, **overrides) -> dict:
        payload: dict = {
            "model": self.config.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": stream,
            "options": {
                "temperature": overrides.get("temperature", self.config.temperature),
                "num_predict": overrides.get("max_tokens", self.config.max_tokens),
            },
        }
        if overrides.get("json_mode"):
            payload["format"] = "json"
        return payload

    def chat(self, messages: list[ChatMessage], **overrides) -> CompletionResult:
        request_timeout_s = overrides.get("request_timeout_s")
        url = f"{self.config.effective_base_url()}/api/chat"
        try:
            with self._client(request_timeout_s) as client:
                response = client.post(url, json=self._payload(messages, stream=False, **overrides))
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc, request_timeout_s) from exc
        self._raise_for_status(response)
        data = response.json()
        return CompletionResult(
            text=data.get("message", {}).get("content", ""),
            model=data.get("model", self.config.model),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            finish_reason=data.get("done_reason"),
        )

    def chat_stream(self, messages: list[ChatMessage], **overrides) -> Iterator[str]:
        request_timeout_s = overrides.get("request_timeout_s")
        url = f"{self.config.effective_base_url()}/api/chat"
        try:
            with (
                self._client(request_timeout_s) as client,
                client.stream(
                    "POST", url, json=self._payload(messages, stream=True, **overrides)
                ) as response,
            ):
                self._raise_for_status(response)
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        return
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc, request_timeout_s) from exc

    def list_models(self) -> list[str]:
        url = f"{self.config.effective_base_url()}/api/tags"
        try:
            with self._client() as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc) from exc
        self._raise_for_status(response)
        return [m["name"] for m in response.json().get("models", [])]

    def _map_transport_error(
        self, exc: Exception, request_timeout_s: float | None = None
    ) -> Exception:
        if isinstance(exc, httpx.TimeoutException):
            timeout_s = request_timeout_s or self.config.timeout_s
            return ProviderTimeout(
                f"Ollama did not respond within {timeout_s:g} seconds. Start the "
                "Ollama application and confirm the selected model is available, "
                "or choose another provider in Settings → AI providers.",
                detail=str(exc),
            )
        if isinstance(exc, httpx.TransportError):
            return ProviderUnavailable(
                "Ollama is selected as the active AI provider, but its local server "
                "is not running. Start Ollama, or select a working device CLI or "
                "cloud provider in Settings → AI providers.",
                detail=str(exc),
            )
        return exc
