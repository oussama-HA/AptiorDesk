# Privacy

AptiorDesk is a desktop application that runs on your computer. **We — the
maintainers — receive nothing.** There is no AptiorDesk server, no account, no
telemetry, and no analytics. This document describes exactly what the software
does with your data, so you can verify the claims rather than trust them.

## What is stored, and where

Everything lives in a single SQLite database plus a few files in your user
data directory:

| Platform | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\AptiorDesk\` |
| macOS | `~/Library/Application Support/AptiorDesk/` |
| Linux | `~/.local/share/AptiorDesk/` |

That directory contains:

- `aptiordesk.db` — profile, resumes and their versions, jobs and analyses,
  tailoring suggestions, cover letters, interview questions/answers/feedback,
  provider configuration, and UI settings.
- `models/` — the local speech model, if you enabled voice practice.
- `scratch/` — temporary WAV recordings awaiting transcription.
- `logs/` — application logs (see *Logging* below).

The app never writes your personal data anywhere else.

## What leaves your computer

**Only after an explicit action.** AptiorDesk makes no background job-search
requests. AI actions go only to the provider you configure.

| Action | What is sent | Where |
|---|---|---|
| Capture the active browser job | Reviewed job fields from the active tab | AptiorDesk on `127.0.0.1` only |
| Analyze a job posting | The job description text | Your configured provider |
| Import a resume | The resume's extracted text | Your configured provider |
| Job-fit analysis | Job description + resume | Your configured provider |
| Tailor a resume | Job description + structured resume | Your configured provider |
| Cover letter | Job description + resume + profile + your notes | Your configured provider |
| Interview questions | Job description + resume | Your configured provider |
| Answer feedback | The question, your answer, and your resume | Your configured provider |
| Session report | The interview transcript | Your configured provider |

If your provider is **Ollama or another local endpoint, nothing leaves the
machine at all** — the request goes to `localhost`.

If your provider is a cloud service (OpenAI, Anthropic, Gemini, OpenRouter,
Groq, …), the listed content is sent to **that provider only**, under their
privacy policy and data-retention terms. Read your provider's policy — some
retain API inputs for abuse monitoring, and some use inputs for training
unless you opt out.

The **Privacy & Data** page inside the app shows which provider is active and
whether it is local, in plain language.

Optional local model downloads happen only after you explicitly confirm them.
AptiorDesk does not send job-search queries to external job sources.

The optional, separately distributed proprietary companion extension declares
HTTP(S) host access so Chromium can
reliably inject its extractor from a persistent side panel. The implementation
uses that permission only after you press **Capture this job**, and only against
the active tab. It does not request the `tabs` permission, enumerate other tabs
or windows, crawl, search, apply, or run page automation in the background. It
shows an editable preview and sends approved job information only to the loopback bridge at
`127.0.0.1:8765`. The bridge accepts only the centrally configured official
Chrome extension origin, rejects ordinary pages and other extensions, and issues the
companion a random, in-memory session token automatically. That token changes
whenever AptiorDesk restarts and is never written to the database or a backup.

The extension source and store package are not part of this open-source
repository or its Apache-2.0 license. This repository contains the desktop-side
loopback bridge so its validation, authorization, and persistence behavior can
be audited independently.

## Voice recordings

Spoken answers are recorded to a temporary WAV file and transcribed by
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) **running on your
computer**. Audio is never uploaded — not to us, not to your AI provider. Only
the resulting text follows the table above when you ask for feedback.

Voice input is optional. Packaged releases include its runtime; source
contributors install the `[voice]` extra.

## API keys

API keys are stored in your operating system's credential manager (Windows
Credential Locker, macOS Keychain, Linux Secret Service) via the `keyring`
library. Keys are **never** written to the database, config files, logs, or
backups. If no secure credential store is available, AptiorDesk refuses to store
the key rather than fall back to plaintext.

Keys are transmitted only to the provider endpoint you configured for them.

## Device AI command-line tools

You may choose an installed Codex CLI, Claude Code, or Gemini CLI as the active
AI provider. AptiorDesk does not store or copy that tool's credentials. It
starts the selected executable directly without a shell, passes the task on
standard input, and captures the response. Each request runs in a new empty
temporary folder so the CLI cannot inspect the AptiorDesk project or your
documents through its working directory.

Running the executable on your device does **not** mean the model is local. The
CLI may transmit the prompt—including the relevant resume, job description, or
interview text—to the service and account configured in that CLI. Review that
provider's privacy settings before enabling it.

## Logging

Logs go to `logs/aptiordesk.log` in the data directory and stay on your machine.
A redaction filter scrubs credential-shaped strings (`sk-…`, `AIza…`,
`x-api-key: …`, PEM private keys) before anything is written. Document bodies
— resumes, job descriptions, interview answers — are not logged; the code logs
lengths and identifiers instead.

## Your control

From **Privacy & Data** in the app you can:

- **Export a backup** — a zip of readable JSON containing all your data.
  API keys are deliberately excluded.
- **Restore a backup** — replaces local data with the backup's contents.
- **Delete all local data** — permanently erases the database, temporary
  recordings, and every stored API key, with an optional wipe of downloaded
  speech models. This requires typing `DELETE` to confirm and cannot be undone.

You can also simply delete the data directory; AptiorDesk keeps nothing outside
it.

## Third parties

External services are limited to the AI provider you choose and optional
one-time local-model downloads. Browser job capture communicates only with the
AptiorDesk process on this computer. AptiorDesk has no maintainer-operated server.

## Changes

Material changes to this document will be noted in
[CHANGELOG.md](CHANGELOG.md).
