"""Repository-wide source-boundary checks for the complete SAgents V2 package."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[3]
V2_ROOT = REPOSITORY_ROOT / "sagents" / "v2"
FIRST_PARTY_ROOTS = {
    "sagents",
    "common",
    "app",
    "mcp_servers",
    "agents",
    "skills",
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPOSITORY_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_targets(path: Path) -> list[tuple[int, str]]:
    """Return static and literal-dynamic imports from one V2 source file."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[tuple[int, str]] = []
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                targets.append((node.lineno, node.module))
            elif node.level:
                # Resolve relative imports so ``from ...legacy`` cannot escape
                # the V2 package while looking harmless in a textual scan.
                base = package.split(".")
                keep = len(base) - node.level + 1
                prefix = base[: max(0, keep)]
                if node.module:
                    prefix.extend(node.module.split("."))
                targets.append((node.lineno, ".".join(prefix)))
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"import_module", "find_spec"}
                )
            )
        ):
            targets.append((node.lineno, node.args[0].value))
    return targets


def test_every_v2_domain_imports_only_v2_first_party_code():
    offenders: list[str] = []
    covered_domains: set[str] = set()
    for path in V2_ROOT.rglob("*.py"):
        relative = path.relative_to(V2_ROOT)
        covered_domains.add(relative.parts[0] if len(relative.parts) > 1 else "root")
        for line, module in _import_targets(path):
            root = module.split(".", 1)[0]
            if root in FIRST_PARTY_ROOTS and not module.startswith("sagents.v2"):
                offenders.append(f"{relative}:{line}: {module}")

    assert covered_domains == {
        "root",
        "agent",
        "context",
        "contracts",
        "flow",
        "interfaces",
        "memory",
        "model",
        "package",
        "runtime",
        "skill",
        "testing",
        "tool",
    }
    assert offenders == []


def test_v2_contains_no_symlink_to_repository_owned_code():
    offenders = [
        str(path.relative_to(V2_ROOT))
        for path in V2_ROOT.rglob("*")
        if path.is_symlink()
    ]
    assert offenders == []


def test_v2_imports_when_it_is_the_only_sagents_implementation(tmp_path: Path):
    """Physically isolate V2 so an accidental old-module import cannot succeed."""

    package_root = tmp_path / "isolated"
    isolated_sagents = package_root / "sagents"
    isolated_sagents.mkdir(parents=True)
    (isolated_sagents / "__init__.py").write_text(
        '"""Isolated package used by the V2 source-boundary test."""\n',
        encoding="utf-8",
    )
    shutil.copytree(V2_ROOT, isolated_sagents / "v2", ignore=shutil.ignore_patterns("__pycache__"))
    script = r'''
import importlib
import importlib.abc
from pathlib import Path

forbidden = ("common", "app", "mcp_servers", "agents", "skills")
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(forbidden):
            raise ImportError(f"forbidden first-party dependency: {fullname}")
        if fullname.startswith("sagents.") and not fullname.startswith("sagents.v2"):
            raise ImportError(f"forbidden SAgents dependency: {fullname}")
        return None

import sys
sys.meta_path.insert(0, Boundary())
root = Path("sagents/v2")
modules = []
for source in root.rglob("*.py"):
    parts = list(source.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    modules.append(".".join(parts))
for name in sorted(set(modules), key=lambda value: (value.count("."), value)):
    module = importlib.import_module(name)
    location = getattr(module, "__file__", None)
    if location and root.resolve() not in Path(location).resolve().parents:
        raise RuntimeError(f"{name} loaded outside isolated V2: {location}")
print(len(set(modules)))
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root)
    environment["PYTHONNOUSERSITE"] = "1"
    expected_module_count = len({_module_name(path) for path in V2_ROOT.rglob("*.py")})
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=package_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected_module_count)
