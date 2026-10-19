from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pydantic import BaseModel, ConfigDict
from sagents.v2.package.manifest.runtime import CapabilitySelection

from app.v2.server.routers.deps import ReadUser, CatalogDep, CurrentUser, AdminUser, HostDep, PackageDep, SkillDep
from app.v2.server.runtime.official import official_tool_catalog, tool_catalog_item
from app.v2.server.routers.render import success
from app.v2.server.routers.schemas.common import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.v2.server.routers.schemas.catalog import (
    AgentBody, AgentPublic, AgentSummary, ToolPublic, AgentToolOption, AgentEditorResources,
)
from app.v2.server.routers.schemas.skills import SkillBindBody, SkillPublic
from app.v2.server.skills.agent_guidance import sync_agent_guidance
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

agent_router = APIRouter(tags=["agents"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})
guidance_router = APIRouter(tags=["agents"], responses=VALIDATION_ERRORS)
skill_binding_router = APIRouter(tags=["skills"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@agent_router.get("/api/plugins")
async def list_plugins(user: CurrentUser, host: HostDep):
    return success(host.agent_plugin_catalog)


@agent_router.get("/api/plugins/server")
async def server_plugins(user: AdminUser, host: HostDep):
    from dataclasses import asdict, replace
    from app.v2.server.config.manifest import server_v2_manifest
    from app.v2.server.observability.diagnostics import redact

    manifest = server_v2_manifest(host.settings)
    providers = []
    selections = {
        key: value.model_dump(mode="json")
        for key, value in manifest.runtime.capabilities.items()
    }
    for provider in host.application.resolved_plan.providers:
        row = asdict(provider)
        try:
            implementation = host.application.service(provider.capability)
        except KeyError:
            implementation = None
        if implementation is not None:
            row["implementation"] = type(implementation).__name__
            if provider.source == "host":
                row["plugin_id"] = getattr(implementation, "plugin_id", None)
            elif row["plugin_id"] is None:
                row["plugin_id"] = getattr(implementation, "plugin_id", None)
        providers.append(row)
    sandbox = host.execution.sandbox_provider
    if sandbox is not None:
        providers.append({"capability": "execution.sandbox", "name": "default",
            "api_version": "3", "plugin_id": sandbox.plugin_id,
            "scope": "process", "source": "host", "implementation": type(sandbox).__name__})
    from app.v2.server.config.plugins import ServerPluginConfig, SERVER_CONFIGURABLE, SERVER_DEFAULTS, revision
    saved = ServerPluginConfig(host.paths.data_root, registry=host.extensions).read()
    active = host.settings.plugin_overrides
    pending = sorted(key for key in set(saved) | set(active) if saved.get(key) != active.get(key))
    deployment_defaults = {key: {"plugin": plugin, "config": {}} for key, plugin in SERVER_DEFAULTS.items()}
    deployment_defaults.update({
        key: value.model_dump(mode="json", exclude_none=True)
        for key, value in server_v2_manifest(replace(host.settings, plugin_overrides={})).runtime.capabilities.items()
        if key in SERVER_CONFIGURABLE
    })
    result = redact({
                "providers": providers,
                "selections": selections,
                "interfaces": {
                    key: value.model_dump(mode="json")
                    for key, value in manifest.interfaces.items()
                },
            })
    # Editable selections contain only schema-approved configuration, not
    # host-injected credentials/DSNs. Environment variable names must roundtrip.
    result.update(
        configurable=sorted(SERVER_CONFIGURABLE),
        saved=saved, revision=revision(saved), pending=pending,
        defaults=deployment_defaults,
        storage_root=str(host.paths.data_root / "runtime" / "plugins"),
    )
    return success(result)


class ServerPluginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    changes: dict[str, CapabilitySelection | None]


@agent_router.put("/api/plugins/server")
async def save_server_plugins(body: ServerPluginBody, user: AdminUser, host: HostDep):
    import asyncio
    from app.v2.server.config.plugins import ServerPluginConfig

    try:
        await asyncio.to_thread(
            ServerPluginConfig(host.paths.data_root, registry=host.extensions).save,
            {key: value.model_dump(mode="json", exclude_none=True) if value else None
             for key, value in body.changes.items()},
            body.revision,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await server_plugins(user, host)


@agent_router.get("/api/tools", response_model=ApiResponse[list[ToolPublic]])
async def list_tools(user: ReadUser, packages: PackageDep, service: CatalogDep):
    from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin

    definitions = AgentManagementToolPlugin(packages).definitions
    servers = [item for _, item in await service.list_resources([user.user_id], "mcp_servers")]
    plugin = service.mcp_plugins.get(user.user_id, servers)
    external = await plugin.list_tools(run_id="catalog") if plugin is not None else ()
    return success(
        [
            *official_tool_catalog(),
            *[
                tool_catalog_item(item, category="MCP", source="mcp")
                for item in external
            ],
            *[
                tool_catalog_item(item, category="agent-management", source="host")
                for item in definitions
            ],
        ]
    )


@agent_router.get("/api/agents", response_model=ApiResponse[list[AgentPublic]])
async def list_agents(user: ReadUser, service: CatalogDep):
    agents = (await service.get(user.user_id)).agents
    return success([item.public_dict() for item in agents])


@agent_router.get("/api/agents/editor-resources", response_model=ApiResponse[AgentEditorResources])
async def agent_editor_resources(
    user: ReadUser, service: CatalogDep, packages: PackageDep, host: HostDep,
    include_plugins: bool = True,
):
    from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin

    resources = await service.editor_resources(user.user_id)
    resources["tools"] = [
        *official_tool_catalog(),
        *[tool_catalog_item(item, category="agent-management", source="host")
          for item in AgentManagementToolPlugin(packages).definitions],
    ]
    resources["plugins"] = host.agent_plugin_catalog if include_plugins else None
    return success(resources)


@agent_router.get("/api/tools/options", response_model=ApiResponse[list[AgentToolOption]])
async def agent_tool_options(user: ReadUser, packages: PackageDep, service: CatalogDep):
    # Remote discovery is only needed when opening per-tool approval choices.
    return await list_tools(user, packages, service)


@agent_router.post("/api/agents", response_model=ApiResponse[AgentPublic])
async def create_agent(body: AgentBody, user: CurrentUser, service: CatalogDep):
    record = await service.create_agent(user.user_id, body.model_dump(exclude={key for key in ("tool_approval", "fast_model_id", "tools", "external_tools") if key not in body.model_fields_set}))
    return success(record.public_dict())


@agent_router.get("/api/agents/summary", response_model=ApiResponse[list[AgentSummary]])
async def agent_summaries(user: ReadUser, service: CatalogDep):
    return success(await service.list_agent_summaries([user.user_id]))


@agent_router.get("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def get_agent(agent_id: str, user: ReadUser, service: CatalogDep):
    return success(await service.get_agent(user.user_id, agent_id))


@agent_router.put("/api/agents/{agent_id}", response_model=ApiResponse[AgentPublic])
async def update_agent(
    agent_id: str, body: AgentBody, user: CurrentUser, service: CatalogDep
):
    record = await service.update_agent(
        user.user_id, agent_id, body.model_dump(exclude={key for key in ("tool_approval", "fast_model_id", "tools", "external_tools") if key not in body.model_fields_set})
    )
    return success(record.public_dict())


@agent_router.delete("/api/agents/{agent_id}", response_model=ApiResponse[None])
async def remove_agent(agent_id: str, user: CurrentUser, service: CatalogDep):
    await service.delete_agent(user.user_id, agent_id)
    return success()


@guidance_router.put("/api/agents/{agent_id}/guidance", response_model=ApiResponse[dict])
async def put_agent_guidance(
    agent_id: str,
    host: HostDep,
    prompt: Annotated[str, Form(min_length=1)],
    files: Annotated[list[UploadFile], File()],
):
    owner_id = await host.catalog.agent_owner(agent_id)
    if owner_id is None:
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.agent_not_found",
            category=ErrorCategory.VALIDATION, message="Agent not found"))
    if len(files) > 32:
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.validation",
            category=ErrorCategory.VALIDATION, message="too many Skill ZIP files"))
    uploads = [(item.filename or "unknown.zip", await item.read((32 << 20) + 1)) for item in files]
    try:
        result = await sync_agent_guidance(host, owner_id=owner_id,
                                          agent_id=agent_id, prompt=prompt, files=uploads)
    except ValueError as exc:
        raise SageV2Error(RuntimeErrorInfo(code="server.agent_guidance.validation",
            category=ErrorCategory.VALIDATION, message=str(exc))) from exc
    return success(result)


@skill_binding_router.get(
    "/api/agents/{agent_id}/skills", response_model=ApiResponse[list[SkillPublic]]
)
async def list_agent_skills(agent_id: str, user: ReadUser, service: SkillDep):
    bound = await service.bound_skills(
        owner_user_id=user.user_id, agent_id=agent_id
    )
    return success(
        [
            {
                **item.public_dict(),
                "workspace_status": await service.workspace_status(
                    user_id=user.user_id, agent_id=agent_id, name=item.name
                ),
            }
            for item in bound
        ]
    )


@skill_binding_router.put(
    "/api/agents/{agent_id}/skills", response_model=ApiResponse[list[SkillPublic]]
)
async def bind_agent_skills(
    agent_id: str, body: SkillBindBody, user: CurrentUser, service: CatalogDep
):
    skills = await service.bind_agent_skills(user.user_id, agent_id, body.names)
    return success([item.public_dict() for item in skills])


router = APIRouter()
router.include_router(agent_router)
router.include_router(guidance_router)
router.include_router(skill_binding_router)
