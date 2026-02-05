import asyncio
import logging
from typing import List, Dict, Any, Optional, Union, AsyncGenerator
import uuid
import copy

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext, init_session_context
from sagents.context.session_context_manager import session_manager
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.fibre.tools import FibreTools
from sagents.fibre.sub_agent import FibreSubAgent
from sagents.agent.simple_agent import SimpleAgent

logger = logging.getLogger(__name__)

class FibreOrchestrator:
    """
    The Core (FibreOrchestrator)
    
    Manages the lifecycle of sub-agents (Strands), message routing, and resource scheduling.
    """
    
    def __init__(self, agent, observability_manager=None):
        self.agent = agent
        self.observability_manager = observability_manager
        self.sub_sessions: Dict[str, FibreSubAgent] = {}
        self.active_tasks = []
        
    async def run_loop(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        system_context: Optional[Dict[str, Any]] = None,
        context_budget_config: Optional[Dict[str, Any]] = None,
        max_loop_count: int = 10,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        
        # Initialize Main Session Context
        # Note: FibreAgent shares the same workspace root as SAgent
        session_context = init_session_context(
            session_id=session_id,
            user_id=user_id,
            workspace_root=self.agent.workspace,
            context_budget_config=context_budget_config,
            user_memory_manager=self.agent.user_memory_manager,
            tool_manager=tool_manager,
            skill_manager=skill_manager,
        )
        
        with session_manager.session_context(session_id):
            logger.info(f"FibreOrchestrator: Starting session {session_id}")
            
            # 1. Setup Context
            if system_context:
                session_context.add_and_update_system_context(system_context)
            await session_context.init_user_memory_context()
            
            # 2. Inject Fibre System Prompt
            self._inject_fibre_system_prompt(session_context)
            
            # 3. Inject Fibre Tools
            fibre_tools_impl = FibreTools(self, session_context)
            
            # 4. Initialize Core Agent (The Container)
            # In Fibre architecture, the Container itself acts like a SimpleAgent 
            # that can spawn others.
            container_agent = SimpleAgent(
                self.agent.model, 
                self.agent.model_config, 
                system_prefix=self.agent.system_prefix
            )
            if self.observability_manager:
                from sagents.observability import AgentRuntime
                container_agent = AgentRuntime(container_agent, self.observability_manager)

            # 5. Process Initial Messages
            # Ensure messages are in message_manager
            initial_msgs = self._prepare_initial_messages(input_messages)
            for msg in initial_msgs:
                if msg.role != MessageRole.SYSTEM.value: # System prompt handled by context
                     session_context.message_manager.add_messages(msg)

            # 6. Main Execution Loop
            # The Container runs as the primary agent.
            # When it calls sys_spawn_agent, we intercept and manage sub-agents.
            
            # Create a combined tool manager that includes Fibre tools
            combined_tool_manager = self._create_combined_tool_manager(tool_manager, fibre_tools_impl)

            loop_count = 0
            while loop_count < max_loop_count:
                loop_count += 1
                logger.info(f"FibreOrchestrator: Loop {loop_count}")
                
                # A. Run Container Agent
                # We need to run the container agent to get next actions
                # SimpleAgent.run_stream returns a generator of chunks
                
                async for chunks in container_agent.run_stream(
                    session_context=session_context,
                    tool_manager=combined_tool_manager,
                    session_id=session_id
                ):
                    yield chunks
                    
                    # Note: We rely on the tool execution logic within SimpleAgent/AgentRuntime
                    # to execute the tools (including sys_spawn_agent).
                    # Since we passed combined_tool_manager, it should handle it.
                
                # Check if task is finished? 
                last_msg = session_context.message_manager.messages[-1]
                if last_msg.role == MessageRole.ASSISTANT.value and not last_msg.tool_calls:
                    # Assistant spoke without calling tools -> likely finished
                    break
                    
    def _inject_fibre_system_prompt(self, session_context: SessionContext):
        # Add the Mandatory Fibre Prompt to system context or system message
        from sagents.prompts.fibre_agent_prompts import fibre_system_prompt
        
        # Determine language (default to 'en' or use context language)
        lang = session_context.get_language()
        prompt_content = fibre_system_prompt.get(lang, fibre_system_prompt.get("en", ""))
        
        session_context.add_and_update_system_context({"fibre_system_prompt": prompt_content})
        # We also need to ensure this prompt is actually used. 
        # SimpleAgent usually concatenates system_prefix + system_context prompts.
        # Assuming SimpleAgent logic handles "fibre_system_prompt" or generic system context items.
        # If not, we might need to update system_prefix.
        # Let's verify if SimpleAgent uses all system context. 
        # Usually it uses 'system_prompt' key or specific keys.
        # To be safe, let's append to 'system_prompt' if it exists, or set it.
        # But SessionContext structure might vary.
        # Let's just update the system_prefix passed to SimpleAgent in run_loop (Wait, SimpleAgent init takes system_prefix).
        # We can't change SimpleAgent init easily now.
        # But SimpleAgent.run uses session_context to build messages.
        # Let's add it as a specific system message in context if needed.
        pass

    def _prepare_initial_messages(self, input_messages):
        # Helper to convert dicts to MessageChunks
        msgs = []
        if isinstance(input_messages, list):
            for m in input_messages:
                if isinstance(m, dict):
                    msgs.append(MessageChunk(**m))
                else:
                    msgs.append(m)
        return msgs

    def _create_combined_tool_manager(self, original_tm, fibre_tools_impl):
        # Create a new ToolManager or reuse the existing one
        new_tm = original_tm if original_tm else ToolManager(is_auto_discover=False)
        
        # Add Fibre Tools using @tool decorator metadata
        # We need to bind the tool spec to the instance method
        
        # Helper to register bound method
        def register_bound_tool(bound_method):
            if hasattr(bound_method, "_tool_spec"):
                spec = copy.deepcopy(bound_method._tool_spec)
                # Important: update func to be the bound method so 'self' is passed correctly
                spec.func = bound_method
                new_tm.register_tool(spec)
            else:
                logger.warning(f"FibreOrchestrator: {bound_method.__name__} has no _tool_spec")

        register_bound_tool(fibre_tools_impl.sys_spawn_agent)
        register_bound_tool(fibre_tools_impl.sys_send_message)
        register_bound_tool(fibre_tools_impl.sys_finish_task)
        
        return new_tm

    # Methods called by FibreTools
    async def spawn_agent(self, parent_context, name, role, instruction):
        logger.info(f"Spawning agent: {name}")
        # Create Sub Session
        sub_session_id = f"{parent_context.session_id}/{name}"
        
        # Initialize Sub Agent
        sub_agent = FibreSubAgent(
            agent_name=name,
            session_id=sub_session_id,
            parent_context=parent_context,
            instruction=instruction,
            orchestrator=self
        )
        self.sub_sessions[name] = sub_agent
        
        # We just return the name as ID. The agent is lazy-initialized on first message.
        return name

    async def send_message(self, agent_id, content):
        if agent_id in self.sub_sessions:
            return await self.sub_sessions[agent_id].process_message(content)
        return f"Error: Agent {agent_id} not found."
