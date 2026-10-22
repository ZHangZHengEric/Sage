"""Factories that compose a resolved Agent from injected capability ports."""

from __future__ import annotations

from typing import Any

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.observed import ObservedRunDriver
from sagents.v2.agent.step_request import AgentStepRequestBuilder
from sagents.v2.agent.policy.plugins.continuation import CompositeContinuationPolicy
from sagents.v2.agent.policy.continuation import ContinuationPolicy, ContinuationSignalProvider
from sagents.v2.agent.policy.approval_memory import ApprovalMemory
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.context.assembler import ContextAssembler, DefaultContextAssembler
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.context.contracts import ContextBudget, ContextSegmentProvider
from sagents.v2.context.runtime_metadata import RunMetadataContextProvider
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.goal import (
    GoalCompletionGatePolicy,
    GoalContextProvider,
    GoalStateService,
)
from sagents.v2.memory import MemoryService
from sagents.v2.memory import MemoryRecallQueryGenerator
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.plan import PlanCompletionGatePolicy, PlanContextProvider
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.runtime.artifact.contracts import ArtifactStore
from sagents.v2.session_memory import SessionMemoryService
from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
    FilteredSkillCatalog,
    InvocationGrantSkillCatalog,
    SkillActivationRepository,
    SkillCatalog,
    SkillLoader,
    SkillSource,
    SkillWorkspace,
)
from sagents.v2.tool import (
    InvocationGrantToolCatalog,
    ToolCatalog,
    ToolExecutor,
    ToolSelectionPolicy,
)


from sagents.v2.tool.result_processing import ToolResultProcessor


