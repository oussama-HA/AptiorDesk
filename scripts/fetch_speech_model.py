"""Fetch the default offline speech-to-text model for release packaging.

This is a build-time operation.  The installed application never invokes pip
or downloads this required default component during onboarding.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

MODEL_REPOSITORY = "Systran/faster-whisper-small"
ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "models" / "faster-whisper" / "small"
REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json")


def complete(directory: Path = DESTINATION) -> bool:
    required_ready = all(
        (directory / name).is_file() and (directory / name).stat().st_size > 0
        for name in REQUIRED_FILES
    )
    vocabulary = tuple(directory.glob("vocabulary.*"))
    return (
        required_ready
        and bool(vocabulary)
        and all(path.is_file() and path.stat().st_size > 0 for path in vocabulary)
    )


def fetch(destination: Path = DESTINATION) -> None:
    if complete(destination):
        print(f"Speech model already verified at {destination}")
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface-hub is required at build time. Install AptiorDesk's "
            "voice dependencies before fetching release assets."
        ) from exc

    destination.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    snapshot_download(
        repo_id=MODEL_REPOSITORY,
        local_dir=destination,
        allow_patterns=[
            "config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    )
    metadata = destination / ".cache"
    if metadata.exists():
        shutil.rmtree(metadata)
    if not complete(destination):
        missing = [name for name in REQUIRED_FILES if not (destination / name).is_file()]
        raise SystemExit("Speech model download is incomplete: " + ", ".join(missing))
    size = sum(path.stat().st_size for path in destination.iterdir() if path.is_file())
    print(f"Verified {size / 1024 / 1024:.1f} MB speech model at {destination}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the release model without downloading it",
    )
    args = parser.parse_args()
    if args.check:
        if not complete():
            raise SystemExit(f"Speech model is missing or incomplete at {DESTINATION}")
        print(f"Speech model is complete at {DESTINATION}")
        return 0
    fetch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
