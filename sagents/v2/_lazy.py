"""Small PEP 562 helper for side-effect-free public package facades."""

from __future__ import annotations

from importlib import import_module
from typing import Any


LazyExports = dict[str, tuple[str, str]]


def resolve_export(
    name: str,
    exports: LazyExports,
    namespace: dict[str, Any],
) -> Any:
    """Load one public symbol without importing unrelated implementations."""

    try:
        module_name, attribute = exports[name]
    except KeyError as exc:
        module_name = str(namespace.get("__name__") or "module")
        raise AttributeError(
            f"module {module_name!r} has no attribute {name!r}"
        ) from exc
    value = getattr(import_module(module_name), attribute)
    namespace[name] = value
    return value


def exported_names(exports: LazyExports, namespace: dict[str, Any]) -> list[str]:
    return sorted({*namespace, *exports})


__all__ = ["LazyExports", "exported_names", "resolve_export"]
