"""Repository-wide source-boundary checks for the complete SAgents V2 package."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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
        "composition",
        "flow",
        "goal",
        "interfaces",
        "memory",
        "model",
        "optimization",
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

    filesystem = V2_ROOT / "runtime" / "session" / "plugins" / "filesystem"
    mysql = V2_ROOT / "runtime" / "session" / "plugins" / "mysql"
    state = V2_ROOT / "runtime" / "session" / "state.py"
    filesystem_imports = {module for path in filesystem.rglob("*.py") for _, module in _import_targets(path)}
    mysql_imports = {
        module
        for path in mysql.rglob("*.py")
        for _, module in _import_targets(path)
    }
    state_imports = {module for _, module in _import_targets(state)}

    assert "sagents.v2.runtime.session.plugins.ephemeral" not in filesystem_imports
    assert "sagents.v2.runtime.session.plugins.mysql" not in filesystem_imports
    assert "sagents.v2.runtime.session.plugins.filesystem" not in mysql_imports
    assert "sagents.v2.runtime.session.plugins.ephemeral" not in mysql_imports
    assert "sagents.v2.runtime.session.plugins.filesystem" not in state_imports
    assert "sagents.v2.runtime.session.plugins.ephemeral" not in state_imports
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
        _module_name(path)
        for path in _plugin_entries(V2_ROOT / "runtime" / "observability" / "plugins")
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
    plugin_modules = {path: _module_name(path) for path in _plugin_entries(plugin_dir)}
    for entry, module in plugin_modules.items():
        paths = entry.parent.rglob("*.py") if entry.name == "__init__.py" else (entry,)
        imported = {target for path in paths for _, target in _import_targets(path)}
        siblings = set(plugin_modules.values()) - {module}
        offenders = sorted(
            target for target in imported
            if any(target == sibling or target.startswith(sibling + ".") for sibling in siblings)
        )
        assert offenders == [], f"{module} imports {offenders}"


def _plugin_entries(plugin_dir: Path):
    for path in sorted(plugin_dir.iterdir()):
        if path.name in {"__init__.py", "__pycache__", "_shared"}:
            continue
        if path.is_file() and path.suffix == ".py" and path.name != "__init__.py":
            yield path
        elif path.is_dir() and (path / "__init__.py").is_file():
            yield path / "__init__.py"


def test_plugin_implementations_do_not_import_siblings():
    """A plugin may use other domains, but never another plugin in its domain."""

    offenders: list[str] = []
    for plugin_dir in sorted(V2_ROOT.rglob("plugins")):
        if not plugin_dir.is_dir():
            continue
        prefix = f"{_module_name(plugin_dir / '__init__.py')}."
        for entry in _plugin_entries(plugin_dir):
            own_module = _module_name(entry)
            paths = (
                sorted(entry.parent.rglob("*.py"))
                if entry.name == "__init__.py" else (entry,)
            )
            for path in paths:
                for line, module in _import_targets(path):
                    own_implementation = module == own_module or module.startswith(own_module + ".")
                    shared_support = module == prefix + "_shared" or module.startswith(prefix + "_shared.")
                    if module.startswith(prefix) and not own_implementation and not shared_support:
                        offenders.append(f"{path.relative_to(V2_ROOT)}:{line}: {module}")

        shared_dir = plugin_dir / "_shared"
        for path in sorted(shared_dir.rglob("*.py")):
            for line, module in _import_targets(path):
                if module.startswith(prefix) and not module.startswith(prefix + "_shared."):
                    offenders.append(f"{path.relative_to(V2_ROOT)}:{line}: {module}")

    assert offenders == []


@pytest.mark.timeout(30)
def test_importing_one_plugin_does_not_eager_load_siblings():
    """Package facades must not turn one plugin import into sibling fan-out."""

    modules = sorted(
        _module_name(path)
        for plugin_dir in V2_ROOT.rglob("plugins")
        if plugin_dir.is_dir()
        for path in _plugin_entries(plugin_dir)
    )
    script = r"""
import importlib
import json
import sys

target = sys.argv[1]
plugin_modules = set(json.loads(sys.argv[2]))
domain_prefix = target.split(".plugins.", 1)[0] + ".plugins."
importlib.import_module(target)
loaded = sorted(
    name
    for name in plugin_modules.intersection(sys.modules)
    if name.startswith(domain_prefix) and name != target
)
print(json.dumps(loaded))
"""
    offenders: list[str] = []
    encoded_modules = json.dumps(modules)

    def inspect_import(module):
        return subprocess.run(
            [sys.executable, "-c", script, module, encoded_modules],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    # Each import still gets a fresh interpreter; bound startup concurrency so
    # growing the plugin inventory does not consume the whole test deadline.
    with ThreadPoolExecutor(max_workers=4) as executor:
        for module, result in zip(modules, executor.map(inspect_import, modules)):
            assert result.returncode == 0, f"{module}: {result.stderr}"
            loaded = json.loads(result.stdout)
            if loaded:
                offenders.append(f"{module}: {loaded}")

    assert offenders == []


def test_tool_selection_plugins_do_not_import_the_package_facade():
    """Import concrete ports without eagerly loading sibling plugins."""
    for path in sorted((V2_ROOT / "tool" / "plugins").glob("selection_*.py")):
        imports = {module for _, module in _import_targets(path)}
        assert "sagents.v2.tool.plugins" not in imports


def test_continuation_plugins_do_not_inherit_each_other():
    """Each continuation plugin owns its policy pipeline."""

    path = V2_ROOT / "agent" / "policy" / "continuation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    plugin_classes = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(member, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "plugin_id"
                for target in member.targets
            )
            for member in node.body
        )
    }
    inherited_plugins = {
        node.name: ast.unparse(base)
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in plugin_classes
        for base in node.bases
        if ast.unparse(base) in plugin_classes
    }
    assert inherited_plugins == {}


def test_agent_loop_engine_does_not_depend_on_observability():
    """The RunDriver executes the loop; an outer adapter observes it."""

    engine = V2_ROOT / "agent" / "engine.py"
    offenders = [
        f"{engine.relative_to(V2_ROOT)}:{line}: {module}"
        for line, module in _import_targets(engine)
        if module.startswith("sagents.v2.runtime.observability")
    ]
    assert offenders == []

    tree = ast.parse(engine.read_text(encoding="utf-8"), filename=str(engine))
    constructor = next(
        member
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AgentLoopEngine"
        for member in node.body
        if isinstance(member, ast.FunctionDef) and member.name == "__init__"
    )
    parameters = {
        argument.arg
        for argument in (*constructor.args.args, *constructor.args.kwonlyargs)
    }
    assert parameters.isdisjoint({"trace_sink", "log_sink", "observability"})


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
        (V2_ROOT / "agent" / "policy" / "continuation.py", "sagents.v2.agent.policy.plugins"),
        (V2_ROOT / "agent" / "policy" / "tool_policy.py", "sagents.v2.agent.policy.plugins"),
        (V2_ROOT / "agent" / "policy" / "approval_memory.py", "sagents.v2.agent.policy.plugins"),
        (V2_ROOT / "runtime" / "session" / "child_heads.py", "sagents.v2.runtime.session.plugins"),
        (V2_ROOT / "runtime" / "session" / "metadata_replay.py", "sagents.v2.runtime.session.plugins"),
        (V2_ROOT / "runtime" / "observability" / "query.py", "sagents.v2.runtime.observability.plugins"),
        (V2_ROOT / "package" / "registry" / "contracts.py", "sagents.v2.package.registry.plugins"),
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
