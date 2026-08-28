"""SAgents V2 module for runtime/credentials/contracts.py."""

from __future__ import annotations

from datetime import datetime

from pydantic import SecretStr

from sagents.v2.contracts.common import Identifier, StrictModel


class CredentialRef(StrictModel):
    credential_id: Identifier
    purpose: Identifier


class CredentialMaterial(StrictModel):
    credential_id: Identifier
    secret: SecretStr
    source: str
    expires_at: datetime | None = None
