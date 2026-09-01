"""Decorator-based authoring for native V2 Tool providers."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from sagents.v2.tool.contracts import (
    CancelSemantics,
    IdempotencyStrategy,
    ResumeStrategy,
    SideEffectLevel,
    ToolDefinition,
)


def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    strict: bool | None = None,
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE,
    idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.FINGERPRINT,
    cancel_semantics: CancelSemantics = CancelSemantics.NOT_STARTED_ONLY,
    resume_strategy: ResumeStrategy = ResumeStrategy.REPLAY_RESULT,
    supports_reconciliation: bool = False,
    requires_approval: bool = False,
    plan_safe: bool = False,
    required_scopes: tuple[str, ...] = (),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach a complete ToolDefinition to one implementation method.

    Explicit schemas take precedence. Signature inference exists for small
    native tools, while compatibility-sensitive tools should pass their frozen
    schema so names, defaults and nested parameter shapes cannot drift.
    """

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        definition = ToolDefinition(
            name=name or function.__name__,
            description=description or inspect.getdoc(function) or "",
            input_schema=input_schema or _schema_from_signature(function),
            output_schema=output_schema,
            strict=strict,
            side_effect_level=side_effect_level,
            idempotency_strategy=idempotency_strategy,
            cancel_semantics=cancel_semantics,
            resume_strategy=resume_strategy,
            supports_reconciliation=supports_reconciliation,
            requires_approval=requires_approval,
            plan_safe=plan_safe,
            required_scopes=required_scopes,
        )

        @wraps(function)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            value = function(*args, **kwargs)
            return await value if inspect.isawaitable(value) else value

        wrapped.__sagents_v2_tool__ = definition  # type: ignore[attr-defined]
        return wrapped

    return decorate


def decorated_tool_definition(value: Any) -> ToolDefinition | None:
    """Read decorator metadata from a function or bound method."""

    definition = getattr(value, "__sagents_v2_tool__", None)
    if definition is None and hasattr(value, "__func__"):
        definition = getattr(value.__func__, "__sagents_v2_tool__", None)
    return definition if isinstance(definition, ToolDefinition) else None


def _schema_from_signature(function: Callable[..., Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    hints = get_type_hints(function)
    for parameter in inspect.signature(function).parameters.values():
        # Runtime-owned values are injected by DecoratedToolProvider and are
        # intentionally absent from the model-visible argument schema.
        if parameter.name in {"self", "invocation", "request_context"}:
            continue
        schema = _annotation_schema(hints.get(parameter.name, parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
        else:
            schema["default"] = parameter.default
        properties[parameter.name] = schema
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in {Union, UnionType}:
        choices = [
            _annotation_schema(value) for value in arguments if value is not type(None)
        ]
        if len(choices) == 1 and len(choices) != len(arguments):
            return {"anyOf": [choices[0], {"type": "null"}]}
        return {"anyOf": choices}
    if origin is Literal:
        values = list(arguments)
        schema = _annotation_schema(type(values[0])) if values else {"type": "string"}
        schema["enum"] = values
        return schema
    if origin in {list, tuple}:
        return {
            "type": "array",
            "items": _annotation_schema(arguments[0]) if arguments else {},
        }
    if origin is dict:
        return {"type": "object"}
    return {
        "type": {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }.get(annotation, "string")
    }
