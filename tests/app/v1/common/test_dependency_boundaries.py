import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COMMON_ROOT = REPOSITORY_ROOT / "app/v1/common"


def _app_dependencies(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dependencies: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dependencies.extend(
                alias.name for alias in node.names if alias.name.startswith("app.")
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "app" or node.module.startswith("app.")):
                dependencies.append(node.module)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str) and node.value.startswith("app."):
                dependencies.append(node.value)

    return [name for name in dependencies if name != "app.v1.common" and not name.startswith("app.v1.common.")]


def test_common_does_not_depend_on_application_packages():
    assert COMMON_ROOT.is_dir()
    violations = {
        str(path.relative_to(REPOSITORY_ROOT)): dependencies
        for path in COMMON_ROOT.rglob("*.py")
        if (dependencies := _app_dependencies(path))
    }

    assert violations == {}
