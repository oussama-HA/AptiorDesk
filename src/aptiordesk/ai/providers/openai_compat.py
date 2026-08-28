"""OpenAI-compatible adapter. Covers OpenAI itself plus LM Studio,
OpenRouter, Groq, Together, Mistral, and any other server exposing
``/chat/completions`` — selected via ``base_url``.

The ``response_format`` JSON mode is deliberately not sent: many compatible
servers reject it, and schema-in-prompt (handled by ``AIProvider.structured``)
works everywhere."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from aptiordesk.ai.base import AIProvider, Capabilities, ChatMessage, CompletionResult


class OpenAICompatProvider(AIProvider):
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            streaming=True, json_mode=False, model_listing=True, is_local=self.config.is_local
        )

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _payload(self, messages: list[ChatMessage], stream: bool, **overrides) -> dict:
        return {
            "model": self.config.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "temperature": overrides.get("temperature", self.config.temperature),
            "max_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "stream": stream,
        }

    def chat(self, messages: list[ChatMessage], **overrides) -> CompletionResult:
        request_timeout_s = overrides.get("request_timeout_s")
        url = f"{self.config.effective_base_url()}/chat/completions"
        try:
            with self._client(request_timeout_s) as client:
                response = client.post(
                    url,
                    headers=self._headers(),
                    json=self._payload(messages, stream=False, **overrides),
                )
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc, request_timeout_s) from exc
        self._raise_for_status(response)
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return CompletionResult(
            text=(choice.get("message") or {}).get("content") or "",
            model=data.get("model", self.config.model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )

    def chat_stream(self, messages: list[ChatMessage], **overrides) -> Iterator[str]:
        request_timeout_s = overrides.get("request_timeout_s")
        url = f"{self.config.effective_base_url()}/chat/completions"
        try:
            with (
                self._client(request_timeout_s) as client,
                client.stream(
                    "POST",
                    url,
                    headers=self._headers(),
                    json=self._payload(messages, stream=True, **overrides),
                ) as response,
            ):
                self._raise_for_status(response)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        return
                    chunk = json.loads(body)
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc, request_timeout_s) from exc

    def list_models(self) -> list[str]:
        url = f"{self.config.effective_base_url()}/models"
        try:
            with self._client() as client:
                response = client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc) from exc
        self._raise_for_status(response)
        return sorted(m["id"] for m in response.json().get("data", []))
