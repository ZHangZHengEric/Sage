from typing import List, Dict, Any, Optional, Union, AsyncGenerator
import uuid
import time
import traceback
import json

from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext
from sagents.tool import ToolManager, ToolProxy
from sagents.agent.fibre.orchestrator import FibreOrchestrator
from sagents.observability import ObservabilityManager, OpenTelemetryTraceHandler, ObservableAsyncOpenAI
from sagents.agent.agent_base import AgentBase
from sagents.utils.logger import logger

class FibreAgent(AgentBase):
    """
    Fibre Agent Container
    
    Implements the Fibre Agent Architecture (Parallel Implementation).
    Acts as a pipeline controller compatible with SAgent, but delegates
    execution to FibreOrchestrator for dynamic multi-agent orchestration.
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", enable_obs: bool = True):
        super().__init__(model, model_config, system_prefix)
        # self.workspace = workspace
            
        # Observability
        self.observability_manager = None
        if enable_obs:
            otel_handler = OpenTelemetryTraceHandler(service_name="sagents-fibre")
            self.observability_manager = ObservabilityManager(handlers=[otel_handler])
            self.model = ObservableAsyncOpenAI(self.model, self.observability_manager)
            
        # Core Orchestrator
        self.orchestrator = FibreOrchestrator(
            agent=self,
            observability_manager=self.observability_manager
        )
        
        logger.info("FibreAgent initialized")

    async def run_stream(self, session_context: SessionContext) -> AsyncGenerator[List["MessageChunk"], None]:
        if not session_context.tool_manager:
            raise ValueError("ToolManager is not initialized in SessionContext")
        
        session_id = session_context.session_id or str(uuid.uuid4())
        if session_context and isinstance(getattr(session_context, "agent_config", None), dict):
            max_loop_count = session_context.agent_config.get("max_loop_count")
        else:
            max_loop_count = None
        if max_loop_count is None:
            raise ValueError("FibreAgent requires session_context.agent_config.max_loop_count")
        
        if self.observability_manager:
            self.observability_manager.on_chain_start(session_id=session_id, input_data=list(session_context.message_manager.messages))
            
        try:
            _start_time = time.time()
            
            # Delegate to Orchestrator
            async for message_chunks in self.orchestrator.run_loop(
                session_context=session_context,
                max_loop_count=max_loop_count,
            ):
                # Basic filtering similar to SAgent
                if message_chunks:
                     yield message_chunks

            _end_time = time.time()
            _total_ms = int((_end_time - _start_time) * 1000)
            logger.info(f"FibreAgent: Session {session_id} completed in {_total_ms} ms")
            
            if self.observability_manager:
                self.observability_manager.on_chain_end(output_data={"status": "finished"}, session_id=session_id)
                
        except Exception as e:
            if self.observability_manager:
                self.observability_manager.on_chain_error(e, session_id=session_id)
            logger.error(f"FibreAgent: Error in run_stream: {e}\n{traceback.format_exc()}")
            raise e
