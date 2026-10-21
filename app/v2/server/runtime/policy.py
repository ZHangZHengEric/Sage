"""Host-owned execution grants; model/request data cannot enlarge them."""

from __future__ import annotations

import hashlib
import json
import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EXECUTION_METADATA_KEY = "server_v2.execution"
SHELL_ORDER = {"deny": 0, "ask": 1, "sandboxed": 2}


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shell: Literal["ask", "sandboxed", "deny"] = "ask"
    on_approval_required: Literal["suspend", "deny"] = "suspend"
    approval_timeout_seconds: int = Field(default=86400, ge=60, le=604800, strict=True)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def intersect_policies(*policies: ExecutionPolicy) -> ExecutionPolicy:
    return ExecutionPolicy(
        shell=min((p.shell for p in policies), key=SHELL_ORDER.__getitem__),
        on_approval_required="deny" if any(p.on_approval_required == "deny" for p in policies) else "suspend",
        approval_timeout_seconds=min(p.approval_timeout_seconds for p in policies),
    )


def execution_metadata(policy: ExecutionPolicy, *, user_id: str, agent_id: str,
                       key_id: str | None = None) -> dict:
    return {EXECUTION_METADATA_KEY: {
        "user_id": user_id, "key_id": key_id, "agent_id": agent_id,
        "policy": policy.model_dump(), "policy_hash": policy.fingerprint,
    }}


def frozen_execution(command, *, catalog_agent_id: str | None = None) -> tuple[str | None, ExecutionPolicy]:
    raw = command.config.metadata.get(EXECUTION_METADATA_KEY)
    if raw is None:
        return None, ExecutionPolicy()
    policy = ExecutionPolicy.model_validate(raw["policy"])
    expected = catalog_agent_id or command.agent_id
    if raw["agent_id"] != expected and catalog_agent_id is None:
        from app.v2.server.conversations.composition import load_composition
        composition = load_composition(command, user_id=raw["user_id"])
        if composition is not None:
            expected = composition.agent.id
    if raw["policy_hash"] != policy.fingerprint or raw["agent_id"] != expected:
        raise ValueError("execution grant does not match the admitted Run")
    return raw["key_id"], policy


def server_ceiling(settings) -> ExecutionPolicy:
    return ExecutionPolicy(shell=settings.execution_shell_mode,
                           approval_timeout_seconds=settings.approval_timeout_seconds)


async def live_execution_policy(command, *, users, keys, catalog, settings, user_id, catalog_agent_id=None,
                                package_authorizer=None, context=None):
    key_id, frozen = frozen_execution(command, catalog_agent_id=catalog_agent_id)
    raw = command.config.metadata.get(EXECUTION_METADATA_KEY)
    source_agent_id = catalog_agent_id or (raw["agent_id"] if raw is not None else command.agent_id)
    if raw is not None and raw.get("user_id") != user_id:
        return None
    from app.v2.server.conversations.composition import load_composition
    composition = load_composition(command, user_id=user_id)
    package = composition.package if composition is not None else None
    if package is not None:
        assert composition is not None
        # Direct Packages carry an authorized immutable bundle, not a Catalog
        # Agent row. Recheck the same host Package policy used at HTTP admission
        # on every capability decision; a missing/revoked grant fails closed.
        if package_authorizer is None or context is None or key_id is not None:
            return None
        if (context.actor.principal_id != user_id or context.actor.tenant_id != user_id
                or composition.agent.id != source_agent_id):
            return None
        try:
            await package_authorizer("run", package, context)
        except PermissionError:
            return None
        user = await users.get_by_id(user_id)
        return intersect_policies(frozen, user.execution_policy, server_ceiling(settings)) if user is not None else None
    reads = [users.get_by_id(user_id), catalog.get_execution_policy(user_id, source_agent_id)]
    if key_id is not None:
        reads.append(keys.get(key_id))
    user, agent_policy, *key_records = await asyncio.gather(*reads)
    if user is None:
        return None
    if key_id is not None:
        key = key_records[0]
        if (key is None or key.revoked or key.owner_user_id != user_id
                or (key.agent_id and key.agent_id != source_agent_id)
                or not key.allows("a2a:invoke")):
            return None
    if agent_policy is None:
        return None
    return intersect_policies(frozen, user.execution_policy, agent_policy,
                              server_ceiling(settings))
