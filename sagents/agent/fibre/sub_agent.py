import logging
import uuid
import traceback
from typing import Optional, AsyncGenerator, List
from sagents.context.session_context import SessionContext, init_session_context
from sagents.context.session_context_manager import session_manager
from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.tool import ToolManager, ToolProxy, get_tool_manager
from sagents.skill import SkillManager, SkillProxy, get_skill_manager
from sagents.utils.prompt_manager import PromptManager

logger = logging.getLogger(__name__)

class FibreSubAgent:
    """
    Fibre Sub-Agent (The Strand)
    
    A lightweight wrapper around a SimpleAgent running in its own sub-session.
    """
    
    def __init__(self, agent_name: str, session_id: str, parent_context: SessionContext, system_prompt: str, orchestrator, 
                 available_tools: Optional[List[str]] = None, available_skills: Optional[List[str]] = None,
                 available_workflows: Optional[List[str]] = None, system_context: Optional[dict] = None):
        self.agent_name = agent_name
        self.session_id = session_id
        self.parent_context = parent_context
        self.system_prompt = system_prompt
        self.orchestrator = orchestrator
        self.status = "active"
        self.initialized = False
        self.available_tools = available_tools
        self.available_skills = available_skills
        self.available_workflows = available_workflows
        self.system_context = system_context
        
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
        

        # 1.0 Apply Tool Restrictions and Register FibreTools
        # We use ToolProxy to manage multiple ToolManagers (Isolated + Global/Parent) with priority.
        # Priority: Isolated ToolManager (FibreTools) > Parent/Global ToolManager

        # 1.1 Create Isolated ToolManager for FibreTools
        # Use isolated=True to create a standalone instance without affecting global state
        from sagents.tool.tool_manager import ToolManager
        from sagents.agent.fibre.tools import FibreTools

        isolated_tm = ToolManager(is_auto_discover=False, isolated=True)
        
        # Register orchestrator in sub_session_context
        self.sub_session_context.orchestrator = self.orchestrator
        
        fibre_tools_impl = FibreTools()
        isolated_tm.register_tools_from_object(fibre_tools_impl)

        # Get list of FibreTools names to ensure they are allowed
        fibre_tool_names = isolated_tm.list_all_tools_name()

        # 1.2 Determine managers and available tools
        managers = [isolated_tm]
        allowed_tools = None

        if self.available_tools:
            # Case A: Explicit restriction requested (Whitelist mode)
            # Use Global ToolManager as base
            base_tm = ToolManager.get_instance()
            managers.append(base_tm)

            # Combine user-allowed tools with FibreTools (system tools)
            # We must explicitly allow FibreTools if filtering is active
            allowed_tools = list(set(self.available_tools) | set(fibre_tool_names))

            logger.info(f"SubAgent {self.agent_name}: Restricted available tools to {self.available_tools} + FibreTools")
        else:
            # Case B: Inherit from parent
            # Use parent's tool manager as base
            parent_tm = self.parent_context.tool_manager
            managers.append(parent_tm)

            # allowed_tools remains None -> Allow all tools from both managers
            # (No need to explicitly list parent tools, ToolProxy handles inheritance)

        # 1.3 Create Composite ToolProxy
        sub_agent_tm = ToolProxy(managers, allowed_tools)

        # Assign to context
        self.sub_session_context.tool_manager = sub_agent_tm

        if self.available_skills:
            # Use global SkillManager singleton as base
            base_sm = SkillManager.get_instance()
            if base_sm:
                self.sub_session_context.skill_manager = SkillProxy(
                    base_sm,
                    self.available_skills
                )
                logger.info(f"SubAgent {self.agent_name}: Restricted available skills to {self.available_skills}")
        
        # 1.2 Inherit system_context from parent
        if self.parent_context.system_context:
             self.sub_session_context.add_and_update_system_context(self.parent_context.system_context)

        # 1.2 Update system_context with sub-agent specific configuration
        if self.system_context:
            self.sub_session_context.add_and_update_system_context(self.system_context)

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
        lang = self.sub_session_context.get_language()
        
        # Get prompts via PromptManager
        pm = PromptManager()
        
        # 1. Base Description (Sage Persona) - REMOVE
        # base_desc = pm.get_prompt('fibre_agent_description', agent='FibreAgent', language=lang)
        
        # 2. System Mechanics (Shared)
        system_mechanics = pm.get_prompt('fibre_system_prompt', agent='FibreAgent', language=lang)
        
        # 3. Sub Agent Specifics (Strand Role)
        sub_agent_rules = pm.get_prompt('sub_agent_extra_prompt', agent='FibreAgent', language=lang)
        
        # Combine instruction with some base sub-agent prompt
        system_prompt = f"""## Sub-Agent Identity
You are a Sub-Agent named '{self.agent_name}', working as part of the Fibre Agent System.

## Specific Role & Task
{self.system_prompt}

{system_mechanics}

{sub_agent_rules}
"""
        # self.sub_session_context.add_and_update_system_context({"system_prompt": system_prompt})

        available_tools = []
        if self.sub_session_context.tool_manager:
            available_tools = self.sub_session_context.tool_manager.list_all_tools_name()

        available_skills = []
        if self.sub_session_context.skill_manager:
            available_skills = self.sub_session_context.skill_manager.list_skills()

        max_loop_count = 10
        if isinstance(self.parent_context.agent_config, dict):
            max_loop_count = self.parent_context.agent_config.get("maxLoopCount", 10)
        
        agent_mode = None
        if isinstance(self.parent_context.agent_config, dict):
            agent_mode = self.parent_context.agent_config.get("agentMode")

        self.sub_session_context.set_agent_config(
            model=self.orchestrator.agent.model,
            model_config=self.orchestrator.agent.model_config,
            system_prefix=system_prompt,
            available_tools=available_tools,
            available_skills=available_skills,
            system_context=self.sub_session_context.system_context,
            available_workflows=self.available_workflows or {},
            agent_mode=agent_mode,
            max_loop_count=max_loop_count,
        )

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
        self.sub_session_context.add_messages(msg)
        
        try:
            # 2. Run Agent
            # We need to use session_manager context
            with session_manager.session_context(self.session_id):
                # Use the tool_manager from context (which we configured in initialization)
                sub_agent_tm = self.sub_session_context.tool_manager
                
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
                        self.sub_session_context.add_messages(chunks)

                    yield chunks
            
            # Save session after agent execution
            # if self.sub_session_context:
            #     logger.debug(f"SubAgent {self.agent_name}: Saving session context")
            #     self.sub_session_context.save()
            #     logger.info(f"SubAgent {self.agent_name}: Session saved successfully")

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
