# Repository structure

AptiorDesk uses a standard Python `src` layout with domain-oriented feature
boundaries. It intentionally avoids a JavaScript-style monorepo structure
because the desktop application, local services, database, and UI ship as one
versioned Python product.

```text
src/aptiordesk/
  app/            application startup, shell, navigation, onboarding
  features/       jobs, resumes, tailoring, letters, profile, interviews, settings
  ai/             providers, prompts, validation, orchestration
  database/       connection ownership, migrations, repositories, models
  documents/      secure import, rendering, PDF and DOCX export
  integrations/   desktop-side protocols for external products and services
  ui/             shared controls, layout, theme, and design tokens
  core/           paths, identity migration, logging, diagnostics
installer/
  windows/        Inno Setup source and installer-facing documentation
packaging/        PyInstaller configuration and platform build metadata
models/kokoro/    verified neural voice assets shipped in release builds
scripts/          repeatable build and verification commands
tests/            unit, UI, integration, and end-to-end coverage
docs/             architecture, privacy, contribution, and release guidance
```

## Browser extension boundary

The browser extension is a separately distributed proprietary companion and is
not stored in this repository. The only extension-related code retained here is
the desktop loopback bridge in
`src/aptiordesk/integrations/browser_extension/bridge.py`. It owns the local
protocol, authentication, validation, and job import boundary used by the
desktop application. The official production identity and loopback endpoint
have one source of truth in
`src/aptiordesk/integrations/browser_extension/config.py`.

Do not add extension manifests, scripts, styles, packaged archives, or extension
tests to this repository. The root `.gitignore` enforces this boundary.

## Dependency direction

Feature UI may call its feature services and shared UI controls. Business logic
may call database repositories, AI orchestration, document services, or
integration protocols. Shared and database layers must not import feature UI.
This keeps worker/thread boundaries testable and prevents circular dependencies.
