import logging
import uuid
import traceback
from typing import Optional, AsyncGenerator, List
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
    
    def __init__(self, agent_name: str, session_id: str, parent_context: SessionContext, system_prompt: str, orchestrator):
        self.agent_name = agent_name
        self.session_id = session_id
        self.parent_context = parent_context
        self.system_prompt = system_prompt
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
        # Reconstruct context_budget_config from parent's manager
        budget_manager = self.parent_context.message_manager.context_budget_manager
        context_budget_config = {
            'max_model_len': budget_manager.max_model_len,
            'history_ratio': budget_manager.history_ratio,
            'active_ratio': budget_manager.active_ratio,
            'max_new_message_ratio': budget_manager.max_new_message_ratio,
            'recent_turns': budget_manager.recent_turns
        }

        self.sub_session_context = init_session_context(
            session_id=self.session_id,
            user_id=self.parent_context.user_id,
            workspace_root=self.parent_context.session_workspace,
            # Inherit configuration from parent
            context_budget_config=context_budget_config, 
            tool_manager=self.parent_context.tool_manager,
            skill_manager=self.parent_context.skill_manager,
        )

        # SHARE AGENT WORKSPACE (SANDBOX) WITH PARENT
        # We want the sub-agent to operate on the same files as the parent
        self.sub_session_context.sandbox = self.parent_context.sandbox
        self.sub_session_context.agent_workspace = self.parent_context.agent_workspace
        self.sub_session_context.file_system = self.parent_context.file_system
        # We also need to ensure the system_context reflects the shared workspace if needed
        # But init_more sets 'file_workspace' to virtual_workspace (/workspace), which is fine.
        
        # 2. Setup System Prompt
        # Inject Fibre System Prompt
        from sagents.prompts.fibre_agent_prompts import fibre_system_prompt, sub_agent_requirement_prompt
        lang = self.sub_session_context.get_language()
        fibre_prompt_content = fibre_system_prompt.get(lang, fibre_system_prompt.get("en", ""))
        sub_agent_req_content = sub_agent_requirement_prompt.get(lang, sub_agent_requirement_prompt.get("en", ""))
        
        # Combine instruction with some base sub-agent prompt
        system_prompt = f"""You are a Sub-Agent named '{self.agent_name}'.
Role: {self.system_prompt}
You are working as part of a larger system.

{fibre_prompt_content}

{sub_agent_req_content}
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

    async def process_message(self, content: str) -> AsyncGenerator[List[MessageChunk], None]:
        """
        Process a message sent from the parent/orchestrator.
        Yields chunks as they are generated.
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
        
        try:
            # 2. Run Agent
            # We need to use session_manager context
            with session_manager.session_context(self.session_id):
                # We need to pass tools. 
                # Use the tool_manager from context (which we inherited from parent)
                
                async for chunks in self.agent.run_stream(
                    session_context=self.sub_session_context,
                    tool_manager=self.sub_session_context.tool_manager,
                    session_id=self.session_id
                ):
                    # Ensure chunks have the correct session_id
                    for chunk in chunks:
                        chunk.session_id = self.session_id
                    yield chunks
                            
        except Exception as e:
            logger.error(f"Error in SubAgent {self.agent_name}: {e}")
            traceback.print_exc()
            # Yield an error chunk
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"Error executing task: {str(e)}",
                message_type="text",
                session_id=self.session_id
            )]
