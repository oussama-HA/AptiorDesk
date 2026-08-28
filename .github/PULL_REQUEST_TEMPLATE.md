## What this changes

## Why

## How you verified it

Describe what you actually ran — not just that tests pass. If you exercised
the change in the running app, say what you did and what you saw.

- [ ] `pytest` passes
- [ ] `ruff check src tests` passes
- [ ] Exercised the affected flow in the app

## Project rules

- [ ] No feature fabricates candidate information (experience, metrics,
      credentials)
- [ ] No data is sent anywhere without an explicit user action
- [ ] API keys are not written to the database, files, logs, or exports
- [ ] Untrusted text (job descriptions, resumes, answers) passes through
      `wrap_untrusted`
- [ ] User content is never silently overwritten
- [ ] If a prompt template changed, its `version` was bumped
- [ ] If a table was added, it was added to `_TABLES` in `export_service.py`
