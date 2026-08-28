# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

Use GitHub's [private vulnerability
reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
on this repository (Security → Report a vulnerability).

Please include: what the issue is, how to reproduce it, the impact you see,
and your environment (OS, Python version, AptiorDesk version). A proof of
concept helps enormously.

You can expect an acknowledgement within a few days. Because this is a
volunteer-maintained project, fixes are best-effort; we will keep you updated
and credit you in the release notes unless you prefer otherwise.

## Scope

AptiorDesk is a local desktop application with no server component, so the
threat model centres on the data on your machine and the untrusted content the
app processes.

**In scope:**

- API key exposure — keys appearing in the database, logs, exports, or being
  sent to an endpoint other than the one configured for them.
- Prompt injection through job descriptions, resumes, or other imported
  documents that changes what the application does (e.g. exfiltrating other
  data through a crafted posting).
- Malicious documents — crafted PDF/DOCX files causing code execution, path
  traversal, resource exhaustion, or a crash that loses user data.
- Path traversal or arbitrary file write through import/export.
- Unsafe rendering of model output or imported content (HTML/script injection
  into the UI).
- Backup/restore flaws that corrupt or leak data.
- Deletion that does not actually delete.

**Out of scope:**

- Vulnerabilities in your chosen AI provider's service.
- An attacker who already has full access to your user account or an unlocked
  machine (AptiorDesk does not defend against a local attacker with your
  privileges; the database is not separately encrypted).
- The quality or accuracy of AI-generated content.
- Denial of service caused by pointing the app at your own enormous file.

## Current protections

- **Untrusted text is fenced.** Job descriptions, resumes, and interview
  answers are wrapped in explicit `<<<BEGIN ...>>> / <<<END ...>>>` markers
  with a standing system instruction that fenced content is data, not
  instructions. Fence-marker look-alikes are stripped from the content so it
  cannot forge a boundary.
- **Model output is not trusted.** Structured output is validated against
  pydantic schemas. Tailoring suggestions may only rewrite fields that already
  exist (validated JSON pointers), and suggestions containing numbers absent
  from the source materials are flagged rather than applied.
- **Rendered output is escaped.** Model and document text is HTML-escaped
  before display; the app does not render remote content.
- **Document imports are validated.** Size cap (10 MB), extension allow-list, and
  magic-byte checks; parse failures surface as errors rather than crashes.
- **Keys are kept in the OS keyring**, never in files, and are excluded from
  backups. Logs pass through a redaction filter.
- **Device CLI execution is constrained.** Users select an executable and a
  reviewed adapter; there is no arbitrary shell-command field. Prompts travel
  over stdin, `shell=False` is enforced, and each call runs in a fresh temporary
  working directory with non-interactive/read-only or plan-mode flags.

## Known limitations

- The local SQLite database is **not encrypted**. Anyone with access to your
  user account can read it. Use full-disk encryption if that matters to you.
- A determined prompt injection could still influence the *content* of AI
  suggestions (for example, a job posting that argues for particular wording).
  The review-before-apply design is the mitigation: nothing is written to your
  resume without your explicit approval.
- Dependencies are pinned by minimum version, not locked. Run `pip-audit`
  before packaging a release.
- Installed AI CLIs are separate trusted programs with their own global
  configuration, extensions, hooks, and network behavior. AptiorDesk isolates
  their working directory but cannot override every user-level CLI setting.
