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

        # Calculate workspace root for sub-session to ensure physical nesting
        # The structure will be: parent_workspace/sub_sessions/{sub_session_id}
        import os
        workspace_root = os.path.join(self.parent_context.session_workspace, "sub_sessions")

        self.sub_session_context = init_session_context(
            session_id=self.session_id,
            user_id=self.parent_context.user_id,
            workspace_root=workspace_root,
            # Inherit configuration from parent
            context_budget_config=context_budget_config, 
            tool_manager=self.parent_context.tool_manager,
            skill_manager=self.parent_context.skill_manager,
        )

        # SHARE AGENT WORKSPACE (SANDBOX) WITH PARENT
        # We want the sub-agent to operate on the same files as the parent
        self.sub_session_context.sandbox = self.parent_context.sandbox
        # Ensure sub-agent uses parent's agent_workspace path directly to avoid nested workspaces
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
        # self.sub_session_context.add_and_update_system_context({"system_prompt": system_prompt})
        
        # 3. Initialize Agent
        # We use SimpleAgent for the logic
        self.agent = SimpleAgent(
            model=self.orchestrator.agent.model,
            model_config=self.orchestrator.agent.model_config,
            system_prefix=system_prompt
        )
        # Update agent name to specific sub-agent name
        self.agent.agent_name = self.agent_name
        
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
            # Ensure FibreTools are properly registered in the sub-agent's tool manager context
            # The parent's tool manager might not have the FibreTools instance registered in the same way
            # or it might be the original one without FibreTools.
            # We need to make sure the sub-agent can call sys_finish_task.
            
            # The tool_manager passed to run_stream is self.sub_session_context.tool_manager
            # which is self.parent_context.tool_manager.
            
            # If parent_context.tool_manager doesn't have FibreTools, we need to add them.
            # But wait, the container agent uses a *combined* tool manager.
            # The parent_context.tool_manager is the *original* one.
            
            # We need to inject FibreTools into the sub-agent's tool manager.
            # We should create a new ToolManager for the sub-agent that includes FibreTools.
            
                # 1. Get FibreTools instance
                # We can create a new one bound to the sub-agent's context?
                # Or use the one from orchestrator?
                # FibreTools needs orchestrator and session_context.
                # If we bind it to sub_session_context, then sys_spawn_agent would spawn sub-sub-agents (which is allowed).
                
                from sagents.fibre.tools import FibreTools
                fibre_tools_impl = FibreTools(self.orchestrator, self.sub_session_context)
                
                # 2. Create combined tool manager
                original_tm = self.sub_session_context.tool_manager
                sub_agent_tm = self.orchestrator._create_combined_tool_manager(original_tm, fibre_tools_impl)
                
                async for chunks in self.agent.run_stream(
                    session_context=self.sub_session_context,
                    tool_manager=sub_agent_tm,
                    session_id=self.session_id
                ):
                    # Ensure chunks have the correct session_id
                    for chunk in chunks:
                        chunk.session_id = self.session_id
                    
                    # Sync to sub-session context immediately
                    if self.sub_session_context:
                        self.sub_session_context.message_manager.add_messages(chunks)

                    yield chunks
            
            # Save session after agent execution
            if self.sub_session_context:
                logger.debug(f"SubAgent {self.agent_name}: Saving session context")
                self.sub_session_context.save()
                logger.info(f"SubAgent {self.agent_name}: Session saved successfully")

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
