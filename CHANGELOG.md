# Changelog

All notable changes to the open-source AptiorDesk desktop application are
documented here. The separately distributed proprietary browser extension has
its own release history and is intentionally not represented in this repository.
The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Centralized the official Chrome companion identity and restricted automatic
  pairing, CORS, and job imports to that exact production extension origin.

### Changed

**First-run setup and progress**

- Rebuilt AI-provider onboarding around equal local/cloud choice cards with
  contextual configuration, clear cost/privacy labels, and whole-card
  selection.
- Reduced the AI choice to two balanced, keyboard-accessible surfaces and
  reveal only the setup details for the selected local or cloud path.
- Standardized long-running task feedback: real percentages, byte totals, and
  estimated time are shown when the underlying operation reports them;
  unmeasurable initialization is explicitly labeled indeterminate.
- Added real progress and cancellation for streamed Ollama model downloads;
  the default speech model is now staged during release builds instead of
  downloaded after launch.

**Mock interview experience**
- Kokoro, its ONNX runtime, and the complete local voice model are now standard
  AptiorDesk components included in fresh installations rather than an
  optional add-on.
- Ari now selects one validated facial-control family at a time, uses
  eyelid-only ARKit blink targets, and starts from a restrained lowered-arm
  pose instead of compounding aliases and crossing both hands over the torso.
- Kokoro speech now produces audio-energy-aware IPA mouth cues so pauses,
  consonants, and vowel shapes track the generated waveform.
- Interview Voice settings use a responsive, scroll-safe two-column layout and
  show only the controls supported by the selected provider.
- Interview preparation now has one clear Start action; the obsolete question
  preview workflow and its unused AI response field have been removed.
- Recorded answers save and advance immediately. Feedback is generated once,
  from the complete transcript, in a guarded final-report flow that prevents
  duplicate reports and changes End Interview to Exit Interview when ready.
- Microphone answers now show bounded, CPU-safe live transcription chunks
  without repeatedly processing the whole recording.

**Resume workflows**
- Added a deterministic Job Fit Ratio with persisted current-versus-tailored
  comparison, visible improvement, weighted factor evidence, and explicit
  critical-qualification penalties. AI writes the narrative but never chooses
  the score.
- Individual resume versions can be deleted without deleting the resume;
  dependency checks protect tailored-resume history and the final version.
- Resume Tailoring now lists every generated tailored version and opens the
  selected result directly in the Resumes workspace.

**Interface readability**
- AptiorDesk now uses a single, purpose-built dark theme. Existing saved light
  preferences are migrated safely to dark on startup.
- Increased the global type scale and text contrast, and improved rich-text
  heading, paragraph, and line spacing for easier scanning.
- The Profile page's **Your background** section now stays top-aligned and
  grows only to fit its active tab, eliminating the large empty areas above
  and below empty or short lists.
- Desktop styling now uses logo-derived design tokens, led by the exact coral
  `#FF5757` from the supplied artwork.
- Every desktop combobox now uses one shared dropdown control with consistent
  popup sizing, option height, scrolling, focus, selected states, text elision,
  keyboard behavior, and full-label tooltips.
- The desktop-side job-import bridge now exposes a narrow, authenticated
  loopback protocol for the separately distributed companion extension.

### Added

**Activity feedback and branding**
- Prominent animated progress windows for user-initiated AI, provider,
  transcription, and setup tasks, with task-specific details and elapsed time.
- Official AptiorDesk artwork as the desktop, window, and installer icon.

**AI providers**
- Device CLI provider with reviewed adapters for Codex CLI, Claude Code, and
  Gemini CLI, automatic `PATH` discovery, executable selection, CLI-owned
  authentication, connection testing, and optional model overrides.
- CLI requests use argument arrays rather than a user-editable shell command,
  send prompt content over stdin, run in an isolated temporary directory, and
  execute serially for multi-section resume extraction.

**Getting started**
- A signed-installer-ready Windows setup installs the immutable desktop and
  Kokoro runtimes plus the default offline speech-to-text model, verifies voice
  and model health, creates shortcuts, supports repair installs, and preserves
  user data during upgrades.
- First-run setup wizard: privacy explainer, AI provider setup (detects a
  running Ollama, recommends models with sizes and RAM requirements, and
  downloads the chosen one with live progress — or accepts a cloud API key),
  optional voice-support install, and profile basics, ending in a summary of
  what is ready and what was skipped. Re-runnable from Settings.
- Nothing downloads or installs without an explicit press, every download
  states its size first, and package installation is restricted to a fixed
  allow-list so no config or model output can reach pip.

**Candidate profile**
- Structured profile: contact details, summary, career preferences, work
  authorization, and entries for experience, education, skills, projects,
  certifications, languages, awards, publications, and volunteering.
- Opt-in one-time import from the legacy `config.json` of the previous
  prototype.

**Resumes**
- Import from PDF, DOCX, TXT, and Markdown with a size cap, extension and
  magic-byte validation, and clear errors for encrypted or image-only PDFs.
- AI-assisted structuring with a **mandatory review step** — extraction is
  never saved without your correction.
- Immutable versions: edits, restores, and tailoring all create new versions.
  Side-by-side diff comparison between any two versions.
- Download controls for every selected resume version in PDF and DOCX formats.

