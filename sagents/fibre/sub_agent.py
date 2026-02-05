import logging
import uuid
import traceback
from typing import Optional, Dict, Any, AsyncGenerator, List
from sagents.context.session_context import SessionContext, init_session_context
from sagents.context.session_context_manager import session_manager
from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.tool import ToolManager

logger = logging.getLogger(__name__)

class FibreSubAgent:
    """
    Fibre Sub-Agent (The Strand)
    
    A lightweight wrapper around a SimpleAgent running in its own sub-session.
    """
    
    def __init__(self, agent_name: str, session_id: str, parent_context: SessionContext, instruction: str, orchestrator):
        self.agent_name = agent_name
        self.session_id = session_id
        self.parent_context = parent_context
        self.instruction = instruction
        self.orchestrator = orchestrator
        self.status = "active"
        self.initialized = False
        
        # Sub-agent components
        self.sub_session_context: Optional[SessionContext] = None
        self.agent: Optional[SimpleAgent] = None
        
    async def _initialize_if_needed(self):
        if self.initialized:
            return

        logger.info(f"Initializing SubAgent {self.agent_name} in session {self.session_id}")
        
        # 1. Create Sub-Session Context
        # Inherit workspace_root, user_id, etc. from parent
        # But use a new session_id (which creates a sub-folder structure conceptually)
        self.sub_session_context = init_session_context(
            session_id=self.session_id,
            user_id=self.parent_context.user_id,
            workspace_root=self.parent_context.workspace_root,
            # We might want to inherit budget config
            context_budget_config=None, # For now use default
            # We do NOT share tool_manager directly, or maybe we do?
            # Sub-agents should probably have access to basic tools, but not system tools recursively (unless allowed)
            # For now, let's assume they get the same tools as parent minus FibreTools?
            # Or just pass None and let SimpleAgent handle it?
            tool_manager=None, # Will be passed in run
            skill_manager=None,
        )
        
        # 2. Setup System Prompt
        # Combine instruction with some base sub-agent prompt
        system_prompt = f"""You are a Sub-Agent named '{self.agent_name}'.
Role: {self.instruction}
You are working as part of a larger system.
"""
        self.sub_session_context.add_and_update_system_context({"system_prompt": system_prompt})
        
        # 3. Initialize Agent
        # We use SimpleAgent for the logic
        self.agent = SimpleAgent(
            model=self.orchestrator.agent.model,
            model_config=self.orchestrator.agent.model_config,
            system_prefix=system_prompt
        )
        
        self.initialized = True

    async def process_message(self, content: str) -> str:
        """
        Process a message sent from the parent/orchestrator.
        Returns the final response text.
        """
        await self._initialize_if_needed()
        
        # 1. Add User Message to Sub-Session
        msg = MessageChunk(
            role=MessageRole.USER.value,
            content=content,
            message_type="text",
            session_id=self.session_id
        )
        self.sub_session_context.message_manager.add_messages(msg)
        
        response_text = ""
        
        try:
            # 2. Run Agent
            # We need to use session_manager context
            with session_manager.session_context(self.session_id):
                # We need to pass tools. Let's assume we pass the PARENT's basic tools?
                # For now, pass None or minimal tools.
                # TODO: Pass tools from orchestrator if needed.
                
                async for chunks in self.agent.run_stream(
                    session_context=self.sub_session_context,
                    tool_manager=None, # No tools for sub-agents for now
                    session_id=self.session_id
                ):
                    for chunk in chunks:
                        if chunk.role == MessageRole.ASSISTANT.value and chunk.content:
                            response_text += chunk.content
                            
        except Exception as e:
            logger.error(f"Error in SubAgent {self.agent_name}: {e}")
            traceback.print_exc()
            return f"Error executing task: {str(e)}"
            
        return response_text
