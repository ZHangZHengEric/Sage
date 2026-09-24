from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

TOKEN_PREFIX = "sage_a2a"

SCOPE_INVOKE = "a2a:invoke"
SCOPE_READ = "a2a:read"
SUPPORTED_SCOPES = (SCOPE_INVOKE, SCOPE_READ)
DEFAULT_SCOPES = (SCOPE_INVOKE, SCOPE_READ)


class ApiKeyRecord(BaseModel):
    """One machine credential, owned by a user and bound to one of their Agents.

    A key is a *service* principal: it never carries the owner's console
    privileges, only the scopes stored here. ``agent_id`` is part of the
    credential rather than the request, so a caller holding one key cannot
    reach another of the tenant's Agents by naming it.
    """

    key_id: str
    owner_user_id: str
    agent_id: str = ""
    name: str = ""
    key_hash: str = ""
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    revoked_at: str = ""

    @property
    def revoked(self) -> bool:
        return bool(self.revoked_at)

    def allows(self, scope: str) -> bool:
        return scope in self.scopes

    def public_dict(self) -> dict[str, object]:
        return {
            "key_id": self.key_id,
            "agent_id": self.agent_id,
            "name": self.name,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "revoked_at": self.revoked_at or None,
        }


def issue_api_key(
    *,
    owner_user_id: str,
    agent_id: str,
    name: str = "",
    scopes: list[str] | None = None,
) -> tuple[ApiKeyRecord, str]:
    """Mint a key, returning the record to persist and the one-time plaintext.

    The plaintext is never stored and never recoverable: a caller who loses it
    issues a new key. The key id travels inside the token so verification is a
    single primary-key lookup — scanning every stored key and hashing against
    each one would turn any bad token into work proportional to the tenant's
    key count.
    """

    key_id = new_id("akey")
    secret = secrets.token_urlsafe(32)
    record = ApiKeyRecord(
        key_id=key_id,
        owner_user_id=owner_user_id,
        agent_id=str(agent_id or "").strip(),
        name=str(name or "").strip()[:191],
        key_hash=hash_secret(secret),
        scopes=normalize_scopes(scopes),
    )
    return record, f"{TOKEN_PREFIX}.{key_id}.{secret}"


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    if scopes is None:
        return list(DEFAULT_SCOPES)
    requested = [str(item or "").strip() for item in scopes]
    unknown = [item for item in requested if item and item not in SUPPORTED_SCOPES]
    if unknown:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.keys.validation",
                category=ErrorCategory.VALIDATION,
                message=f"unsupported scope: {unknown[0]}",
            )
        )
    kept = [item for item in SUPPORTED_SCOPES if item in requested]
    if not kept:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.keys.validation",
                category=ErrorCategory.VALIDATION,
                message="at least one scope is required",
            )
        )
    return kept


def hash_secret(secret: str) -> str:
    """Hash the random half of a token.

    Unlike a password this secret is 256 bits of machine-generated entropy, so
    it is not guessable and key stretching buys nothing — while a stretched
    hash would add its full cost to *every* inbound A2A call, which is
    machine-to-machine traffic rather than an occasional login.
    """

    return "sha256$" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def split_token(token: str) -> tuple[str, str] | None:
    """Return ``(key_id, secret)`` for a well-formed token, else ``None``."""

    parts = str(token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    if not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def verify_secret(secret: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), key_hash)


def require_usable_key(record: ApiKeyRecord | None, secret: str) -> ApiKeyRecord:
    if record is None or record.revoked or not verify_secret(secret, record.key_hash):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.keys.unauthenticated",
                category=ErrorCategory.AUTHENTICATION,
                message="invalid api key",
            )
        )
    return record


def require_scope(record: ApiKeyRecord, scope: str) -> ApiKeyRecord:
    if not record.allows(scope):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.identity.keys.forbidden",
                category=ErrorCategory.AUTHORIZATION,
                message=f"api key is missing scope {scope}",
            )
        )
    return record


def revoke(record: ApiKeyRecord) -> ApiKeyRecord:
    if record.revoked:
        return record
    return record.model_copy(
        update={"revoked_at": datetime.now(timezone.utc).isoformat()}
    )
