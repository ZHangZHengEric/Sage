"""sagents/v2 Skill ports backed by the Server catalog.

Listing never copies. ``load_skill`` read-throughs the catalog artifact unless
the tenant workspace already has a local copy.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.model import RecordingModelProvider
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.skill import (
    InMemorySkillActivationRepository,
    SkillBundle,
    SkillDescriptor,
)
from sagents.v2.tool.composite import CompositeToolCatalog, CompositeToolExecutor
from sagents.v2.tool.plugins.skill import SkillToolPlugin

from app.server_v2.domain.catalog import catalog_model, enabled_mcp_servers, require_agent
from app.server_v2.domain.skills import (
    SkillRecord,
    inspect_skill_directory,
    package_sha256_of,
    resolve_artifact_path,
    workspace_skill_path,
)
from app.server_v2.services.mcp import mcp_plugin
from app.server_v2.services.official import attach_official_tools, resolve_agent_tools
from app.server_v2.services.package import server_v2_run_manifest


class CatalogSkillProvider:
    """Level-1 catalog + Level-2 source over immutable catalog artifacts."""

    def __init__(self, records: tuple[SkillRecord, ...], data_root: Path) -> None:
        self._records = {item.name: item for item in records}
        self.data_root = Path(data_root)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        del run_id
        return tuple(
            _descriptor(item) for item in sorted(self._records.values(), key=lambda value: value.name)
        )

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        del run_id
        try:
            return _descriptor(self._records[name])
        except KeyError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"skill {name!r} is not registered",
                    safe_to_resume=True,
                )
            ) from exc

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        descriptor = await self.get_skill(name, run_id=run_id)
        record = self._records[name]
        package = inspect_skill_directory(resolve_artifact_path(self.data_root, record.artifact_path))
        return SkillBundle(
            descriptor=descriptor,
            files=package.files,
            content_hash=package.package_sha256,
        )


class ReadThroughSkillWorkspace:
    """Return the catalog artifact path unless a workspace copy already exists."""

    def __init__(self, data_root: Path, user_id: str, records: tuple[SkillRecord, ...]) -> None:
        self.data_root = Path(data_root)
        self.user_id = user_id
        self._records = {item.name: item for item in records}

    async def materialize(self, bundle: SkillBundle, *, run_id: str, destination: str) -> str:
        del run_id, destination
        name = bundle.descriptor.name
        workspace = workspace_skill_path(self.data_root, self.user_id, name)
        if workspace.is_dir():
            return str(workspace)
        record = self._records.get(name)
        if record is None:
            return str(workspace)
        return str(resolve_artifact_path(self.data_root, record.artifact_path))


class CatalogRunDriver:
    """Load the catalog Agent, then materialize a sagents/v2 loop for this run."""

    def __init__(self, service, run_id: str) -> None:
        self.service = service
        self.run_id = run_id
        self._driver = None
        self._ports = None

    async def _resolve(self, context: RequestContext):
        if self._driver is not None:
            return self._driver
        runtime = self.service.application.entrypoint().runtime
        command = await runtime.session_store.get_start_command(self.run_id)
        self._driver, self._ports = await compose_catalog_loop(
            self.service,
            command,
            user_id=context.actor.principal_id,
        )
        return self._driver

    async def execute(self, run_id: str, context: RequestContext):
        try:
            return await (await self._resolve(context)).execute(run_id, context)
        finally:
            await self._close_ports()

    async def resume(self, run_id: str, context: RequestContext):
        try:
            return await (await self._resolve(context)).resume(run_id, context)
        finally:
            await self._close_ports()

    async def _close_ports(self) -> None:
        ports = self._ports
        self._ports = None
        if ports is None:
            return
        for handle in ports.scope_handles:
            closer = getattr(handle, "close", None)
            if closer is not None:
                await closer()


SkillAwareRunDriver = CatalogRunDriver


async def compose_catalog_loop(service, command: StartRun, *, user_id: str):
    catalog = await service.catalog.get(user_id)
    agent = require_agent(catalog, command.agent_id)
    names = await service.skill_catalog.bound_names(user_id, agent.id)
    records = tuple(
        await service.skill_catalog.bound_skills(
            owner_user_id=user_id, agent_id=agent.id
        )
    )
    tools = resolve_agent_tools(agent.tools, has_skills=bool(names))
    manifest = server_v2_run_manifest(
        service.settings,
        agent=agent,
        skills=names,
        tools=tools,
    )
    resolved = CompositionResolver().resolve(manifest)
    model = _recorded_model(service, _run_model(service, catalog, agent))
    ports = await service.application.materialize_agent(
        manifest,
        tenant_id=user_id,
        agent_id=agent.id,
        run_id=command.idempotency_key,
        model=model,
    )
    extra = []
    try:
        official, official_runtime, sandbox_handle = await attach_official_tools(
            service, command, user_id=user_id
        )
        extra.extend([official_runtime, sandbox_handle])
        factory = AgentCompositionFactory(
            service.application.entrypoint().runtime,
            context_components=ContextComponentBundle(
                token_estimator=ports.token_estimator,
                summary_store=_optional_service(service, "context.summary-store"),
                summarizer=ports.summarizer,
                reducer=ports.context_reducer,
            ),
        )
        provider = CatalogSkillProvider(records, service.paths.data_root)
        workspace = ReadThroughSkillWorkspace(service.paths.data_root, user_id, records)
        loader = factory.create_skill_loader(
            resolved,
            agent.id,
            catalog=provider,
            source=provider,
            workspace=workspace,
            activations=InMemorySkillActivationRepository(),
            enabled_skills=names,
            workspace_root="/workspace",
        )
        catalogs = [official.catalog]
        executors = [official.executor]
        if names:
            skill_tool = SkillToolPlugin(loader, language=service.settings.language)
            catalogs.append(skill_tool.catalog)
            executors.append(skill_tool.executor)
        mcp = mcp_plugin(enabled_mcp_servers(catalog))
        if mcp is not None:
            catalogs.append(mcp)
            executors.append(mcp)
        loop = factory.create_loop(
            resolved,
            agent.id,
            model=model,
            tool_catalog=CompositeToolCatalog(tuple(catalogs)),
            tool_executor=CompositeToolExecutor(tuple(executors)),
            skill_loader=loader if names else None,
            continuation_policy=ports.continuation_policy,
            tool_selection_policy=ports.tool_selection_policy,
            log_sink=service.application.service("observability.log-sink"),
            trace_sink=_optional_service(service, "observability.trace-sink"),
        )
        loop.expected_resolved_spec_hash = command.resolved_spec_hash
        return loop, replace(
            ports, scope_handles=(*ports.scope_handles, *extra)
        )
    except BaseException:
        for handle in extra:
            closer = getattr(handle, "close", None)
            if closer is not None:
                await closer()
        raise


async def compose_skill_loop(service, command: StartRun, *, user_id: str, names: tuple[str, ...]):
    del names
    loop, _ports = await compose_catalog_loop(service, command, user_id=user_id)
    return loop


def install_skill_driver(service) -> None:
    agent = service.application.entrypoint()
    agent.driver_factory = lambda run_id: CatalogRunDriver(service, run_id)


def _run_model(service, catalog, agent):
    record = catalog_model(catalog, agent.model_id)
    if record is not None:
        return record.to_provider()
    return service._host_models or service.application.service("model.provider")


def _recorded_model(service, model):
    if isinstance(model, RecordingModelProvider):
        return model
    runtime = service.application.entrypoint().runtime

    async def resolve_session_id(run_id: str) -> str:
        return (await runtime.session_store.get_run(run_id)).session_id

    return RecordingModelProvider(
        model,
        sink=service.application.service("observability.diagnostic-sink"),
        log_sink=service.application.service("observability.log-sink"),
        trace_sink=_optional_service(service, "observability.trace-sink"),
        session_id_resolver=resolve_session_id,
    )


def workspace_content_hash(path: Path) -> str:
    if not path.is_dir():
        return ""
    return package_sha256_of(path)


def _descriptor(record: SkillRecord) -> SkillDescriptor:
    return SkillDescriptor(
        name=record.name,
        description=record.description,
        source_id="catalog",
        version=record.version_id,
        metadata={
            "skill_id": record.skill_id,
            "dimension": record.dimension,
            "artifact_path": record.artifact_path,
        },
    )


def _context_components(service) -> ContextComponentBundle:
    try:
        return ContextComponentBundle(
            token_estimator=service.application.service("context.token-estimator"),
            summary_store=service.application.service("context.summary-store"),
            summarizer=service.application.service("context.summarizer"),
            reducer=service.application.service("context.reducer"),
        )
    except KeyError:
        return ContextComponentBundle()


def _optional_service(service, name: str):
    try:
        return service.application.service(name)
    except KeyError:
        return None


def bundle_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"
