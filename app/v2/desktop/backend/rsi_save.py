"""Save an immutable RSI candidate as an independently owned Desktop Agent."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import TYPE_CHECKING

from pydantic import Field, field_validator

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.common import StrictModel

from .catalog import DesktopAgentRecord

if TYPE_CHECKING:
    from .service import DesktopV2Service


class RsiSaveAs(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("agent name cannot be empty")
        return value


def rebind_package(
    package: AgentPackageBundle, source_id: str, agent_id: str, name: str
):
    data = package.model_dump(mode="json")
    manifest = data["manifest"]
    definition = manifest["agents"].pop(source_id)
    definition["name"] = name
    definition["subagents"] = [
        agent_id if v == source_id else v for v in definition["subagents"]
    ]
    manifest["agents"][agent_id] = definition
    if manifest["entrypoint"].get("agent") == source_id:
        manifest["entrypoint"]["agent"] = agent_id
    for flow in manifest["flows"].values():
        for node in flow["nodes"]:
            if node.get("agent") == source_id:
                node["agent"] = agent_id
    manifest["metadata"].update(id=agent_id, name=name)
    return AgentPackageBundle.model_validate(data)


async def save_rsi_version_as_agent(
    service: DesktopV2Service,
    agent_id: str,
    version_id: str,
    request: RsiSaveAs,
    user_id: str,
):
    async with service._agent_update_lock:
        await service._agent(agent_id, user_id)
        version = service.rsi_store.get(version_id, user_id, agent_id, "version")
        if version["source"] == "rsi" and not version.get("ready"):
            raise ValueError(
                "This iteration is not complete; inspect its retained evidence first"
            )
        if version.get("review") and not version["review"]["approved"]:
            raise ValueError("Semantic review rejected this version")
        origin = {
            "agent_id": agent_id,
            "version_id": version_id,
            "run_id": version.get("run_id"),
            "iteration": version.get("iteration"),
            "package_hash": version["package_hash"],
            "request_id": request.request_id,
            "name": request.name,
        }
        # A lost HTTP response can be retried without creating a second Agent.
        identity = json.dumps([user_id, agent_id, version_id, request.request_id])
        new_agent_id = "agent_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        existing = await service.catalog.get_agent(new_agent_id, user_id)
        if existing is not None:
            if existing.config.get("rsiOrigin") != origin:
                raise ValueError("Save request already used with different parameters")
            return await service.get_agent_settings(new_agent_id, user_id)
        package = rebind_package(
            AgentPackageBundle.model_validate(version["package"]),
            agent_id,
            new_agent_id,
            request.name,
        )
        definition = package.resolved_manifest().agents[new_agent_id]
        config = deepcopy(version["config"])
        if version["source"] == "rsi":
            config.update(
                systemPrefix=definition.instructions.inline,
                availableTools=list(definition.tools),
                availableSkills=list(definition.skills),
                maxLoopCount=definition.budgets.max_steps,
            )
        config.update(
            name=request.name,
            rsiPackage=package.model_dump(mode="json"),
            rsiAssets=deepcopy(version.get("assets", {})),
            rsiOrigin=origin,
        )
        created = DesktopAgentRecord(
            agent_id=new_agent_id, user_id=user_id, name=request.name, config=config
        )
        await service._record_agent_version(
            created, source="activation", package=package
        )
        await service.catalog.save_agent(created)
    return await service.get_agent_settings(new_agent_id, user_id)
