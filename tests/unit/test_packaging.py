"""Guards against the repository shipping broken.

A clean-room clone once failed to import because an unanchored `models/`
pattern in .gitignore silently excluded src/aptiordesk/database/models/. These
tests catch that class of bug in CI instead of in a user's first clone.
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
from pathlib import Path

import pytest

import aptiordesk

SRC = Path(aptiordesk.__file__).resolve().parent
REPO = SRC.parent.parent


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def _in_git_repo() -> bool:
    try:
        _git("rev-parse", "--git-dir")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


@pytest.mark.skipif(not _in_git_repo(), reason="not a git checkout")
def test_every_source_file_is_tracked_by_git():
    """A source file that git ignores will be missing for everyone who clones."""
    ignored = _git(
        "ls-files", "--others", "--ignored", "--exclude-standard", "--", "src", "tests"
    ).splitlines()
    ignored_python = [
        path
        for path in ignored
        if path.endswith(".py") and "__pycache__" not in path and "egg-info" not in path
    ]
    assert ignored_python == [], (
        "These source files are excluded by .gitignore and would be missing "
        f"from a fresh clone: {ignored_python}"
    )


@pytest.mark.skipif(not _in_git_repo(), reason="not a git checkout")
def test_package_data_is_tracked():
    """Runtime resources must exist and must not be excluded from packaging."""
    for pattern in (
        "src/aptiordesk/database/migrations/0001_initial.sql",
        "src/aptiordesk/ai/prompts/templates/job_extraction.md",
        "src/aptiordesk/ui/theme/tokens.py",
        "src/aptiordesk/ui/theme/brand_tokens.css",
        "src/aptiordesk/features/interviews/avatar/office-background.png",
        "models/kokoro/kokoro-v1.0.int8.onnx",
        "models/kokoro/voices-v1.0.bin",
    ):
        assert (REPO / pattern).is_file(), f"{pattern} is missing"
        ignored = (
            subprocess.run(["git", "check-ignore", "-q", "--", pattern], cwd=REPO).returncode == 0
        )
        assert not ignored, f"{pattern} is excluded by .gitignore"


def test_every_subpackage_imports():
    """Catches a package that exists on disk but was never shipped, and any
    import-time error in a module the test suite does not otherwise touch."""
    failures: list[str] = []
    for module in pkgutil.walk_packages([str(SRC)], prefix="aptiordesk."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 — report all, fail once
            failures.append(f"{module.name}: {exc}")
    assert failures == [], "Modules failed to import: " + "; ".join(failures)


def test_expected_packages_are_present():
    """An explicit list, so an accidentally-dropped package is obvious."""
    for name in (
        "aptiordesk.core",
        "aptiordesk.database",
        "aptiordesk.database.models",
        "aptiordesk.database.repositories",
        "aptiordesk.ai",
        "aptiordesk.ai.providers",
        "aptiordesk.ai.prompts",
        "aptiordesk.documents",
        "aptiordesk.features.interviews.voice",
        "aptiordesk.features",
        "aptiordesk.features.jobs",
        "aptiordesk.features.resumes",
        "aptiordesk.integrations.browser_extension",
        "aptiordesk.ui",
        "aptiordesk.ui.components",
    ):
        importlib.import_module(name)


def test_release_identity_and_native_packaging_files_are_present():
    assert aptiordesk.CREATOR_NAME == "Oussama Hamida"
    assert aptiordesk.CREATOR_COMPANY == "Glidd.io"

    expected = (
        "packaging/aptiordesk.spec",
        "scripts/fetch_speech_model.py",
        "scripts/prepare_release_avatar.py",
        "installer/windows/AptiorDesk.iss",
        "installer/windows/version_info.txt",
        "docs/RELEASING.md",
        "packaging/macos/entitlements.plist",
        "packaging/linux/AppRun",
        "packaging/linux/aptiordesk.desktop",
        ".github/workflows/release.yml",
    )
    for relative_path in expected:
        assert (REPO / relative_path).is_file(), f"{relative_path} is missing"

    workflow = (REPO / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "AptiorDesk-Windows-x64-Setup.exe" in workflow
    assert "AptiorDesk-macOS-x64.dmg" in workflow
    assert "AptiorDesk-Linux-x86_64.AppImage" in workflow
    assert "scripts/prepare_release_avatar.py" in workflow
    assert "APTIORDESK_REQUIRE_AVATAR" in workflow

    spec = (REPO / "packaging/aptiordesk.spec").read_text(encoding="utf-8")
    assert '"espeakng_loader"' in spec
    assert '"phonemizer"' in spec
    assert '"language_tags"' in spec
    assert "models/faster-whisper/small" in spec
    assert "APTIORDESK_REQUIRE_SPEECH_MODEL" in spec
    assert "APTIORDESK_REQUIRE_AVATAR" in spec
    assert '"PySide6.QtQuickWidgets"' in spec
    assert "scripts/fetch_speech_model.py" in workflow
    installer = (REPO / "installer/windows/AptiorDesk.iss").read_text(encoding="utf-8")
    assert "--verify-install" in installer
    assert "offline speech-to-text model" in installer
    assert "PrivilegesRequired=lowest" in installer


def test_proprietary_extension_source_is_not_in_public_repository():
    """Only the desktop interoperability protocol belongs in this repository."""
    assert not (REPO / "src/aptiordesk/integrations/browser_extension/extension").exists()
    assert not (REPO / "tests/browser_extension").exists()
    assert not list((REPO / "src/aptiordesk/integrations/browser_extension").glob("*.zip"))
    config = (REPO / "src/aptiordesk/integrations/browser_extension/config.py").read_text(
        encoding="utf-8"
    )
    assert "EXTENSION_ID =" in config

    spec = (REPO / "packaging/aptiordesk.spec").read_text(encoding="utf-8")
    assert "integrations/browser_extension/extension" not in spec
    notice = (REPO / "NOTICE.md").read_text(encoding="utf-8")
    assert "separately distributed proprietary" in notice


@pytest.mark.skipif(not _in_git_repo(), reason="not a git checkout")
def test_licensed_avatar_source_is_excluded_from_public_repository():
    for relative_path in (
        "src/aptiordesk/features/interviews/avatar/library/ari.glb",
        "src/aptiordesk/features/interviews/avatar/library/ari.jpg",
    ):
        path = REPO / relative_path
        if path.exists():
            assert (
                subprocess.run(
                    ["git", "check-ignore", "-q", "--", relative_path], cwd=REPO
                ).returncode
                == 0
            )

    policy = (REPO / "docs/ASSET_LICENSING.md").read_text(encoding="utf-8")
    assert "excluded from this public source" in policy
    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
    assert "avatar/library/ari.glb" in manifest
    assert "avatar/library/ari.jpg" in manifest
