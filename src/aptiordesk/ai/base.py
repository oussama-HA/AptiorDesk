"""Provider-agnostic AI interface.

Services depend only on ``AIProvider``. Adapters translate to each
provider's HTTP API and map failures onto ``aptiordesk.ai.errors``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from aptiordesk.ai.errors import (
    AuthError,
    ModelNotFoundError,
    OutputParseError,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
)
from aptiordesk.ai.prompts.parsing import JsonExtractionError, extract_json
from aptiordesk.ai.prompts.schema_hint import schema_hint
from aptiordesk.database.models.provider import ProviderConfig

S = TypeVar("S", bound=BaseModel)


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class Capabilities:
    streaming: bool
    json_mode: bool
    model_listing: bool
    is_local: bool


@dataclass
class CompletionResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class HealthStatus:
    ok: bool
    message: str = ""
    models: list[str] = field(default_factory=list)


class AIProvider(ABC):
    """One instance per configured provider; short-lived, cheap to build."""

    def __init__(self, config: ProviderConfig, api_key: str | None = None):
        self.config = config
        self._api_key = api_key

    # -- interface -----------------------------------------------------------

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def chat(self, messages: list[ChatMessage], **overrides) -> CompletionResult:
        """Blocking completion.

        Supported common overrides include ``temperature``, ``max_tokens``,
        ``json_mode``, and ``request_timeout_s``. The last one changes only the
        response/read deadline; connecting to an unreachable service still
        fails quickly.
        """

    @abstractmethod
    def chat_stream(self, messages: list[ChatMessage], **overrides) -> Iterator[str]:
        """Yield text deltas. Raises UnsupportedFeature if not capable."""

    @abstractmethod
    def list_models(self) -> list[str]: ...

    def health_check(self) -> HealthStatus:
        try:
            models = self.list_models()
            return HealthStatus(ok=True, message="Connected", models=models)
        except Exception as exc:  # mapped errors carry user_message
            msg = getattr(exc, "user_message", str(exc))
            return HealthStatus(ok=False, message=msg)

    # -- structured output ---------------------------------------------------

    def structured(
        self,
        messages: list[ChatMessage],
        schema: type[S],
        *,
        max_repair_attempts: int = 1,
        min_output_tokens: int | None = None,
        validate_result: Callable[[S], str | None] | None = None,
        **overrides,
    ) -> S:
        """Get a completion validated against `schema`.

        The shape is communicated as a concrete example object rather than raw
        JSON Schema — see ``prompts.schema_hint`` for why.

        ``min_output_tokens`` raises the output budget for this call when the
        configured ``max_tokens`` is too small for the expected result. A
        truncated JSON response is *worse* than an error: the balanced-delimiter
        scan can recover a shorter valid object from it, which then validates as
        a mostly-empty result and looks like the model simply found nothing.

        ``validate_result`` is a semantic check run after schema validation. It
        returns an error message to trigger a repair round-trip, or None to
        accept. Schema validation alone is not enough: models with every field
        optional will happily return ``{}``.
        """
        instruction = (
            schema_hint(schema)
            + "\n\nOutput only the JSON object — no prose, no explanation, no code fences."
        )
        augmented = [*messages, ChatMessage(Role.USER, instruction)]

        if min_output_tokens and overrides.get("max_tokens", self.config.max_tokens) < (
            min_output_tokens
        ):
            overrides["max_tokens"] = min_output_tokens

        text = self.chat(augmented, json_mode=True, **overrides).text
        last_error: Exception | None = None
        for attempt in range(max_repair_attempts + 1):
            try:
                data = extract_json(text)
                result = schema.model_validate(data)
                problem = validate_result(result) if validate_result else None
                if problem is None:
                    return result
                last_error = OutputParseError(problem, raw_output=text)
                error_message = problem
            except (JsonExtractionError, ValidationError) as exc:
                last_error = exc
                error_message = _short(str(exc))
            if attempt == max_repair_attempts:
                break
            repair = (
                f"That response was not usable. Problem: {error_message}\n"
                "Return ONLY a corrected JSON object in the shape given above."
            )
            text = self.chat(
                [*augmented, ChatMessage(Role.ASSISTANT, text), ChatMessage(Role.USER, repair)],
                json_mode=True,
                **overrides,
            ).text
        raise OutputParseError(
            "The AI response could not be parsed into the expected format.",
            raw_output=text,
            detail=str(last_error),
        )

    # -- shared HTTP helpers -------------------------------------------------

    def _client(self, request_timeout_s: float | None = None) -> httpx.Client:
        timeout_s = request_timeout_s or self.config.timeout_s
        return httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10))

    def _map_transport_error(
        self, exc: Exception, request_timeout_s: float | None = None
    ) -> Exception:
        if isinstance(exc, httpx.TimeoutException):
            timeout_s = request_timeout_s or self.config.timeout_s
            return ProviderTimeout(
                f"{self.config.name or self.config.kind} did not respond within "
                f"{timeout_s:g} seconds. The model may still be loading or generating; "
                "you can increase its timeout in Settings → AI providers.",
                detail=str(exc),
            )
        if isinstance(exc, httpx.TransportError):
            return ProviderUnavailable(
                f"Could not reach {self.config.effective_base_url()}. "
                "Check the URL and your network.",
                detail=str(exc),
            )
        return exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        status = response.status_code
        detail = _short(response.text)
        if status in (401, 403):
            raise AuthError("Authentication failed — check your API key.", detail=detail)
        if status == 404 and self.config.model and self.config.model in response.text:
            raise ModelNotFoundError(
                f"Model '{self.config.model}' was not found on this provider.", detail=detail
            )
        if status == 429:
            retry_after = response.headers.get("retry-after")
            raise RateLimitError(
                "Rate limit reached. Wait a moment and try again.",
                retry_after_s=float(retry_after) if retry_after else None,
                detail=detail,
            )
        if status >= 500:
            raise ProviderUnavailable(
                "The provider reported a server error. Try again later.", detail=detail
            )
        raise ProviderUnavailable(f"Provider returned HTTP {status}.", detail=detail)


def _short(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
