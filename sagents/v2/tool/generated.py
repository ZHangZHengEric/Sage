"""Versioned, pure JSON-expression tools produced by package optimization.

Expressions are data interpreted by a bounded allowlist, never Python, shell,
network, filesystem or dynamic imports. Tool implementation travels with package.
"""

from __future__ import annotations

import json
import math
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.items import TextBlock
from sagents.v2.tool.contracts import ToolDefinition, ToolExecutionResult
from sagents.v2.tool.plugins.ephemeral import EphemeralToolPlugin

PREFIX = "tools/rsi/"
OPS = {
    "if",
    "and",
    "or",
    "not",
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "add",
    "sub",
    "mul",
    "div",
    "in",
    "concat",
    "coalesce",
    "filter", "map", "sort", "length", "sum", "at",
}


def _check(value, depth=0, count=None):
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > 512 or depth > 24:
        raise ValueError("generated tool expression exceeds complexity bound")
    if isinstance(value, dict):
        if "op" in value:
            if (
                set(value) != {"op", "args"}
                or value["op"] not in OPS
                or not isinstance(value["args"], list)
            ):
                raise ValueError("invalid generated tool operation")
            arity = {
                "if": (3, 3),
                "not": (1, 1),
                "eq": (2, 2),
                "ne": (2, 2),
                "lt": (2, 2),
                "lte": (2, 2),
                "gt": (2, 2),
                "gte": (2, 2),
                "sub": (2, 2),
                "div": (2, 2),
                "in": (2, 2),
                "filter": (2, 2), "map": (2, 2), "sort": (2, 2),
                "length": (1, 1), "sum": (1, 1), "at": (2, 2),
            }.get(value["op"], (1, 32))
            if not arity[0] <= len(value["args"]) <= arity[1]:
                raise ValueError("invalid generated tool operation arity")
        elif "var" in value:
            if (
                set(value) != {"var"}
                or not isinstance(value["var"], str)
                or len(value["var"]) > 256
            ):
                raise ValueError("invalid generated tool argument path")
        for child in value.values():
            _check(child, depth + 1, count)
    elif isinstance(value, list):
        for child in value:
            _check(child, depth + 1, count)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("generated tools only accept JSON expressions")


class GeneratedTool(StrictModel):
    description: str = Field(min_length=1, max_length=2000)
    input_schema: dict[str, Any]
    expression: Any

    @model_validator(mode="after")
    def validate_implementation(self):
        encoded = json.dumps(self.model_dump(mode="json"), allow_nan=False)
        if len(encoded.encode()) > 32768:
            raise ValueError("generated tool exceeds 32 KiB")
        if self.input_schema.get("type") != "object":
            raise ValueError("generated tool input must be an object")

        def check_schema(value):
            if isinstance(value, dict):
                if any(k in value for k in ("$ref", "$dynamicRef", "$recursiveRef")):
                    raise ValueError("generated tool schemas cannot resolve references")
                for child in value.values():
                    check_schema(child)
            elif isinstance(value, list):
                for child in value:
                    check_schema(child)

        check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.input_schema)
        _check(self.expression)
        return self


def evaluate(expression, arguments):
    steps = 0

    def walk(value, environment=None):
        nonlocal steps
        steps += 1
        if steps > 20000:
            raise ValueError("generated tool execution exceeds step bound")
        environment = arguments if environment is None else environment
        if isinstance(value, list):
            return [walk(v, environment) for v in value]
        if not isinstance(value, dict):
            return value
        if "var" in value:
            result = environment
            for part in value["var"].split("."):
                result = (result.get(part) if isinstance(result, dict) else
                          result[int(part)] if isinstance(result, list) and part.isdigit() and int(part) < len(result) else None)
            return result
        if "op" not in value:
            return {k: walk(v, environment) for k, v in value.items()}
        op, args = value["op"], value["args"]
        if op in {"filter", "map", "sort"}:
            items = walk(args[0], environment)
            if not isinstance(items, list) or len(items) > 256:
                raise ValueError("collection operations require an array of at most 256 items")
            def project(item):
                return walk(args[1], {**environment, "item": item})
            if op == "filter":
                return [item for item in items if project(item)]
            if op == "map":
                return [project(item) for item in items]
            return sorted(items, key=project)
        if op == "if":
            return walk(args[1] if walk(args[0], environment) else args[2], environment)
        if op == "and":
            return all(walk(a, environment) for a in args)
        if op == "or":
            return any(walk(a, environment) for a in args)
        if op == "coalesce":
            for a in args:
                result = walk(a, environment)
                if result is not None:
                    return result
            return None
        values = [walk(a, environment) for a in args]
        a = values[0]
        b = values[1] if len(values) > 1 else None
        if op in {"length", "sum", "at"}:
            if not isinstance(a, list) or len(a) > 256:
                raise ValueError("collection operation requires a bounded array")
            if op == "length":
                return len(a)
            if op == "at":
                if type(b) is not int or not -len(a) <= b < len(a):
                    raise ValueError("array index is out of range")
                return a[b]
            if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e15 for v in a):
                raise ValueError("sum requires bounded finite numbers")
            return sum(a)
        if op == "not":
            return not a
        if op == "eq":
            return type(a) is type(b) and a == b
        if op == "ne":
            return not (type(a) is type(b) and a == b)
        if op == "in":
            return a in b
        if op == "concat":
            if not all(isinstance(v, str) for v in values):
                raise ValueError("concat requires strings")
            return "".join(values)
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e15
            for v in values
        ):
            raise ValueError("numeric operation requires bounded finite numbers")
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "add":
            return sum(values)
        if op == "sub":
            return a - b
        if op == "mul":
            return math.prod(values)
        if op == "div":
            return a / b
        raise ValueError("unknown generated tool operation")

    result = walk(expression)
    if len(json.dumps(result, allow_nan=False).encode()) > 65536:
        raise ValueError("generated tool result exceeds 64 KiB")
    return result


def generated_tools(files):
    values = {}
    for path, content in files.items():
        if path.startswith(PREFIX):
            name = path[len(PREFIX) : -5] if path.endswith(".json") else ""
            if (
                not name.startswith("rsi_")
                or not name.replace("_", "").isalnum()
                or len(name) > 64
            ):
                raise ValueError(
                    "generated tool names must use rsi_ and ASCII letters, digits, underscores"
                )
            if not name.isascii():
                raise ValueError("generated tool names must be ASCII")
            values[name] = GeneratedTool.model_validate_json(content)
    if len(values) > 8:
        raise ValueError("at most eight generated tools are supported per package")
    return values


def generated_tool_provider(files):
    specs = generated_tools(files)
    definitions, handlers = [], {}
    for name, spec in specs.items():
        definitions.append(
            ToolDefinition(
                name=name, description=spec.description, input_schema=spec.input_schema
            )
        )

        async def execute(call, context, spec=spec):
            result = evaluate(spec.expression, call.arguments)
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text=json.dumps(result, ensure_ascii=False)),),
            )

        handlers[name] = execute
    return EphemeralToolPlugin(tuple(definitions), handlers)
