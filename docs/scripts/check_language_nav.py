#!/usr/bin/env python3
"""Check every built bilingual page, its sidebar order, and its language switch."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import yaml

from check_translations import load_pages, metadata


def extract_nav(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r'<nav aria-label="Main" id="site-nav" class="site-nav">(.*?)</nav>',
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"Could not find site nav in {path}")
    return match.group(1)


def main() -> int:
    docs = Path(__file__).resolve().parents[1]
    site = docs / "_site"
    base = (
        yaml.safe_load((docs / "_config.yml").read_text())
        .get("baseurl", "")
        .rstrip("/")
    )
    pages = load_pages(docs)
    targets = {}
    for relative, text in pages.items():
        meta = metadata(text)
        url = meta.get("permalink") or "/" + str(Path(relative).with_suffix(".html"))
        target = site / url.lstrip("/")
        if url.endswith("/"):
            target /= "index.html"
        targets[relative] = (meta, base + url, target)
    errors = []
    nav_by_language = {}
    for lang in ("en", "zh"):
        expected = {
            url
            for rel, (meta, url, _) in targets.items()
            if rel.startswith(lang + "/") and not meta.get("nav_exclude")
        }
        for relative, (meta, url, path) in targets.items():
            if not relative.startswith(lang + "/"):
                continue
            if not path.is_file():
                errors.append(f"{relative}: missing built page {path}")
                continue
            nav = extract_nav(path)
            hrefs = [unquote(h) for h in re.findall(r'<a\b[^>]*href="([^"]+)"', nav)]
            local = [h for h in hrefs if h.startswith(base + "/" + lang + "/")]
            if set(local) != expected or len(local) != len(expected):
                errors.append(
                    f"{relative}: sidebar missing/duplicate/unexpected pages: {sorted(set(local) ^ expected)}"
                )
            other = "zh" if lang == "en" else "en"
            if any(h.startswith(base + "/" + other + "/") for h in hrefs):
                errors.append(f"{relative}: sidebar mixes languages")
            normalized = [h.replace(base + "/" + lang + "/", "/", 1) for h in local]
            if lang in nav_by_language and nav_by_language[lang] != normalized:
                errors.append(
                    f"{relative}: sidebar order differs from same-language pages"
                )
            nav_by_language[lang] = normalized
            counterpart = other + relative[len(lang) :]
            switch = re.search(
                r'<div class="sage-lang-switcher">(.*?)</div>', path.read_text(), re.S
            )
            switches = re.findall(r'href="([^"]+)"', switch.group(1)) if switch else []
            if set(switches) != {url, targets[counterpart][1]}:
                errors.append(f"{relative}: missing or incorrect language switch")
    if nav_by_language.get("en") != nav_by_language.get("zh"):
        errors.append("English and Chinese sidebar order/hierarchy differs")
    if errors:
        raise SystemExit("\n".join(errors))
    print(
        f"Validated sidebars and translation switches on all {len(pages)} built pages."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
