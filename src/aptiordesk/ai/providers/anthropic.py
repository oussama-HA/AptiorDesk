"""Anthropic Messages API adapter. The system prompt is passed via the
dedicated ``system`` parameter; streaming is deferred to a later phase."""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from aptiordesk.ai.base import AIProvider, Capabilities, ChatMessage, CompletionResult, Role
from aptiordesk.ai.errors import UnsupportedFeature

_API_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(streaming=False, json_mode=False, model_listing=True, is_local=False)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self._api_key or "",
            "anthropic-version": _API_VERSION,
        }

    def chat(self, messages: list[ChatMessage], **overrides) -> CompletionResult:
        request_timeout_s = overrides.get("request_timeout_s")
        system_parts = [m.content for m in messages if m.role == Role.SYSTEM]
        turns = [
            {"role": m.role.value, "content": m.content} for m in messages if m.role != Role.SYSTEM
        ]
        payload: dict = {
            "model": self.config.model,
            "max_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "temperature": overrides.get("temperature", self.config.temperature),
            "messages": turns,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        url = f"{self.config.effective_base_url()}/v1/messages"
        try:
            with self._client(request_timeout_s) as client:
                response = client.post(url, headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc, request_timeout_s) from exc
        self._raise_for_status(response)
        data = response.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        return CompletionResult(
            text=text,
            model=data.get("model", self.config.model),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            finish_reason=data.get("stop_reason"),
        )

    def chat_stream(self, messages: list[ChatMessage], **overrides) -> Iterator[str]:
        raise UnsupportedFeature("Streaming is not yet implemented for Anthropic.")

    def list_models(self) -> list[str]:
        url = f"{self.config.effective_base_url()}/v1/models"
        try:
            with self._client() as client:
                response = client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc) from exc
        self._raise_for_status(response)
        return [m["id"] for m in response.json().get("data", [])]
