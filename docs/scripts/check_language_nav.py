#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_nav(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r'<nav aria-label="Main" id="site-nav" class="site-nav">(.*?)</nav>',
        text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"Could not find site nav in {path}")
    return match.group(1)


def require_contains(nav: str, needle: str, path: Path) -> None:
    if needle not in nav:
        raise SystemExit(f"Expected {path} nav to contain {needle!r}")


def require_absent(nav: str, needle: str, path: Path) -> None:
    if needle in nav:
        raise SystemExit(f"Expected {path} nav to exclude {needle!r}")


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "_site"
    en_path = root / "en" / "index.html"
    zh_path = root / "zh" / "index.html"

    en_nav = extract_nav(en_path)
    zh_nav = extract_nav(zh_path)

    require_contains(en_nav, "Overview", en_path)
    require_contains(en_nav, "Getting Started", en_path)
    require_absent(en_nav, "概览", en_path)
    require_absent(en_nav, "快速开始", en_path)

    require_contains(zh_nav, "概览", zh_path)
    require_contains(zh_nav, "快速开始", zh_path)
    require_absent(zh_nav, "Overview", zh_path)
    require_absent(zh_nav, "Getting Started", zh_path)

    print("Language-specific navigation looks correct.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
