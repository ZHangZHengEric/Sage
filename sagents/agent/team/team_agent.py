from typing import Any, AsyncGenerator, Dict, List
import time
import traceback
import uuid

from sagents.agent.agent_base import AgentBase
from sagents.agent.team.orchestrator import TeamOrchestrator
from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext
from sagents.observability import (
    ObservableAsyncOpenAI,
    ObservabilityManager,
    OpenTelemetryTraceHandler,
)
from sagents.utils.logger import logger


class TeamAgent(AgentBase):
    """Team mode container.

    Coordinates existing team members in the leader workspace. Unlike Fibre,
    Team mode does not support spawning new agents.
    """

    def __init__(
        self,
        model: Any,
        model_config: Dict[str, Any],
        system_prefix: str = "",
        enable_obs: bool = True,
    ):
        super().__init__(model, model_config, system_prefix)
        self.observability_manager = None
        if enable_obs:
            otel_handler = OpenTelemetryTraceHandler(service_name="sagents-team")
            self.observability_manager = ObservabilityManager(handlers=[otel_handler])
            self.model = ObservableAsyncOpenAI(self.model, self.observability_manager)

        self.orchestrator = TeamOrchestrator(
            agent=self, observability_manager=self.observability_manager
        )
        logger.info("TeamAgent initialized")

    async def run_stream(
        self, session_context: SessionContext
    ) -> AsyncGenerator[List[MessageChunk], None]:
        if not session_context.tool_manager:
            raise ValueError("ToolManager is not initialized in SessionContext")

        session_id = session_context.session_id or str(uuid.uuid4())
        max_loop_count = (
            session_context.agent_config.get("max_loop_count")
            if isinstance(getattr(session_context, "agent_config", None), dict)
            else None
        )
        if max_loop_count is None:
            raise ValueError(
                "TeamAgent requires session_context.agent_config.max_loop_count"
            )

        if self.observability_manager:
            self.observability_manager.on_chain_start(
                session_id=session_id,
                input_data=list(session_context.message_manager.messages),
            )

        try:
            start_time = time.time()
            async for message_chunks in self.orchestrator.run_loop(
                session_context=session_context,
                max_loop_count=max_loop_count,
            ):
                if message_chunks:
                    yield message_chunks

            total_ms = int((time.time() - start_time) * 1000)
            logger.info(f"TeamAgent: Session {session_id} completed in {total_ms} ms")

            if self.observability_manager:
                self.observability_manager.on_chain_end(
                    output_data={"status": "finished"}, session_id=session_id
                )
        except Exception as e:
            if self.observability_manager:
                self.observability_manager.on_chain_error(e, session_id=session_id)
            logger.error(
                f"TeamAgent: Error in run_stream: {e}\n{traceback.format_exc()}"
            )
            raise
