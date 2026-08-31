from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_production_composition_never_calls_registration_factory_directly():
    allowed = ROOT / "sagents/v2/runtime/extensions/host.py"
    violations: list[str] = []
    sources = (
        *(ROOT / "sagents/v2").rglob("*.py"),
        *(ROOT / "app/desktop_v2/backend").rglob("*.py"),
    )
    for path in sources:
        if path == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "factory":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_removed_v2_compatibility_entrypoints_do_not_return():
    public_source = (ROOT / "sagents/v2/__init__.py").read_text(encoding="utf-8")
    builder_source = (ROOT / "sagents/v2/builder.py").read_text(encoding="utf-8")
    assert "AgentHost" not in public_source
    assert "build_sync" not in builder_source
    assert not (ROOT / "sagents/v2/host.py").exists()
