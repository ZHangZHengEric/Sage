from __future__ import annotations

import sys

import pytest

from sagents.v2.compat import (
    MIN_PYTHON,
    require_python,
    unsupported_python_message,
)


def test_v2_requires_python_312_or_newer():
    assert MIN_PYTHON == (3, 12)
    assert sys.version_info >= MIN_PYTHON


def test_require_python_rejects_older_interpreters():
    with pytest.raises(RuntimeError, match="Python 3.12") as exc:
        require_python((3, 11, 9))
    assert unsupported_python_message((3, 11, 9)) in str(exc.value)


@pytest.mark.parametrize("version", [(3, 12, 0), (3, 13, 1)])
def test_require_python_accepts_supported_interpreters(version: tuple[int, int, int]):
    require_python(version)
