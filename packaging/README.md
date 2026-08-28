# AptiorDesk desktop releases

AptiorDesk is frozen with PyInstaller on each target operating system. Native
Qt, camera, microphone, keyring, ONNX, speech, phonemizer, and espeak-ng
libraries must not be cross-compiled from a different host OS.

## Production voice architecture

Kokoro is part of the immutable application payload. Release builds contain:

- `kokoro-onnx` and ONNX Runtime;
- `phonemizer` and `espeakng-loader`, including the native espeak-ng library
  and language data;
- the verified Kokoro model and voice assets under `models/kokoro`;
- local microphone and speech-to-text dependencies from the `voice` extra;
- the verified faster-whisper `small` model under
  `models/faster-whisper/small`.

The desktop application never runs `pip` inside a frozen runtime. **Repair
Kokoro** verifies the packaged files and may restore verified model assets to
the writable AptiorDesk data directory. Missing Python modules or native
libraries require rerunning the installer, which replaces application files
without deleting `%LOCALAPPDATA%\AptiorDesk` user data.

Both the release workflow and the Windows installer run
`AptiorDesk.exe --verify-install <report.json>`. The command validates the
frozen core runtime, initializes Kokoro, verifies the speech runtime and
bundled model from the actual executable, emits a secret-free diagnostic
report, and returns a non-zero exit code when a required component is
incomplete. A release must not be published when this check fails.

The `Desktop release` GitHub Actions workflow produces:

- `AptiorDesk-Windows-x64-Setup.exe`;
- `AptiorDesk-macOS-x64.dmg`;
- `AptiorDesk-Linux-x86_64.AppImage` plus a portable tarball.

Run the workflow manually from GitHub Actions, or push a version tag such as
`v0.1.0`. The generated files are uploaded as workflow artifacts.

## Local Windows build

```powershell
python -m pip install -e ".[voice]" pyinstaller pillow
python scripts/generate_release_icons.py
python scripts/fetch_release_avatar.py
python scripts/prepare_release_avatar.py
python scripts/fetch_speech_model.py
$env:APTIORDESK_RELEASE_ICON = (Resolve-Path packaging/icons/aptiordesk.ico).Path
$env:APTIORDESK_REQUIRE_SPEECH_MODEL = "1"
$env:APTIORDESK_REQUIRE_AVATAR = "1"
pyinstaller --noconfirm --clean packaging/aptiordesk.spec
```

`fetch_release_avatar.py` accepts an existing ignored local `ari.glb`/`ari.jpg`
pair or downloads a private ZIP through `APTIORDESK_AVATAR_BUNDLE_URL` and the
optional `APTIORDESK_AVATAR_BUNDLE_TOKEN`. Configure those as protected release
secrets. Never commit the licensed stock model to the public repository.

The intermediate frozen application will be at
`dist/AptiorDesk/AptiorDesk.exe`. It is an installer input, not the recommended
end-user distribution. Publish `dist/installer/AptiorDesk-Windows-x64-Setup.exe`.
Compile `installer/windows/AptiorDesk.iss` with Inno Setup 6 to create the
installer. Verify the frozen runtime before compiling:

```powershell
dist\AptiorDesk\AptiorDesk.exe --verify-install dist\install-health.json
if ($LASTEXITCODE -ne 0) { throw "Frozen voice verification failed" }
```

The Inno Setup package is a per-user installer. It provides component
selection, license/privacy and local-AI guidance, shortcuts, upgrade support,
uninstall support, and post-install verification. First launch then runs the
in-app System Setup wizard for core storage, voice, AI provider/Ollama, browser
extension, microphone, camera, speech-to-text, ports, and permissions.

## Signing

The workflow currently produces unsigned community builds. Windows
Authenticode signing and Apple Developer ID signing/notarization require
private certificates owned by the publisher. Do not place signing certificates
or passwords in this repository; add them as protected release secrets before
publishing builds to end users.
