"""Google Gemini adapter. The API key is sent via the ``x-goog-api-key``
header — never as a URL query parameter."""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from aptiordesk.ai.base import AIProvider, Capabilities, ChatMessage, CompletionResult, Role
from aptiordesk.ai.errors import UnsupportedFeature


class GeminiProvider(AIProvider):
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(streaming=False, json_mode=True, model_listing=True, is_local=False)

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "x-goog-api-key": self._api_key or ""}

    def chat(self, messages: list[ChatMessage], **overrides) -> CompletionResult:
        request_timeout_s = overrides.get("request_timeout_s")
        system_parts = [m.content for m in messages if m.role == Role.SYSTEM]
        contents = [
            {
                "role": "model" if m.role == Role.ASSISTANT else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role != Role.SYSTEM
        ]
        generation_config: dict = {
            "temperature": overrides.get("temperature", self.config.temperature),
            "maxOutputTokens": overrides.get("max_tokens", self.config.max_tokens),
        }
        if overrides.get("json_mode"):
            generation_config["responseMimeType"] = "application/json"
        payload: dict = {"contents": contents, "generationConfig": generation_config}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        model = self.config.model
        url = f"{self.config.effective_base_url()}/v1beta/models/{model}:generateContent"
        try:
            with self._client(request_timeout_s) as client:
                response = client.post(url, headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc, request_timeout_s) from exc
        self._raise_for_status(response)
        data = response.json()
        candidates = data.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        usage = data.get("usageMetadata") or {}
        return CompletionResult(
            text="".join(p.get("text", "") for p in parts),
            model=self.config.model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            finish_reason=candidates[0].get("finishReason"),
        )

    def chat_stream(self, messages: list[ChatMessage], **overrides) -> Iterator[str]:
        raise UnsupportedFeature("Streaming is not yet implemented for Gemini.")

    def list_models(self) -> list[str]:
        url = f"{self.config.effective_base_url()}/v1beta/models"
        try:
            with self._client() as client:
                response = client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise self._map_transport_error(exc) from exc
        self._raise_for_status(response)
        names = [m.get("name", "") for m in response.json().get("models", [])]
        return [n.removeprefix("models/") for n in names if n]
