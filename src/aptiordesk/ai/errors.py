"""Provider-agnostic AI error types. Every adapter maps HTTP/transport
failures onto these so the UI can react uniformly."""

from aptiordesk.core.errors import AptiorDeskError


class AIError(AptiorDeskError):
    """Base class for AI-layer failures."""


class AuthError(AIError):
    """Invalid or missing API key (HTTP 401/403)."""


class RateLimitError(AIError):
    def __init__(self, user_message: str, *, retry_after_s: float | None = None, detail=None):
        super().__init__(user_message, detail=detail)
        self.retry_after_s = retry_after_s


class ModelNotFoundError(AIError):
    """Requested model does not exist on the provider."""


class ProviderTimeout(AIError):
    """The provider did not respond within the configured timeout."""


class ProviderUnavailable(AIError):
    """Network failure or provider downtime (connect error, 5xx)."""


class UnsupportedFeature(AIError):
    """The provider does not support the requested capability."""


class OutputParseError(AIError):
    """The model's output could not be parsed/validated against the schema."""

    def __init__(self, user_message: str, *, raw_output: str = "", detail=None):
        super().__init__(user_message, detail=detail)
        self.raw_output = raw_output
