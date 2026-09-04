from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from PIL import Image

from sagents.llm.model_capabilities import (
    build_llm_extra_body,
    is_openai_reasoning_model,
)
from sagents.utils.multimodal_image import compress_image_to_jpeg_bytes_for_llm
from app.desktop_v2.backend.catalog import (
    DesktopAgentRecord,
    DesktopModelCompatibilityProfile,
    DesktopModelProviderRecord,
)
from app.desktop_v2.backend.shell_policy import (
    ShellCommandOperationAssessor,
)
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from app.desktop_v2.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    stable_component_id as _stable_component_id,
)
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    WorkspaceSharingPolicy,
)
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.contracts.commands import (
    InputItem,
    StartRun,
)
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.agent import AgentCompositionFactory
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.package.manifest.agents import (
    AgentBudgets,
    AgentDefinition,
    AgentMemoryBehavior,
    ApplicationEntrypoint,
    Instructions,
)
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.package.manifest.models import (
    ModelCapabilityDeclaration,
    ModelLimits,
    ModelRequestDefaults,
    ModelRoute,
)
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.root import ManifestMetadata, SageManifest
from sagents.v2.package.manifest.runtime import PolicyConfig
from sagents.v2.context import (
    ContextBudget,
    DefaultContextAssembler,
    RunMetadataContextProvider,
)
from sagents.v2.goal import (
    GoalCompletionGatePolicy,
    GoalContextProvider,
    GoalStateService,
)
from sagents.v2.i18n import normalize_language
from sagents.v2.plan import (
    PlanCompletionGatePolicy,
    PlanContextProvider,
)
from sagents.v2.runtime.credentials import CredentialMaterial
from sagents.v2.model import (
    RecordingModelProvider,
)
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.model.protocols import create_registered_model_provider
from sagents.v2.agent.policy import (
    ApprovalStrategy,
    DefaultToolPolicy,
)
from sagents.v2.runtime.execution.sandbox import (
    FileSystemMode,
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    IsolationLevel,
    LifecyclePolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxReleaseDisposition,
)
from sagents.v2.runtime.execution import (
    ExecutionBindingLifecycleCoordinator,
)
from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
)
from sagents.v2.tool import (
    CompositeToolCatalog,
    CompositeToolExecutor,
)
from app.desktop_v2.backend.package import desktop_v2_manifest
from app.desktop_v2.backend.schemas import (
    DesktopRunRequest,
    RunMessage,
    RunMessageReferenceContent,
    RunMessageTextContent,
)
from app.desktop_v2.backend.run_lifecycle import (
    ACTIVE_EXTENSION_SCOPE_HANDLES as _ACTIVE_EXTENSION_SCOPE_HANDLES,
    DesktopRunResources as _DesktopRunResources,
)
from app.desktop_v2.backend.run_context import (
    AgentRosterContextProvider,
    LocalSkillWorkspace,
    PreferredSkillsContextProvider,
    SandboxSkillWorkspace,
)
from app.desktop_v2.backend.runtime_config import (
    _PLAN_BLOCKED_TOOLS,
    _REASONING_DISABLE_EXTRAS,
    _SKILL_NAME,
    _TOOL_NAME,
    _continuation_agent_instructions,
    _resolved_sandbox_config,
    _sandbox_workspace_root,
    _tool_selection_component_config,
)
from app.desktop_v2.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)


