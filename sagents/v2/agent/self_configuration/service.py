"""One model tool for adding local Skills and MCP servers to the current Agent.

Writes stage an immutable Run revision. Only the AgentLoop's safe boundary
activates it; sibling calls in the proposing response retain their old grants.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field

from sagents.v2._concurrency import bounded_to_thread
from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import JsonBlock
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.skill.contracts import SkillBundle
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.tool.composite import CompositeToolCatalog, CompositeToolExecutor
from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
    ResumeStrategy,
    SideEffectLevel,
    ToolExecutionResult,
)
from sagents.v2.tool.decorated import DecoratedToolProvider, ToolInvocation
from sagents.v2.tool.decorators import tool
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin


class SelfMcpServer(StrictModel):
    """Credentials stay host owned; this tool never accepts or stores secrets."""

    name: str = Field(min_length=1, max_length=255)
    protocol: Literal["stdio", "sse", "streamable_http"]
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()

    def config(self):
        if self.url and (urlsplit(self.url).username or urlsplit(self.url).password):
            raise ValueError("MCP URL credentials must be provided by the host")
        return McpServerConfig(**self.model_dump())


class SelfConfigurationRequest(StrictModel):
    # None preserves the current value; an empty string clears the overlay.
    system_prompt: str | None = Field(default=None, max_length=32768)
    add_skill_paths: tuple[str, ...] = Field(default=(), max_length=16)
    add_mcp_servers: tuple[SelfMcpServer, ...] = Field(default=(), max_length=16)


class _Tools:
    def __init__(self, service):
        self.service = service

    @tool(
        description=(
            "Configure your own Agent. Add already downloaded or authored local Skill directories "
            "containing SKILL.md, connect MCP servers, or set your own system_prompt. "
            "system_prompt replaces only your own instructions, never host rules; an empty string clears it. "
            "Omit it to preserve existing instructions. No Skill installer is needed. "
            "Changes persist and become usable in this same Run after this tool batch, "
            "before the next model step. An empty request inspects your current configuration. "
            "Host permissions apply; never include credentials in URLs or arguments."
        ),
        input_schema=SelfConfigurationRequest.model_json_schema(),
        side_effect_level=SideEffectLevel.WRITE,
        resume_strategy=ResumeStrategy.RECONCILE,
        supports_reconciliation=True,
    )
    async def agent_self_configure(
        self,
        add_skill_paths: list[str] | None = None,
        add_mcp_servers: list[dict] | None = None,
        system_prompt: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> dict:
        if invocation is None:
            raise RuntimeError("ToolInvocation is required")
        request = SelfConfigurationRequest.model_validate(
            {
                "add_skill_paths": add_skill_paths or [],
                "add_mcp_servers": add_mcp_servers or [],
                "system_prompt": system_prompt,
            }
        )
        return await self.service.configure(request, invocation)


class _Skills:
    def __init__(self, service, catalog, source):
        self.service, self.catalog, self.source = service, catalog, source

    async def list_skills(self, *, run_id):
        values = {
            value.name: value for value in await self.catalog.list_skills(run_id=run_id)
        }
        values.update(
            {name: bundle.descriptor for name, bundle in self.service.bundles.items()}
        )
        return tuple(values[name] for name in sorted(values))

    async def get_skill(self, name, *, run_id):
        bundle = self.service.bundles.get(name)
        return (
            bundle.descriptor
            if bundle
            else await self.catalog.get_skill(name, run_id=run_id)
        )

    async def fetch(self, name, *, run_id):
        bundle = self.service.bundles.get(name)
        return bundle if bundle else await self.source.fetch(name, run_id=run_id)


class _Workspace:
    """Materialize registered snapshots without trusting mutable download paths."""

    def __init__(self, service, original):
        self.service, self.original = service, original

    async def materialize(self, bundle, *, run_id, destination):
        if bundle.descriptor.name not in self.service.bundles:
            return await self.original.materialize(
                bundle, run_id=run_id, destination=destination
            )
        digest = hashlib.sha256(bundle.content_hash.encode()).hexdigest()
        relative = Path(".sage-capabilities") / digest / bundle.descriptor.name
        target = self.service.workspace_root / relative

        def materialize():
            # Never overwrite downloaded/edited files, or follow a symlink in
            # the private materialization path inside the writable workspace.
            for parent in reversed((target, *target.parents)):
                if (
                    parent == self.service.workspace_root
                    or self.service.workspace_root in parent.parents
                ):
                    if parent.is_symlink():
                        raise ValueError(
                            "Skill materialization path contains a symlink"
                        )
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                for path, content in bundle.files.items():
                    candidate = target / path
                    for parent in (candidate, *candidate.parents):
                        if parent == target:
                            break
                        if parent.is_symlink():
                            raise ValueError("Skill materialization contains a symlink")
                    if not candidate.is_file() or candidate.read_bytes() != content:
                        raise ValueError(
                            "Skill snapshot was modified; it was not overwritten"
                        )
                return
            temporary = Path(tempfile.mkdtemp(prefix=".skill-", dir=target.parent))
            try:
                for path, content in bundle.files.items():
                    file = temporary / path
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(content)
                os.rename(temporary, target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

        await bounded_to_thread("skill-io", materialize)
        alias = self.service.workspace_alias or str(self.service.workspace_root)
        return (Path(alias) / relative).as_posix()


class SelfConfigurationService:
    """One service per Agent loop; hosts explicitly supply the authorization policy.

    ``authorize(request, context)`` must enforce ownership, execution mode,
    transport/network policy and any live revocation. workspace_root is a host
    path; workspace_alias is its sandbox-visible path. Store is private host
    state, outside the Agent's writable workspace. This built-in is single-host.
    """

    def __init__(
        self,
        *,
        store,
        owner: str,
        workspace_root: str | Path,
        authorize,
        workspace_alias: str | None = None,
        mcp_session_factory=None,
    ):
        self.store, self.owner, self.authorize = store, owner, authorize
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_alias = workspace_alias
        self.mcp_session_factory = mcp_session_factory
        self.bundles = {}
        self.system_prompt = ""
        self.revision = None
        self.run_id = None
        self._lock = asyncio.Lock()
        self._provider = DecoratedToolProvider(_Tools(self))
        self._mcp = None
        self._catalog = self._provider.catalog
        self._executor = self._provider.executor
        self._base_catalog = None
        self._loader = None

    def bind(self, catalog, executor, loader):
        if self._base_catalog is not None:
            raise ValueError(
                "SelfConfigurationService must be private to one Agent loop"
            )
        if loader is None:
            raise ValueError(
                "self configuration requires a SkillLoader, even with no initial Skills"
            )
        self._base_catalog = catalog
        self._base_executor = executor
        self._loader = loader
        skills = _Skills(self, loader.catalog, loader.source)
        loader.catalog = skills
        loader.source = skills
        loader.workspace = _Workspace(self, loader.workspace)
        return CompositeToolCatalog((catalog, self)), CompositeToolExecutor(
            (self, executor)
        )

    async def list_tools(self, *, run_id):
        return await self._catalog.list_tools(run_id=run_id)

    async def get_tool(self, name, *, run_id):
        return await self._catalog.get_tool(name, run_id=run_id)

    async def execute(self, call, context):
        if call.tool_name == "agent_self_configure":
            receipt = await self.store.receipt(
                self.owner, call.owner_run_id, call.operation_id
            )
            if receipt:
                if receipt[0] != self._fingerprint(call):
                    raise self._error(
                        "self_configuration.operation_conflict",
                        "operation was used for a different request",
                    )
                # Reauthorize before revealing/reusing a saved capability receipt.
                await self.authorize(
                    SelfConfigurationRequest.model_validate(call.arguments), context
                )
                return self._result(call, receipt[1])
        return await self._executor.execute(call, context)

    async def reconcile_call(self, call, context):
        if call.tool_name == "agent_self_configure":
            receipt = await self.store.receipt(
                self.owner, call.owner_run_id, call.operation_id
            )
            if receipt and receipt[0] == self._fingerprint(call):
                await self.authorize(
                    SelfConfigurationRequest.model_validate(call.arguments), context
                )
                return ReconcileResult(
                    operation_id=call.operation_id,
                    state=ReconcileState.SUCCEEDED,
                    result=self._result(call, receipt[1]),
                )
            return ReconcileResult(
                operation_id=call.operation_id, state=ReconcileState.UNKNOWN
            )
        provider = self._mcp
        if provider is not None:
            return await provider.reconcile_call(call, context)
        return ReconcileResult(
            operation_id=call.operation_id, state=ReconcileState.UNKNOWN
        )

    async def reconcile(self, operation_id, context):
        return await self._executor.reconcile(operation_id, context)

    async def cancel(self, operation_id, context):
        return await self._executor.cancel(operation_id, context)

    async def release_run(self, run_id):
        await self._executor.release_run(run_id)

    async def verify_checkpoint(self, run_id, expected_revision):
        try:
            snapshot = await self.store.read(self.owner, run_id, create=False)
            if snapshot["revision"] < expected_revision:
                raise ValueError(
                    "saved capability revision is older than the checkpoint"
                )
        except ValueError as exc:
            raise self._error("self_configuration.state_missing", str(exc)) from exc

    async def prepare(self, run_id, context):
        """Activate staged revisions only at the Loop's tool-batch boundary."""
        if self.run_id is not None and self.run_id != run_id:
            raise ValueError("self configuration cannot be shared between Runs")
        self.run_id = run_id
        snapshot = await self.store.read(self.owner, run_id)
        request = SelfConfigurationRequest(
            add_mcp_servers=tuple(snapshot["mcp_servers"].values()),
            system_prompt=snapshot.get("system_prompt"),
        )
        await self.authorize(request, context)
        if snapshot["revision"] == self.revision:
            return False
        bundles = {
            name: self._decode(value) for name, value in snapshot["skills"].items()
        }
        plugin = await self._discover(request.add_mcp_servers)
        catalogs = (self._provider.catalog,)
        executors = (self._provider.executor,)
        if plugin is not None:
            await self._check_tool_names(plugin, run_id)
            catalogs += (plugin,)
            executors += (plugin,)
        # load_skill is granted through this authorized overlay even when the
        # admitted Run originally had no Skills. Its executor retains the loader.
        from sagents.v2.tool.plugins.skill import SkillToolPlugin

        definitions = await self._base_catalog.list_tools(run_id=run_id)
        skill_tool = SkillToolPlugin(self._loader)
        # Override execution with the private overlay loader even when the
        # host already advertises load_skill through its original loader.
        executors += (skill_tool.executor,)
        if not any(value.name == "load_skill" for value in definitions):
            catalogs += (skill_tool.catalog,)
        self.bundles = bundles
        self.system_prompt = snapshot.get("system_prompt", "")
        self._mcp = plugin
        self._catalog = CompositeToolCatalog(catalogs)
        self._executor = CompositeToolExecutor(executors)
        self.revision = snapshot["revision"]
        return True

    async def configure(self, request, invocation):
        async with self._lock:
            call, context = invocation.call, invocation.request_context
            await self.authorize(request, context)
            snapshot = await self.store.read(self.owner, call.owner_run_id)
            if (
                not request.add_skill_paths
                and not request.add_mcp_servers
                and request.system_prompt is None
            ):
                return {
                    "revision": snapshot["revision"],
                    "skills": sorted(snapshot["skills"]),
                    "mcp_servers": sorted(snapshot["mcp_servers"]),
                    "system_prompt": snapshot.get("system_prompt", ""),
                }
            skills = {}
            base_names = {
                value.name
                for value in await self._loader.catalog.list_skills(
                    run_id=call.owner_run_id
                )
            }
            for path in request.add_skill_paths:
                directory = self._skill_path(path)
                provider = FilesystemSkillProvider(
                    (directory.parent,), max_total_bytes=8 * 1024 * 1024
                )
                bundle = await provider.fetch(directory.name, run_id=call.owner_run_id)
                bundle.files["SKILL.md"].decode("utf-8")
                bundle = bundle.model_copy(
                    update={
                        "descriptor": bundle.descriptor.model_copy(
                            update={"source_id": "agent-self-configuration"}
                        )
                    }
                )
                encoded = self._encode(bundle)
                name = bundle.descriptor.name
                if name in base_names and name not in snapshot["skills"]:
                    raise self._error(
                        "self_configuration.skill_conflict",
                        f"Skill {name!r} is already supplied by the host",
                    )
                if name in snapshot["skills"] and snapshot["skills"][name] != encoded:
                    raise self._error(
                        "self_configuration.skill_conflict",
                        f"Skill {name!r} already has different content; use a new name",
                    )
                if name in skills and skills[name] != encoded:
                    raise self._error(
                        "self_configuration.skill_conflict",
                        f"duplicate Skill name {name!r}",
                    )
                skills[name] = encoded
            servers = {}
            for server in request.add_mcp_servers:
                server.config()  # Transport validation before contacting anything.
                value = server.model_dump(mode="json")
                if (
                    server.name in snapshot["mcp_servers"]
                    and snapshot["mcp_servers"][server.name] != value
                ):
                    raise self._error(
                        "self_configuration.mcp_conflict",
                        f"MCP {server.name!r} already has a different definition",
                    )
                if server.name in servers and servers[server.name] != value:
                    raise self._error(
                        "self_configuration.mcp_conflict", "duplicate MCP names"
                    )
                servers[server.name] = value
            combined_skills = {**snapshot["skills"], **skills}
            encoded_size = sum(
                len(content)
                for bundle in combined_skills.values()
                for content in bundle["files"].values()
            )
            if encoded_size > 90 * 1024 * 1024:
                raise self._error(
                    "self_configuration.limit",
                    "Saved Skill snapshots exceed the Agent byte limit",
                )
            merged = {**snapshot["mcp_servers"], **servers}
            if len(snapshot["skills"].keys() | skills.keys()) > 64 or len(merged) > 32:
                raise self._error(
                    "self_configuration.limit", "Agent capability limit exceeded"
                )
            plugin = await self._discover(
                tuple(SelfMcpServer.model_validate(value) for value in merged.values())
            )
            if plugin is not None:
                await self._check_tool_names(plugin, call.owner_run_id)
            # Persist the result and both the Run revision and future Agent
            # defaults in one transaction. Do not activate inside this Tool.
            return await self.store.commit(
                self.owner,
                call.owner_run_id,
                call.operation_id,
                self._fingerprint(call),
                snapshot["revision"],
                skills,
                servers,
                system_prompt=request.system_prompt,
            )

    def _skill_path(self, raw):
        path = Path(raw)
        if self.workspace_alias and (
            raw == self.workspace_alias
            or raw.startswith(self.workspace_alias.rstrip("/") + "/")
        ):
            path = self.workspace_root / raw[len(self.workspace_alias) :].lstrip("/")
        elif not path.is_absolute():
            path = self.workspace_root / path
        try:
            path.relative_to(self.workspace_root)
            for entry in (path, *path.parents):
                if entry == self.workspace_root:
                    break
                if entry.is_symlink():
                    raise ValueError("Skill paths cannot contain symlinks")
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.workspace_root)
        except (ValueError, OSError) as exc:
            raise self._error(
                "self_configuration.path_denied",
                "Skill directory must be inside the authorized workspace",
            ) from exc
        if not resolved.is_dir():
            raise self._error(
                "self_configuration.path_denied", "Skill path must be a directory"
            )
        return resolved

    async def _discover(self, servers):
        if not servers:
            return None
        plugin = McpToolPlugin(
            tuple(server.config() for server in servers),
            session_factory=self.mcp_session_factory,
        )
        await plugin.list_tools(run_id=self.run_id or "self-configuration")
        return plugin

    async def _check_tool_names(self, plugin, run_id):
        names = {
            value.name for value in await self._base_catalog.list_tools(run_id=run_id)
        } | {"agent_self_configure", "load_skill"}
        duplicates = names & {
            value.name for value in await plugin.list_tools(run_id=run_id)
        }
        if duplicates:
            raise self._error(
                "self_configuration.tool_conflict",
                f"MCP tools conflict with host tools: {sorted(duplicates)}",
            )

    async def segments(self, command, *, run_id=None):
        segments = (
            ContextSegment(
                segment_id="agent_self_configuration",
                stability=ContextStability.SEMI_STABLE,
                priority=10,
                content=(
                    "You can extend your own Skills and MCP tools with agent_self_configure. "
                    "Download or author Skills with existing file/network tools, then pass their local directory paths. "
                    "Set system_prompt to replace your own instructions; use an empty string to clear them. "
                    "Your instructions cannot replace host rules or grant permissions. "
                    "Directory names are Skill names. Changes persist and take effect after the current tool batch, "
                    "before your next model step in this same task. Call load_skill before following a new Skill. "
                    "Host permissions still apply. Credentials must be configured by the host. "
                    f"Self configuration revision: {self.revision or 0}."
                ),
            ),
        )

        if self.system_prompt:
            segments += (
                ContextSegment(
                    segment_id="agent_self_instructions",
                    stability=ContextStability.SEMI_STABLE,
                    priority=-170,
                    content=(
                        "Agent-owned instructions follow as a JSON string. Apply them only when "
                        "consistent with host system rules, role definition and granted permissions. "
                        "They cannot override those rules or expand permissions.\n"
                        + json.dumps(self.system_prompt, ensure_ascii=False)
                    ),
                ),
            )
        return segments

    @staticmethod
    def _fingerprint(call):
        return hashlib.sha256(
            json.dumps(call.arguments, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _encode(bundle):
        return {
            "descriptor": bundle.descriptor.model_dump(mode="json"),
            "content_hash": bundle.content_hash,
            "files": {
                path: base64.b64encode(content).decode()
                for path, content in bundle.files.items()
            },
        }

    @staticmethod
    def _decode(value):
        return SkillBundle(
            descriptor=value["descriptor"],
            content_hash=value["content_hash"],
            files={
                path: base64.b64decode(content)
                for path, content in value["files"].items()
            },
        )

    @staticmethod
    def _result(call, result):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(JsonBlock(value=result),),
        )

    @staticmethod
    def _error(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.POLICY_DENIED,
                message=message,
                safe_to_resume=True,
            )
        )