class AgentCompositionFactory:
    """Turn a resolved manifest into a loop from injected capability ports.

    This is separate from :class:`SAgentBuilder`: the builder selects and owns
    concrete plugins, while this factory only wires already-resolved domain
    ports into an Agent loop. Keeping those responsibilities separate also
    makes custom hosts able to reuse loop composition without plugin discovery.
    """

    def __init__(
        self,
        runtime: RuntimePort,
        *,
        context_components: ContextComponentBundle | None = None,
        tool_result_processor: ToolResultProcessor | None = None,
    ) -> None:
        self.runtime = runtime
        self.context_components = context_components or ContextComponentBundle()
        self.tool_result_processor = tool_result_processor

    def create_skill_loader(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        catalog: SkillCatalog,
        source: SkillSource,
        workspace: SkillWorkspace,
        activations: SkillActivationRepository,
        enabled_skills: tuple[str, ...] | None = None,
        workspace_root: str = "/workspace",
        skill_loading=None,
        runtime_skills=(),
    ) -> SkillLoader:
        """Compose the static Skill ceiling with explicitly admitted attachments."""

        agent = resolved.agents[agent_id]
        ceiling = resolved.policy_ceilings[agent_id]
        selected = tuple(enabled_skills) if enabled_skills is not None else agent.skills
        outside_ceiling = sorted(set(selected) - ceiling.allowed_skills)
        if outside_ceiling:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="manifest.skill_override_denied",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"skills exceed agent policy ceiling: {outside_ceiling}",
                )
            )

        async def inherited_skills(run_id: str) -> tuple[str, ...]:
            from sagents.v2.context.session_history import SessionHistoryLedgerBuilder

            command = await self.runtime.session_store.get_start_command(run_id)
            messages = await SessionHistoryLedgerBuilder(
                self.runtime.session_store
            ).build(command, run_id=run_id)
            # SkillLoadTool emits these metadata fields only after a successful
            # load. A call alone (failed, denied, or unfinished) is not activation.
            successful_loads = {
                (
                    message.metadata.get("source_run_id"),
                    message.tool_call_id,
                ): message.metadata["skill_name"]
                for message in messages
                if message.role == "tool"
                and message.metadata.get("skill_name")
                and message.metadata.get("content_hash")
            }
            names: list[str] = []
            for message in reversed(messages):
                for call in reversed(message.tool_calls):
                    if call.name != "load_skill":
                        continue
                    name = call.arguments.get("skill_name")
                    if (
                        successful_loads.get(
                            (message.metadata.get("source_run_id"), call.tool_call_id)
                        )
                        != name
                    ):
                        continue
                    if isinstance(name, str) and name and name not in names:
                        names.append(name)
            return tuple(names)

        if skill_loading is None:
            from sagents.v2.skill.plugins.loading import SkillLoadingPlugin

            selections = resolved.runtime.selections("skill.loading")
            if len(selections) > 1:
                raise ValueError("skill.loading requires a single provider")
            selection = selections[0] if selections else None
            if (
                selection is not None
                and selection.plugin != SkillLoadingPlugin.plugin_id
            ):
                raise ValueError("custom skill.loading provider must be injected")
            config = next(
                (
                    dict(p.config)
                    for p in resolved.plugins
                    if p.id == SkillLoadingPlugin.plugin_id
                ),
                {},
            )
            if selection is not None:
                config.update(selection.config)
            skill_loading = SkillLoadingPlugin(**config)

        filtered_catalog = InvocationGrantSkillCatalog(
            FilteredSkillCatalog(catalog, selected),
            self.runtime.session_store.get_start_command,
        )
        if runtime_skills:
            from sagents.v2.skill.runtime import RuntimeSkillProvider
            source = RuntimeSkillProvider(filtered_catalog, source, catalog, runtime_skills)
            filtered_catalog = source
        return skill_loading.create_loader(
            catalog=filtered_catalog,
            source=source,
            workspace=workspace,
            activations=activations,
            workspace_root=workspace_root,
            inherited_skills=inherited_skills,
        )

    def create_engine(
        self,
        *,
        model: ModelProvider,
        tool_catalog: ToolCatalog,
        tool_executor: ToolExecutor,
        context_assembler: ContextAssembler,
        tool_result_runtime=None,
        tool_policy: DefaultToolPolicy | None = None,
        approval_memory: ApprovalMemory | None = None,
        continuation_policy: ContinuationPolicy | None = None,
        continuation_signal_provider: ContinuationSignalProvider | None = None,
        tool_selection_policy: ToolSelectionPolicy | None = None,
        tool_selection_model: ModelProvider | None = None,
        step_request_builder: AgentStepRequestBuilder | None = None,
        automatic_memory_recall: bool = False,
        memory_recall_limit: int = 5,
        memory_recall_query_generator: MemoryRecallQueryGenerator | None = None,
        expected_resolved_spec_hash: str | None = None,
        self_configuration=None,
        skill_loader=None,
        preload_skills: tuple[str, ...] = (),
        trace_sink=None,
        log_sink=None,
    ) -> AgentLoopEngine:
        """Build the pure Loop, adding the host observability adapter when selected."""

        engine_type = (
            ObservedRunDriver
            if trace_sink is not None or log_sink is not None
            else AgentLoopEngine
        )
        observation: dict[str, Any] = ({"trace_sink": trace_sink, "log_sink": log_sink}
            if engine_type is ObservedRunDriver else {})
        return engine_type(
            runtime=self.runtime,
            model=model,
            tool_catalog=tool_catalog,
            tool_executor=tool_executor,
            tool_result_processor=self.tool_result_processor,
            tool_result_runtime=tool_result_runtime,
            tool_policy=tool_policy,
            approval_memory=approval_memory,
            continuation_policy=continuation_policy,
            continuation_signal_provider=continuation_signal_provider,
            tool_selection_policy=tool_selection_policy,
            tool_selection_model=tool_selection_model,
            step_request_builder=step_request_builder,
            automatic_memory_recall=automatic_memory_recall,
            memory_recall_limit=memory_recall_limit,
            memory_recall_query_generator=memory_recall_query_generator,
            context_assembler=context_assembler,
            expected_resolved_spec_hash=expected_resolved_spec_hash,
            self_configuration=self_configuration,
            skill_loader=skill_loader,
            preload_skills=preload_skills,
            **observation,
        )

    def create_context(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        providers: tuple[ContextSegmentProvider, ...] = (),
        developer_instructions: str | None = None,
        session_memory_service: SessionMemoryService | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> DefaultContextAssembler:
        """Compose history and context under the selected Agent's budget.

        Providers are used in exactly the supplied order. Custom hosts own
        their prompt and completion policies; the factory owns budget defaults,
        reduction and the authoritative history reader. Pass the root Agent ID
        when delegated loops must share the root's context budget.
        """
        agent = resolved.agents[agent_id]
        ceiling = resolved.policy_ceilings[agent_id]
        route_id = agent.model_bindings.get("primary")
        route = resolved.model_routes.get(route_id, {}) if route_id is not None else {}
        limits = route.get("limits", {})
        request_defaults = route.get("request", {})
        candidates = [
            value
            for value in (
                limits.get("context_window"),
                ceiling.max_input_tokens,
            )
            if value is not None
        ]
        candidates = candidates or [32_768]
        context_budget = ContextBudget(
            max_system_tokens=ceiling.max_system_tokens or 16_384,
            protected_recent_tokens=(
                ceiling.protected_recent_tokens
                if ceiling.protected_recent_tokens is not None
                else 8_192
            ),
            max_input_tokens=min(int(value) for value in candidates),
            reserve_output_tokens=int(
                request_defaults.get("max_output_tokens")
                or limits.get("max_output_tokens")
                or ceiling.max_output_tokens
                or 0
            ),
        )
        return DefaultContextAssembler(
            max_system_tokens=ceiling.max_system_tokens or 16_384,
            developer_instructions=(
                agent.instructions
                if developer_instructions is None
                else developer_instructions
            ),
            providers=providers,
            budget=context_budget,
            reducer=self.context_components.create_reducer(),
            history_reader=self.runtime.session_store,
            projection_observer=session_memory_service,
            artifact_store=artifact_store,
        )

    def create_loop(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        model: ModelProvider,
        tool_catalog: ToolCatalog,
        tool_executor: ToolExecutor,
        tool_policy: DefaultToolPolicy | None = None,
        approval_memory: ApprovalMemory | None = None,
        continuation_policy: ContinuationPolicy | None = None,
        continuation_signal_provider: ContinuationSignalProvider | None = None,
        tool_selection_policy: ToolSelectionPolicy | None = None,
        tool_selection_model: ModelProvider | None = None,
        step_request_builder: AgentStepRequestBuilder | None = None,
        enabled_tools: tuple[str, ...] | None = None,
        skill_loader: SkillLoader | None = None,
        self_configuration=None,
        memory_service: MemoryService | None = None,
        session_memory_service: SessionMemoryService | None = None,
        memory_recall_limit: int = 8,
        memory_recall_query_generator: MemoryRecallQueryGenerator | None = None,
        goal_state_service: GoalStateService | None = None,
        additional_runtime_tools: tuple[str, ...] = (),
        additional_preload_skills: tuple[str, ...] = (),
        granted_catalogs: tuple[ToolCatalog, ...] = (),
        fallback_invocation_mode: str | None = None,
        additional_context_providers: tuple[ContextSegmentProvider, ...] = (),
        context_providers: tuple[ContextSegmentProvider, ...] | None = None,
        developer_instructions: str | None = None,
        context_agent_id: str | None = None,
        completion_gates: tuple[str, ...] = ("goal", "plan"),
        automatic_memory_recall: bool | None = None,
        artifact_store: ArtifactStore | None = None,
        expected_resolved_spec_hash: str | None = None,
        tool_result_runtime=None,
        trace_sink=None,
        log_sink=None,
    ) -> AgentLoopEngine:
        """Compose a loop through the same policy/context boundary for every host.

        Explicit context providers replace the default provider order. Completion
        gates are applied in the supplied order; an empty tuple disables wrapping.
        These host parameters do not alter an already admitted package identity.
        """
        unknown_gates = set(completion_gates) - {"goal", "plan"}
        if unknown_gates:
            raise ValueError(f"unknown completion gates: {sorted(unknown_gates)}")
        if context_providers is not None and additional_context_providers:
            raise ValueError(
                "choose explicit or additional context providers, not both"
            )

        agent = resolved.agents[agent_id]
        ceiling = resolved.policy_ceilings[agent_id]
        selected_tools = (
            tuple(enabled_tools) if enabled_tools is not None else agent.tools
        )
        outside_ceiling = sorted(set(selected_tools) - ceiling.allowed_tools)
        if outside_ceiling:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="manifest.tool_override_denied",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"tools exceed agent policy ceiling: {outside_ceiling}",
                )
            )
        if context_providers is None:
            context_providers = (
                RunMetadataContextProvider(),
                *additional_context_providers,
            )
            if goal_state_service is not None:
                context_providers = (
                    *context_providers,
                    GoalContextProvider(goal_state_service),
                    PlanContextProvider(goal_state_service),
                )
            if skill_loader is not None:
                context_providers = (
                    *context_providers,
                    AvailableSkillsContextProvider(skill_loader.catalog),
                    ActiveSkillsContextProvider(skill_loader),
                )
        if automatic_memory_recall is None:
            automatic_memory_recall = (
                (memory_service is not None or session_memory_service is not None)
                and "search_memory" in selected_tools
                and agent.memory.recall
            )
        selected_continuation_policy = (
            continuation_policy or CompositeContinuationPolicy()
        )
        if goal_state_service is not None:
            gate_types = {
                "goal": GoalCompletionGatePolicy,
                "plan": PlanCompletionGatePolicy,
            }
            for gate in completion_gates:
                selected_continuation_policy = gate_types[gate](
                    selected_continuation_policy,
                    goal_state_service,
                )
        return self.create_engine(
            model=model,
            tool_result_runtime=tool_result_runtime,
            tool_catalog=InvocationGrantToolCatalog(
                tool_catalog,
                selected_tools,
                self.runtime.session_store.get_start_command,
                granted_catalogs=granted_catalogs,
                runtime_tools=additional_runtime_tools,
                fallback_invocation_mode=fallback_invocation_mode,
            ),
            tool_executor=tool_executor,
            self_configuration=self_configuration,
            skill_loader=skill_loader,
            preload_skills=(*agent.preload_skills, *additional_preload_skills),
            tool_policy=(tool_policy or DefaultToolPolicy()).with_approval_config(
                agent.tool_approval
            ),
            approval_memory=approval_memory,
            continuation_policy=selected_continuation_policy,
            continuation_signal_provider=continuation_signal_provider,
            tool_selection_policy=tool_selection_policy,
            tool_selection_model=tool_selection_model,
            step_request_builder=step_request_builder,
            automatic_memory_recall=automatic_memory_recall,
            memory_recall_limit=memory_recall_limit,
            memory_recall_query_generator=memory_recall_query_generator,
            context_assembler=self.create_context(
                resolved,
                context_agent_id or agent_id,
                providers=context_providers,
                developer_instructions=developer_instructions,
                session_memory_service=session_memory_service,
                artifact_store=artifact_store,
            ),
            expected_resolved_spec_hash=expected_resolved_spec_hash
            or resolved.manifest_hash,
            trace_sink=trace_sink,
            log_sink=log_sink,
        )


__all__ = ["AgentCompositionFactory"]
