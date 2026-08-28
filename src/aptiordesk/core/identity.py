"""Stable product identity and transitional compatibility identifiers."""

from __future__ import annotations

PRODUCT_NAME = "AptiorDesk"
PRODUCT_SLUG = "aptiordesk"

DATA_DIR_NAME = PRODUCT_NAME
DATABASE_NAME = f"{PRODUCT_SLUG}.db"
LOG_NAME = f"{PRODUCT_SLUG}.log"
KEYRING_SERVICE = f"{PRODUCT_SLUG}-ai"
BACKUP_MANIFEST = f"{PRODUCT_SLUG}-backup.json"
BROWSER_TOKEN_HEADER = "X-AptiorDesk-Token"
LOG_LEVEL_ENV = "APTIORDESK_LOG_LEVEL"

# Read-only compatibility identifiers. They are deliberately centralized so
# they can be removed after the transition window without another repo-wide
# archaeology exercise.
LEGACY_PRODUCT_NAME = "OpenHire"
LEGACY_DATA_DIR_NAME = LEGACY_PRODUCT_NAME
LEGACY_DATABASE_NAME = "openhire.db"
LEGACY_LOG_NAME = "openhire.log"
LEGACY_KEYRING_SERVICE = "openhire-ai"
LEGACY_BACKUP_MANIFEST = "openhire-backup.json"
LEGACY_BROWSER_TOKEN_HEADER = "X-OpenHire-Token"
LEGACY_LOG_LEVEL_ENV = "OPENHIRE_LOG_LEVEL"


__all__ = [
    "BACKUP_MANIFEST",
    "BROWSER_TOKEN_HEADER",
    "DATABASE_NAME",
    "DATA_DIR_NAME",
    "KEYRING_SERVICE",
    "LEGACY_BACKUP_MANIFEST",
    "LEGACY_BROWSER_TOKEN_HEADER",
    "LEGACY_DATABASE_NAME",
    "LEGACY_DATA_DIR_NAME",
    "LEGACY_KEYRING_SERVICE",
    "LEGACY_LOG_NAME",
    "LEGACY_LOG_LEVEL_ENV",
    "LEGACY_PRODUCT_NAME",
    "LOG_NAME",
    "LOG_LEVEL_ENV",
    "PRODUCT_NAME",
    "PRODUCT_SLUG",
]
