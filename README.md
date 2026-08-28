# AptiorDesk

**A privacy-first, local-first job hunting assistant.** Tailor your resume to a
specific role, write cover letters that are actually grounded in your
experience, practice realistic mock interviews out loud, and capture job
postings from your browser — with your data on your own machine and the AI provider of
*your* choice.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

[Website](https://aptiordesk.netlify.app) · [Windows download](https://github.com/oussama-HA/AptiorDesk/releases/latest/download/AptiorDesk-Windows-x64-Setup.exe) · [Releases](https://github.com/oussama-HA/AptiorDesk/releases)

> **Status: pre-release (v0.1.0 in preparation).** Every feature below is
> implemented and tested. Expect rough edges, and please report them.

Created by **Oussama Hamida** at **[Glidd.io](https://glidd.io)**.

## Why this exists

Most résumé and interview tools are web services that want your employment
history, your salary expectations, and your practice interview answers on
their servers. Those are among the most sensitive documents a person produces,
and they are being handed over at the most vulnerable moment in someone's
career.

AptiorDesk is the opposite arrangement:

- **Local by default.** Everything is stored in a SQLite database on your
  computer. No account, no server, no telemetry, no analytics.
- **Your AI, your key.** Run a local model through Ollama and *nothing* leaves
  your machine. Or bring your own API key for a cloud provider — the app tells
  you exactly what gets sent and where.
- **It will not lie for you.** No feature invents experience, employers,
  metrics, or credentials. Every tailoring suggestion cites the part of your
  background that supports it, and numbers that do not appear in your
  materials are flagged rather than quietly inserted.

## What it does

**Workspace overview** — shows the state of your profile, resumes, captured
jobs, analyses, tailored materials, and interview practice, then points to the
next useful workflow without inventing activity targets.

**Universal browser capture** — the separately distributed AptiorDesk
companion extension is the only job-ingestion path. Its side panel captures the
current public job page after a user action. Pairing with the desktop app is
automatic and local; it does not crawl sites, run searches, or automate an
account. The extension is proprietary, is delivered through the Chrome Web
Store, and is intentionally not included in this repository.

**Profile** — one structured record of your experience, education, skills,
projects, preferences, and work authorization, reused everywhere else.

**Resumes** — import PDF/DOCX/TXT/Markdown, correct the extracted structure
(always reviewed by you, never trusted blindly), and keep immutable versions
you can diff and restore. Download any selected version as an ATS-friendly PDF
or editable DOCX.

**Jobs** — capture a posting with the browser extension to get structured
requirements, keywords, red flags, and *missing* information. The transparent
Job Fit Ratio compares the current and tailored resume across explicit skills,
experience, seniority, responsibilities, industry, education, keywords,
location/work mode, and authorization requirements. It shows every weighted
factor and critical-gap penalty; the AI never invents the number and the ratio
is not presented as an ATS or hiring prediction.

**Tailoring** — suggestion-by-suggestion resume rewrites across seven
strategies. Each card shows what changed, why, which phrase in the posting
motivated it, and what in your background makes it true. Accept, reject, or
edit each one; applying creates a new version and leaves the original intact.
Keywords from the posting and matching job-fit analysis are carried into the
tailoring brief. Missing skills can be proposed only when the resume contains
grounding evidence, and every addition remains reviewable.

**Cover letters** — grounded in your resume, the posting, and your own words
about why you want the role. Eight tones, three lengths, an explicit
anti-cliché brief, an explanation of which experiences it chose and why, and a
list of claims to confirm before sending. Export to Markdown, TXT, PDF, or
DOCX.

**Interview practice** — question sets by stage and difficulty, including the
uncomfortable ones. Then mock interviews with six interviewer personas that ask
one question at a time, probe vague answers with follow-ups, and withhold
feedback until you have finished — like a real interview. Feedback scores
relevance, clarity, structure, specificity, and evidence, assesses STAR
structure, and rewrites your answer using only what you actually said.

**Voice practice** *(optional)* — answer out loud. Recording is transcribed by
a model running on your computer; you get speaking pace, filler-word counts,
and length guidance alongside the content feedback. **Audio never leaves your
machine.** The interviewer reads questions with the local Kokoro neural voice
by default, or ElevenLabs when the user explicitly configures it. AptiorDesk
does not silently fall back to a browser or operating-system voice. If the
Kokoro runtime is unavailable, the interview loading screen and **Settings →
System setup** provide verified diagnostics and repair guidance. Voice, accent, speed,
supported expression controls, and reduced motion are configurable locally.

**AptiorDesk interviewers** — mock interviews use a curated, built-in 3D
avatar library designed for AptiorDesk's blinking, listening, nodding, and
speech synchronization. Users choose an interviewer from the in-app library;
arbitrary 3D-model uploads are intentionally not supported.

**Privacy & Data** — see what is stored and where, export a full backup,
restore it, or permanently delete everything.

## Install

End users should install a platform release, not run the Python source tree.
The Windows Setup wizard installs AptiorDesk, its managed Python runtime,
Kokoro, ONNX Runtime, espeak-ng/phonemizer data, voice assets, shortcuts,
verification and an uninstaller. Python and terminal commands are not
required. Repair and upgrade installs preserve the AptiorDesk user-data
directory.

Source installation is for contributors:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    POSIX: source .venv/bin/activate
pip install -e ".[dev,voice]"
python -m aptiordesk
```

### First launch

AptiorDesk opens a short setup that gets you working:

1. **Welcome** — the privacy guarantees, in plain language.
2. **System check** — core files, writable storage, database, Kokoro, local
   ports, camera/microphone support, speech-to-text and companion connectivity.
3. **Choose your AI** — it checks whether [Ollama](https://ollama.com) is
   running on your machine, and if so offers a few recommended models with
   their sizes and RAM needs, downloading the one you pick with a live
   progress bar. No Ollama? It links you to the installer, or takes a cloud
   API key instead.
4. **Voice practice** *(optional)* — verifies the bundled neural voice,
   transcription runtime, and default offline speech-to-text model. A missing
   packaged model is handled as an installation repair, not a first-run
   download.
5. **About you** — name, email, and the roles you are after.
6. **Ready** — what is set up, what was skipped, and what to do next.

Required core checks must pass. Feature-specific setup may be skipped, nothing
downloads until you approve it, and all checks can be rerun from **Settings →
System setup**.

If you would rather configure the AI yourself, **Settings → AI Providers**
supports Ollama, Anthropic, Google Gemini, any OpenAI-compatible endpoint
(OpenAI, LM Studio, OpenRouter, Groq, Together, Mistral), and AI command-line
tools installed on your device. Device CLI presets are available for Codex
CLI, Claude Code, and Gemini CLI. AptiorDesk discovers the executable from
`PATH` or lets you select it, while the CLI keeps its own login. API keys added
directly to AptiorDesk go into your operating system's credential manager,
never into a file.

Device CLI calls are non-interactive: prompts are passed through standard
input, not a shell command, and the process runs in a fresh temporary folder.
The executable is local, but the CLI may send your prompt to its configured AI
service; that service's privacy and account policies still apply.

Larger local models produce noticeably better tailoring and feedback. If a
local model returns malformed output, AptiorDesk retries once automatically and
then shows you the raw response rather than guessing.

## Documentation

- [PRIVACY.md](PRIVACY.md) — exactly what is stored, and what is sent where
- [SECURITY.md](SECURITY.md) — threat model, protections, reporting
- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, architecture, project rules
- [CHANGELOG.md](CHANGELOG.md) — release history

- [Repository structure](docs/REPOSITORY_STRUCTURE.md)
- [Companion extension boundary](docs/COMPANION_EXTENSION.md)
- [Asset and model licensing](docs/ASSET_LICENSING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Architecture

```
src/aptiordesk/
  app/          bootstrap, desktop shell, navigation, onboarding
  features/     profile, resumes, jobs, tailoring, letters, interviews, settings
  database/     SQLite, forward-only migrations, models, repositories
  ai/           providers, versioned prompts, schemas, output guards
  integrations/ loopback protocol bridge for the external companion extension
  documents/    shared PDF/DOCX/TXT/Markdown import and export
  ui/           shared components, background workers, theme
installer/      native installer definitions and installer guidance
packaging/      platform-native freezing and release metadata
tests/          unit, UI, integration, and end-to-end coverage
```

Design decisions worth knowing:

- **Plain `sqlite3` with a repository layer**, not an ORM — one user, about two
  dozen focused tables, no session/threading traps.
- **Deterministic persistence, optional AI.** Browsing saved data, editing
  profiles and resumes, backups, exports, and document versioning work without
  a configured model.
- **Untrusted text is fenced** before entering any prompt, and fence markers in
  the content are stripped so a malicious posting cannot forge a boundary.
- **Model output is never trusted**: validated against schemas, tailoring
  targets are verified against the real document, invented numbers are flagged.
- **PDF export uses Qt's own text engine**, avoiding a heavyweight native
  dependency.

## Development

```bash
pip install -e ".[dev]"
pytest                              # tests never call a paid AI API
ruff check src tests
```

## Known limitations

- Output quality depends heavily on the model you choose. Small local models
  produce weaker tailoring and blander feedback than large ones.
- Resume extraction from complex multi-column PDFs is imperfect — which is why
  the correction step is mandatory rather than optional.
- PDF export is clean and ATS-safe but plain; there are no designed templates
  yet.
- Voice transcription accuracy varies with microphone quality and accent, and
  the filler-word list is English-only.
- The local database is not encrypted; use full-disk encryption if that matters
  to you.
- Desktop releases are produced for Windows, macOS, and Linux from the
  platform-native release workflow.

The longer-term product and AI architecture is documented in
[docs/PRODUCT_ARCHITECTURE.md](docs/PRODUCT_ARCHITECTURE.md).
Maintainers preparing a public build should follow the complete
[release and GitHub publication checklist](docs/RELEASING.md).

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md)
first, particularly the ground rules: no fabricated candidate information, no
data leaving the machine without an explicit user action, and no placeholder UI
pretending to be a working feature.

## License and companion products

The AptiorDesk desktop source in this repository is licensed under the
[Apache License 2.0](LICENSE). The AptiorDesk browser extension is a separately
distributed proprietary companion product. Its source, tests, unpacked build,
and store package are not part of this repository or the Apache-2.0 license. See
[COMPANION_EXTENSION.md](docs/COMPANION_EXTENSION.md) and [NOTICE.md](NOTICE.md).

## Credits

AptiorDesk was created by **Oussama Hamida** at
**[Glidd.io](https://glidd.io)**, with contributions from the open-source
community.
