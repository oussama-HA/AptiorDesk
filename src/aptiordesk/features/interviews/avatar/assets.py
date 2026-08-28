"""AptiorDesk-owned interviewer avatar catalog and local preparation."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from aptiordesk.core import paths


class AvatarAssetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AvatarDefinition:
    """One curated avatar distributed as part of AptiorDesk."""

    id: str
    name: str
    description: str
    asset_name: str
    thumbnail_name: str
    conditioned_name: str

    @property
    def source_path(self) -> Path:
        return _library_dir() / self.asset_name

    @property
    def thumbnail_path(self) -> Path:
        return _library_dir() / self.thumbnail_name

    @property
    def conditioned_path(self) -> Path:
        return _library_dir() / self.conditioned_name


BUILTIN_AVATARS = (
    AvatarDefinition(
        id="ari",
        name="Ari",
        description="Warm, encouraging interviewer",
        asset_name="ari.glb",
        thumbnail_name="ari.jpg",
        conditioned_name="ari-conditioned",
    ),
)
DEFAULT_AVATAR_ID = BUILTIN_AVATARS[0].id


def avatar_catalog() -> tuple[AvatarDefinition, ...]:
    """Return only the curated avatars that ship with the application."""
    return BUILTIN_AVATARS


def get_avatar(avatar_id: str) -> AvatarDefinition:
    for avatar in BUILTIN_AVATARS:
        if avatar.id == avatar_id:
            return avatar
    raise AvatarAssetError(f"Unknown AptiorDesk avatar: {avatar_id}")


def prepare_avatar(avatar_id: str) -> Path:
    """Condition a bundled avatar into the app-data cache and return its QML."""
    avatar = get_avatar(avatar_id)
    conditioned = _conditioned_component(avatar.conditioned_path)
    if conditioned is not None:
        fingerprint = _fingerprint(conditioned)
        destination = (
            paths.models_dir() / "interviewer-avatar" / "builtin" / f"{avatar.id}-{fingerprint}"
        )
        cached = _conditioned_component(destination)
        if cached is not None:
            return cached
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(avatar.conditioned_path, destination, dirs_exist_ok=True)
        cached = _conditioned_component(destination)
        if cached is None:
            raise AvatarAssetError(
                f"The installed {avatar.name} interviewer files are incomplete. "
                "Rerun AptiorDesk Setup and choose Repair, then retry initialization."
            )
        return cached

    if getattr(sys, "frozen", False):
        raise AvatarAssetError(
            f"The installed {avatar.name} interviewer files are missing or damaged. "
            "Rerun AptiorDesk Setup and choose Repair, then retry initialization."
        )

    # Source checkouts may condition a licensed development asset on demand.
    # Release builds never execute this tool on an end-user machine.
    source_path = avatar.source_path
    if not source_path.is_file():
        raise AvatarAssetError(
            f"The {avatar.name} avatar asset is missing. The production avatar is "
            "intentionally excluded from the public source tree. Use an official "
            "AptiorDesk release or provide a licensed release asset."
        )
    fingerprint = _fingerprint(source_path)
    destination = (
        paths.models_dir() / "interviewer-avatar" / "builtin" / f"{avatar.id}-{fingerprint}"
    )
    existing = list(destination.glob("*.qml"))
    if len(existing) == 1:
        return existing[0]
    destination.mkdir(parents=True, exist_ok=True)
    glb_path = destination / f"{avatar.id}.glb"
    shutil.copy2(source_path, glb_path)
    executable = _balsam_executable()
    result = subprocess.run(
        [str(executable), "-o", str(destination), str(glb_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        **_hidden_process_kwargs(),
    )
    if result.returncode != 0:
        raise AvatarAssetError(
            f"The built-in {avatar.name} avatar could not be prepared. "
            + (result.stderr.strip() or result.stdout.strip())
        )
    components = list(destination.glob("*.qml"))
    if len(components) != 1:
        raise AvatarAssetError(
            f"Expected one conditioned component for {avatar.name}; found {len(components)}."
        )
    _repair_conditioned_component(components[0])
    return components[0]


def _library_dir() -> Path:
    return Path(__file__).with_name("library")


def _conditioned_component(directory: Path) -> Path | None:
    """Return a complete build-time-conditioned avatar component."""
    try:
        components = tuple(directory.glob("*.qml"))
        maps = directory / "maps"
        meshes = directory / "meshes"
        if (
            len(components) == 1
            and components[0].stat().st_size > 0
            and maps.is_dir()
            and meshes.is_dir()
            and any(path.is_file() and path.stat().st_size > 0 for path in maps.iterdir())
            and any(path.is_file() and path.stat().st_size > 0 for path in meshes.iterdir())
        ):
            return components[0]
    except OSError:
        return None
    return None


def bundled_avatar_runtime_status() -> tuple[bool, str]:
    """Check release-owned avatar and Qt QML assets without touching user data."""
    missing = [
        avatar.name
        for avatar in BUILTIN_AVATARS
        if _conditioned_component(avatar.conditioned_path) is None
    ]
    if missing:
        return False, "Missing conditioned interviewer assets: " + ", ".join(missing)

    required_modules = (
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets",
    )
    unavailable = [name for name in required_modules if importlib.util.find_spec(name) is None]
    if unavailable:
        return False, "Missing packaged Qt modules: " + ", ".join(unavailable)

    if getattr(sys, "frozen", False):
        qml_root = Path(getattr(sys, "_MEIPASS", "")) / "PySide6" / "qml"
        required_qml = (
            qml_root / "QtQuick3D" / "qmldir",
            qml_root / "QtQuick" / "Timeline" / "qmldir",
        )
        if not all(path.is_file() for path in required_qml):
            return False, "Qt Quick 3D or Timeline QML plugins are missing."

    return True, "The interviewer avatar and Qt rendering runtime are bundled and ready."


def _repair_conditioned_component(component: Path) -> None:
    source = component.read_text(encoding="utf-8")
    # Imported facial test tracks must never continuously overwrite the live
    # blink/lip controls.
    source = re.sub(
        r"(\s+enabled:) true(\s+animations: TimelineAnimation \{)",
        r"\1 false\2",
        source,
    )
    source = re.sub(
        r"(\s+running:) true(\s+loops:)",
        r"\1 false\2",
        source,
    )
    # Ari's exact resting stance is a one-frame action baked from the
    # model author's Blender pose library. Keep that coordinated timeline
    # enabled and parked on its authored frame; every other imported test
    # timeline remains disabled so it cannot fight blinking or lip sync.
    source = re.sub(
        r'(Timeline \{\s+id: [^\n]+\s+objectName: "AptiorDesk_Idle_Pose"'
        r"\s+property real framesPerSecond: [^\n]+\s+startFrame: [^\n]+"
        r"\s+endFrame: [^\n]+\s+currentFrame:) [^\n]+"
        r"(\s+enabled:) false",
        r"\1 endFrame\2 true",
        source,
    )
    # Some Character Creator exports encode the eye-occlusion shells as fully
    # opaque black. They should be transparent shadow geometry.
    source = re.sub(
        r'(objectName: "Std_Eye_Occlusion_[RL]"\s+baseColor:) "#ff000000"',
        r'\1 "#00000000"',
        source,
    )
    component.write_text(source, encoding="utf-8")


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _balsam_executable() -> Path:
    beside_python = Path(sys.executable).with_name(
        "pyside6-balsam.exe" if sys.platform == "win32" else "pyside6-balsam"
    )
    if beside_python.exists():
        return beside_python
    discovered = shutil.which("pyside6-balsam")
    if discovered:
        return Path(discovered)
    raise AvatarAssetError(
        "Qt's development avatar conditioner is unavailable. Run "
        "scripts/prepare_release_avatar.py from a complete development environment."
    )


def _hidden_process_kwargs() -> dict:
    """Prevent development-only conversion tools from flashing a console on Windows."""
    if sys.platform != "win32":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startup,
    }
