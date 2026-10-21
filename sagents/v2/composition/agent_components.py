"""Agent capability dependencies, independent of application services and drivers.

The injected opener owns plugin selection and scope registration. This composer
only defines dependency order; it never opens, caches or closes resources itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.agent.policy import CompositeContinuationPolicy
from sagents.v2.agent.policy.continuation import ContinuationPolicy
from sagents.v2.context import (
    PersistentSummaryContextReducer,
    SessionDerivedConversationSummaryStore,
)
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.memory import (
    DirectMemoryRecallQueryGenerator,
    MemoryRecallQueryGenerator,
)
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.skill.plugins.loading import SkillLoadingPlugin
from sagents.v2.tool.plugins.result_file import FileToolResultProcessor


@dataclass(frozen=True)
class AgentComponents:
    factory: AgentCompositionFactory
    context: ContextComponentBundle
    skill_loading: Any
    continuation_policy: ContinuationPolicy
    memory_query_generator: MemoryRecallQueryGenerator

    def services(self) -> dict[str, Any]:
        """Expose the root Agent's providers for readiness and plan inspection."""
        return {
            "context.summary-store": self.context.summary_store,
            "context.summarizer": self.context.summarizer,
            "context.reducer": self.context.reducer,
            "skill.loading": self.skill_loading,
            "agent.continuation-policy": self.continuation_policy,
            "tool.result-processor": self.factory.tool_result_processor,
        }

    @classmethod
    async def compose(
        cls,
        *,
        open_capability: Callable[..., Awaitable[Any]],
        agent_id: str,
        runtime: RuntimePort,
    ) -> AgentComponents:
        summary_store = await open_capability(
            capability="context.summary-store",
            default_plugin=SessionDerivedConversationSummaryStore.plugin_id,
            agent_id=agent_id,
        )
        summarizer = await open_capability(
            capability="context.summarizer",
            default_plugin=ModelConversationSummarizer.plugin_id,
            agent_id=agent_id,
        )
        context_reducer = await open_capability(
            capability="context.reducer",
            default_plugin=PersistentSummaryContextReducer.plugin_id,
            agent_id=agent_id,
        )
        skill_loading = await open_capability(
            capability="skill.loading",
            default_plugin=SkillLoadingPlugin.plugin_id,
            agent_id=agent_id,
        )
        continuation_policy = await open_capability(
            capability="agent.continuation-policy",
            default_plugin=CompositeContinuationPolicy.plugin_id,
            agent_id=agent_id,
        )
        components = ContextComponentBundle(
            summary_store=summary_store,
            summarizer=summarizer,
            reducer=context_reducer,
        )
        result_processor = await open_capability(
            capability="tool.result-processor",
            default_plugin=FileToolResultProcessor.plugin_id,
            agent_id=agent_id,
        )
        factory = AgentCompositionFactory(
            runtime, context_components=components, tool_result_processor=result_processor,
        )
        memory_query_generator = await open_capability(
            capability="memory.recall-query",
            default_plugin=DirectMemoryRecallQueryGenerator.plugin_id,
            agent_id=agent_id,
        )
        return cls(
            factory=factory,
            context=components,
            skill_loading=skill_loading,
            continuation_policy=continuation_policy,
            memory_query_generator=memory_query_generator,
        )
