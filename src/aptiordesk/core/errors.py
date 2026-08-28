"""Application-level exception hierarchy."""


class AptiorDeskError(Exception):
    """Base class for all AptiorDesk errors. `user_message` is safe to display."""

    def __init__(self, user_message: str, *, detail: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


class DataError(AptiorDeskError):
    """Local database or persistence failure."""


class DocumentError(AptiorDeskError):
    """Document import/export failure (bad file, too large, unparseable)."""


class KeystoreUnavailable(AptiorDeskError):
    """No OS keyring backend available; API keys cannot be stored securely."""
