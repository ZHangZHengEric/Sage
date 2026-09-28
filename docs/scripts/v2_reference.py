"""Read public v2 configuration and route declarations without importing the host."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def server_environment() -> dict[str, str]:
    tree = ast.parse((ROOT / "app/v2/server/config/settings.py").read_text())
    values = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"_env", "_choice_env"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            name = node.args[0].value
            if isinstance(name, str) and name.startswith("SAGE_SERVER_"):
                default = node.args[1] if len(node.args) > 1 else ast.Constant("")
                values[name] = (
                    str(default.value) if isinstance(default, ast.Constant) else ""
                )
    return values


def server_routes() -> list[tuple[str, str, str]]:
    card = ast.parse((ROOT / "app/v2/server/conversations/a2a/card.py").read_text())
    constants = {
        n.targets[0].id: n.value.value
        for n in card.body
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and isinstance(n.value, ast.Constant)
    }

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        if isinstance(node, ast.JoinedStr):
            return "".join(
                str(value(n.value if isinstance(n, ast.FormattedValue) else n))
                for n in node.values
            )
        raise ValueError(f"Unsupported route expression: {ast.dump(node)}")

    routes = []
    for path in sorted((ROOT / "app/v2/server/routers").glob("*.py")):
        tree = ast.parse(path.read_text())
        prefix = ""
        for n in tree.body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                if (
                    isinstance(n.value.func, ast.Name)
                    and n.value.func.id == "APIRouter"
                ):
                    prefix = next(
                        (value(k.value) for k in n.value.keywords if k.arg == "prefix"),
                        "",
                    )
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if not (
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "router"
                ):
                    continue
                methods = [d.func.attr.upper()]
                if d.func.attr == "api_route":
                    methods = next(
                        ast.literal_eval(k.value)
                        for k in d.keywords
                        if k.arg == "methods"
                    )
                routes.append(("/".join(methods), prefix + value(d.args[0]), path.stem))
    return sorted(routes, key=lambda row: (row[2], row[1], row[0]))


def route_table() -> str:
    return "\n".join(
        f"| `{method}` | `{path}` | `{router}` |"
        for method, path, router in server_routes()
    )
