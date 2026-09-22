"""sagents/v2 Skill ports backed by the Server catalog.

Listing never copies. ``load_skill`` prefers an edited tenant Skill and otherwise
materializes one content-addressed bundle inside the sandbox-visible workspace.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AsyncExitStack
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath

from sagents.v2._concurrency import bounded_to_thread
from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.model import RecordingModelProvider
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.skill import (
    SkillBundle,
    SkillDescriptor,
)
from sagents.v2.skill.plugins.session import SessionDerivedSkillActivationRepository
from sagents.v2.tool.composite import CompositeToolCatalog, CompositeToolExecutor
from sagents.v2.tool.plugins.skill import SkillToolPlugin

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import (
    catalog_model,
    enabled_mcp_servers,
    require_agent,
)
from app.server_v2.domain.skills import (
    SkillPackage,
    SkillRecord,
    artifact_relative_path,
    inspect_skill_directory,
    normalize_skill_name,
    package_sha256_of,
    resolve_artifact_path,
    workspace_skill_path,
    write_skill_package,
)
from app.server_v2.services.models import create_catalog_provider, close_model_provider
from app.server_v2.services.mcp import mcp_plugin
from app.server_v2.services.official import attach_official_tools, resolve_agent_tools
from app.server_v2.services.package import server_v2_run_manifest


SKILL_SNAPSHOT_METADATA_KEY = "server_v2.skill_snapshot"


def skill_snapshot_metadata(records: tuple[SkillRecord, ...]) -> dict[str, object]:
    """Serialize the exact immutable Skill versions admitted with a Run."""

    return {SKILL_SNAPSHOT_METADATA_KEY: [asdict(record) for record in records]}


def _skill_snapshot(
    command: StartRun, *, user_id: str
) -> tuple[SkillRecord, ...] | None:
    raw = command.config.metadata.get(SKILL_SNAPSHOT_METADATA_KEY)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise _invalid_skill_snapshot("Skill snapshot must be a list")
    records: list[SkillRecord] = []
    try:
        for value in raw:
            if not isinstance(value, dict):
                raise TypeError("Skill snapshot entries must be objects")
            record = SkillRecord(**value)
            normalize_skill_name(record.name)
            if record.dimension not in {"system", "user"}:
                raise ValueError(f"invalid skill dimension: {record.dimension!r}")
            if record.dimension == "user" and record.owner_user_id != user_id:
                raise ValueError(f"skill {record.name!r} belongs to another user")
            expected_path = artifact_relative_path(
                dimension=record.dimension,
                owner_user_id=record.owner_user_id,
                name=record.name,
                version_id=record.version_id,
            )
            if record.artifact_path != expected_path:
                raise ValueError(f"skill {record.name!r} has an invalid artifact path")
            records.append(record)
    except (ServerV2Error, TypeError, ValueError) as exc:
        raise _invalid_skill_snapshot(str(exc)) from exc
    enabled = command.config.enabled_skills
    if enabled is None or tuple(record.name for record in records) != tuple(enabled):
        raise _invalid_skill_snapshot("Skill snapshot does not match the Run grant")
    return tuple(records)


def _invalid_skill_snapshot(message: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code="skill.snapshot_invalid",
            category=ErrorCategory.VALIDATION,
            message=message,
            safe_to_resume=False,
        )
    )


class CatalogSkillProvider:
    """Level-1 catalog + Level-2 source over immutable catalog artifacts."""

    def __init__(self, records: tuple[SkillRecord, ...], data_root: Path) -> None:
        self._records = {item.name: item for item in records}
        self.data_root = Path(data_root)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        del run_id
        return tuple(
            _descriptor(item)
            for item in sorted(self._records.values(), key=lambda value: value.name)
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
        package = await bounded_to_thread(
            "skill-io",
            lambda: inspect_skill_directory(
                resolve_artifact_path(self.data_root, record.artifact_path)
            ),
        )
        if package.package_sha256 != record.package_sha256:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.artifact_changed",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=f"skill {name!r} artifact no longer matches its version",
                    safe_to_resume=False,
                )
            )
        return SkillBundle(
            descriptor=descriptor,
            files=package.files,
            content_hash=package.package_sha256,
        )


class ReadThroughSkillWorkspace:
    """Expose edited Skills or lazily materialize immutable versions in /workspace."""

    def __init__(
        self, data_root: Path, user_id: str, records: tuple[SkillRecord, ...]
    ) -> None:
        self.data_root = Path(data_root)
        self.user_id = user_id
        self._records = {item.name: item for item in records}

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        del run_id
        name = bundle.descriptor.name
        workspace = workspace_skill_path(self.data_root, self.user_id, name)
        if workspace.is_dir():
            return destination
        record = self._records.get(name)
        if record is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_found",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=f"skill {name!r} was not admitted for this run",
                    safe_to_resume=False,
                )
            )
        cache_key = hashlib.sha256(bundle.content_hash.encode()).hexdigest()
        host_cache = workspace.parent / ".catalog" / name / cache_key
        wire_cache = (
            PurePosixPath(destination).parent / ".catalog" / name / cache_key
        ).as_posix()
        if host_cache.is_dir():
            current_hash = await bounded_to_thread(
                "skill-io", lambda: package_sha256_of(host_cache)
            )
            if current_hash != bundle.content_hash:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="skill.workspace_cache_changed",
                        category=ErrorCategory.CONFLICT,
                        message=f"materialized cache for skill {name!r} was modified",
                        safe_to_resume=True,
                    )
                )
            return wire_cache
        files = dict(bundle.files)
        files[".materialized-skill.json"] = json.dumps(
            {
                "name": name,
                "version": bundle.descriptor.version,
                "content_hash": bundle.content_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        package = SkillPackage(
            name=name,
            description=bundle.descriptor.description,
            files=files,
            skill_md_sha256=(
                f"sha256:{hashlib.sha256(bundle.files['SKILL.md']).hexdigest()}"
            ),
            package_sha256=bundle.content_hash,
            file_count=len(bundle.files),
            total_bytes=sum(len(value) for value in bundle.files.values()),
        )
        try:
            await bounded_to_thread(
                "skill-io", lambda: write_skill_package(host_cache, package)
            )
        except ServerV2Error as exc:
            if exc.reason != "conflict" or not host_cache.is_dir():
                raise
        current_hash = await bounded_to_thread(
            "skill-io", lambda: package_sha256_of(host_cache)
        )
        if current_hash != bundle.content_hash:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.workspace_cache_changed",
                    category=ErrorCategory.CONFLICT,
                    message=f"materialized cache for skill {name!r} is invalid",
                    safe_to_resume=True,
                )
            )
        return wire_cache


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
        async with AsyncExitStack() as stack:
            for handle in ports.scope_handles:
                closer = getattr(handle, "close", None)
                if closer is not None:
                    stack.push_async_callback(closer)


SkillAwareRunDriver = CatalogRunDriver


async def compose_catalog_loop(service, command: StartRun, *, user_id: str):
    catalog = await service.catalog.get(user_id)
    agent = require_agent(catalog, command.agent_id)
    records = _skill_snapshot(command, user_id=user_id)
    if records is None:
        records = tuple(
            await service.skill_catalog.bound_skills(
                owner_user_id=user_id, agent_id=agent.id
            )
        )
    names = tuple(record.name for record in records)
    tools = resolve_agent_tools(agent.tools, has_skills=bool(names))
    manifest = server_v2_run_manifest(
        service.settings,
        agent=agent,
        skills=names,
        tools=tools,
    )
    resolved = CompositionResolver().resolve(manifest)
    raw_model, model_scope = await _run_model(service, catalog, agent, user_id=user_id)
    extra = [model_scope] if model_scope is not None else []
    ports = None
    try:
        model = _recorded_model(service, service.model_budget.wrap(raw_model))
        ports = await service.application.materialize_agent(
            manifest,
            tenant_id=user_id,
            agent_id=agent.id,
            run_id=command.idempotency_key,
            model=model,
        )
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

        async def resolve_session_id(run_id: str) -> str:
            run = await service.application.entrypoint().runtime.session_store.get_run(
                run_id
            )
            return run.session_id

        loader = factory.create_skill_loader(
            resolved,
            agent.id,
            catalog=provider,
            source=provider,
            workspace=workspace,
            activations=SessionDerivedSkillActivationRepository(
                service.application.service("derived-state.store"),
                resolve_session_id,
            ),
            enabled_skills=names,
            workspace_root="/workspace",
            skill_loading=ports.skill_loading,
        )
        catalogs = [official.catalog]
        executors = [official.executor]
        if service.agent_management is not None:
            from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin
            management = AgentManagementToolPlugin(service.agent_management)
            catalogs.append(management.catalog)
            executors.append(management.executor)
        if names:
            skill_tool = SkillToolPlugin(loader, language=service.settings.language)
            catalogs.append(skill_tool.catalog)
            executors.append(skill_tool.executor)
        mcp = mcp_plugin(enabled_mcp_servers(catalog))
        if mcp is not None:
            catalogs.append(mcp)
            executors.append(mcp)
        from app.server_v2.services.tool_policy import server_tool_policy
        loop = factory.create_loop(
            resolved,
            agent.id,
            model=model,
            tool_catalog=CompositeToolCatalog(tuple(catalogs)),
            tool_executor=CompositeToolExecutor(tuple(executors)),
            skill_loader=loader if names else None,
            tool_policy=server_tool_policy(service.agent_management) if service.agent_management is not None else None,
            continuation_policy=ports.continuation_policy,
            tool_selection_policy=ports.tool_selection_policy,
            log_sink=service.application.service("observability.log-sink"),
            trace_sink=_optional_service(service, "observability.trace-sink"),
        )
        loop.expected_resolved_spec_hash = command.resolved_spec_hash
        return loop, replace(ports, scope_handles=(*extra, *ports.scope_handles))
    except BaseException:
        async with AsyncExitStack() as stack:
            for handle in (*extra, *(ports.scope_handles if ports else ())):
                closer = getattr(handle, "close", None)
                if closer is not None:
                    stack.push_async_callback(closer)
        raise


async def compose_skill_loop(
    service, command: StartRun, *, user_id: str, names: tuple[str, ...]
):
    del names
    loop, _ports = await compose_catalog_loop(service, command, user_id=user_id)
    return loop


def install_skill_driver(service) -> None:
    agent = service.application.entrypoint()
    agent.driver_factory = lambda run_id: CatalogRunDriver(service, run_id)


async def _run_model(service, catalog, agent, *, user_id):
    record = catalog_model(catalog, agent.model_id)
    if record is not None:
        if service._host_models is not None:
            lease = await service._host_models.acquire_model(user_id, record)
            return lease.provider, lease
        model = await create_catalog_provider(record)
        return model, _OwnedModelScope(model)
    return service._host_models or service.application.service("model.provider"), None


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


class _OwnedModelScope:
    def __init__(self, model):
        self.model = model

    async def close(self):
        model, self.model = self.model, None
        if model is not None:
            await close_model_provider(model)
