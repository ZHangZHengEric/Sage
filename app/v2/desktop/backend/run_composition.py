from __future__ import annotations

from app.v2.desktop.backend.run_environment import catalog_agent_id

import base64
import hashlib
import io
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.v2.desktop.backend.model_providers import DesktopModelProviders, thinking_config
from sagents.v2.tool.official.media import compress_image_to_jpeg_bytes_for_llm
from app.v2.desktop.backend.catalog import (
    DesktopAgentRecord,
    DesktopModelCompatibilityProfile,
    DesktopModelProviderRecord,
)
from app.v2.desktop.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    stable_component_id as _stable_component_id,
)
from sagents.v2.contracts.commands import (
    InputItem,
    StartRun,
)
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.package.manifest.agents import (
    AgentBudgets,
    AgentDefinition,
    AgentMemoryBehavior,
    ApplicationEntrypoint,
    Instructions,
)
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.root import ManifestMetadata, SageManifest
from sagents.v2.package.manifest.runtime import PolicyConfig
from sagents.v2.i18n import normalize_language
from app.v2.desktop.backend.studio import STUDIO_TOOLS
from app.v2.desktop.backend.schemas import (
    DesktopRunRequest,
    DesktopV2Settings,
    RunMessage,
    RunMessageReferenceContent,
    RunMessageTextContent,
)
from app.v2.desktop.backend.run_environment import DesktopRunEnvironmentMixin
from app.v2.desktop.backend.runtime_config import (
    _PLAN_BLOCKED_TOOLS,
    _agent_memory_behavior,
    _resolved_sandbox_config,
    _sandbox_workspace_root,
)
from app.v2.desktop.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)


