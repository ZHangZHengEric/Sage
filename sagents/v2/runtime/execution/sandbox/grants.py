"""Short-lived sandbox grant signing shared by execution providers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.runtime.execution.sandbox.contracts import (
    OperationIntent,
    SandboxGrant,
    SandboxRef,
)


def grant_payload(grant: SandboxGrant) -> bytes:
    data = grant.model_dump(mode="json", exclude={"signature"})
    import json

    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class SandboxGrantIssuer:
    """Runtime-side short-lived grant signer; the key is never serialized."""

    def __init__(
        self,
        key: bytes | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._key = key or secrets.token_bytes(32)
        self._clock = clock

    @property
    def verification_key(self) -> bytes:
        return self._key

    def issue(
        self,
        *,
        ref: SandboxRef,
        intent: OperationIntent,
        allowed_operations: frozenset[str],
        ttl: timedelta = timedelta(minutes=1),
        single_use: bool = True,
    ) -> SandboxGrant:
        now = self._clock()
        unsigned = SandboxGrant(
            grant_id=new_id("grant"),
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            sandbox_id=ref.sandbox_id,
            tenant_id=ref.tenant_id,
            policy_hash=ref.policy_hash,
            spec_hash=ref.spec_hash,
            operation_digest=intent.digest(),
            allowed_operations=allowed_operations,
            issued_at=now,
            expires_at=now + ttl,
            nonce=new_id("nonce"),
            single_use=single_use,
            signature="unsigned",
        )
        signature = hmac.new(
            self._key, grant_payload(unsigned), hashlib.sha256
        ).hexdigest()
        return unsigned.model_copy(update={"signature": signature})
