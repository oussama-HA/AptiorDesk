"""Stage the privately stored, licensed interviewer assets for release builds."""

from __future__ import annotations

import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = (
    ROOT / "src/aptiordesk/features/interviews/avatar/library"
)
REQUIRED = {
    "ari.glb": 10 * 1024 * 1024,
    "ari.jpg": 10 * 1024,
}


def _validate() -> bool:
    return all(
        (DESTINATION / name).is_file()
        and (DESTINATION / name).stat().st_size >= minimum
        for name, minimum in REQUIRED.items()
    )


def main() -> None:
    if _validate():
        print("Licensed interviewer assets are already staged.")
        return

    url = os.environ.get("APTIORDESK_AVATAR_BUNDLE_URL", "").strip()
    if not url:
        raise SystemExit(
            "The licensed interviewer assets are missing. Set "
            "APTIORDESK_AVATAR_BUNDLE_URL to a private ZIP containing ari.glb "
            "and ari.jpg. These files must never be committed to the public repository."
        )

    request = urllib.request.Request(url)
    token = os.environ.get("APTIORDESK_AVATAR_BUNDLE_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with tempfile.TemporaryDirectory(prefix="aptiordesk-release-") as directory:
        archive = Path(directory) / "avatar.zip"
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            archive.write_bytes(response.read())

        with zipfile.ZipFile(archive) as bundle:
            members = {
                Path(member.filename).name: member
                for member in bundle.infolist()
                if not member.is_dir()
            }
            missing = sorted(set(REQUIRED) - set(members))
            if missing:
                raise SystemExit(
                    "The private avatar bundle is incomplete: " + ", ".join(missing)
                )
            DESTINATION.mkdir(parents=True, exist_ok=True)
            for name in REQUIRED:
                target = DESTINATION / name
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(bundle.read(members[name]))
                temporary.replace(target)

    if not _validate():
        raise SystemExit("The staged interviewer assets failed size validation.")
    print("Licensed interviewer assets staged for this release build.")


if __name__ == "__main__":
    main()
