"""Repository-wide source-boundary checks for the complete SAgents V2 package."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


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
        "goal",
        "interfaces",
        "memory",
        "model",
        "package",
        "plan",
        "runtime",
            "session_memory",
            "skill",
        "testing",
        "tool",
        "workspace",
    }
    assert offenders == []


def test_v2_internal_module_graph_is_acyclic():
    """Domain modules must not rely on import-order cycles to initialize."""

    modules = {_module_name(path): path for path in V2_ROOT.rglob("*.py")}
    edges = {
        name: {
            target
            for _, target in _import_targets(path)
            if target in modules and target != name
        }
        for name, path in modules.items()
    }
    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            start = active.index(module)
            cycle = " -> ".join((*active[start:], module))
            raise AssertionError(f"cyclic V2 dependency: {cycle}")
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(edges[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(modules):
        visit(module)


def test_session_port_does_not_depend_on_store_implementations():
    """Keep the storage protocol usable without importing a concrete backend."""

    contracts = V2_ROOT / "runtime" / "session" / "contracts.py"
    implementation_modules = {
        "sagents.v2.runtime.session.plugins.ephemeral",
        "sagents.v2.runtime.session.plugins.filesystem",
        "sagents.v2.runtime.session.plugins.postgres",
        "sagents.v2.runtime.session.plugins.mysql",
    }

    offenders = [
        f"{contracts.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(contracts)
        if module in implementation_modules
    ]

    assert offenders == []


def test_session_backends_share_state_machine_without_inheriting_each_other():
    """Concrete SessionStore backends may depend only on the shared state core."""

    filesystem = V2_ROOT / "runtime" / "session" / "plugins" / "filesystem.py"
    postgres = V2_ROOT / "runtime" / "session" / "plugins" / "postgres.py"
    mysql = V2_ROOT / "runtime" / "session" / "plugins" / "mysql.py"
    state = V2_ROOT / "runtime" / "session" / "state.py"
    filesystem_imports = {module for _, module in _import_targets(filesystem)}
    postgres_imports = {module for _, module in _import_targets(postgres)}
    mysql_imports = {module for _, module in _import_targets(mysql)}
    state_imports = {module for _, module in _import_targets(state)}

    assert "sagents.v2.runtime.session.plugins.ephemeral" not in filesystem_imports
    assert "sagents.v2.runtime.session.plugins.postgres" not in filesystem_imports
    assert "sagents.v2.runtime.session.plugins.mysql" not in filesystem_imports
    assert "sagents.v2.runtime.session.plugins.filesystem" not in postgres_imports
    assert "sagents.v2.runtime.session.plugins.ephemeral" not in postgres_imports
    assert "sagents.v2.runtime.session.plugins.mysql" not in postgres_imports
    assert "sagents.v2.runtime.session.plugins.filesystem" not in mysql_imports
    assert "sagents.v2.runtime.session.plugins.ephemeral" not in mysql_imports
    assert "sagents.v2.runtime.session.plugins.postgres" not in mysql_imports
    assert "sagents.v2.runtime.session.plugins.filesystem" not in state_imports
    assert "sagents.v2.runtime.session.plugins.ephemeral" not in state_imports
    assert "sagents.v2.runtime.session.plugins.postgres" not in state_imports
    assert "sagents.v2.runtime.session.plugins.mysql" not in state_imports


def test_runtime_kernel_does_not_select_a_session_store_backend():
    """The lifecycle kernel must receive its SessionStore from composition."""

    kernel = V2_ROOT / "runtime" / "kernel.py"
    implementation_prefix = "sagents.v2.runtime.session."
    allowed_port = "sagents.v2.runtime.session.contracts"
    offenders = [
        f"{kernel.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(kernel)
        if module.startswith(implementation_prefix) and module != allowed_port
    ]

    assert offenders == []


def test_execution_domains_depend_on_runtime_port_not_kernel_implementation():
    """Drivers and facades must remain replaceable from the Runtime kernel."""

    consumers = (
        V2_ROOT / "agent" / "engine.py",
        V2_ROOT / "flow" / "engine.py",
        V2_ROOT / "sagent.py",
    )
    offenders = [
        f"{path.relative_to(V2_ROOT)}:{line}: {module}"
        for path in consumers
        for line, module in _import_targets(path)
        if module == "sagents.v2.runtime.kernel"
    ]

    assert offenders == []


def test_agent_and_flow_depend_on_session_port_not_store_implementations():
    """Execution engines should consume SessionStore contracts only."""

    consumers = (
        V2_ROOT / "agent" / "engine.py",
        V2_ROOT / "flow" / "engine.py",
    )
    implementation_prefix = "sagents.v2.runtime.session.plugins"
    offenders = [
        f"{path.relative_to(V2_ROOT)}:{line}: {module}"
        for path in consumers
        for line, module in _import_targets(path)
        if module.startswith(implementation_prefix)
    ]

    assert offenders == []


def test_observability_port_does_not_depend_on_sink_implementations():
    """Keep diagnostic/log/trace contracts usable without importing a sink."""

    contracts = V2_ROOT / "runtime" / "observability" / "contracts.py"
    implementation_modules = {
        f"sagents.v2.runtime.observability.plugins.{path.stem}"
        for path in (V2_ROOT / "runtime" / "observability" / "plugins").glob("*.py")
        if path.name != "__init__.py"
    }
    offenders = [
        f"{contracts.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(contracts)
        if module in implementation_modules
    ]
    assert offenders == []


def test_observability_sinks_do_not_import_each_other():
    """Each sink plugin shares contracts, not other sink implementations."""

    plugin_dir = V2_ROOT / "runtime" / "observability" / "plugins"
    plugin_files = sorted(
        path for path in plugin_dir.glob("*.py") if path.name != "__init__.py"
    )
    plugin_modules = {
        path: f"sagents.v2.runtime.observability.plugins.{path.stem}"
        for path in plugin_files
    }
    for path, module in plugin_modules.items():
        imported = {target for _, target in _import_targets(path)}
        offenders = sorted((set(plugin_modules.values()) - {module}) & imported)
        assert offenders == [], f"{path.name} imports {offenders}"


def test_agent_does_not_import_observability_sink_plugins():
    """The Loop emits spans through ports; Builder selects the sink."""

    engine = V2_ROOT / "agent" / "engine.py"
    offenders = [
        f"{engine.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(engine)
        if module.startswith("sagents.v2.runtime.observability.plugins")
        or module == "sagents.v2.runtime.observability"
    ]
    assert offenders == []


def test_execution_ports_do_not_depend_on_backend_plugins():
    """Scheduler, sandbox, and job contracts stay backend-neutral."""

    contracts = (
        V2_ROOT / "runtime" / "execution" / "scheduler" / "contracts.py",
        V2_ROOT / "runtime" / "execution" / "scheduler" / "provider.py",
        V2_ROOT / "runtime" / "execution" / "sandbox" / "contracts.py",
        V2_ROOT / "runtime" / "execution" / "sandbox" / "provider.py",
        V2_ROOT / "runtime" / "execution" / "jobs" / "provider.py",
    )
    forbidden = "sagents.v2.runtime.execution."
    plugin_suffix = ".plugins"
    offenders = [
        f"{path.relative_to(V2_ROOT)}:{line}: {module}"
        for path in contracts
        for line, module in _import_targets(path)
        if module.startswith(forbidden) and plugin_suffix in module
    ]
    assert offenders == []


def test_workspace_credentials_and_artifact_ports_do_not_import_plugins():
    contracts = (
        V2_ROOT / "workspace" / "contracts.py",
        V2_ROOT / "runtime" / "credentials" / "contracts.py",
        V2_ROOT / "runtime" / "credentials" / "provider.py",
        V2_ROOT / "runtime" / "artifact" / "contracts.py",
    )
    forbidden = (
        "sagents.v2.workspace.plugins",
        "sagents.v2.runtime.credentials.plugins",
        "sagents.v2.runtime.artifact.plugins",
    )
    offenders = [
        f"{path.relative_to(V2_ROOT)}:{line}: {module}"
        for path in contracts
        for line, module in _import_targets(path)
        if module.startswith(forbidden)
    ]
    assert offenders == []


def test_context_contracts_do_not_import_context_plugins():
    contracts = V2_ROOT / "context" / "contracts.py"
    offenders = [
        f"{contracts.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(contracts)
        if module.startswith("sagents.v2.context.plugins")
    ]
    assert offenders == []


def test_domain_ports_do_not_import_their_plugin_implementations():
    """Ports stay backend-neutral so a new implementation is only a new file."""

    ports = (
        (V2_ROOT / "context" / "summary.py", "sagents.v2.context.plugins"),
        (V2_ROOT / "tool" / "selection.py", "sagents.v2.tool.plugins"),
        (V2_ROOT / "memory" / "query.py", "sagents.v2.memory.plugins"),
    )
    offenders = [
        f"{path.relative_to(V2_ROOT)}:{line}: {module}"
        for path, prefix in ports
        for line, module in _import_targets(path)
        if module.startswith(prefix)
    ]
    assert offenders == []


def test_agent_composition_does_not_discover_or_select_plugins():
    """Builder owns plugin selection; Agent composition receives resolved ports."""

    factory = V2_ROOT / "agent" / "factory.py"
    forbidden_prefixes = (
        "sagents.v2.runtime.extensions",
        "sagents.v2.package.manifest.loader",
    )
    offenders = [
        f"{factory.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(factory)
        if module.startswith(forbidden_prefixes)
    ]

    assert offenders == []


def test_v2_contains_no_symlink_to_repository_owned_code():
    offenders = [
        str(path.relative_to(V2_ROOT))
        for path in V2_ROOT.rglob("*")
        if path.is_symlink()
    ]
    assert offenders == []


@pytest.mark.timeout(30)
def test_v2_imports_when_it_is_the_only_sagents_implementation(tmp_path: Path):
    """Physically isolate V2 so an accidental old-module import cannot succeed.

    This copies the whole V2 tree and imports every module in a fresh interpreter;
    that is well beyond the 2s default budget on CI runners, so it gets its own limit.
    """

    package_root = tmp_path / "isolated"
    isolated_sagents = package_root / "sagents"
    isolated_sagents.mkdir(parents=True)
    (isolated_sagents / "__init__.py").write_text(
        '"""Isolated package used by the V2 source-boundary test."""\n',
        encoding="utf-8",
    )
    shutil.copytree(
        V2_ROOT, isolated_sagents / "v2", ignore=shutil.ignore_patterns("__pycache__")
    )
    script = r"""
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
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root)
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
