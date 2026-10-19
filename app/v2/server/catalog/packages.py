"""Canonical standard packages for catalog Agents."""

from __future__ import annotations

import hashlib
import json

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.agent.management.service import owner_key
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.package.manifest import SageManifest


def is_external_tool(name: str) -> bool:
    """MCP/A2A bridges reserve these public tool-name prefixes."""
    return name.startswith(("mcp_", "a2a_"))


def package_owner(user_id: str) -> str:
    return owner_key(
        RequestContext(
            actor=ActorRef(
                tenant_id=user_id,
                principal_id=user_id,
                principal_type=PrincipalType.USER,
            )
        )
    )


def build_package(record, *, sandbox=None, previous=None) -> AgentPackageBundle:
    if previous is None:
        data = {
            "metadata": {"id": record.id, "name": record.name, "version": "initial"},
            "entrypoint": {"agent": record.id},
            "agents": {
                record.id: {
                    "name": record.name,
                    "instructions": {"inline": record.instructions},
                    "models": {"primary": record.model_id or "default"},
                    "memory": {"recall": True, "auto_write": True, "scope": "agent"},
                }
            },
        }
        manifest = SageManifest.model_validate(data)
        bundle = AgentPackageBundle(manifest=manifest)
    else:
        bundle = previous
    data = bundle.model_dump(mode="json")
    manifest = data["manifest"]
    definition = manifest["agents"][record.id]
    definition.update(
        name=record.name,
        description=record.description,
        instructions={"inline": record.instructions},
        tools=list(dict.fromkeys([
            *[name for name in record.tools if not is_external_tool(name)],
            *record.external_tools,
        ])),
        skills=record.skills,
        tool_approval=record.tool_approval.model_dump()
        if record.tool_approval
        else None,
    )
    if sandbox is not None:
        definition["sandbox"] = sandbox
    definition["models"]["primary"] = record.model_id or "default"
    manifest["metadata"].update(name=record.name, version="content")
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]
    manifest["metadata"]["version"] = digest
    return AgentPackageBundle.model_validate(data)


def project_package(record):
    package = record.package
    manifest = package.manifest
    if manifest.entrypoint.agent != record.id or set(manifest.agents) != {record.id}:
        raise ValueError("catalog package must contain exactly its stable Agent ID")
    definition = manifest.agents[record.id]
    model_id = definition.models.get("primary", "default")
    record.name = definition.name
    record.description = definition.description or ""
    record.instructions = (
        package.resolved_manifest().agents[record.id].instructions.inline or ""
    )
    record.model_id = "" if model_id == "default" else model_id
    record.tools = [name for name in definition.tools if not is_external_tool(name)]
    record.external_tools = [name for name in definition.tools if is_external_tool(name)]
    record.skills = list(definition.skills)
    record.tool_approval = definition.tool_approval
    return record


def bind_catalog_members(record, catalog) -> AgentPackageBundle:
    """Pin owned catalog revisions into the standard dependency graph.

    Rebind at admission as well as save: later Runs see member edits, while an
    admitted Run keeps the complete graph across queueing and recovery.
    """
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

    records = {item.id: item for item in catalog.agents}
    records[record.id] = record

    def invalid(message):
        raise SageV2Error(RuntimeErrorInfo(
            code="server.catalog.validation", category=ErrorCategory.VALIDATION,
            message=message,
        ))

    def bind(current, path):
        if current.id in path:
            invalid("团队成员不能包含自身或形成循环依赖")
        members = current.available_sub_agent_ids
        if len(members) != len(set(members)):
            invalid("团队成员不能重复")
        dependencies = {}
        for member_id in members:
            member = records.get(member_id)
            if member is None:
                invalid("团队成员必须是当前用户已有的智能体")
            dependencies[member_id] = bind(member, (*path, current.id))
        package = current.package.model_copy(update={"dependencies": dependencies})
        if path:
            # A member's ordinary model setting is also its delegated setting.
            definition = package.manifest.agents[current.id]
            definition = definition.model_copy(update={
                "delegation_model_bindings": {**definition.models, **definition.delegation_model_bindings},
            })
            package = package.model_copy(update={"manifest": package.manifest.model_copy(update={
                "agents": {current.id: definition},
            })})
        return package

    return AgentPackageBundle.model_validate(bind(record, ()).model_dump(mode="json"))


def catalog_execution_grants(bundle, catalog):
    """Freeze each compiled member's host execution ceiling with the Run."""
    records = {item.id: item for item in catalog.agents}
    grants = {}

    def visit(package, alias):
        agent_id = package.manifest.entrypoint.agent
        grants[alias] = {"agent_id": agent_id, "policy": records[agent_id].execution_policy.model_dump()}
        for name, child in package.dependencies.items():
            visit(child, f"{alias}.{name}" if alias != bundle.manifest.entrypoint.agent else name)

    visit(bundle, bundle.manifest.entrypoint.agent)
    return grants
