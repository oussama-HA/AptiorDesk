# Contributing to AptiorDesk

Thanks for considering a contribution. AptiorDesk is a job hunting assistant for
people in a stressful situation, so the bar for honesty and correctness is
higher than for a typical side project.

## Ground rules

These are not negotiable, because they are the point of the project:

1. **Never fabricate candidate information.** No feature may invent
   experience, employers, dates, metrics, skills, or credentials. If a
   suggestion would be stronger with a fact the user has not provided, ask the
   user for it or use an explicit `[placeholder]` — never guess.
2. **Nothing leaves the machine without the user's action.** No telemetry, no
   analytics, no "anonymous usage stats", no background requests.
3. **API keys stay in the OS keyring.** Never write them to the database,
   files, logs, or exports.
4. **Untrusted text stays fenced.** Job descriptions, resumes, and answers go
   through `ai.prompts.guards.wrap_untrusted` before entering a prompt.
5. **Never silently overwrite the user's content.** Edits create new versions;
   destructive actions require confirmation.
6. **Don't ship placeholder UI.** Incomplete experiments stay outside the
   production navigation and package.

## Getting set up

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    POSIX: source .venv/bin/activate
pip install -e ".[dev]"          # add ,voice for microphone + local STT
python -m aptiordesk
```

For AI features, install [Ollama](https://ollama.com), `ollama pull gemma3`,
then add it in Settings → AI Providers.

## Running checks

```bash
pytest                                   # full suite
QT_QPA_PLATFORM=offscreen pytest         # headless (as CI runs it)
ruff check src tests
ruff check --fix src tests
mypy src/aptiordesk
python -m build
```

**Tests must never call a paid AI API.** Provider adapters are tested against
mocked HTTP (`respx`); services are tested with `tests/helpers.ScriptedProvider`,
which returns canned responses. If your change needs a new AI interaction, add
a scripted fixture for it.

## Project layout

```
src/aptiordesk/
  app/          bootstrap, shell, navigation, onboarding
  features/     pages and business services grouped by workflow
  database/     db, SQL migrations, pydantic models, repositories
  ai/           providers, keyring, prompts, JSON parsing, guards
  integrations/ public loopback bridge for separately distributed companions
  documents/    shared import and export
  ui/           reusable components, workers, theme
  core/         identity, storage, environment, logging, errors
```

UI code should not talk to repositories directly for anything non-trivial —
put the logic in a service so it can be tested without Qt.

## Database changes

Migrations are forward-only numbered SQL files in `database/migrations/`, applied
in order and tracked with `PRAGMA user_version`. Add a new file
(`000N_description.sql`); never edit one that has shipped. Keep to plain DDL —
the runner splits on semicolons and does not handle triggers or semicolons
inside string literals.

If you add a table, add it to `_TABLES` in `features/privacy/service.py` so it
is included in backups and in delete-all-data, and add a test that a
backup/restore round-trip preserves it.

## Prompt changes

Prompts are versioned Markdown files in `ai/prompts/templates/` with front matter:

```markdown
---
id: job_extraction
version: 2
---
```

**Bump `version` whenever you change a template's text.** The stored analyses
record which prompt id and version produced them, so users can tell what
generated their results. If you change an output schema, update the matching
pydantic model in `ai/prompts/` or `database/models/` and the tests that
exercise it.

Every template that includes user or third-party content must include
`{untrusted_preamble}` and pass that content through `wrap_untrusted`.
Templates that generate candidate-facing claims must include
`{fabrication_rules}`.

## Pull requests

- Keep PRs focused; one concern per PR.
- Include tests for behaviour you add or fix.
- Run `pytest` and `ruff check` before pushing.
- Describe what you changed **and how you verified it actually works** — if you
  exercised it in the running app, say so.
- If you found a real bug while testing, mention it; that is the most valuable
  part of the report.

## Reporting bugs

Include your OS, Python version, which AI provider you were using (never paste
your key), what you expected, what happened, and the relevant part of
`logs/aptiordesk.log`. Check the log for personal information before pasting it.

Security issues go through [SECURITY.md](SECURITY.md), not the public tracker.
