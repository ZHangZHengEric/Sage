"""SAgents V2 module for runtime/credentials/providers.py."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import SecretStr

from sagents.v2.runtime.credentials.contracts import (
    CredentialMaterial,
    CredentialRef,
)
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.package.manifest.credentials import CredentialDeclaration


class EnvironmentCredentialProvider:
    """Composition-root provider; env access never leaks into Kernel/AgentLoop."""

    def __init__(
        self,
        declarations: Mapping[str, CredentialDeclaration],
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._declarations = dict(declarations)
        self._environment = environment if environment is not None else os.environ

    async def resolve(
        self, ref: CredentialRef, context: RequestContext
    ) -> CredentialMaterial:
        declaration = self._declarations.get(ref.credential_id)
        if (
            declaration is None
            or declaration.source != "env"
            or declaration.key is None
        ):
            raise _error(
                "credential.not_found",
                ErrorCategory.AUTHENTICATION,
                "credential reference is not available from environment provider",
            )
        value = self._environment.get(declaration.key)
        if value is None or value == "":
            raise _error(
                "credential.unavailable",
                ErrorCategory.AUTHENTICATION,
                f"credential environment key {declaration.key!r} is unavailable",
            )
        return CredentialMaterial(
            credential_id=ref.credential_id,
            secret=SecretStr(value),
            source="env",
        )


class MappingCredentialProvider:
    """Host/test secret store adapter; values are injected, never declared in YAML."""

    def __init__(self, values: Mapping[str, str], *, source: str = "host") -> None:
        self._values = dict(values)
        self._source = source

    async def resolve(self, ref: CredentialRef, context: RequestContext):
        value = self._values.get(ref.credential_id)
        if value is None:
            raise _error(
                "credential.not_found",
                ErrorCategory.AUTHENTICATION,
                "credential reference is unavailable",
            )
        return CredentialMaterial(
            credential_id=ref.credential_id,
            secret=SecretStr(value),
            source=self._source,
        )


def _error(code, category, message):
    return SageV2Error(RuntimeErrorInfo(code=code, category=category, message=message))
