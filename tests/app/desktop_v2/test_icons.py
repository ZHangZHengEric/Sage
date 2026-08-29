import plistlib
from pathlib import Path

from PIL import Image, ImageChops


ICON_DIR = (
    Path(__file__).resolve().parents[3]
    / "app/desktop_v2/macos/Runner/Assets.xcassets/AppIcon.appiconset"
)
INFO_PLIST = ICON_DIR.parents[1] / "Info.plist"


def test_macos_uses_named_asset_catalog_app_icon():
    with INFO_PLIST.open("rb") as file:
        info = plistlib.load(file)

    assert info["CFBundleIconName"] == "AppIcon"


def test_macos_app_icons_use_native_rounded_mask():
    icons = sorted(ICON_DIR.glob("app_icon_*.png"))

    assert icons
    for path in icons:
        alpha = Image.open(path).convert("RGBA").getchannel("A")
        assert alpha.getextrema() == (0, 255), path.name
        assert alpha.getpixel((0, 0)) == 0, path.name

    alpha = Image.open(ICON_DIR / "app_icon_1024.png").convert("RGBA").getchannel("A")
    assert alpha.getbbox() == (55, 55, 969, 969)


def test_macos_mark_stays_inside_a_centered_safe_area():
    image = Image.open(ICON_DIR / "app_icon_1024.png").convert("RGB")
    difference = ImageChops.difference(
        image,
        Image.new("RGB", image.size, (0, 0, 0)),
    )
    left, top, right, bottom = difference.getbbox()
    width = right - left
    height = bottom - top

    assert 0.4 <= width / image.width <= 0.48
    assert 0.4 <= height / image.height <= 0.48
    assert abs((left + right) / 2 - image.width / 2) <= 8
    assert abs((top + bottom) / 2 - image.height / 2) <= 8


def test_macos_mark_uses_a_visually_white_non_monochrome_tint():
    image = Image.open(ICON_DIR / "app_icon_1024.png").convert("RGBA")

    assert image.getpixel((512, 512)) == (254, 255, 255, 255)
