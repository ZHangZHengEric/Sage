"""Credential plugins exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.credentials.plugins.environment import EnvironmentCredentialProvider as EnvironmentCredentialProvider
    from sagents.v2.runtime.credentials.plugins.mapping import MappingCredentialProvider as MappingCredentialProvider


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "EnvironmentCredentialProvider": (
        "sagents.v2.runtime.credentials.plugins.environment",
        "EnvironmentCredentialProvider",
    ),
    "MappingCredentialProvider": (
        "sagents.v2.runtime.credentials.plugins.mapping",
        "MappingCredentialProvider",
    ),
}

__all__ = [
    "EnvironmentCredentialProvider",
    "MappingCredentialProvider",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
