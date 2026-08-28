"""Condition licensed interviewer assets before freezing a desktop release."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from aptiordesk.features.interviews.avatar.assets import (
    _hidden_process_kwargs,
    _repair_conditioned_component,
)

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "src/aptiordesk/features/interviews/avatar/library"
SOURCE = LIBRARY / "ari.glb"
DESTINATION = LIBRARY / "ari-conditioned"
MANIFEST = DESTINATION / "conditioning.json"


def _source_hash() -> str:
    digest = hashlib.sha256()
    with SOURCE.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _balsam_executable() -> Path:
    script = Path(sys.executable).with_name(
        "pyside6-balsam.exe" if sys.platform == "win32" else "pyside6-balsam"
    )
    if script.is_file():
        return script
    raise SystemExit("PySide6's Balsam conditioner is unavailable in this release environment.")


def _ready(source_hash: str) -> bool:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return (
            manifest.get("source_sha256") == source_hash
            and len(tuple(DESTINATION.glob("*.qml"))) == 1
            and any((DESTINATION / "maps").iterdir())
            and any((DESTINATION / "meshes").iterdir())
        )
    except (OSError, ValueError, TypeError):
        return False


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(
            "The licensed ari.glb is missing. Run scripts/fetch_release_avatar.py first."
        )
    source_hash = _source_hash()
    if _ready(source_hash):
        print("The release interviewer is already conditioned.")
        return

    temporary = LIBRARY / ".ari-conditioned-building"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    try:
        completed = subprocess.run(
            [
                str(_balsam_executable()),
                "-o",
                str(temporary),
                str(SOURCE),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            **_hidden_process_kwargs(),
        )
        if completed.returncode != 0:
            raise SystemExit(
                "Avatar conditioning failed: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )
        components = tuple(temporary.glob("*.qml"))
        if len(components) != 1:
            raise SystemExit(f"Expected one conditioned QML component; found {len(components)}.")
        _repair_conditioned_component(components[0])
        (temporary / "conditioning.json").write_text(
            json.dumps(
                {
                    "source_sha256": source_hash,
                    "conditioner": "PySide6 Balsam",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        temporary.replace(DESTINATION)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print("Licensed interviewer conditioned for the desktop release.")


if __name__ == "__main__":
    main()