**Jobs**
- Structured extraction from a pasted posting: responsibilities, required and
  preferred qualifications, skills, tools, education, salary, work
  authorization, keywords, red flags, and missing information.
- Job-fit analysis separating strong matches, partial matches, missing
  qualifications, and transferable experience — each backed by evidence from
  your own materials. No fabricated "ATS score"; the methodology and its
  limits are stated instead.

**Resume tailoring**
- Suggestion-based workflow across seven strategies (ATS, recruiter,
  technical, executive, career change, entry level, balanced).
- Every suggestion shows what changed, why, which part of the posting motivated
  it, and which part of your background supports it.
- Posting-analysis keywords and truthfully supported job-fit keywords now feed
  the tailoring prompt, with semantic coverage validation to prevent the model
  from silently ignoring them.
- Evidence-backed missing skills can be proposed as explicit additions. The
  validator rejects duplicates, job-irrelevant terms, and additions whose
  cited candidate evidence cannot be grounded in the resume.
- Suggestions targeting fields that do not exist are discarded; suggestions
  containing numbers absent from your materials are flagged, not applied.
- Accept, reject, or edit each suggestion; applying creates a new version and
  leaves the original untouched.

**Cover letters**
- Generation from job + resume + profile + your own words about motivation,
  the company, and any personal connection.
- Eight tones and three lengths; explicit anti-cliché instructions.
- Shows which experiences it drew on and why, and flags claims you should
  confirm before sending.
- Versioned; editing carries the rationale forward.

**Interview practice**
- Question generation by stage (ten stages), category, count, and difficulty,
  grounded in the posting and your resume — including the uncomfortable
  questions, but only where your materials actually show such a situation.
- Mock interviews with six interviewer personas, one question at a time, and
  adaptive follow-ups (capped at two per question). Feedback is withheld until
  you submit, as in a real interview.
- Structured feedback: per-dimension scores, STAR assessment, missing
  specifics phrased as questions, red flags, and a stronger rewrite built only
  from what you actually said.
- Retry a question (earlier attempts are kept), save answers to a library, and
  get an end-of-session report.

**Voice practice** (optional `[voice]` extra)
- Microphone recording with a live level meter.
- Local speech-to-text via faster-whisper — audio never leaves your computer;
  the model downloads once after you confirm.
- Delivery analysis: speaking pace, filler words, and answer-length guidance.

**Privacy and data control**
- Privacy & Data page showing what is stored, where it lives, and whether your
  active AI provider is local or remote.
- Backup to a readable JSON zip (never containing API keys), restore, and
  permanent delete-all-data with typed confirmation.

**AI layer**
- Bring-your-own-key support for Ollama, any OpenAI-compatible endpoint
  (OpenAI, LM Studio, OpenRouter, Groq, Together, Mistral, …), Anthropic, and
  Google Gemini, with capability detection and uniform error handling for
  invalid keys, rate limits, timeouts, and outages.
- API keys stored in the OS keyring only; the app refuses plaintext storage.
- Structured output validated against schemas, with automatic repair retry and
  robust JSON extraction.
- Versioned prompt templates; every stored analysis records the prompt id and
  version that produced it.

### Changed

- The bottom-left provider card now refreshes immediately after adding,
  editing, removing, or activating an AI provider in Settings.
- Renamed the product and canonical Python package to AptiorDesk, with verified
  migration of the legacy local database, keyring, backup, extension, and
  launcher identifiers.
- Removed the former planning and application-status workspaces. Existing
  records are exported to a checksummed local migration archive before their
  tables are retired.
- Reorganized the source tree around active product features, database,
  application shell, AI, integrations, shared documents, and UI components.
- Browser capture is the only job-ingestion workflow; obsolete direct-search
  adapters, source credentials, filters, and tests were removed.

- Replaced the previous prototype (a live interview-assistance tool using
  PyQt5, qfluentwidgets, and Google Cloud Speech) with a local-first job
  hunting assistant on PySide6. The prototype's history is preserved at the
  `v0-legacy` tag.
- Relicensed to MIT, which the move off GPL-licensed Qt bindings made possible.

### Removed

- Live interview transcription and the associated Google Cloud dependency.
- Committed service-account credentials and personal data from the prototype
  (the exposed key was revoked separately).

### Fixed

- Mock interview question generation now uses an AI-only draft schema that
  cannot supply database IDs, follow-up flags, or parent-question references.
  Generated question sets are saved atomically, and failed preparation removes
  its empty session instead of leaving stale active records.
- Resume tailoring now uses an operation-aware response deadline of at least
  five minutes across HTTP, Ollama, and device CLI providers instead of being
  terminated by the standard 60-second request timeout. Connection failures
  still surface quickly, and longer user-configured timeouts are preserved.
- Mock interview question generation, feedback, follow-up decisions, and
  session reports now keep SQLite persistence on the connection-owning UI
  thread while AI work runs in background workers.

- Captured-job rows reserve enough height for two-line titles, scroll smoothly,
  and preserve the selected job by id during refreshes so analysis completion
  no longer leaves an empty detail pane or clipped list item.
- Local speech-to-text no longer fails on machines that report a CUDA device
  but lack the CUDA runtime libraries: device selection now verifies cuBLAS
  loads, and inference falls back to CPU rather than losing the recording.
- JSON extraction from model output no longer truncates nested objects (the
  prototype's regex stopped at the first closing brace).
