"""Check version boundaries and Python source imports without importing runtimes.

Run from any directory: python scripts/checks/check_architecture.py
Only version-controlled and non-ignored new Python files are inspected.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FIRST_PARTY = {"sagents", "app", "common", "mcp_servers", "clients"}
# Independent MCP integration; its package is checked separately below.
MCP_INTEGRATIONS = {
    ("app/v2/desktop/backend/anytool.py", "mcp_servers.anytool.anytool_server"),
}


def imports(tree: ast.AST, package: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = package.split(".")
                module = ".".join(parts[:len(parts) - node.level + 1] + ([module] if module else []))
            if module:
                yield node.lineno, module
                if module in {"sagents", "app"}:
                    for alias in node.names:
                        if alias.name != "*":
                            yield node.lineno, module + "." + alias.name
        elif isinstance(node, ast.Call) and node.args:
            name = ast.unparse(node.func)
            if name in {"importlib.import_module", "__import__"}:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yield node.lineno, arg.value


def check() -> tuple[int, list[str]]:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT
    ).decode().split("\0")
    errors = []
    count = 0
    for name in sorted(set(paths)):
        path = ROOT / name
        if path.suffix != ".py" or not path.is_file():
            continue
        count += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        # Archived manual demos are not supported application entry points.
        if name.startswith("tests/manual/"):
            continue
        package = ".".join(path.relative_to(ROOT).parts[:-1])
        for line, module in imports(tree, package):
            top = module.split(".")[0]
            if top not in FIRST_PARTY:
                continue
            if name.startswith("mcp_servers/anytool/") and top in {"app", "common", "sagents"}:
                errors.append(f"{name}:{line}: standalone MCP depends on Sage {module}")
            target = ROOT.joinpath(*module.split("."))
            if module not in {"sagents.SAgent"} and not target.is_dir() and not target.with_suffix(".py").is_file():
                errors.append(f"{name}:{line}: missing internal module {module}")
            runtime = "v1" if name.startswith("sagents/v1/") else "v2" if name.startswith("sagents/v2/") else None
            if runtime and top in {"app", "common"}:
                errors.append(f"{name}:{line}: runtime depends on application {module}")
            if runtime and module.startswith("sagents.") and not module.startswith(f"sagents.{runtime}.") and module != f"sagents.{runtime}":
                errors.append(f"{name}:{line}: cross-version runtime dependency {module}")
            if name.startswith(("app/v2/desktop/", "app/v2/server/", "app/v2/cli/")):
                legacy = top in {"common", "mcp_servers"} or module.startswith(("sagents.v1", "app.v1")) or module in {"sagents", "sagents.SAgent"}
                if legacy and (name, module) not in MCP_INTEGRATIONS:
                    errors.append(f"{name}:{line}: unregistered legacy application dependency {module}")
    for obsolete in ("common", "app/desktop_v2", "app/server_v2", "app/cli", "app/terminal"):
        if (ROOT / obsolete).exists():
            errors.append(f"obsolete source directory {obsolete}; use the versioned application tree")
    if (ROOT / "sagents/shared").exists():
        errors.append("sagents/shared must not exist; implementations belong to their version")
    return count, sorted(set(errors))


if __name__ == "__main__":
    total, failures = check()
    print(f"Checked {total} Python files; {len(failures)} architecture/import issues.")
    for failure in failures:
        print(failure)
    raise SystemExit(bool(failures))
