"""Bounded numeric probes matching the native OpenUI arithmetic contract.

These probes provide reproducible evidence, not exhaustive proof over input ranges.
"""

import math
from functools import reduce
from operator import mul

from .openui import validate_tree


class NumericEvaluation:
    def __init__(self, values):
        self.values = values
        self.remaining = 2048
        self.active = set()

    def resolve(self, value, depth=0, *, selection=False) -> float | None:
        self.remaining -= 1
        if self.remaining < 0 or depth > 12:
            return None
        if isinstance(value, str):
            if value in self.active:
                return None
            self.active.add(value)
            result = self.resolve(
                self.values.get(value), depth + 1, selection=selection
            )
            self.active.remove(value)
            return result
        if selection:
            if isinstance(value, dict) and value.get("component") == "CheckboxGroup":
                return self.resolve(value["props"]["name"], depth + 1, selection=True)
            if (
                isinstance(value, list)
                and len(value) <= 100
                and all(isinstance(v, str) for v in value)
            ):
                return float(len(set(value)))
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value) if math.isfinite(value) else None
        if isinstance(value, dict):
            props = value.get("props", {})
            if value.get("component") == "Computed":
                return self.compute(
                    props.get("operation"), props.get("inputs", []), depth + 1
                )
            if value.get("component") in {"NumberInput", "Slider"}:
                return self.resolve(props.get("name"), depth + 1)
        return None

    def compute(self, operation, inputs, depth=0) -> float | None:
        if depth > 12 or not 1 <= len(inputs) <= 16:
            return None
        args: list[float] = []
        for value in inputs:
            resolved = self.resolve(value, depth, selection=operation == "count")
            if resolved is None:
                return None
            args.append(resolved)
        try:
            if operation in {"count", "sum"}:
                result = sum(args)
            elif operation == "product":
                result = reduce(mul, args, 1)
            elif operation in {"difference", "divide", "ratioPercent", "percent"}:
                if len(args) != 2:
                    return None
                a, b = args
                if operation == "difference":
                    result = a - b
                elif operation == "divide":
                    result = a / b
                elif operation == "ratioPercent":
                    if b <= 0:
                        return None
                    result = a / b * 100
                else:
                    result = a * b / 100
            elif operation in {"compoundGrowth", "loanPayment"}:
                if len(args) != 3:
                    return None
                a, b, c = args
                if operation == "compoundGrowth":
                    if a < 0 or b < -100 or c < 0 or c > 1000:
                        return None
                    result = a * math.pow(1 + b / 100, c)
                else:
                    if a < 0 or b < 0 or c <= 0 or c > 12000:
                        return None
                    rate = b / 1200
                    result = (
                        a / c if rate == 0 else a * rate / (1 - math.pow(1 + rate, -c))
                    )
            else:
                return None
        except (OverflowError, ValueError, ZeroDivisionError):
            return None
        return result if math.isfinite(result) and abs(result) <= 1e15 else None


def probe_tree(tree, *, max_work=100_000):
    fields, actions = validate_tree(tree)
    bindings = {}
    outputs = []

    def walk(value, path="root"):
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, dict):
            component = value.get("component")
            props = value.get("props", {})
            if "id" in value:
                bindings[value["id"]] = value
            if component == "Computed":
                outputs.append((path, value, "computed"))
            elif component == "Progress":
                outputs.append((path, props["value"], "progress"))
            elif component == "Chart":
                for i, series in enumerate(props["series"]):
                    for j, operand in enumerate(series["values"]):
                        outputs.append(
                            (f"{path}.series[{i}].values[{j}]", operand, props["type"])
                        )
            for key, item in value.items():
                walk(item, f"{path}.{key}")

    walk(tree)
    values = {**bindings, **{key: spec.get("value") for key, spec in fields.items()}}

    remaining_work = max_work

    def evaluate(current):
        nonlocal remaining_work
        results, errors = {}, []
        for path, operand, kind in outputs:
            evaluator = NumericEvaluation(current)
            result = (
                evaluator.compute(
                    operand["props"]["operation"], operand["props"]["inputs"]
                )
                if kind == "computed"
                else evaluator.resolve(operand)
            )
            remaining_work -= max(1, 2048 - evaluator.remaining)
            if remaining_work < 0:
                raise ValueError(
                    "Numeric self-check work budget exceeded; simplify the dependency graph"
                )
            results[path] = result
            if result is None:
                errors.append(
                    f"{path}: calculation is undefined or exceeds native numeric limits"
                )
            elif kind == "progress" and not 0 <= result <= 100:
                errors.append(f"{path}: progress {result:g} is outside 0..100")
            elif kind == "pie" and result < 0:
                errors.append(f"{path}: pie value {result:g} is negative")
        return results, errors

    initial, errors = evaluate(values)
    probes = []
    for name, spec in fields.items():
        candidates = []
        if spec["component"] in {"NumberInput", "Slider"}:
            lo, hi, value = spec["min"], spec["max"], spec["value"]
            candidates = [lo, hi, min(hi, value + spec.get("step", 1))]
        elif spec["component"] == "CheckboxGroup":
            candidates = [[], list(spec["options"])]
        for candidate in candidates:
            if candidate == values[name] or any(
                p["field"] == name and p["value"] == candidate for p in probes
            ):
                continue
            results, failures = evaluate({**values, name: candidate})
            probes.append(
                {
                    "field": name,
                    "value": candidate,
                    "results": results,
                    "errors": failures,
                }
            )
            # An explicitly allowed input must not break a displayed calculation.
            errors.extend(
                f"When {name}={candidate!r}: {failure}" for failure in failures
            )
    return errors, {
        "defaults": initial,
        "probes": probes,
        "fields": fields,
        "actions": actions,
    }
