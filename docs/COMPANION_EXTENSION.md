# AptiorDesk companion extension

The AptiorDesk browser extension is a separately distributed proprietary
companion product. It is not part of this open-source repository and is not
licensed under this repository's Apache License 2.0.

This repository intentionally contains only the desktop-side integration
boundary:

- a loopback-only HTTP bridge bound to `127.0.0.1`;
- the validated job-import payload schema;
- automatic, per-process pairing;
- origin, size and authorization checks;
- health diagnostics and connection status;
- tests for the public protocol and persistence boundary.

The official production extension identity is defined once in
`src/aptiordesk/integrations/browser_extension/config.py`. The bridge accepts
only that exact Chrome extension origin; Settings and diagnostics read the
same configuration. Do not duplicate or override the ID elsewhere.

The current production transport is the authenticated loopback API. The
central configuration reserves a native-messaging host name, but AptiorDesk
does not register a native host because no stdio native-messaging transport is
implemented. This avoids shipping a misleading or non-functional manifest.

It does **not** contain the extension manifest, extraction engine, side-panel
UI, browser background worker, store assets, unpacked build, or extension
tests. Those are developed and published separately.

The boundary lets contributors review the desktop application's security and
data handling without granting rights to the companion extension. A compatible
client still must satisfy the bridge's origin and ephemeral-token checks; the
public bridge is not an invitation to impersonate AptiorDesk trademarks or
redistribute the proprietary companion.

When the official Chrome Web Store listing is available, the product website
and AptiorDesk's Settings screen will link to it. End users should never need
Developer mode, an unpacked folder, Python, or a manual pairing key.
