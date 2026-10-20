from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_hosts_remain_independent_and_sdk_never_imports_applications():
    boundaries = {
        "app/v2/desktop/backend": ("app.v2.server",),
        "app/v2/server": ("app.v2.desktop",),
        "sagents/v2": ("app",),
    }
    violations = []
    for directory, forbidden in boundaries.items():
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        package = list(path.relative_to(ROOT).parent.parts)
                        package = package[:len(package) - node.level + 1]
                        module = ".".join([*package, *module.split(".")]).rstrip(".")
                    imports = [module, *(f"{module}.{alias.name}" for alias in node.names)]
                else:
                    continue
                for name in imports:
                    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert violations == []


def test_production_composition_never_calls_registration_factory_directly():
    allowed = ROOT / "sagents/v2/runtime/extensions/host.py"
    violations: list[str] = []
    sources = (
        *(ROOT / "sagents/v2").rglob("*.py"),
        *(ROOT / "app/v2/desktop/backend").rglob("*.py"),
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
