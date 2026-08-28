"""API key storage in the OS keyring (Windows Credential Locker, macOS
Keychain, Secret Service). Keys never touch the database, config files,
exports, or logs. If no secure backend exists we refuse to store keys
rather than fall back to plaintext."""

from __future__ import annotations

import logging

import keyring
import keyring.backends.fail
from keyring.errors import KeyringError

from aptiordesk.core.errors import KeystoreUnavailable
from aptiordesk.core.identity import KEYRING_SERVICE, LEGACY_KEYRING_SERVICE

log = logging.getLogger(__name__)


def available() -> bool:
    backend = keyring.get_keyring()
    return not isinstance(backend, keyring.backends.fail.Keyring)


def _username(provider_id: int) -> str:
    return f"provider-{provider_id}"


def set_secret(name: str, value: str) -> None:
    """Store one named secret. Used for AI provider keys and job-source
    credentials alike — nothing else in the app may write credentials."""
    if not available():
        raise KeystoreUnavailable(
            "No secure credential store is available on this system. "
            "AptiorDesk will not save API keys in plaintext."
        )
    try:
        keyring.set_password(KEYRING_SERVICE, name, value)
    except KeyringError as exc:
        raise KeystoreUnavailable("Failed to store the API key securely.", detail=str(exc)) from exc


def get_secret(name: str) -> str | None:
    if not available():
        return None
    try:
        value = keyring.get_password(KEYRING_SERVICE, name)
        if value is not None:
            return value
        legacy = keyring.get_password(LEGACY_KEYRING_SERVICE, name)
        if legacy is None:
            return None
        # Best-effort copy with read-back verification. The legacy entry is
        # intentionally preserved as a rollback path for the transition.
        try:
            keyring.set_password(KEYRING_SERVICE, name, legacy)
            if keyring.get_password(KEYRING_SERVICE, name) == legacy:
                return legacy
        except KeyringError as exc:
            log.warning("Keyring identity migration failed: %s", exc)
        return legacy
    except KeyringError as exc:
        log.warning("Keyring read failed: %s", exc)
        return None


def delete_secret(name: str) -> None:
    if not available():
        return
    try:
        for service in (KEYRING_SERVICE, LEGACY_KEYRING_SERVICE):
            try:
                keyring.delete_password(service, name)
            except KeyringError:
                pass
    except KeyringError:
        pass  # nothing stored


def set_key(provider_id: int, api_key: str) -> None:
    set_secret(_username(provider_id), api_key)


def get_key(provider_id: int) -> str | None:
    return get_secret(_username(provider_id))


def delete_key(provider_id: int) -> None:
    delete_secret(_username(provider_id))
