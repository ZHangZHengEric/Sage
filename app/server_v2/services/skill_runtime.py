"""sagents/v2 Skill ports backed by the Server catalog.

Listing never copies. ``load_skill`` read-throughs the catalog artifact unless
the tenant workspace already has a local copy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.skill import (
    InMemorySkillActivationRepository,
    SkillBundle,
    SkillDescriptor,
)
from sagents.v2.tool.composite import CompositeToolCatalog, CompositeToolExecutor
from sagents.v2.tool.plugins.skill import SkillToolPlugin

from app.server_v2.domain.skills import (
    SkillRecord,
    inspect_skill_directory,
    package_sha256_of,
    resolve_artifact_path,
    workspace_skill_path,
)
from app.server_v2.services.package import server_v2_run_manifest
from app.server_v2.services.skills import SkillCatalogService


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


class SkillAwareRunDriver:
    """Use the process loop when no Skills are bound; otherwise compose a v2 loader."""

    def __init__(self, service, inner_factory, run_id: str) -> None:
        self.service = service
        self.inner_factory = inner_factory
        self.run_id = run_id
        self._driver = None

    async def _resolve(self, context: RequestContext):
        if self._driver is not None:
            return self._driver
        runtime = self.service.application.entrypoint().runtime
        command = await runtime.session_store.get_start_command(self.run_id)
        names = await self.service.skill_catalog.bound_names(
            context.actor.principal_id, command.agent_id
        )
        if not names:
            self._driver = self.inner_factory(self.run_id)
            return self._driver
        self._driver = await compose_skill_loop(
            self.service,
            command,
            user_id=context.actor.principal_id,
            names=names,
        )
        return self._driver

    async def execute(self, run_id: str, context: RequestContext):
        return await (await self._resolve(context)).execute(run_id, context)

    async def resume(self, run_id: str, context: RequestContext):
        return await (await self._resolve(context)).resume(run_id, context)


async def compose_skill_loop(service, command: StartRun, *, user_id: str, names: tuple[str, ...]):
    records = tuple(
        await service.skill_catalog.bound_skills(
            owner_user_id=user_id, agent_id=command.agent_id
        )
    )
    provider = CatalogSkillProvider(records, service.paths.data_root)
    workspace = ReadThroughSkillWorkspace(service.paths.data_root, user_id, records)
    runtime = service.application.entrypoint().runtime
    factory = AgentCompositionFactory(
        runtime,
        context_components=_context_components(service),
    )
    manifest = server_v2_run_manifest(
        service.settings,
        agent_id=command.agent_id,
        skills=names,
    )
    resolved = CompositionResolver().resolve(manifest)
    activations = InMemorySkillActivationRepository()
    loader = factory.create_skill_loader(
        resolved,
        command.agent_id,
        catalog=provider,
        source=provider,
        workspace=workspace,
        activations=activations,
        enabled_skills=names,
        workspace_root="/workspace",
    )
    skill_tool = SkillToolPlugin(loader, language=service.settings.language)
    catalogs = [skill_tool.catalog]
    executors = [skill_tool.executor]
    try:
        catalogs.insert(0, service.application.service("tool.catalog"))
        executors.insert(0, service.application.service("tool.executor"))
    except KeyError:
        pass
    loop = factory.create_loop(
        resolved,
        command.agent_id,
        model=service._host_models or service.application.service("model.provider"),
        tool_catalog=CompositeToolCatalog(tuple(catalogs)),
        tool_executor=CompositeToolExecutor(tuple(executors)),
        skill_loader=loader,
        log_sink=service.application.service("observability.log-sink"),
        trace_sink=_optional_service(service, "observability.trace-sink"),
    )
    # StartRun 带着进程 Application 的 composition_hash；per-run 带 skills 的
    # manifest 会算出另一个 hash。对齐方式与 loop_factory 相同：创建后再改。
    loop.expected_resolved_spec_hash = command.resolved_spec_hash
    return loop


def install_skill_driver(service) -> None:
    agent = service.application.entrypoint()
    inner = agent.driver_factory
    agent.driver_factory = lambda run_id: SkillAwareRunDriver(service, inner, run_id)


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
