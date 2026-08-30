"""Secret-free credential declarations used by manifests."""

from __future__ import annotations

from typing import Literal

from sagents.v2.contracts.common import StrictModel


class CredentialDeclaration(StrictModel):
    source: Literal["env", "host"]
    key: str | None = None
    ref: str | None = None
