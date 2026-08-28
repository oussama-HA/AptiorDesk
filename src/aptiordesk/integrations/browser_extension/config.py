"""Single source of truth for the proprietary companion integration.

The extension is distributed separately from this repository. Keeping its
public identity here prevents the loopback bridge, diagnostics, installer
copy, and settings UI from drifting to different production IDs.
"""

from __future__ import annotations

EXTENSION_ID = "lplgadbgmnaglcclkmhhpnmnapaahmpk"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
ALLOWED_EXTENSION_ORIGINS = (EXTENSION_ORIGIN,)

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
BRIDGE_BASE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"

CHROME_WEB_STORE_URL = f"https://chromewebstore.google.com/detail/{EXTENSION_ID}"

# Reserved for a future native-messaging transport. The current production
# extension uses the authenticated loopback bridge; no native host is
# registered until the desktop app implements Chrome's stdio protocol.
NATIVE_MESSAGING_HOST = "io.glidd.aptiordesk"

__all__ = [
    "ALLOWED_EXTENSION_ORIGINS",
    "BRIDGE_BASE_URL",
    "BRIDGE_HOST",
    "BRIDGE_PORT",
    "CHROME_WEB_STORE_URL",
    "EXTENSION_ID",
    "EXTENSION_ORIGIN",
    "NATIVE_MESSAGING_HOST",
]
