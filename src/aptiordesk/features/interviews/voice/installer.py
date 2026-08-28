"""Production-safe verification and repair for AptiorDesk's Kokoro runtime.

The frozen application is immutable. This module never invokes pip and never
tries to modify PyInstaller's embedded interpreter. Package/runtime repair is
owned by the desktop installer; the application may only restore model assets
to AptiorDesk's writable user-data directory.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aptiordesk.core import paths
from aptiordesk.features.interviews.voice.settings import VoiceSettings
from aptiordesk.features.interviews.voice.synthesis import (
    KOKORO_ASSET_HASHES,
    _kokoro_engine,
    bundled_kokoro_dir,
    kokoro_files,
    prepare_voice,
)

RUNTIME_MODULES = (
    "kokoro_onnx",
    "onnxruntime",
    "numpy",
    "phonemizer",
    "espeakng_loader",
)


class KokoroInstallError(RuntimeError):
    """Compatibility name for a Kokoro verification/repair failure."""


@dataclass(frozen=True, slots=True)
class KokoroRuntimeStatus:
    ready: bool
    detail: str
    assets_dir: Path | None = None
    missing_modules: tuple[str, ...] = ()
    assets_valid: bool = False
    initialized: bool = False
    runtime_errors: tuple[str, ...] = ()

    @property
    def repair_action(self) -> str:
        if self.missing_modules:
            return "Rerun the AptiorDesk installer and choose Repair."
        if not self.assets_valid:
            return "Restore the bundled voice assets."
        return "Retry voice initialization."


def inspect_kokoro_runtime(
    *,
    initialize: bool = False,
    bundled_only: bool = False,
) -> KokoroRuntimeStatus:
    """Verify Python modules, native espeak data, assets, and optionally ONNX."""
    missing: list[str] = []
    errors: list[str] = []
    for module_name in RUNTIME_MODULES:
        try:
            if initialize:
                importlib.import_module(module_name)
            elif importlib.util.find_spec(module_name) is None:
                missing.append(module_name)
        except Exception as exc:
            missing.append(module_name)
            errors.append(f"{module_name}: {exc}")

    # espeakng-loader can import while its DLL/data directory is absent.
    if "espeakng_loader" not in missing:
        try:
            if initialize:
                loader = importlib.import_module("espeakng_loader")
                library = Path(loader.get_library_path())
                data = Path(loader.get_data_path())
            else:
                spec = importlib.util.find_spec("espeakng_loader")
                if spec is None or spec.origin is None:
                    raise FileNotFoundError("espeakng_loader package is missing")
                package_dir = Path(spec.origin).parent
                library = package_dir / "espeak-ng.dll"
                data = package_dir / "espeak-ng-data"
            if not library.is_file() or not data.is_dir():
                missing.append("espeak-ng native data")
        except Exception as exc:
            missing.append("espeak-ng native data")
            errors.append(f"espeak-ng: {exc}")

    files = _bundled_kokoro_files() if bundled_only else kokoro_files()
    valid_assets = files is not None and all(
        _matches_hash(path, KOKORO_ASSET_HASHES[path.name]) for path in files
    )
    if missing:
        return KokoroRuntimeStatus(
            False,
            "The packaged neural-voice runtime is incomplete: "
            + ", ".join(dict.fromkeys(missing))
            + ". Rerun the AptiorDesk installer to repair the application. "
            + "Diagnostic detail: "
            + " | ".join(errors),
            files[0].parent if files else None,
            tuple(dict.fromkeys(missing)),
            valid_assets,
            False,
            tuple(errors),
        )
    if files is None:
        return KokoroRuntimeStatus(
            False,
            "Kokoro model or voice assets are missing. Restore the bundled assets "
            "or rerun the AptiorDesk installer.",
        )
    if not valid_assets:
        return KokoroRuntimeStatus(
            False,
            "Kokoro model assets failed their integrity check.",
            files[0].parent,
            (),
            False,
            False,
        )
    if initialize:
        try:
            prepare_voice(VoiceSettings())
        except Exception as exc:
            return KokoroRuntimeStatus(
                False,
                f"Kokoro is bundled but could not initialize: {exc}",
                files[0].parent,
                (),
                True,
                False,
            )
    return KokoroRuntimeStatus(
        True,
        "Kokoro neural voice is bundled, verified, and ready.",
        files[0].parent,
        (),
        True,
        initialize,
    )


def _bundled_kokoro_files() -> tuple[Path, Path] | None:
    directory = bundled_kokoro_dir()
    if directory is None:
        return None
    model = directory / "kokoro-v1.0.int8.onnx"
    voices = directory / "voices-v1.0.bin"
    try:
        if model.is_file() and voices.is_file():
            return model, voices
    except OSError:
        return None
    return None


def repair_kokoro_runtime(report: Callable[[str], None] | None = None) -> str:
    """Restore bundled model assets into writable user data, then verify.

    Missing Python/native libraries cannot safely be repaired from inside a
    frozen process. In that case the signed installer must restore them.
    """
    notify = report or (lambda _message: None)
    notify("Checking the packaged Kokoro runtime")
    initial = inspect_kokoro_runtime()
    if initial.missing_modules:
        raise KokoroInstallError(initial.detail)

    source = bundled_kokoro_dir()
    if source is None:
        raise KokoroInstallError(
            "This build does not contain the original Kokoro assets. Rerun the "
            "AptiorDesk installer to repair the application."
        )
    destination = paths.models_dir() / "kokoro"
    destination.mkdir(parents=True, exist_ok=True)
    for filename, expected_hash in KOKORO_ASSET_HASHES.items():
        source_file = source / filename
        if not source_file.is_file() or not _matches_hash(source_file, expected_hash):
            raise KokoroInstallError(
                f"The installed copy of {filename} is missing or corrupted. "
                "Rerun the AptiorDesk installer to restore it."
            )
        notify(f"Restoring {filename} to AptiorDesk user data")
        temporary = destination / f".{filename}.repairing"
        shutil.copy2(source_file, temporary)
        if not _matches_hash(temporary, expected_hash):
            temporary.unlink(missing_ok=True)
            raise KokoroInstallError(f"Integrity verification failed for {filename}.")
        temporary.replace(destination / filename)

    _kokoro_engine.cache_clear()
    notify("Initializing the repaired neural voice")
    status = inspect_kokoro_runtime(initialize=True)
    if not status.ready:
        raise KokoroInstallError(status.detail)
    return "Kokoro voice assets were restored and verified."


def install_kokoro_runtime(report: Callable[[str], None] | None = None) -> str:
    """Deprecated compatibility wrapper; repair without package installation."""
    return repair_kokoro_runtime(report)


def _matches_hash(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return False
    return digest.hexdigest().casefold() == expected.casefold()
