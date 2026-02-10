import asyncio
import logging
from typing import List, Dict, Any, Optional, Union, AsyncGenerator
import uuid
import copy

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.prompt_manager import PromptManager
from sagents.context.session_context import SessionContext, init_session_context, SessionStatus
from sagents.context.session_context_manager import session_manager
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.agent.fibre.tools import FibreTools
from sagents.agent.fibre.sub_agent import FibreSubAgent
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
        self.output_queue: Optional[asyncio.Queue] = None

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
        session_context: Optional[SessionContext] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        
        # Initialize Output Queue for merging streams
        self.output_queue = asyncio.Queue()
        
        # Initialize Main Session Context
        # Note: FibreAgent shares the same workspace root as SAgent
        if session_context is None:
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
            
            try:
                session_context.status = SessionStatus.RUNNING

                # 1. Setup Context
                if system_context:
                    session_context.add_and_update_system_context(system_context)
                await session_context.init_user_memory_context()
                
                # 2. Get Fibre System Prompt
                fibre_prompt = self._get_fibre_system_prompt_content(session_context)
                
                # 3. Inject Fibre Tools
                fibre_tools_impl = FibreTools(self, session_context)
                
                # Register Fibre tools to tool_manager if not already there
                # Use register_tools_from_object to correctly register bound methods
                if tool_manager:
                    tool_manager.register_tools_from_object(fibre_tools_impl)
                
                # 4. Initialize Core Agent (The Container)
                # In Fibre architecture, the Container itself acts like a SimpleAgent 
                # that can spawn others.
                # Combine system_prefix with fibre prompt
                combined_system_prefix = f"{self.agent.system_prefix or ''}\n\n{fibre_prompt}"
                
                container_agent = SimpleAgent(
                    self.agent.model, 
                    self.agent.model_config, 
                    system_prefix=combined_system_prefix
                )
                # Ensure container agent has the same name as the main FibreAgent
                container_agent.agent_name = self.agent.agent_name if hasattr(self.agent, 'agent_name') else "FibreAgent"
                
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
                
                if tool_manager:
                    # IMPORTANT: Main Agent (Orchestrator) is NOT allowed to use sys_finish_task
                    # Use ToolProxy to restrict access instead of modifying the tool manager directly
                    all_tools = tool_manager.list_all_tools_name()
                    if 'sys_finish_task' in all_tools:
                        allowed_tools = [t for t in all_tools if t != 'sys_finish_task']
                        tool_manager = ToolProxy(tool_manager, allowed_tools)
                        logger.info("FibreOrchestrator: Using ToolProxy to exclude sys_finish_task for Main Agent")

                # A. Run Container Agent
                # We need to run the container agent to get next actions
                # SimpleAgent.run_stream returns a generator of chunks
                
                # We run the container stream in a background task to allow stream merging
                # We use a sentinel to indicate end of stream
                
                async def run_container_stream():
                    try:
                        # Set max_loop_count in session context config
                        if session_context.agent_config is None:
                            session_context.agent_config = {}
                        session_context.agent_config['maxLoopCount'] = max_loop_count
                        
                        async for chunks in container_agent.run_stream(
                            session_context=session_context,
                            tool_manager=tool_manager,
                            session_id=session_id
                        ):
                            await self.output_queue.put(chunks)
                    except Exception as e:
                        logger.error(f"Error in container stream: {e}", exc_info=True)
                        raise
                    finally:
                            await self.output_queue.put(None) # Sentinel

                # Start the producer task
                producer_task = asyncio.create_task(run_container_stream())
                
                # Consumer Loop
                while True:
                    chunks = await self.output_queue.get()
                    if chunks is None:
                        # End of current run_stream
                        break
                    yield chunks
                
                # Wait for task to finish cleanly
                await producer_task
                
                # Check if interrupted or completed
                if session_context.status != SessionStatus.INTERRUPTED:
                    session_context.status = SessionStatus.COMPLETED

            except asyncio.CancelledError:
                logger.warning(f"FibreOrchestrator: Session {session_id} interrupted (CancelledError)")
                session_context.status = SessionStatus.INTERRUPTED
                raise
            except Exception as e:
                logger.error(f"FibreOrchestrator: Session {session_id} failed: {e}", exc_info=True)
                session_context.status = SessionStatus.ERROR
                raise
            finally:
                logger.info(f"FibreOrchestrator: Saving session context for {session_id}")
                try:
                    session_context.save()
                except Exception as e:
                    logger.error(f"FibreOrchestrator: Failed to save session context: {e}", exc_info=True)
                    
    def _get_fibre_system_prompt_content(self, session_context: SessionContext) -> str:
        # Get the Mandatory Fibre Prompt
        
        # Determine language (default to 'en' or use context language)
        lang = session_context.get_language()
        
        # Load prompt parts
        pm = PromptManager()
        
        # 1. Base Description (Sage Persona)
        # Check if system_prompt is already provided in session context (from agent config)
        base_desc = None
        if session_context.agent_config:
            base_desc = session_context.agent_config.get("systemPrefix")
            
        if not base_desc:
            base_desc = pm.get_prompt('fibre_agent_description', agent='FibreAgent', language=lang)
        
        # 2. System Mechanics (Shared)
        system_mechanics = pm.get_prompt('fibre_system_prompt', agent='FibreAgent', language=lang)
        
        # 3. Main Agent Specifics (Orchestrator Role)
        main_agent_rules = pm.get_prompt('main_agent_extra_prompt', agent='FibreAgent', language=lang)
        
        # Combine
        return f"{base_desc}\n\n{system_mechanics}\n\n{main_agent_rules}"

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

    # Methods called by FibreTools
    async def spawn_agent(self, parent_context, name, role, system_prompt):
        logger.info(f"Spawning agent: {name}")
        # Create Sub Session ID: parent_session_id_{index}_{agent_name}
        # Index is 1-based based on current sub_sessions count
        sub_session_index = len(self.sub_sessions) + 1
        # Use a flat string ID (safe for session_manager keys), path hierarchy is handled by workspace_root in sub_agent.py
        sub_session_id = f"{parent_context.session_id}_{sub_session_index}_{name}"
        
        # Initialize Sub Agent
        sub_agent = FibreSubAgent(
            agent_name=name,
            session_id=sub_session_id,
            parent_context=parent_context,
            system_prompt=system_prompt,
            orchestrator=self
        )
        self.sub_sessions[name] = sub_agent
        
        # Update parent context with available sub-agents
        if 'available_sub_agents' not in parent_context.system_context:
            parent_context.system_context['available_sub_agents'] = []
            
        # Add new agent info if not exists
        agent_info = {"id": name, "role": role}
        if agent_info not in parent_context.system_context['available_sub_agents']:
            parent_context.system_context['available_sub_agents'].append(agent_info)
        
        # We just return the name as ID. The agent is lazy-initialized on first message.
        return name

    async def delegate_tasks(self, tasks):
        """
        Execute multiple tasks in parallel.
        Args:
            tasks: List of dicts with 'agent_id' and 'content'
        """
        import asyncio
        
        async def _run_single_task(task):
            agent_id = task.get('agent_id')
            content = task.get('content')
            if not agent_id or not content:
                return f"Invalid task format: {task}"
            
            return await self.delegate_task(agent_id, content)

        # Run all tasks concurrently
        results = await asyncio.gather(*[_run_single_task(t) for t in tasks])
        
        # Format results
        final_output = []
        for i, result in enumerate(results):
            agent_id = tasks[i].get('agent_id')
            final_output.append(f"=== Result from {agent_id} ===\n{result}")
            
        return "\n\n".join(final_output)

    async def delegate_task(self, agent_id, content):
        if agent_id in self.sub_sessions:
            sub_agent = self.sub_sessions[agent_id]
            task_result = None

            try:
                accumulated_messages = []
                # Temporary buffer to hold chunks until we can merge them properly (although MessageManager.merge expects full messages or chunks to merge into list)
                # Actually, process_message yields List[MessageChunk]. We can just collect them.
                all_filtered_chunks = []
                
                # Stream the response
                async for chunks in sub_agent.process_message(content):
                    # Filter chunks for the current sub-agent session (exclude nested sub-sessions)
                    # We collect all relevant chunks first
                    filtered_chunks = [
                        c for c in chunks 
                        if c.session_id == sub_agent.session_id and c.role == MessageRole.ASSISTANT.value
                    ]
                    if filtered_chunks:
                        all_filtered_chunks.extend(filtered_chunks)

                    # Check for tool calls to sys_finish_task
                    for chunk in chunks:
                        if chunk.tool_calls:
                            for tool_call in chunk.tool_calls:
                                func_name = tool_call.function.name if hasattr(tool_call, 'function') else tool_call.get('function', {}).get('name')
                                if func_name == 'sys_finish_task':
                                    args_str = tool_call.function.arguments if hasattr(tool_call, 'function') else tool_call.get('function', {}).get('arguments')
                                    try:
                                        import json
                                        args = json.loads(args_str)
                                        task_result = f"Task finished: {args.get('status')}. Result: {args.get('result')}"
                                    except Exception as e:
                                        logger.error(f"Error parsing sys_finish_task arguments: {e}")

                    # Push to output queue if available
                    if self.output_queue:
                         await self.output_queue.put(chunks)
                
                # Merge messages after the loop to save processing
                if all_filtered_chunks:
                    accumulated_messages = MessageManager.merge_new_messages_to_old_messages(
                        all_filtered_chunks, []
                    )
            except Exception as e:
                return f"Error executing sub-agent task: {e}"
            
            # If sys_finish_task was called, return its result.
            if task_result:
                return task_result
            
            # If sub-agent finished without calling sys_finish_task, summarize the history
            try:
                history_str = MessageManager.convert_messages_to_str(accumulated_messages)
                if sub_agent.agent and sub_agent.agent.model:
                     # Get prompt from PromptManager
                     language = sub_agent.parent_context.get_language() if sub_agent.parent_context else "en"
                     summary_prompt_template = PromptManager().get_agent_prompt_auto('sub_agent_fallback_summary_prompt', language=language)
                     prompt = summary_prompt_template.format(history_str=history_str)
                     
                     # Use AgentBase's _call_llm_streaming method for consistent logging and handling
                     # We wrap the prompt in a user message
                     messages_input = [{'role': 'user', 'content': prompt}]
                     
                     # We need to access the private method, assuming we are in a trusted context (Orchestrator managing SubAgent)
                     # Or check if there is a public wrapper. SimpleAgent uses _call_llm_streaming internally.
                     # We will use _call_llm_streaming and accumulate the result.
                     response_stream = sub_agent.agent._call_llm_streaming(
                         messages=messages_input,
                         session_id=sub_agent.session_id,
                         step_name="sub_agent_fallback_summary"
                     )
                     
                     summary_content = ""
                     async for chunk in response_stream:
                         if chunk.choices and chunk.choices[0].delta.content:
                             summary_content += chunk.choices[0].delta.content
                             
                     return f"Sub-agent finished without calling 'sys_finish_task'. AI Summary:\n{summary_content}"
            except Exception as e:
                 logger.error(f"Error generating summary: {e}")
                 history_str = MessageManager.convert_messages_to_str(accumulated_messages)
                 return f"Sub-agent finished without calling 'sys_finish_task'. Aggregated response:\n{history_str}"
            finally:
                # Ensure sub-session state is saved
                if sub_agent.sub_session_context:
                    try:
                        sub_agent.sub_session_context.save()
                    except Exception as e:
                        logger.error(f"Failed to save sub-session context for {sub_agent.session_id}: {e}")
            
        return f"Error: Agent {agent_id} not found."
