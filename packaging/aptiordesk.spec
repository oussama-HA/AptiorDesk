# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller definition for AptiorDesk desktop releases."""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIRECTORY = Path(SPECPATH).resolve()
if SPEC_DIRECTORY.is_file():
    SPEC_DIRECTORY = SPEC_DIRECTORY.parent
ROOT = SPEC_DIRECTORY.parent
SRC = ROOT / "src"

# PyInstaller always probes the global user-site directory while resolving
# binary parents, even when a release is built from an isolated virtual
# environment with PYTHONNOUSERSITE enabled. A locked-down or redirected
# Windows profile can make that unrelated directory raise PermissionError and
# abort an otherwise hermetic build. Exclude it when it cannot be inspected;
# release dependencies must come from the active build environment.
try:
    Path(site.getusersitepackages()).is_dir()
except OSError:
    site.getusersitepackages = lambda: ""

APP_ICON = Path(
    os.environ.get("APTIORDESK_RELEASE_ICON", ROOT / "src/aptiordesk/assets/aptior.png")
)
SPEECH_MODEL_DIR = ROOT / "models/faster-whisper/small"
CONDITIONED_AVATAR_DIR = (
    ROOT / "src/aptiordesk/features/interviews/avatar/library/ari-conditioned"
)
SPEECH_MODEL_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
)
speech_model_ready = all(
    (SPEECH_MODEL_DIR / name).is_file()
    and (SPEECH_MODEL_DIR / name).stat().st_size > 0
    for name in SPEECH_MODEL_FILES
) and any(
    path.is_file() and path.stat().st_size > 0
    for path in SPEECH_MODEL_DIR.glob("vocabulary.*")
)
if os.environ.get("APTIORDESK_REQUIRE_SPEECH_MODEL") == "1" and not speech_model_ready:
    raise RuntimeError(
        "The default speech-to-text model is missing. Run "
        "'python scripts/fetch_speech_model.py' before the release build."
    )
conditioned_avatar_ready = (
    len(tuple(CONDITIONED_AVATAR_DIR.glob("*.qml"))) == 1
    and (CONDITIONED_AVATAR_DIR / "maps").is_dir()
    and (CONDITIONED_AVATAR_DIR / "meshes").is_dir()
)
if os.environ.get("APTIORDESK_REQUIRE_AVATAR") == "1" and not conditioned_avatar_ready:
    raise RuntimeError(
        "The release interviewer has not been conditioned. Run "
        "'python scripts/prepare_release_avatar.py' before the release build."
    )

datas = [
    (str(ROOT / "src/aptiordesk/assets"), "aptiordesk/assets"),
    (str(ROOT / "src/aptiordesk/database/migrations"), "aptiordesk/database/migrations"),
    (str(ROOT / "src/aptiordesk/ai/prompts/templates"), "aptiordesk/ai/prompts/templates"),
    (
        str(ROOT / "src/aptiordesk/features/interviews/avatar"),
        "aptiordesk/features/interviews/avatar",
    ),
    (
        str(ROOT / "src/aptiordesk/ui/theme/brand_tokens.css"),
        "aptiordesk/ui/theme",
    ),
    (str(ROOT / "models/kokoro"), "models/kokoro"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE.md"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "README.md"), "."),
]
if speech_model_ready:
    datas.append((str(SPEECH_MODEL_DIR), "models/faster-whisper/small"))
binaries = []
hiddenimports = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "keyring.backends",
]

# These packages load providers, native binaries, or model helpers dynamically.
# collect_all is deliberately best-effort so typed-only developer builds still
# work, while release builds install the complete voice extra.
for package in (
    "kokoro_onnx",
    # kokoro_onnx imports these dynamically. espeakng_loader also carries the
    # native espeak-ng library and its language data, neither of which module
    # analysis discovers from Python imports alone.
    "espeakng_loader",
    "phonemizer",
    # phonemizer -> segments -> csvw reads this JSON registry at import time.
    # It is package data, so dependency analysis does not copy it automatically.
    "language_tags",
    "onnxruntime",
    "sounddevice",
    "_sounddevice_data",
    "faster_whisper",
    "ctranslate2",
    "keyring",
):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("keyring.backends")

analysis = Analysis(
    [str(ROOT / "src/aptiordesk/__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AptiorDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(APP_ICON),
    version=(
        str(ROOT / "installer/windows/version_info.txt")
        if sys.platform == "win32"
        else None
    ),
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("APTIORDESK_CODESIGN_IDENTITY") or None,
    entitlements_file=(
        str(ROOT / "packaging/macos/entitlements.plist")
        if sys.platform == "darwin"
        else None
    ),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="AptiorDesk",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="AptiorDesk.app",
        icon=str(APP_ICON),
        bundle_identifier="io.glidd.aptiordesk",
        version="0.1.0",
        info_plist={
            "CFBundleDisplayName": "AptiorDesk",
            "CFBundleName": "AptiorDesk",
            "CFBundleShortVersionString": "0.1.0",
            "NSCameraUsageDescription": (
                "AptiorDesk uses the camera only when you enable your local "
                "mock-interview preview."
            ),
            "NSMicrophoneUsageDescription": (
                "AptiorDesk uses the microphone only when you record a mock "
                "interview answer."
            ),
            "NSHumanReadableCopyright": (
                "Copyright © 2026 Oussama Hamida, Glidd.io, and contributors."
            ),
        },
    )
