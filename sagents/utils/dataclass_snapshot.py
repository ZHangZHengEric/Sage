"""Fast paths for plain dataclass payloads, with standard-library fallbacks."""
from dataclasses import asdict, dataclass, fields

# Exact types only: subclasses may customize deepcopy/conversion behavior.
_ATOMIC_TYPES = frozenset((type(None), bool, int, float, str, bytes, complex))


@dataclass
class _Field:
    value: object


def _field_snapshot(value):
    kind = type(value)
    if kind in _ATOMIC_TYPES:
        return value
    if kind is dict:
        return {_field_snapshot(k): _field_snapshot(v) for k, v in value.items()}
    if kind is list:
        return [_field_snapshot(item) for item in value]
    if kind is tuple:
        return tuple(_field_snapshot(item) for item in value)
    # Includes nested dataclasses, named tuples, container subclasses, enums,
    # SDK objects and custom deepcopy hooks. Preserve native asdict semantics.
    return asdict(_Field(value))["value"]


def dataclass_snapshot(value):
    return {field.name: _field_snapshot(getattr(value, field.name)) for field in fields(value)}


def is_plain_snapshot(value):
    """Whether another deepcopy can add no custom conversion behavior.

    Repeated/cyclic containers and subclasses conservatively use deepcopy.
    This guard matters for SDK/custom objects whose copy hooks transform data.
    """
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        kind = type(item)
        if kind in _ATOMIC_TYPES:
            continue
        if kind not in (dict, list, tuple) or id(item) in seen:
            return False
        seen.add(id(item))
        if kind is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        else:
            pending.extend(item)
    return True
