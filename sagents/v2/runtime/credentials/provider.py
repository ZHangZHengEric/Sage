"""SAgents V2 module for runtime/credentials/provider.py."""

from __future__ import annotations

from typing import Protocol

from sagents.v2.runtime.credentials.contracts import (
    CredentialMaterial,
    CredentialRef,
)
from sagents.v2.contracts.principals import RequestContext


class CredentialProvider(Protocol):
    async def resolve(
        self, ref: CredentialRef, context: RequestContext
    ) -> CredentialMaterial: ...
