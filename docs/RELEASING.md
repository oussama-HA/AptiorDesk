# Publishing AptiorDesk

This checklist publishes the open-source desktop application only. The
proprietary browser extension must remain in its separate private repository
and Chrome Web Store pipeline.

## 1. Prepare the workstation

Install Git, Git LFS, Python 3.12, and Inno Setup 6 on Windows. Then create an
isolated environment and install release dependencies:

```powershell
git lfs install
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,voice]"
```

Do not copy a local AptiorDesk database, resume, `.env`, credential file,
extension build, or licensed interviewer model into the checkout.

## 2. Run the release gate

```powershell
.\.venv\Scripts\python -m ruff format --check src tests
.\.venv\Scripts\python -m ruff check src tests
.\.venv\Scripts\python -m mypy src\aptiordesk
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m build
.\.venv\Scripts\python scripts\fetch_speech_model.py
$env:APTIORDESK_REQUIRE_SPEECH_MODEL = "1"
.\.venv\Scripts\pyinstaller --noconfirm --clean packaging\aptiordesk.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" `
  "installer\windows\AptiorDesk.iss"
```

Install the resulting
`dist/installer/AptiorDesk-Windows-x64-Setup.exe` in a fresh Windows user
profile or clean VM. Complete onboarding, verify Kokoro and offline
speech-to-text without a model download, connect an AI provider, pair the
official extension, and uninstall.

## 3. Create the GitHub repository

1. On GitHub, choose **New repository**.
2. Name it `AptiorDesk`.
3. Leave **Initialize this repository** options unchecked because this
   checkout already contains the README, license, and ignore rules.
4. Keep it private for the first review if desired, then change visibility
   after the release audit.

## 4. Initialize and review Git safely

If this folder is not already a Git checkout:

```powershell
git init -b main
git lfs install
```

Review what Git would publish:

```powershell
git status --short
git check-ignore -v build dist .venv .pytest-tmp .pytest_cache .ruff_cache
git ls-files --others --exclude-standard
git diff --check
```

Confirm the following do not appear:

- an extension `manifest.json`, service worker, content script, side-panel
  source, extension tests, or extension ZIP;
- `.env`, API keys, access tokens, credentials, databases, resumes, exports,
  logs, caches, screenshots, or machine-specific absolute paths;
- the privately licensed interviewer GLB or source artwork.

The only allowed extension code is the desktop protocol under
`src/aptiordesk/integrations/browser_extension/`.

## 5. Stage and inspect the first commit

```powershell
git add --all
git status --short
git diff --cached --stat
git diff --cached --check
git diff --cached
git lfs ls-files
```

The Kokoro ONNX and voice binaries must appear in `git lfs ls-files`. If any
unexpected private or generated file is staged, unstage it with
`git restore --staged -- <path>`, update `.gitignore`, and repeat the review.

Create the first commit only after the staged diff is understood:

```powershell
git commit -m "Initial open-source AptiorDesk desktop release"
```

## 6. Add the remote and push

Replace the example owner with the real GitHub organization or account:

```powershell
git remote add origin https://github.com/OWNER/AptiorDesk.git
git remote -v
git push -u origin main
```

Immediately inspect the GitHub file browser and verify that no proprietary
extension files, user data, secrets, or build output are present.

## 7. Create the first release

1. Tag the verified commit:

   ```powershell
   git tag -a v0.1.0 -m "AptiorDesk v0.1.0"
   git push origin v0.1.0
   ```

2. Open **GitHub → Releases → Draft a new release** and choose `v0.1.0`.
3. Copy the relevant entries from `CHANGELOG.md`.
4. Upload `AptiorDesk-Windows-x64-Setup.exe` as a release asset.
5. Add its SHA-256 checksum:

   ```powershell
   Get-FileHash `
     dist\installer\AptiorDesk-Windows-x64-Setup.exe `
     -Algorithm SHA256
   ```

6. Mark the release as a pre-release while AptiorDesk remains at alpha status.

## 8. Final publication audit

After pushing, clone the repository into a new empty directory with Git LFS
enabled and rerun lint, typing, tests, and the production build. Search both
the GitHub file browser and clone for secrets, local paths, old branding, and
extension implementation files. Revoke and rotate any credential immediately
if it was ever committed; deleting it in a later commit does not remove it from
history.
