"""Factories that compose a resolved Agent from injected capability ports."""

from __future__ import annotations

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.step_request import AgentStepRequestBuilder
from sagents.v2.agent.policy.continuation import (
    CompositeContinuationPolicy,
    ContinuationPolicy,
    ContinuationSignalProvider,
)
from sagents.v2.agent.policy.tool_policy import DefaultToolPolicy
from sagents.v2.context.assembler import DefaultContextAssembler
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
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.plan import PlanCompletionGatePolicy, PlanContextProvider
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.session_memory import SessionMemoryService
from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
    FilteredSkillCatalog,
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
    ) -> None:
        self.runtime = runtime
        self.context_components = context_components or ContextComponentBundle()

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
    ) -> SkillLoader:
        """Create a lazy loader restricted to the Agent's resolved Skill ceiling."""

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
        return SkillLoader(
            catalog=FilteredSkillCatalog(catalog, selected),
            source=source,
            workspace=workspace,
            activations=activations,
            workspace_root=workspace_root,
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
        continuation_policy: ContinuationPolicy | None = None,
        continuation_signal_provider: ContinuationSignalProvider | None = None,
        tool_selection_policy: ToolSelectionPolicy | None = None,
        tool_selection_model: ModelProvider | None = None,
        step_request_builder: AgentStepRequestBuilder | None = None,
        enabled_tools: tuple[str, ...] | None = None,
        skill_loader: SkillLoader | None = None,
        memory_service: MemoryService | None = None,
        session_memory_service: SessionMemoryService | None = None,
        goal_state_service: GoalStateService | None = None,
        additional_runtime_tools: tuple[str, ...] = (),
        additional_context_providers: tuple[ContextSegmentProvider, ...] = (),
    ) -> AgentLoopEngine:
        """Create the standard single-Agent Loop from resolved capabilities."""

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
        route_id = agent.model_bindings.get("primary")
        route = resolved.model_routes.get(route_id, {})
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
        context_budget = None
        if candidates:
            context_budget = ContextBudget(
                max_input_tokens=min(int(value) for value in candidates),
                reserve_output_tokens=int(
                    request_defaults.get("max_output_tokens")
                    or limits.get("max_output_tokens")
                    or ceiling.max_output_tokens
                    or 0
                ),
            )
        context_providers: tuple[ContextSegmentProvider, ...] = (
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
        automatic_memory_recall = (
            memory_service is not None and "search_memory" in selected_tools
        )
        selected_continuation_policy = (
            continuation_policy or CompositeContinuationPolicy()
        )
        if goal_state_service is not None:
            selected_continuation_policy = GoalCompletionGatePolicy(
                selected_continuation_policy,
                goal_state_service,
            )
            selected_continuation_policy = PlanCompletionGatePolicy(
                selected_continuation_policy,
                goal_state_service,
            )
        return AgentLoopEngine(
            runtime=self.runtime,
            model=model,
            tool_catalog=InvocationGrantToolCatalog(
                tool_catalog,
                (*selected_tools, *additional_runtime_tools),
                self.runtime.session_store.get_start_command,
            ),
            tool_executor=tool_executor,
            tool_policy=tool_policy,
            continuation_policy=selected_continuation_policy,
            continuation_signal_provider=continuation_signal_provider,
            tool_selection_policy=tool_selection_policy,
            tool_selection_model=tool_selection_model,
            step_request_builder=step_request_builder,
            automatic_memory_recall=automatic_memory_recall,
            context_assembler=DefaultContextAssembler(
                developer_instructions=agent.instructions,
                providers=context_providers,
                budget=context_budget,
                reducer=(
                    self.context_components.create_reducer()
                    if context_budget is not None
                    else None
                ),
                estimator=self.context_components.token_estimator,
                history_reader=self.runtime.session_store,
                projection_observer=session_memory_service,
            ),
        )


__all__ = ["AgentCompositionFactory"]
