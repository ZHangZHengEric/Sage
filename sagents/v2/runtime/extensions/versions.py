"""Numeric protocol version constraints shared by registration and resolution."""

import re

_VERSION = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _VERSION.match(version.strip())
    if match is None:
        raise ValueError(f"invalid version {version!r}")
    return tuple(int(value or 0) for value in match.groups())  # type: ignore[return-value]


def version_satisfies(version: str, requirement: str) -> bool:
    """Return whether a numeric semantic version satisfies simple constraints."""

    current = _version_tuple(version)
    clauses = [value.strip() for value in requirement.split(",") if value.strip()]
    if not clauses:
        raise ValueError("version requirement must contain at least one clause")
    for clause in clauses:
        operator = next(
            (
                value
                for value in (">=", "<=", "==", ">", "<")
                if clause.startswith(value)
            ),
            None,
        )
        if operator is None:
            if current[0] != _version_tuple(clause)[0]:
                return False
            continue
        target = _version_tuple(clause[len(operator) :])
        if operator == ">=" and current < target:
            return False
        if operator == "<=" and current > target:
            return False
        if operator == ">" and current <= target:
            return False
        if operator == "<" and current >= target:
            return False
        if operator == "==" and current != target:
            return False
    return True
