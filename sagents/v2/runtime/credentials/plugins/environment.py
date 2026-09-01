"""Composition-root environment credential provider."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import SecretStr

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.runtime.credentials.contracts import (
    CredentialMaterial,
    CredentialRef,
)


class EnvironmentCredentialProvider:
    """Env access never leaks into Kernel/AgentLoop."""

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


def _error(code, category, message):
    return SageV2Error(RuntimeErrorInfo(code=code, category=category, message=message))
