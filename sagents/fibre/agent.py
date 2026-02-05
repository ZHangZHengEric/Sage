from typing import List, Dict, Any, Optional, Union, AsyncGenerator
import uuid
import time
import traceback
import logging

from sagents.context.messages.message import MessageChunk
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.fibre.orchestrator import FibreOrchestrator
from sagents.context.user_memory import UserMemoryManager
from sagents.observability import ObservabilityManager, OpenTelemetryTraceHandler, ObservableAsyncOpenAI
from sagents.agent.agent_base import AgentBase
from sagents.utils.prompt_manager import PromptManager

logger = logging.getLogger(__name__)

class FibreAgent(AgentBase):
    """
    Fibre Agent Container
    
    Implements the Fibre Agent Architecture (Parallel Implementation).
    Acts as a pipeline controller compatible with SAgent, but delegates
    execution to FibreOrchestrator for dynamic multi-agent orchestration.
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", workspace: str = "/tmp/sage", memory_type: str = "session", enable_obs: bool = True):
        if not system_prefix:
            try:
                system_prefix = PromptManager().get_prompt("fibre_agent_description", agent="FibreAgent", language="zh")
            except Exception as e:
                logger.warning(f"Failed to load default system prefix: {e}")
        
        super().__init__(model, model_config, system_prefix)
        self.workspace = workspace
        
        # User Memory (similar to SAgent)
        if memory_type == "user":
            self.user_memory_manager = UserMemoryManager(model=self.model, workspace=workspace)
        else:
            self.user_memory_manager = None
            
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

    async def run_stream(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        system_context: Optional[Dict[str, Any]] = None,
        context_budget_config: Optional[Dict[str, Any]] = None,
        max_loop_count: int = 10,
        **kwargs
    ) -> AsyncGenerator[List["MessageChunk"], None]:
        
        session_id = session_id or str(uuid.uuid4())
        
        if self.observability_manager:
            self.observability_manager.on_chain_start(session_id=session_id, input_data=input_messages)
            
        try:
            _start_time = time.time()
            
            # Delegate to Orchestrator
            async for message_chunks in self.orchestrator.run_loop(
                input_messages=input_messages,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                session_id=session_id,
                user_id=user_id,
                system_context=system_context,
                context_budget_config=context_budget_config,
                max_loop_count=max_loop_count
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
