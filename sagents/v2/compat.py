"""Python version floor for sagents.v2 and hosts that embed it."""

from __future__ import annotations

import sys

MIN_PYTHON = (3, 12)


def python_version_label(version: tuple[int, ...] | None = None) -> str:
    current = version or sys.version_info
    patch = current[2] if len(current) > 2 else 0
    return f"{current[0]}.{current[1]}.{patch}"


def unsupported_python_message(version: tuple[int, ...] | None = None) -> str:
    return (
        "sagents.v2 requires Python 3.12 or newer; "
        f"current version is {python_version_label(version)}"
    )


def require_python(version: tuple[int, ...] | None = None) -> None:
    current = version or sys.version_info
    if current < MIN_PYTHON:
        raise RuntimeError(unsupported_python_message(current))
