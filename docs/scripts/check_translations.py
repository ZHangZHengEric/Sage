"""Validate bilingual structure and executable examples, without a Jekyll build."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

FIELDS = ("ref", "nav_order", "has_children", "nav_exclude", "layout")


def metadata(text: str) -> dict:
    return yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---\n") else {}


def snippets(text: str) -> list[tuple[str, str]]:
    result = []
    for language, body in re.findall(r"^```([^\n]*)\n(.*?)^```\s*$", text, re.M | re.S):
        if language == "mermaid":
            # Diagram labels are translated; the graph remains manually reviewed.
            continue
        lines = [
            line.rstrip()
            for line in body.splitlines()
            if not line.lstrip().startswith("#")
        ]
        result.append((language, "\n".join(lines).strip()))
    return result


def translation_errors(pages: dict[str, str]) -> list[str]:
    errors = []
    by_lang = {
        lang: {
            p[len(lang) + 1 :]: text
            for p, text in pages.items()
            if p.startswith(lang + "/")
        }
        for lang in ("en", "zh")
    }
    for relative in sorted(set(by_lang["en"]) | set(by_lang["zh"])):
        if any(relative not in by_lang[lang] for lang in by_lang):
            errors.append(f"{relative}: missing English/Chinese counterpart")
            continue
        a, b = (by_lang[lang][relative] for lang in ("en", "zh"))
        ma, mb = metadata(a), metadata(b)
        for field in FIELDS:
            if ma.get(field) != mb.get(field):
                errors.append(f"{relative}: translation differs in {field}")
        for lang, m in [("en", ma), ("zh", mb)]:
            if m.get("lang") != lang:
                errors.append(f"{relative}: incorrect {lang} language metadata")
        parents = []
        for lang, m in [("en", ma), ("zh", mb)]:
            parent = m.get("parent")
            matches = (
                [
                    metadata(t).get("ref")
                    for t in by_lang[lang].values()
                    if metadata(t).get("title") == parent
                ]
                if parent
                else [None]
            )
            parents.append(matches)
        if parents[0] != parents[1] or len(parents[0]) != 1:
            errors.append(f"{relative}: translated parent hierarchy differs")
        if re.findall(r"^#{1,6} ", a, re.M) != re.findall(r"^#{1,6} ", b, re.M):
            errors.append(f"{relative}: translated heading structure differs")
        if snippets(a) != snippets(b):
            errors.append(f"{relative}: translated code examples differ")
        links = [re.findall(r"\]\(([^)]+)\)", t) for t in (a, b)]
        if links[0] != links[1]:
            errors.append(f"{relative}: translated link targets/order differ")
    return errors


def load_pages(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text()
        for lang in ("en", "zh")
        for p in (root / lang).rglob("*.md")
    }
