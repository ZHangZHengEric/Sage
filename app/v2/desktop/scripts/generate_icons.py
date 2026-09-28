#!/usr/bin/env python3
"""Generate Desktop v2 native icons from its transparent Sage source asset."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "brand" / "sage_logo.png"
MACOS_MASK = ROOT / "assets" / "brand" / "macos_icon_mask.png"
MACOS_ICON_DIR = ROOT / "macos" / "Runner" / "Assets.xcassets" / "AppIcon.appiconset"
WINDOWS_ICON = ROOT / "windows" / "runner" / "resources" / "app_icon.ico"
MACOS_SIZES = (16, 32, 64, 128, 256, 512, 1024)
MACOS_CANVAS_SIZE = 1024
MACOS_MARK_SIZE = 860
# A fully grayscale icon is treated as monochrome by macOS 26, which places
# the artwork on a light system plate. This visually-white tint keeps the
# intended black background while remaining indistinguishable at icon sizes.
MACOS_MARK_TINT = (254, 255, 255)
WINDOWS_SIZES = tuple((size, size) for size in (16, 24, 32, 48, 64, 128, 256))


def main() -> None:
    master = Image.open(SOURCE).convert("RGBA")
    macos_mask = Image.open(MACOS_MASK).convert("L")
    macos_master = Image.new(
        "RGBA",
        (MACOS_CANVAS_SIZE, MACOS_CANVAS_SIZE),
        (0, 0, 0, 0),
    )
    macos_background = Image.new(
        "RGBA",
        (MACOS_CANVAS_SIZE, MACOS_CANVAS_SIZE),
        (0, 0, 0, 255),
    )
    macos_background.putalpha(macos_mask)
    macos_master.alpha_composite(macos_background)
    mark = master.resize(
        (MACOS_MARK_SIZE, MACOS_MARK_SIZE),
        Image.Resampling.LANCZOS,
    )
    mark_alpha = mark.getchannel("A")
    mark = ImageOps.colorize(
        mark.convert("L"),
        black=(0, 0, 0),
        white=MACOS_MARK_TINT,
    ).convert("RGBA")
    mark.putalpha(mark_alpha)
    offset = (MACOS_CANVAS_SIZE - MACOS_MARK_SIZE) // 2
    macos_master.alpha_composite(mark, (offset, offset))
    macos_master.putalpha(macos_mask)
    for size in MACOS_SIZES:
        macos_master.resize((size, size), Image.Resampling.LANCZOS).save(
            MACOS_ICON_DIR / f"app_icon_{size}.png"
        )

    master.save(WINDOWS_ICON, format="ICO", sizes=WINDOWS_SIZES)


if __name__ == "__main__":
    main()
