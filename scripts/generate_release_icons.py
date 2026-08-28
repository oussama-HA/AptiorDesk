"""Generate platform release icons from AptiorDesk's canonical PNG."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/aptiordesk/assets/aptior.png"
OUTPUT = ROOT / "packaging/icons"
SIZES = (16, 32, 64, 128, 256, 512, 1024)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGBA")
    source.save(
        OUTPUT / "aptiordesk.ico",
        format="ICO",
        sizes=[(size, size) for size in SIZES if size <= 256],
    )
    source.resize((512, 512), Image.Resampling.LANCZOS).save(
        OUTPUT / "aptiordesk.png"
    )
    iconset = OUTPUT / "AptiorDesk.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        source.resize((size, size), Image.Resampling.LANCZOS).save(
            iconset / f"icon_{size}x{size}.png"
        )
        source.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
            iconset / f"icon_{size}x{size}@2x.png"
        )


if __name__ == "__main__":
    main()
