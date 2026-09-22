#!/usr/bin/env python3
"""Validate current v2 docs and their links without network access or a site build."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
REPO_URL = "https://github.com/ZHangZHengEric/Sage/blob/main/"


def main() -> None:
    errors: list[str] = []
    pages = sorted([*(DOCS / "en").rglob("*.md"), *(DOCS / "zh").rglob("*.md")])
    metadata = {}
    refs = set()
    for path in pages:
        text = path.read_text()
        if not text.startswith("---\n"):
            errors.append(f"{path}: missing front matter")
            continue
        meta = yaml.safe_load(text.split("---", 2)[1])
        metadata[path] = meta
        lang = path.relative_to(DOCS).parts[0]
        if meta.get("lang") != lang or not meta.get("ref"):
            errors.append(f"{path}: invalid language/ref")
        key = (lang, meta.get("ref"))
        if key in refs:
            errors.append(f"{path}: duplicate language/ref")
        refs.add(key)
        if text.count("```") % 2:
            errors.append(f"{path}: unbalanced code fence")
    for path, meta in metadata.items():
        parent = meta.get("parent")
        if parent and not any(m.get("title") == parent and m.get("lang") == meta["lang"] and m.get("has_children") for m in metadata.values()):
            errors.append(f"{path}: missing parent {parent}")
    extra = [ROOT / "README.md", ROOT / "README_CN.md", ROOT / "sagents/v2/README.md"]
    for path in pages + extra:
        text = path.read_text()
        for link in re.findall(r'\]\(([^)\s]+)\)|src="([^"]+)"', text):
            target = unquote(link[0] or link[1]).split("#", 1)[0]
            if not target or target.startswith(("{{", "mailto:")):
                continue
            if target.startswith(REPO_URL):
                dest = ROOT / target[len(REPO_URL):]
            elif re.match(r"\w+://", target):
                continue
            else:
                dest = (path.parent / target).resolve()
            if not dest.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing link {target}")
            # Local links to excluded pages would break on the built website.
            if path in pages and DOCS / "archive" in dest.parents and not target.startswith(REPO_URL):
                errors.append(f"{path}: local link into unpublished archive: {target}")
    source = (ROOT / "examples/sagents_v2_quickstart.py").read_text()
    ast.parse(source)
    for path in extra + [DOCS / lang / "applications/GETTING_STARTED.md" for lang in ("en", "zh")]:
        if "```python\n" + source + "```" not in path.read_text():
            errors.append(f"{path}: quick-start copy differs from executable example")
    config = yaml.safe_load((DOCS / "_config.yml").read_text())
    if "archive/" not in config.get("exclude", []):
        errors.append("archive must remain excluded from publication")
    logo = config.get("logo", "").lstrip("/")
    if not (DOCS / logo).is_file():
        errors.append("site logo is missing")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated {len(pages)} current pages, navigation metadata, local links, and 5 quick-start copies.")


if __name__ == "__main__":
    main()
