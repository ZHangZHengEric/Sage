"""Host/test secret store adapter; values are injected, never declared in YAML."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import SecretStr

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.credentials.contracts import (
    CredentialMaterial,
    CredentialRef,
)


class MappingCredentialProvider:
    plugin_id = "sage.credentials.mapping"

    def __init__(self, values: Mapping[str, str], *, source: str = "host") -> None:
        self._values = dict(values)
        self._source = source

    async def resolve(self, ref: CredentialRef, context):
        value = self._values.get(ref.credential_id)
        if value is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="credential.not_found",
                    category=ErrorCategory.AUTHENTICATION,
                    message="credential reference is unavailable",
                )
            )
        return CredentialMaterial(
            credential_id=ref.credential_id,
            secret=SecretStr(value),
            source=self._source,
        )
