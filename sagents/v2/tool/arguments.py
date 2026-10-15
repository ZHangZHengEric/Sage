"""Bind host-provided system context before a Tool call is authorized."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sagents.v2.tool.contracts import ToolDefinition


def apply_system_context_overrides(
    definition: ToolDefinition,
    arguments: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply v1's declared, top-level, non-None context overrides.

    Context can fill an omitted argument as well as replace a model value.
    Never forward unrelated metadata or recursively match nested keys. Copy
    injected values so Tool implementations cannot mutate the Run's context.
    """

    merged = dict(arguments)
    system_context = metadata.get("system_context")
    if not isinstance(system_context, Mapping):
        return merged
    schema = definition.input_schema
    declared = set(schema.get("properties", {})) | set(schema.get("required", ()))
    for name in declared:
        if name in system_context and system_context[name] is not None:
            merged[name] = deepcopy(system_context[name])
    return merged
