"""Host-owned execution grants; model/request data cannot enlarge them."""

from __future__ import annotations

import hashlib
import json
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


def frozen_execution(command) -> tuple[str | None, ExecutionPolicy]:
    raw = command.config.metadata.get(EXECUTION_METADATA_KEY)
    if raw is None:
        return None, ExecutionPolicy()
    policy = ExecutionPolicy.model_validate(raw["policy"])
    if raw["policy_hash"] != policy.fingerprint or raw["agent_id"] != command.agent_id:
        raise ValueError("execution grant does not match the admitted Run")
    return raw["key_id"], policy


def server_ceiling(settings) -> ExecutionPolicy:
    return ExecutionPolicy(shell=settings.execution_shell_mode,
                           approval_timeout_seconds=settings.approval_timeout_seconds)


async def live_execution_policy(command, *, users, keys, catalog, settings, user_id):
    key_id, frozen = frozen_execution(command)
    raw = command.config.metadata.get(EXECUTION_METADATA_KEY)
    if raw is not None and raw.get("user_id") != user_id:
        return None
    user = await users.get_by_id(user_id)
    if user is None:
        return None
    if key_id is not None:
        key = await keys.get(key_id)
        if (key is None or key.revoked or key.owner_user_id != user_id
                or (key.agent_id and key.agent_id != command.agent_id)
                or not key.allows("a2a:invoke")):
            return None
    current = await catalog.get(user_id)
    agent = next((a for a in current.agents if a.id == command.agent_id), None)
    if agent is None:
        return None
    return intersect_policies(frozen, user.execution_policy, agent.execution_policy,
                              server_ceiling(settings))
