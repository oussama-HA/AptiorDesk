# AptiorDesk product architecture

AptiorDesk is a local-first assistant for the evidence-heavy parts of finding
and preparing for a job: maintaining a trustworthy candidate profile, keeping
resume versions, capturing postings, comparing fit, tailoring materials,
writing grounded cover letters, and practicing interviews.

## Product principles

### Evidence before claims

Candidate facts and accomplishments are the source of truth. Generated claims
must trace to profile or resume evidence, or explicitly ask the user to fill a
gap. Model output never silently becomes user data.

### Browser capture, not background search

The separately distributed companion browser extension is the only
job-ingestion path. It reads the active public job page only after the user
presses Capture, sends reviewed fields to the loopback bridge, and never
crawls, searches, applies, or automates an account. Its proprietary source and
store package are outside this repository.

### Human-reviewed transformations

Resume extraction, tailoring suggestions, cover letters, and interview
feedback remain reviewable. Immutable resume and document versions preserve
the exact source material behind later work.

### Local by default

There is no AptiorDesk account, telemetry, background sync, or
maintainer-operated server. Network activity happens only after a clear user
action and goes only to the configured AI provider or an explicitly confirmed
local-model download.

### Optional AI

Profiles, document editing, captured jobs, versions, exports, backups, and data
deletion work without an AI provider. AI is reserved for language extraction,
comparison, drafting, and feedback.

## Active workflow map

```text
Candidate profile ──► Resume versions ──► Tailoring sessions
        │                    │                    │
        │                    └──────────────┐     └──► New resume version
        │                                   │
Browser job capture ──► Saved job ──► Job analysis / fit comparison
                                  │
                                  ├──► Grounded cover-letter versions
                                  └──► Interview sessions / answers / feedback
```

## Source boundaries

```text
src/aptiordesk/
  app/             bootstrap, desktop shell, navigation, onboarding
  features/        one package per active user workflow
  database/        connection, migrations, models, repositories
  ai/              providers, keyring, versioned prompts, output guards
  integrations/    public loopback protocol bridge for external companions
  documents/       shared import, rendering, and export
  ui/              reusable components, workers, and theme
  core/            identity, storage paths, logging, environment, errors
```

- UI modules present state and delegate business rules.
- Feature services orchestrate repositories and AI providers without depending
  on Qt.
- Repositories own SQLite serialization and transaction boundaries.
- Migrations are forward-only. Destructive retirement migrations first create
  and verify a readable archive.
- Third-party text is untrusted and fenced before entering prompts.
- The canonical product identity lives in one module; legacy identifiers exist
  only inside tested migration and compatibility boundaries.
- The open-source desktop bridge and proprietary companion extension are
  separate release, test, and licensing boundaries.

## AI capability contract

Every AI action defines:

- the explicit user action authorizing it;
- the minimum context required;
- the structured output schema;
- evidence requirements for candidate-facing claims;
- prompt and schema versions;
- deterministic validation and repair behavior;
- provider and model capability requirements;
- fixture-based tests that never call a paid API.

## Near-term direction

- Normalize accomplishments, skills, metrics, STAR stories, and provenance
  into reusable evidence records.
- Build a unified job workspace around the posting snapshot, analysis,
  materials, and interview preparation without recreating application-status
  management.
- Add opt-in, dated, source-cited company research while preserving a fully
  functional offline mode.
- Improve extraction evaluation across real-world PDF and DOCX layouts.
