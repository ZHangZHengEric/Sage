import ast
from pathlib import Path


def _imported_modules(node: ast.AST):
    modules = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            modules.extend(alias.name for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module:
            modules.append(child.module)
    return modules


def _calls_function(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
        for child in ast.walk(node)
    )


def test_server_chat_service_does_not_import_desktop_im_storage_model():
    repo_root = Path(__file__).resolve().parents[3]
    tree = ast.parse((repo_root / "common/services/chat_service.py").read_text())

    top_level_imports = []
    helper = None
    desktop_guarded_calls = 0
    total_calls = 0

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            top_level_imports.extend(_imported_modules(node))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_apply_desktop_im_tools":
            helper = node

    assert "common.models.im_channel" not in top_level_imports
    assert helper is not None
    assert "common.models.im_channel" in _imported_modules(helper)

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _calls_function(node.test, "_is_desktop_mode"):
            continue
        if _calls_function(node, "_apply_desktop_im_tools"):
            desktop_guarded_calls += 1

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_apply_desktop_im_tools"
        ):
            total_calls += 1

    assert desktop_guarded_calls == 1
    assert total_calls == 1