class DesktopRunCompositionMixin:
    """Compose immutable Run manifests, providers, tools, and sandboxes."""

    async def _build_loop(
        self,
        *,
        agent,
        provider,
        workspace,
        preferred_skills,
        approval_mode,
        invocation_mode="normal",
        session_id: str | None = None,
        run_id: str | None = None,
        resolved_spec_hash: str | None = None,
        component_snapshot: dict[str, Any] | None = None,
        force_leaf: bool = False,
    ):
        await self.start()
        provisioned: list[Any] = []
        scope_handles: list[Any] = []
        token = _ACTIVE_EXTENSION_SCOPE_HANDLES.set(scope_handles)
        try:
            (
                resolved,
                loop,
                sandbox_handle,
                sandbox_provider,
                sandbox_spec,
                job_runtime,
            ) = await self._compose_run_driver(
                agent=agent,
                provider=provider,
                workspace=workspace,
                preferred_skills=preferred_skills,
                approval_mode=approval_mode,
                invocation_mode=invocation_mode,
                session_id=session_id,
                run_id=run_id,
                resolved_spec_hash=resolved_spec_hash,
                component_snapshot=component_snapshot,
                force_leaf=force_leaf,
                sandbox_observer=provisioned.append,
            )
            lifecycle = None
            if run_id is not None and resolved_spec_hash is not None:
                lifecycle = ExecutionBindingLifecycleCoordinator(
                    sandbox_provider=sandbox_provider,
                    session_store=self.driver_session_store,
                    job_runtime=job_runtime,
                )
            return (
                resolved,
                loop,
                _DesktopRunResources(sandbox_handle, scope_handles, lifecycle),
            )
        except BaseException as exc:
            cleanup_errors: list[BaseException] = []
            # Run-scoped services may still own jobs against the sandbox, so
            # release them before tearing down the execution boundary.
            for handle in reversed(scope_handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    cleanup_errors.append(close_exc)
            for sandbox_handle in reversed(provisioned):
                try:
                    await sandbox_handle.close()
                except BaseException as close_exc:
                    cleanup_errors.append(close_exc)
            if cleanup_errors:
                raise exc from cleanup_errors[0]
            raise
        finally:
            _ACTIVE_EXTENSION_SCOPE_HANDLES.reset(token)

    async def _compose_run_driver(
        self,
        *,
        agent,
        provider,
        workspace,
        preferred_skills,
        approval_mode,
        invocation_mode="normal",
        session_id: str | None = None,
        run_id: str | None = None,
        resolved_spec_hash: str | None = None,
        component_snapshot: dict[str, Any] | None = None,
        force_leaf: bool = False,
        sandbox_observer,
    ):
        skill_provider = self._skill_provider()
        mcp_plugin = await self._mcp_plugin(agent.user_id)
        mcp_definitions = await mcp_plugin.list_tools(run_id="desktop-composition")
        valid_skills = tuple(
            value
            for value in (agent.config.get("availableSkills") or ())
            if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
        )
        configured_tools = agent.config.get("availableTools")
        valid_tools = tuple(
            value
            for value in (
                configured_tools
                if configured_tools is not None
                else tuple(
                    value["name"] for value in await self.list_tools(agent.user_id)
                )
            )
            if isinstance(value, str) and _TOOL_NAME.fullmatch(value)
        )
        tool_definitions = (*self._native_tool_definitions(), *mcp_definitions)
        known_tools = {value.name for value in tool_definitions}
        missing_tools = sorted(set(valid_tools) - known_tools)
        if missing_tools:
            raise ValueError(
                "configured tools are unavailable: " + ", ".join(missing_tools)
            )
        if valid_skills and "load_skill" not in valid_tools:
            valid_tools = (*valid_tools, "load_skill")
        manifest = self._manifest(agent, provider, valid_tools, valid_skills)
        resolved = CompositionResolver().resolve(manifest)
        settings = await self.get_settings()
        if component_snapshot:
            settings = settings.model_copy(
                update={
                    "component_selections": dict(
                        component_snapshot.get("selections") or {}
                    ),
                    "component_configs": dict(component_snapshot.get("configs") or {}),
                }
            )
        current_resolved_spec_hash = self._desktop_spec_hash(
            resolved.manifest_hash, settings
        )
        estimator_id = settings.component_selections.get(
            "context.token-estimator",
            _DESKTOP_COMPONENT_DEFAULTS["context.token-estimator"],
        )
        reducer_id = settings.component_selections.get(
            "context.reducer", _DESKTOP_COMPONENT_DEFAULTS["context.reducer"]
        )
        estimator_id = _stable_component_id("context.token-estimator", estimator_id)
        reducer_id = _stable_component_id("context.reducer", reducer_id)
        # Desktop compression uses the configured route itself. The summary is
        # derived state in SummaryStore; canonical Session events remain intact.
        # Recording the secondary request also keeps provider diagnostics honest.
        model_provider = await self._model_provider(provider, agent)
        recording_model = RecordingModelProvider(
            model_provider,
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": provider.id,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
            },
        )
        judge_provider = await self._fast_provider(agent, provider)
        judge_recording_model = RecordingModelProvider(
            await self._model_provider(judge_provider, agent, enable_thinking=False),
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": judge_provider.id,
                "protocol": judge_provider.protocol,
                "base_url": judge_provider.base_url,
                "model": judge_provider.model,
                "purpose": "task_complete_judge",
                "model_type": "fast",
            },
        )
        memory_query_plugin_id = _stable_component_id(
            "memory.recall-query",
            settings.component_selections.get(
                "memory.recall-query",
                _DESKTOP_COMPONENT_DEFAULTS["memory.recall-query"],
            ),
        )
        memory_query_model = RecordingModelProvider(
            await self._model_provider(judge_provider, agent, enable_thinking=False),
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": judge_provider.id,
                "protocol": judge_provider.protocol,
                "base_url": judge_provider.base_url,
                "model": judge_provider.model,
                "purpose": "memory_recall_query",
                "model_type": "fast",
            },
        )
        tool_selection_model = RecordingModelProvider(
            await self._model_provider(judge_provider, agent, enable_thinking=False),
            sink=self.diagnostics,
            session_id_resolver=self._session_id_for_run,
            provider_metadata={
                "agent_id": agent.agent_id,
                "provider_id": judge_provider.id,
                "protocol": judge_provider.protocol,
                "base_url": judge_provider.base_url,
                "model": judge_provider.model,
                "purpose": "tool_selection",
                "model_type": "fast",
            },
        )
        summarizer_plugin_id = _stable_component_id(
            "context.summarizer",
            settings.component_selections.get(
                "context.summarizer",
                _DESKTOP_COMPONENT_DEFAULTS["context.summarizer"],
            ),
        )
        continuation_plugin_id = _stable_component_id(
            "agent.continuation-policy",
            settings.component_selections.get(
                "agent.continuation-policy",
                _DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"],
            ),
        )
        if continuation_plugin_id in {
            "sage.agent.continuation.llm-judge",
            "sage.agent.continuation.hybrid",
        } and not self._auxiliary_json_compatible(judge_provider):
            continuation_plugin_id = "sage.agent.continuation.deterministic"
        raw_tool_selection = agent.config.get("toolSelection")
        legacy_tool_selection_config = (
            dict(raw_tool_selection) if isinstance(raw_tool_selection, dict) else {}
        )
        legacy_plugin_id = str(
            legacy_tool_selection_config.pop(
                "plugin", _DESKTOP_COMPONENT_DEFAULTS["tool.selection-policy"]
            )
        )
        tool_selection_plugin_id = _stable_component_id(
            "tool.selection-policy",
            settings.component_selections.get(
                "tool.selection-policy", legacy_plugin_id
            ),
        )
        if (
            tool_selection_plugin_id == "sage.tool-selection.llm"
            and not self._auxiliary_json_compatible(judge_provider)
        ):
            tool_selection_plugin_id = "sage.tool-selection.lexical"
        configured_tool_selection = settings.component_configs.get(
            "tool.selection-policy"
        )
        tool_selection_config = _tool_selection_component_config(
            tool_selection_plugin_id,
            configured_tool_selection
            if configured_tool_selection is not None
            else legacy_tool_selection_config,
        )
        run_manifest = desktop_v2_manifest(
            session_root=self.runtime_root,
            component_selections={
                **settings.component_selections,
                "context.token-estimator": estimator_id,
                "context.reducer": reducer_id,
                "context.summarizer": summarizer_plugin_id,
                "agent.continuation-policy": continuation_plugin_id,
                "tool.selection-policy": tool_selection_plugin_id,
                "memory.recall-query": memory_query_plugin_id,
            },
            component_configs=settings.component_configs,
            language=settings.language,
        )
        run_cache_identities = {
            "context.summarizer": {
                "plugin": summarizer_plugin_id,
                "provider": provider.id,
                "model": provider.model,
                "base_url": provider.base_url,
                "credential": SecretStr(provider.api_key or ""),
                "model_binding": "summary",
            },
            "memory.recall-query": {
                "plugin": memory_query_plugin_id,
                "language": settings.language,
                "provider": judge_provider.id,
                "model": judge_provider.model,
                "base_url": judge_provider.base_url,
                "credential": SecretStr(judge_provider.api_key or ""),
            },
            "context.reducer": {
                "plugin": reducer_id,
                "estimator": estimator_id,
                "summarizer": summarizer_plugin_id,
                "summary_store": self.summary_store_plugin_id,
                "provider": provider.id,
                "model": provider.model,
            },
            "tool.selection-policy": {
                "plugin": tool_selection_plugin_id,
                **tool_selection_config,
            },
        }
        ports = await self.application.materialize_agent(
            run_manifest,
            tenant_id=agent.user_id,
            agent_id=agent.agent_id,
            run_id=run_id,
            model=recording_model,
            locked_configs={
                "context.summarizer": {
                    "model": recording_model,
                    "model_binding": "summary",
                },
                "memory.recall-query": (
                    {
                        "model": memory_query_model,
                        "language": settings.language,
                        "timeout_seconds": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                    }
                    if memory_query_plugin_id == "sage.memory.recall-query.llm"
                    else {}
                ),
                "tool.selection-policy": tool_selection_config,
                "agent.continuation-policy": {
                    "repeat_threshold": 3,
                    "model": judge_recording_model,
                    "model_binding": "fast",
                    "timeout_seconds": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                },
                "workspace.initializer": {"language": settings.language},
            },
            cache_identities=run_cache_identities,
        )
        self._last_run_plan = ports.resolved_plan
        owner_handles = _ACTIVE_EXTENSION_SCOPE_HANDLES.get()
        if owner_handles is not None:
            owner_handles.extend(ports.scope_handles)
        memory_query_generator = ports.memory_query_generator
        summarizer = ports.summarizer
        token_estimator = ports.token_estimator
        context_reducer = ports.context_reducer
        tool_selection_policy = ports.tool_selection_policy
        factory = AgentCompositionFactory(
            self.driver_runtime,
            context_components=ContextComponentBundle(
                token_estimator=token_estimator,
                summary_store=self.summary_store,
                summarizer=summarizer,
            ),
        )
        await self._ensure_agent_workspace(
            settings.agent_workspace_path,
            component_selections=settings.component_selections,
            language=settings.language,
        )
        sandbox_plugin_id, sandbox_config = _resolved_sandbox_config(settings)
        workspace_root = _sandbox_workspace_root(sandbox_config, workspace)
        issuer = self._sandbox_grant_issuer
        sandbox_provider = self._sandbox_provider(sandbox_plugin_id)
        capabilities = await sandbox_provider.capabilities()
        architecture = str(
            sandbox_config.get("architecture") or capabilities.architectures[0]
        )
        filesystem_mode = FileSystemMode(str(sandbox_config["filesystem_mode"]))
        if architecture not in capabilities.architectures:
            raise ValueError("sandbox architecture is unsupported by the provider")
        if filesystem_mode not in capabilities.filesystem_modes:
            raise ValueError("sandbox filesystem_mode is unsupported by the provider")
        process_enabled = bool(
            sandbox_config.get("process_enabled", capabilities.process.available)
        )
        # The bundled local-workspace provider reports IsolationLevel.NONE.
        # Plan mode must be genuinely read-only, so do not expose host process
        # execution when no enforceable OS isolation boundary exists.
        if (
            invocation_mode == "plan"
            and capabilities.isolation_level == IsolationLevel.NONE
        ):
            process_enabled = False
        if process_enabled and not capabilities.process.available:
            raise ValueError("sandbox process execution is unsupported by the provider")
        fingerprint_source = json.dumps(
            {
                "plugin_id": sandbox_plugin_id,
                "config": sandbox_config,
                "host_workspace": str(workspace)
                if sandbox_config["workspace_mapping"] == "active_workspace"
                else None,
                "invocation_mode": invocation_mode,
            },
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
        sandbox_metadata: dict[str, Any] = {}
        if sandbox_config["workspace_mapping"] == "active_workspace":
            sandbox_metadata["host_workspace"] = str(workspace)
        sandbox_spec = ResolvedSandboxSpec(
            spec_hash=f"sha256:{fingerprint}",
            workspace_root=workspace_root,
            architecture=architecture,
            filesystem_mode=filesystem_mode,
            filesystem=FileSystemPolicy(
                allowed_operations=(
                    frozenset({FileOperation.READ, FileOperation.LIST})
                    if invocation_mode == "plan"
                    else frozenset(FileOperation)
                ),
                allowed_roots=(workspace_root,),
                max_file_bytes=64 * 1024 * 1024,
                max_total_bytes=4 * 1024 * 1024 * 1024,
            ),
            process=ProcessPolicy(
                enabled=process_enabled,
                read_only=invocation_mode == "plan",
                allowed_executables=(
                    "git",
                    "rg",
                    "python",
                    "python3",
                    "pytest",
                    "flutter",
                    "dart",
                    "npm",
                    "node",
                    "bash",
                    "sh",
                ),
                allowed_env_names=("PATH", "PYTHONPATH"),
                max_wall_time_seconds=300,
                max_output_bytes=4 * 1024 * 1024,
            ),
            network=NetworkPolicy(),
            lifecycle=LifecyclePolicy(
                durability=(
                    SandboxDurability.DURABLE_EXTERNAL
                    if sandbox_config["workspace_mapping"] == "active_workspace"
                    else SandboxDurability.SNAPSHOTABLE
                ),
                safe_pause_behavior=(
                    SandboxReleaseDisposition.TERMINATE
                    if sandbox_config["workspace_mapping"] == "active_workspace"
                    else SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE
                ),
                unsafe_pause_behavior=SandboxReleaseDisposition.DETACH,
            ),
            policy_hash=f"sha256:{fingerprint}",
            metadata=sandbox_metadata,
        )
        sandbox_context = self._context(agent.user_id, language=settings.language)
        lifecycle_run_exists = False
        if run_id is not None and resolved_spec_hash is not None:
            try:
                await self.driver_session_store.get_run(run_id)
                lifecycle_run_exists = True
            except SageV2Error as exc:
                if exc.info.code not in {"run.not_found", "run_id.not_found"}:
                    raise
        if lifecycle_run_exists:
            acquisition = ExecutionBindingLifecycleCoordinator(
                sandbox_provider=sandbox_provider,
                session_store=self.driver_session_store,
                job_runtime=None,
            )
            sandbox_handle = await acquisition.acquire(
                run_id=run_id,
                spec=sandbox_spec,
                run_resolved_spec_hash=resolved_spec_hash,
                context=sandbox_context,
            )
        else:
            sandbox_handle = await sandbox_provider.provision(
                sandbox_spec,
                sandbox_context,
                run_id=run_id or new_id("desktop_sandbox"),
            )
        sandbox_observer(sandbox_handle)
        skill_workspace = (
            LocalSkillWorkspace(workspace, workspace_root=workspace_root)
            if sandbox_config["workspace_mapping"] == "active_workspace"
            else SandboxSkillWorkspace(sandbox_handle, issuer)
        )
        loader = factory.create_skill_loader(
            resolved,
            agent.agent_id,
            catalog=skill_provider,
            source=skill_provider,
            workspace=skill_workspace,
            activations=self.activations,
            workspace_root=workspace_root,
        )
        goal_state_service = GoalStateService(self.driver_session_store)
        official_runtime = OfficialToolRuntime(
            sandbox_handle,
            issuer,
            memory_service=self.memory_service,
            session_memory_service=self.session_memory_service,
            goal_state_service=goal_state_service,
            tool_selection_policy=tool_selection_policy,
        )
        active_scope_handles = _ACTIVE_EXTENSION_SCOPE_HANDLES.get()
        if active_scope_handles is not None:
            active_scope_handles.append(official_runtime)
        official_tools = self._official_tools(official_runtime)
        skill_tool = SkillToolPlugin(loader)
        catalogs = (
            official_tools.catalog,
            skill_tool.catalog,
        )
        executors = (
            official_tools.executor,
            skill_tool.executor,
        )
        if mcp_definitions:
            catalogs = (*catalogs, mcp_plugin)
            executors = (*executors, mcp_plugin)
        native_catalog = CompositeToolCatalog(catalogs)
        native_executor = CompositeToolExecutor(executors)
        mode = AgentMode(str(agent.config.get("agentMode") or "simple").strip().lower())
        root_descriptor = AgentDescriptor(
            agent_id=agent.agent_id,
            name=agent.name,
            description=str(agent.config.get("description") or ""),
            instructions=(
                agent.config.get("systemPrefix") or "You are a helpful Sage agent."
            ),
            mode=mode,
            tools=tuple(
                value
                for value in valid_tools
                if not (
                    continuation_plugin_id == "sage.agent.continuation.llm-judge"
                    and value == "turn_status"
                )
                and not (invocation_mode == "plan" and value in _PLAN_BLOCKED_TOOLS)
            ),
            skills=tuple(valid_skills),
            allow_delegation=not force_leaf,
        )
        member_descriptors: list[AgentDescriptor] = []
        models_by_agent = {agent.agent_id: recording_model}
        judge_models_by_agent = {agent.agent_id: judge_recording_model}
        configured_member_ids = {
            str(value)
            for value in (agent.config.get("availableSubAgentIds") or ())
            if str(value)
        }
        manual_member_roster = (
            mode in {AgentMode.FIBRE, AgentMode.TEAM}
            and str(agent.config.get("subAgentSelectionMode") or "auto_all") == "manual"
        )
        catalog_members = await self.catalog.list_agents(agent.user_id)
        members_by_id = {value.agent_id: value for value in catalog_members}
        for member in catalog_members:
            if member.agent_id == agent.agent_id:
                continue
            if manual_member_roster and member.agent_id not in configured_member_ids:
                continue
            member_tools = tuple(
                value
                for value in (member.config.get("availableTools") or ())
                if isinstance(value, str)
                and value in known_tools
                and not (
                    continuation_plugin_id == "sage.agent.continuation.llm-judge"
                    and value == "turn_status"
                )
                and not (invocation_mode == "plan" and value in _PLAN_BLOCKED_TOOLS)
            )
            member_skills = tuple(
                value
                for value in (member.config.get("availableSkills") or ())
                if isinstance(value, str) and _SKILL_NAME.fullmatch(value)
            )
            member_mode = AgentMode(
                str(member.config.get("agentMode") or "simple").strip().lower()
            )
            member_descriptors.append(
                AgentDescriptor(
                    agent_id=member.agent_id,
                    name=member.name,
                    description=str(member.config.get("description") or ""),
                    instructions=(
                        member.config.get("systemPrefix")
                        or "You are a helpful Sage agent."
                    ),
                    mode=member_mode,
                    tools=member_tools,
                    skills=member_skills,
                    allow_delegation=False,
                )
            )
            member_provider = await self._provider(member, member.user_id)
            models_by_agent[member.agent_id] = RecordingModelProvider(
                await self._model_provider(member_provider, member),
                sink=self.diagnostics,
                session_id_resolver=self._session_id_for_run,
                provider_metadata={
                    "agent_id": member.agent_id,
                    "provider_id": member_provider.id,
                    "protocol": member_provider.protocol,
                    "base_url": member_provider.base_url,
                    "model": member_provider.model,
                },
            )
            member_judge_provider = await self._fast_provider(member, member_provider)
            judge_models_by_agent[member.agent_id] = RecordingModelProvider(
                await self._model_provider(
                    member_judge_provider, member, enable_thinking=False
                ),
                sink=self.diagnostics,
                session_id_resolver=self._session_id_for_run,
                provider_metadata={
                    "agent_id": member.agent_id,
                    "provider_id": member_judge_provider.id,
                    "protocol": member_judge_provider.protocol,
                    "base_url": member_judge_provider.base_url,
                    "model": member_judge_provider.model,
                    "purpose": "task_complete_judge",
                    "model_type": "fast",
                },
            )

        resolved_agent = resolved.agents[agent.agent_id]
        route_id = resolved_agent.model_bindings.get("primary")
        route = resolved.model_routes.get(route_id, {})
        limits = route.get("limits", {})
        request_defaults = route.get("request", {})
        ceiling = resolved.policy_ceilings[agent.agent_id]
        context_limits = [
            value
            for value in (
                limits.get("context_window"),
                ceiling.max_input_tokens,
            )
            if value is not None
        ]
        context_budget = (
            ContextBudget(
                max_input_tokens=min(int(value) for value in context_limits),
                reserve_output_tokens=int(
                    request_defaults.get("max_output_tokens")
                    or limits.get("max_output_tokens")
                    or ceiling.max_output_tokens
                    or 0
                ),
            )
            if context_limits
            else None
        )

        if mode == AgentMode.FIBRE and session_id:
            try:
                dynamic_members = await self.dynamic_agent_roster.load(session_id)
            except SageV2Error as exc:
                if exc.info.code != "session.not_found":
                    raise
                # Desktop allocates a stable Session ID before the first Run so
                # attachments and UI state can already be scoped to it. The
                # authoritative Session is created by start_run after loop
                # composition, therefore a brand-new Fibre has no durable
                # dynamic roster to restore yet.
                dynamic_members = ()
            existing_ids = {value.agent_id for value in member_descriptors}
            member_descriptors.extend(
                value for value in dynamic_members if value.agent_id not in existing_ids
            )
        if invocation_mode == "plan":
            member_descriptors = [
                value.model_copy(
                    update={
                        "tools": tuple(
                            tool
                            for tool in value.tools
                            if tool not in _PLAN_BLOCKED_TOOLS
                        )
                    }
                )
                for value in member_descriptors
            ]

        member_registry = AgentRegistry(tuple(member_descriptors))

        async def compose_mode_loop(descriptor, run_id, catalog, executor):
            context_providers = (
                RunMetadataContextProvider(),
                PlanContextProvider(goal_state_service),
                GoalContextProvider(goal_state_service),
                AgentRosterContextProvider(
                    member_registry,
                    descriptor.mode,
                    allow_delegation=descriptor.allow_delegation,
                ),
                AvailableSkillsContextProvider(loader.catalog),
                ActiveSkillsContextProvider(loader),
                PreferredSkillsContextProvider(),
            )
            if descriptor.agent_id == agent.agent_id:
                base_continuation_policy = ports.continuation_policy
            else:
                member_ports = await self.application.materialize_agent(
                    run_manifest,
                    tenant_id=agent.user_id,
                    agent_id=descriptor.agent_id,
                    run_id=run_id,
                    model=judge_models_by_agent.get(
                        descriptor.agent_id, judge_recording_model
                    ),
                    locked_configs={
                        "agent.continuation-policy": {
                            "repeat_threshold": 3,
                            "model": judge_models_by_agent.get(
                                descriptor.agent_id, judge_recording_model
                            ),
                            "model_binding": "fast",
                        }
                    },
                    cache_identities=run_cache_identities,
                )
                owner = _ACTIVE_EXTENSION_SCOPE_HANDLES.get()
                if owner is not None:
                    owner.extend(member_ports.scope_handles)
                base_continuation_policy = member_ports.continuation_policy
            continuation_policy = base_continuation_policy
            owns_invocation = descriptor.agent_id == agent.agent_id
            if invocation_mode == "plan" and owns_invocation:
                continuation_policy = PlanCompletionGatePolicy(
                    continuation_policy,
                    goal_state_service,
                )
            elif invocation_mode == "goal" and owns_invocation:
                continuation_policy = GoalCompletionGatePolicy(
                    continuation_policy,
                    goal_state_service,
                )
            return factory.create_engine(
                model=models_by_agent.get(descriptor.agent_id, recording_model),
                tool_catalog=catalog,
                tool_executor=executor,
                tool_policy=DefaultToolPolicy(
                    approval_strategy=ApprovalStrategy(approval_mode),
                    operation_assessor=ShellCommandOperationAssessor(
                        agent.config.get("commandPolicy"),
                        agent.config.get("approvedShellCommands") or (),
                    ),
                    operation_assessor_id="v2-desktop-shell-policy",
                ),
                tool_selection_policy=tool_selection_policy,
                tool_selection_model=tool_selection_model,
                continuation_policy=continuation_policy,
                continuation_signal_provider=(
                    official_runtime.consume_continuation_signals
                ),
                automatic_memory_recall=(
                    (
                        self.memory_plugin_id != "sage.memory.noop"
                        or self.session_memory_plugin_id != "sage.session-memory.noop"
                    )
                    and "search_memory" in descriptor.tools
                ),
                memory_recall_limit=8,
                memory_recall_query_generator=memory_query_generator,
                context_assembler=DefaultContextAssembler(
                    developer_instructions=(
                        descriptor.instructions
                        + _continuation_agent_instructions(continuation_plugin_id)
                    ),
                    providers=context_providers,
                    budget=context_budget,
                    reducer=(context_reducer if context_budget is not None else None),
                    estimator=token_estimator,
                    history_reader=self.driver_session_store,
                    projection_observer=self.session_memory_service,
                ),
                expected_resolved_spec_hash=current_resolved_spec_hash,
            )

        async def compose_child_loop(descriptor, child_run_id, child_context):
            del child_context
            member = members_by_id.get(descriptor.agent_id)
            if member is None:
                member_config = {
                    **agent.config,
                    "description": descriptor.description,
                    "systemPrefix": descriptor.instructions,
                    "agentMode": descriptor.mode.value,
                    "availableTools": list(descriptor.tools),
                    "availableSkills": list(descriptor.skills),
                }
                member = agent.model_copy(
                    update={
                        "agent_id": descriptor.agent_id,
                        "name": descriptor.name,
                        "config": member_config,
                    }
                )
            child_run = await self.runtime.get_run(child_run_id)
            child_command = await self.session_store.get_start_command(child_run_id)
            member_provider = await self._provider_for_command(
                child_command, member, member.user_id
            )
            _, child_loop, child_sandbox = await self._build_loop(
                agent=member,
                provider=member_provider,
                workspace=workspace,
                preferred_skills=(),
                approval_mode=approval_mode,
                invocation_mode="normal",
                session_id=child_run.session_id,
                run_id=child_run_id,
                resolved_spec_hash=child_command.resolved_spec_hash,
                component_snapshot=child_command.config.metadata.get(
                    "runtime_components"
                ),
                force_leaf=descriptor.mode != AgentMode.TEAM,
            )
            return child_loop, child_sandbox

        mode_factory = ModeAwareAgentLoopFactory(
            runtime=self.driver_runtime,
            model_factory=lambda descriptor, run_id: models_by_agent.get(
                descriptor.agent_id, recording_model
            ),
            base_catalog=native_catalog,
            base_executor=native_executor,
            registry=member_registry,
            resolved_spec_hash=current_resolved_spec_hash,
            max_delegation_concurrency=4,
            delegation_concurrency_limiter=self.delegation_limiter,
            loop_composer=compose_mode_loop,
            workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
            fallback_invocation_mode=invocation_mode,
            child_loop_factory=compose_child_loop,
        )
        loop = await mode_factory.create_loop_async(
            root_descriptor, run_id or "pending"
        )
        return (
            resolved,
            loop,
            sandbox_handle,
            sandbox_provider,
            sandbox_spec,
            official_runtime.job_runtime,
        )

    def _sandbox_provider(self, plugin_id: str):
        cached = self._sandbox_providers.get(plugin_id)
        if cached is not None:
            return cached
        verification_key = self._sandbox_grant_issuer.verification_key
        if plugin_id == LocalWorkspaceSandboxProvider.plugin_id:
            provider = LocalWorkspaceSandboxProvider(verification_key)
        elif plugin_id == InMemorySandboxProvider.plugin_id:
            provider = InMemorySandboxProvider(verification_key)
        else:
            raise ValueError(f"unsupported sandbox plugin {plugin_id!r}")
        self._sandbox_providers[plugin_id] = provider
        return provider

    async def _session_id_for_run(self, run_id: str) -> str:
        return (await self.session_store.get_run(run_id)).session_id

    def _manifest(self, agent, provider, tools, skills):
        max_steps = max(1, min(int(agent.config.get("maxLoopCount") or 24), 200))
        deep_thinking, thinking_level = self._thinking_config(agent)
        compatibility_profile = self._verified_model_compatibility_profile(provider)
        plugin_profile = (
            compatibility_profile.plugin_profile
            if compatibility_profile is not None
            else None
        )
        legacy_profile = compatibility_profile if plugin_profile is None else None
        effective_max_output_tokens = self._effective_model_output_tokens(
            provider, compatibility_profile
        )
        reasoning_effort = self._effective_reasoning_effort(
            compatibility_profile,
            enabled=deep_thinking,
            requested=thinking_level,
            legacy=thinking_level if deep_thinking else None,
        )
        request_extra: dict[str, Any] = {}
        if (
            provider.protocol == "openai-chat-completions"
            and legacy_profile is not None
        ):
            request_extra["max_output_tokens_field"] = (
                legacy_profile.max_output_tokens_field
            )
        if legacy_profile is not None and not deep_thinking:
            request_extra.update(
                self._reasoning_disable_extra(legacy_profile.reasoning_disable_strategy)
            )
        elif legacy_profile is not None:
            request_extra.update(
                self._reasoning_effort_extra(
                    legacy_profile,
                    enabled=deep_thinking,
                    requested=thinking_level,
                )
            )
        memory_enabled = (
            self.memory_plugin_id != "sage.memory.noop" and "search_memory" in tools
        )
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=effective_max_output_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=request_extra,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=effective_max_output_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=provider.supports_tool_calling,
                reasoning=True,
                parallel_tool_calls=provider.supports_tool_calling,
            ),
            capability_profile=plugin_profile,
        )
        return SageManifest(
            kind="agent-package",
            metadata=ManifestMetadata(
                id=f"desktop.{agent.agent_id}",
                version="0.1.0",
                name=agent.name,
                description=agent.config.get("description"),
            ),
            credentials={
                "desktop_model": CredentialDeclaration(
                    source="host", ref=f"llm-provider:{provider.id}"
                )
            },
            models={"primary": route},
            policies=PolicyConfig(budgets={"max_steps": max_steps}),
            agents={
                agent.agent_id: AgentDefinition(
                    name=agent.name,
                    instructions=Instructions(
                        inline=agent.config.get("systemPrefix")
                        or "You are a helpful Sage agent."
                    ),
                    models={"primary": "primary"},
                    tools=tools if provider.supports_tool_calling else (),
                    skills=skills,
                    budgets=AgentBudgets(max_steps=max_steps),
                    memory=AgentMemoryBehavior(
                        recall=memory_enabled,
                        auto_write=memory_enabled,
                        scope="agent",
                    ),
                )
            },
            entrypoint=ApplicationEntrypoint(agent=agent.agent_id),
        )

    async def _model_provider(
        self, provider, agent, *, enable_thinking: bool | None = None
    ):
        deep_thinking, thinking_level = self._thinking_config(agent)
        if enable_thinking is not None:
            deep_thinking = enable_thinking
        request_extra: dict[str, Any] = {}
        compatibility_profile = self._verified_model_compatibility_profile(provider)
        plugin_profile = (
            compatibility_profile.plugin_profile
            if compatibility_profile is not None
            else None
        )
        legacy_profile = compatibility_profile if plugin_profile is None else None
        effective_max_output_tokens = self._effective_model_output_tokens(
            provider, compatibility_profile
        )
        reasoning_effort = self._effective_reasoning_effort(
            compatibility_profile,
            enabled=deep_thinking,
            requested=thinking_level,
            legacy=thinking_level if deep_thinking else None,
        )
        if provider.protocol == "openai-chat-completions":
            if legacy_profile is not None:
                request_extra["max_output_tokens_field"] = (
                    legacy_profile.max_output_tokens_field
                )
                if not deep_thinking:
                    request_extra.update(
                        self._reasoning_disable_extra(
                            legacy_profile.reasoning_disable_strategy
                        )
                    )
                else:
                    request_extra.update(
                        self._reasoning_effort_extra(
                            legacy_profile,
                            enabled=True,
                            requested=thinking_level,
                        )
                    )
            elif enable_thinking is not None:
                request_extra["reasoning_parameter_fallback"] = enable_thinking is False
                # There is no portable "thinking disabled" field. In
                # particular, minimal is still reasoning and some compatible
                # gateways reject reasoning_effort entirely. Auxiliary
                # requests therefore use provider defaults for OpenAI
                # reasoning models; vendor-specific disable controls remain for
                # protocols where Sage has an explicit mapping.
                if enable_thinking or not is_openai_reasoning_model(provider.model):
                    request_extra.update(
                        build_llm_extra_body(
                            provider.model,
                            base_url=provider.base_url,
                            enable_thinking=enable_thinking,
                            thinking_level=(
                                thinking_level if enable_thinking else None
                            ),
                            default_off="minimal",
                        )
                    )
        elif provider.protocol == "openai-responses":
            if legacy_profile is not None and not deep_thinking:
                request_extra.update(
                    self._reasoning_disable_extra(
                        legacy_profile.reasoning_disable_strategy
                    )
                )
            elif legacy_profile is not None:
                request_extra.update(
                    self._reasoning_effort_extra(
                        legacy_profile,
                        enabled=True,
                        requested=thinking_level,
                    )
                )
            elif enable_thinking is not None:
                request_extra["reasoning_parameter_fallback"] = enable_thinking is False
        elif legacy_profile is not None and not deep_thinking:
            request_extra.update(
                self._reasoning_disable_extra(legacy_profile.reasoning_disable_strategy)
            )
        elif legacy_profile is not None:
            request_extra.update(
                self._reasoning_effort_extra(
                    legacy_profile,
                    enabled=True,
                    requested=thinking_level,
                )
            )
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=effective_max_output_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=request_extra,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=effective_max_output_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=provider.supports_tool_calling,
                reasoning=True,
                parallel_tool_calls=provider.supports_tool_calling,
            ),
            capability_profile=plugin_profile,
        )
        cache_key = (
            provider.id,
            agent.agent_id,
            bool(deep_thinking),
            json.dumps(route.model_dump(mode="json"), sort_keys=True),
            json.dumps(
                plugin_profile.model_dump(mode="json") if plugin_profile else None,
                sort_keys=True,
            ),
            hashlib.sha256((provider.api_key or "").encode()).hexdigest(),
        )
        cached = self._host_model_providers.get(cache_key)
        if cached is not None:
            return cached
        model = create_registered_model_provider(
            route,
            CredentialMaterial(
                credential_id=f"llm-provider:{provider.id}",
                secret=SecretStr(provider.api_key or ""),
                source="desktop-catalog",
            ),
            provider_instance_id=provider.id,
            capability_profile=plugin_profile,
        )
        self._host_model_providers[cache_key] = model
        return model

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

    @staticmethod
    def _effective_model_output_tokens(
        provider: DesktopModelProviderRecord,
        profile: DesktopModelCompatibilityProfile | None,
    ) -> int:
        if profile is not None and profile.effective_max_output_tokens is not None:
            return profile.effective_max_output_tokens
        return provider.max_tokens

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

    @staticmethod
    def _effective_reasoning_effort(
        profile: DesktopModelCompatibilityProfile | None,
        *,
        enabled: bool,
        requested: str,
        legacy: str | None,
    ) -> str | None:
        if not enabled:
            return None
        if profile is None:
            return legacy
        if profile.schema_version < 2:
            return None
        if profile.reasoning_effort_strategy != "reasoning_effort":
            return None
        if requested in profile.supported_reasoning_efforts:
            return requested
        return None

    @staticmethod
    def _reasoning_disable_extra(strategy: str) -> dict[str, Any]:
        return dict(_REASONING_DISABLE_EXTRAS.get(strategy, {}))

    @staticmethod
    def _reasoning_effort_extra(
        profile: DesktopModelCompatibilityProfile,
        *,
        enabled: bool,
        requested: str,
    ) -> dict[str, Any]:
        if (
            enabled
            and profile.schema_version >= 2
            and profile.reasoning_effort_strategy == "chat_template_reasoning_effort"
            and requested in profile.supported_reasoning_efforts
        ):
            return {
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": requested,
                }
            }
        return {}

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

    @staticmethod
    def _thinking_config(agent) -> tuple[bool, str]:
        enabled = bool(
            agent.config.get("deepThinking", agent.config.get("deep_thinking", False))
        )
        level = str(
            agent.config.get("thinkingLevel")
            or agent.config.get("thinking_level")
            or "medium"
        ).lower()
        if level not in {"minimal", "low", "medium", "high", "xhigh", "max"}:
            level = "medium"
        return enabled, level

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
    ):
        settings = self._read_settings_sync()
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
        if response_language == "system":
            response_language = "zh"
        response_language = normalize_language(response_language)
        metadata = {
            "workspace_id": request.workspace_id,
            "preferred_skills": request.preferred_skills,
            "approval_mode": request.approval_mode,
            "invocation_mode": request.invocation_mode,
            "response_language": response_language,
            "system_context": configured_context,
            "current_time": current_time,
            "identity_documents": self._identity_documents(
                self._agent_workspace_path(settings.agent_workspace_path)
            ),
            "runtime_components": {
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
        run_config = CompositionResolver().resolve_run_config(
            resolved,
            request.agent_id,
            metadata=metadata,
        )
        invocation_grants = {
            "plan": ("goal_submit",),
            "goal": ("goal_submit", "goal_complete"),
        }.get(request.invocation_mode, ())
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
        for name in ("AGENT", "IDENTITY", "SOUL", "USER", "MEMORY"):
            path = workspace / f"{name}.md"
            if not path.is_file() or path.is_symlink():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if content.strip():
                values[name] = content[:200_000]
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
            return await self._agent(command.agent_id, user_id)
        values = dict(raw_snapshot)
        if values.get("agent_id") != command.agent_id:
            raise ValueError("Run Agent snapshot does not match the StartRun agent")
        current = await self.catalog.get_agent(command.agent_id, user_id)
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