class DesktopRunCompositionMixin(DesktopRunEnvironmentMixin):
    """Compose immutable Run manifests, providers, tools, and sandboxes."""

    def _memory_service_for_agent(self, agent):
        from sagents.v2.memory import MemoryService
        return MemoryService(self.memory_provider, scope_mode=_agent_memory_behavior(agent).scope, session_store=self.session_store)

    async def _session_id_for_run(self, run_id: str) -> str:
        return (await self.session_store.get_run(run_id)).session_id

    def _manifest(self, agent, provider, tools, skills):
        tools = tuple(name for name in tools if name not in STUDIO_TOOLS)
        max_steps = max(1, min(int(agent.config.get("maxLoopCount") or 24), 10_000))
        memory_enabled = (
            self.memory_plugin_id != "sage.memory.noop" and "search_memory" in tools
        )
        memory_behavior = _agent_memory_behavior(agent)
        return SageManifest(
            kind="agent-package",
            metadata=ManifestMetadata(
                id=f"desktop.{agent.agent_id}",
                version="0.1.0",
                name=agent.name,
                description=agent.config.get("description"),
            ),
            policies=PolicyConfig(budgets={"max_steps": max_steps}),
            agents={
                agent.agent_id: AgentDefinition(
                    name=agent.name,
                    instructions=Instructions(
                        inline=agent.config.get("systemPrefix")
                        or "You are a helpful Sage agent."
                    ),
                    models={"primary": provider.id},
                    tools=tools if provider.supports_tool_calling else (),
                    skills=skills,
                    budgets=AgentBudgets(max_steps=max_steps),
                    memory=AgentMemoryBehavior(
                        recall=memory_enabled and memory_behavior.recall,
                        auto_write=memory_enabled and memory_behavior.auto_write,
                        scope=memory_behavior.scope,
                    ),
                )
            },
            entrypoint=ApplicationEntrypoint(agent=agent.agent_id),
        )

    def _model_catalog(self, agent, provider):
        from sagents.v2.model.catalog import ModelCatalogConfig
        route = DesktopModelProviders.route(
            provider, agent,
            compatibility_profile=self._verified_model_compatibility_profile(provider),
        )
        credential_id = "desktop_model_" + provider.id
        route = route.model_copy(update={"credential": credential_id})
        return ModelCatalogConfig(
            models={provider.id: route},
            credentials={credential_id: CredentialDeclaration(
                source="host", ref=f"llm-provider:{provider.id}")},
        )

    async def _model_provider(
        self, provider, agent, *, enable_thinking: bool | None = None
    ):
        return self.model_providers.get(
            provider, agent,
            compatibility_profile=self._verified_model_compatibility_profile(provider),
            enable_thinking=enable_thinking,
        )

    @classmethod
    def _verified_model_compatibility_profile(
        cls,
        provider: DesktopModelProviderRecord,
    ) -> DesktopModelCompatibilityProfile | None:
        profile = provider.compatibility_profile
        if profile is None:
            return None
        if profile.route_fingerprint != cls._model_compatibility_fingerprint(provider):
            return None
        return profile

    @classmethod
    def _auxiliary_json_compatible(
        cls,
        provider: DesktopModelProviderRecord,
    ) -> bool:
        profile = cls._verified_model_compatibility_profile(provider)
        return (
            profile is None
            or profile.schema_version < 2
            or profile.auxiliary_json_compatible
        )

    async def _fast_provider(
        self,
        agent: DesktopAgentRecord,
        fallback: DesktopModelProviderRecord,
    ) -> DesktopModelProviderRecord:
        provider_id = str(agent.config.get("fast_llm_provider_id") or "").strip()
        if not provider_id:
            return fallback
        provider = await self.catalog.get_model_provider(provider_id, agent.user_id)
        if provider is None or not provider.api_key or not provider.base_url:
            return fallback
        return provider

    _thinking_config = staticmethod(thinking_config)

    @staticmethod
    def _attachment_host_path(
        attachment_path: str,
        *,
        workspace: Path,
        workspace_root: str,
    ) -> Path | None:
        """Resolve a sandbox-visible attachment without escaping its workspace."""

        raw = str(attachment_path).strip()
        if not raw:
            return None
        host_root = workspace.expanduser().resolve()
        normalized = raw.replace("\\", "/")
        virtual_root = workspace_root.replace("\\", "/").rstrip("/")
        if normalized == virtual_root:
            relative = ""
        elif normalized.startswith(f"{virtual_root}/"):
            relative = normalized[len(virtual_root) + 1 :]
        else:
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                resolved = candidate.resolve()
                if resolved != host_root and host_root not in resolved.parents:
                    return None
                return resolved
            relative = normalized
        resolved = (host_root / relative).resolve()
        if resolved != host_root and host_root not in resolved.parents:
            return None
        return resolved

    @classmethod
    def _image_attachment_block(
        cls,
        attachment_path: str,
        *,
        workspace: Path,
        workspace_root: str,
    ) -> ImageBlock | None:
        host_path = cls._attachment_host_path(
            attachment_path,
            workspace=workspace,
            workspace_root=workspace_root,
        )
        if host_path is None or not host_path.is_file():
            return None
        mime_type = mimetypes.guess_type(host_path.name)[0]
        if mime_type is None or not mime_type.startswith("image/"):
            return None
        try:
            content = host_path.read_bytes()
        except OSError:
            return None
        # Keep the durable upload untouched, but reuse v1's proven LLM image
        # normalization at the outbound attachment boundary. This applies EXIF
        # orientation, bounds the long edge, removes alpha safely, and uses a
        # byte-budgeted JPEG representation for every decodable raster image.
        try:
            with Image.open(io.BytesIO(content)) as image:
                content = compress_image_to_jpeg_bytes_for_llm(image)
            mime_type = "image/jpeg"
        except (OSError, ValueError, Image.DecompressionBombError):
            # Preserve the previous pass-through behavior for malformed or
            # unsupported formats; the selected model plugin will validate it.
            pass
        return ImageBlock(
            uri=(
                f"data:{mime_type};base64," + base64.b64encode(content).decode("ascii")
            ),
            mime_type=mime_type,
            alt=attachment_path,
        )

    @staticmethod
    def _attachment_markdown_reference(attachment_path: str) -> str:
        """Keep every attachment address visible as a Markdown reference."""

        normalized = str(attachment_path).replace("\\", "/")
        label = Path(normalized).name or normalized
        escaped_label = (
            label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        )
        escaped_destination = normalized.replace("<", "%3C").replace(">", "%3E")
        prefix = (
            "!" if (mimetypes.guess_type(label)[0] or "").startswith("image/") else ""
        )
        return f"{prefix}[{escaped_label}](<{escaped_destination}>)"

    def _run_message_content(
        self,
        message: RunMessage,
        *,
        provider: DesktopModelProviderRecord | None,
        workspace: Path | None,
        workspace_root: str,
    ) -> tuple[TextBlock | ImageBlock, ...]:
        if not message.content:
            return (TextBlock(text=message.text),) if message.text.strip() else ()

        blocks: list[TextBlock | ImageBlock] = []
        for part in message.content:
            if isinstance(part, RunMessageTextContent):
                if part.text:
                    blocks.append(TextBlock(text=part.text))
                continue

            if not isinstance(part, RunMessageReferenceContent):
                continue
            label = part.citation_label or part.name or Path(part.path).name
            if part.quote:
                if part.path.startswith("conversation://"):
                    reference = f"Referenced message excerpt ({label}):\n{part.quote}"
                else:
                    reference = (
                        f"{self._attachment_markdown_reference(part.path)}\n"
                        f"Referenced excerpt:\n{part.quote}"
                    )
                blocks.append(TextBlock(text=reference))
                continue

            blocks.append(
                TextBlock(text=self._attachment_markdown_reference(part.path))
            )
            if provider is not None and provider.supports_multimodal and workspace:
                image = self._image_attachment_block(
                    part.path,
                    workspace=workspace,
                    workspace_root=workspace_root,
                )
                if image is not None:
                    blocks.append(image)
        return tuple(blocks)

    def _command(
        self,
        request: DesktopRunRequest,
        resolved,
        *,
        agent=None,
        provider: DesktopModelProviderRecord | None = None,
        workspace=None,
        environment=None,
    ):
        settings = (
            DesktopV2Settings.model_validate(environment.snapshot["settings"])
            if environment is not None
            else self._read_settings_sync()
        )
        _, sandbox_config = _resolved_sandbox_config(settings)
        workspace_root = _sandbox_workspace_root(
            sandbox_config,
            Path(workspace) if workspace is not None else None,
        )
        current_time = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
        frozen_time = f"<current_time>{current_time}</current_time>"
        items_list: list[InputItem] = []
        for value in request.messages:
            content = self._run_message_content(
                value,
                provider=provider,
                workspace=Path(workspace) if workspace is not None else None,
                workspace_root=workspace_root,
            )
            if not content:
                continue
            items_list.append(
                InputItem(
                    role=value.role,
                    content=content,
                    metadata=(
                        {"frozen_current_time_context": frozen_time}
                        if value.role == "user"
                        else {}
                    ),
                )
            )
        items = tuple(items_list)
        if request.attachment_paths:
            attachment_content: list[TextBlock | ImageBlock] = [
                TextBlock(
                    text="Attached workspace references (files or directories):\n"
                    + "\n".join(
                        self._attachment_markdown_reference(attachment_path)
                        for attachment_path in request.attachment_paths
                    )
                )
            ]
            if provider is not None and provider.supports_multimodal and workspace:
                attachment_content.extend(
                    block
                    for attachment_path in request.attachment_paths
                    if (
                        block := self._image_attachment_block(
                            attachment_path,
                            workspace=Path(workspace),
                            workspace_root=workspace_root,
                        )
                    )
                    is not None
                )
            items = (
                *items,
                InputItem(
                    role="user",
                    content=tuple(attachment_content),
                    metadata={"frozen_current_time_context": frozen_time},
                ),
            )
        configured_context = {}
        if agent is not None:
            raw_context = agent.config.get("systemContext") or agent.config.get(
                "system_context"
            )
            if isinstance(raw_context, dict):
                configured_context = dict(raw_context)
        configured_response_language = configured_context.pop("response_language", None)
        response_language = str(
            request.response_language
            or configured_response_language
            or settings.language
            or "en"
        )
        response_language = normalize_language(response_language)
        metadata = {
            "workspace_id": request.workspace_id,
            "preferred_skills": request.preferred_skills,
            "ui_preference": request.ui_preference,
            "approval_mode": request.approval_mode,
            "invocation_mode": request.invocation_mode,
            "response_language": response_language,
            "system_context": configured_context,
            "current_time": current_time,
            "identity_documents": self._identity_documents(
                self._agent_workspace_path(settings.agent_workspace_path)
            ),
            "runtime_components": {
                "sandbox_path_mode": sandbox_config["workspace_path_mode"],
                "selections": dict(settings.component_selections),
                "configs": dict(settings.component_configs),
            },
        }
        if provider is not None:
            metadata["model_route"] = self._model_route_snapshot(provider)
        if agent is not None:
            metadata["agent_runtime"] = self._agent_runtime_snapshot(agent)
        if request.fork_source_run_id is not None:
            metadata["fork_source_run_id"] = request.fork_source_run_id
        if workspace is not None:
            metadata["working_directory"] = workspace_root
            metadata["workspace_files"] = self._workspace_prompt_listing(
                Path(workspace).resolve()
                if sandbox_config["workspace_mapping"] == "active_workspace"
                else None,
                workspace_root=workspace_root,
            )
        for key in ("todo", "external_paths", "shell_completion_reminder"):
            if key in configured_context:
                metadata[key] = configured_context.pop(key)
        studio_binding = self.studio_request_binding(
            request, agent.user_id if agent is not None else ""
        )
        if studio_binding:
            metadata["studio"] = studio_binding
        run_config = CompositionResolver().resolve_run_config(
            resolved,
            request.agent_id,
            metadata=metadata,
        )
        invocation_grants = {
            "plan": ("goal_submit",),
            "goal": ("goal_submit", "goal_complete"),
        }.get(request.invocation_mode, ())
        if studio_binding:
            invocation_grants = (*invocation_grants, *sorted(STUDIO_TOOLS))
        if invocation_grants:
            base_tools = tuple(
                name
                for name in (run_config.enabled_tools or ())
                if not (
                    request.invocation_mode == "plan" and name in _PLAN_BLOCKED_TOOLS
                )
            )
            enabled_tools = (
                *base_tools,
                *(name for name in invocation_grants if name not in base_tools),
            )
            run_config = run_config.model_copy(
                update={
                    "enabled_tools": enabled_tools,
                    "metadata": {
                        **run_config.metadata,
                        "enabled_tools": list(enabled_tools),
                    },
                }
            )
        return StartRun(
            session_id=request.session_id,
            agent_id=request.agent_id,
            input=items,
            config=run_config,
            resolved_spec_hash=self._desktop_spec_hash(
                resolved.manifest_hash, settings
            ),
            idempotency_key=request.idempotency_key or new_id("desktop_request"),
            session_concurrency_mode=request.session_concurrency_mode,
            base_session_revision=request.base_session_revision,
            invocation_mode=request.invocation_mode,
        )

    def _desktop_spec_hash(self, manifest_hash: str, settings) -> str:
        components = {
            capability: _stable_component_id(
                capability,
                settings.component_selections.get(capability, default_plugin),
            )
            for capability, default_plugin in _DESKTOP_COMPONENT_DEFAULTS.items()
        }
        process_plugins = {
            "session.store": self.session_plugin_id,
            "context.summary-store": self.summary_store_plugin_id,
            "observability.diagnostic-sink": self.diagnostic_plugin_id,
            "memory.provider": self.memory_plugin_id,
            "session-memory.provider": self.session_memory_plugin_id,
        }
        selected_plugins = set(components.values()) | set(process_plugins.values())
        versions = {
            plugin_id: self.extensions.get(plugin_id).descriptor.version
            for plugin_id in sorted(selected_plugins)
            if self.extensions.contains(plugin_id)
        }
        payload = {
            "manifest": manifest_hash,
            "components": components,
            "configs": dict(settings.component_configs),
            "process_plugins": process_plugins,
            "plugin_versions": versions,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _identity_documents(self, root: Path | None = None) -> dict[str, str]:
        values = {}
        workspace = (root or self.agent_workspace).resolve()
        from sagents.v2.context.runtime_metadata import (
            IDENTITY_DOCUMENT_LIMITS,
            bounded_identity_document,
        )

        for name in ("AGENT", "IDENTITY", "SOUL", "USER", "MEMORY"):
            path = workspace / f"{name}.md"
            if not path.is_file() or path.is_symlink():
                continue
            try:
                with path.open(encoding="utf-8") as stream:
                    content = stream.read(IDENTITY_DOCUMENT_LIMITS[name] + 1)
            except (OSError, UnicodeDecodeError):
                continue
            if name == "AGENT":
                bounded_identity_document(name, content)
            if content.strip():
                values[name] = content
        return values

    @staticmethod
    def _workspace_prompt_listing(
        root: Path | None, *, workspace_root: str = "/workspace", maximum: int = 200
    ) -> str:
        """Freeze a deterministic, bounded two-level workspace view for one Run."""

        if root is None:
            return f"Working directory: {workspace_root}\n(Empty isolated sandbox)"
        entries = []
        try:
            top_level = sorted(root.iterdir(), key=lambda value: value.name)
        except OSError:
            return f"Working directory: {workspace_root}\n(Empty isolated sandbox)"
        for child in top_level:
            if child.is_symlink():
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(child.name + suffix)
            if len(entries) >= maximum:
                entries.append("... (truncated)")
                break
            if not child.is_dir():
                continue
            try:
                nested = sorted(child.iterdir(), key=lambda value: value.name)
            except OSError:
                continue
            for grandchild in nested:
                if grandchild.is_symlink():
                    continue
                suffix = "/" if grandchild.is_dir() else ""
                entries.append(f"{child.name}/{grandchild.name}{suffix}")
                if len(entries) >= maximum:
                    entries.append("... (truncated)")
                    break
            if entries and entries[-1] == "... (truncated)":
                break
        return (
            f"Working directory: {workspace_root}"
            + "\n"
            + ("\n".join(entries) if entries else "(Empty)")
        )

    async def _agent(self, agent_id: str, user_id: str) -> DesktopAgentRecord:
        await self._initialize_user(user_id)
        agent = await self.catalog.get_agent(agent_id, user_id)
        if agent is None:
            raise ValueError("agent is not configured for this Desktop user")
        return agent

    async def _provider(
        self, agent: DesktopAgentRecord, user_id: str
    ) -> DesktopModelProviderRecord:
        provider_id = agent.config.get("llm_provider_id")
        provider = (
            await self.catalog.get_model_provider(str(provider_id), agent.user_id)
            if provider_id
            else None
        )
        values = await self.catalog.list_model_providers(user_id)
        if provider is None:
            provider = next((value for value in values if value.is_default), None)
        if provider is None and values:
            provider = values[0]
        if provider is None or not provider.api_key or not provider.base_url:
            raise ValueError("agent has no usable model provider")
        return provider

    async def _agent_for_command(
        self,
        command: StartRun,
        user_id: str,
    ) -> DesktopAgentRecord:
        """Restore the immutable Agent definition selected for this Run."""

        raw_snapshot = command.config.metadata.get("agent_runtime")
        if not isinstance(raw_snapshot, dict):
            return await self._agent(catalog_agent_id(command), user_id)
        values = dict(raw_snapshot)
        if values.get("agent_id") != catalog_agent_id(command):
            raise ValueError("Run Agent snapshot does not match the StartRun agent")
        current = await self.catalog.get_agent(catalog_agent_id(command), user_id)
        frozen_config = dict(values.get("config") or {})
        if current is not None:
            # "Approve and remember" is an explicit monotonic authorization
            # update and should remain useful if this Run is later recovered.
            remembered = current.config.get("approvedShellCommands")
            if remembered is not None:
                frozen_config["approvedShellCommands"] = list(remembered)
            values["updated_at"] = current.updated_at
        values["config"] = frozen_config
        values["user_id"] = user_id
        return DesktopAgentRecord.model_validate(values)

    async def _provider_for_command(
        self,
        command: StartRun,
        agent: DesktopAgentRecord,
        user_id: str,
    ) -> DesktopModelProviderRecord:
        """Restore the immutable model route selected when the Run started."""

        raw_snapshot = command.config.metadata.get("model_route")
        if not isinstance(raw_snapshot, dict):
            # Existing persisted Runs predate route snapshots.
            return await self._provider(agent, user_id)
        provider_id = str(raw_snapshot.get("id") or "").strip()
        if not provider_id:
            raise ValueError("Run model route snapshot has no provider id")
        current = await self.catalog.get_model_provider(provider_id, user_id)
        if current is None or not current.api_key:
            raise ValueError(
                "Run model provider is unavailable; restore the original provider "
                f"{provider_id!r} to continue this Run"
            )
        values = current.model_dump(mode="python")
        values.update(raw_snapshot)
        # Credentials are intentionally never persisted in the StartRun command.
        values["api_key"] = current.api_key
        values["user_id"] = user_id
        return DesktopModelProviderRecord.model_validate(values)

    @staticmethod
    def _model_route_snapshot(
        provider: DesktopModelProviderRecord,
    ) -> dict[str, Any]:
        values = provider.model_dump(
            mode="json",
            exclude={"api_key", "updated_at", "is_default"},
        )
        return values

    @staticmethod
    def _agent_runtime_snapshot(agent: DesktopAgentRecord) -> dict[str, Any]:
        return agent.model_dump(
            mode="json",
            exclude={"user_id", "updated_at"},
        )
