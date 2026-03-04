"""
New FibreOrchestrator Architecture

Separates Agent Definition from Session Runtime:
- sub_agents: Agent definitions (configuration only)
- sub_session_manager: Running sessions with SubSession interface
"""
import asyncio
import logging
import traceback
from typing import List, Dict, Any, Optional, Union, AsyncGenerator
import uuid
import copy

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.prompt_manager import PromptManager
from sagents.context.session_context import SessionContext, init_session_context, SessionStatus, get_session_context
from sagents.context.session_context_manager import session_manager
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.agent.fibre.tools import FibreTools
from sagents.agent.fibre.agent_definition import AgentDefinition
from sagents.agent.fibre.sub_session import SubSession, SubSessionManager
from sagents.agent.simple_agent import SimpleAgent

logger = logging.getLogger(__name__)


class FibreOrchestrator:
    """
    The Core (FibreOrchestrator)
    
    Architecture:
    - sub_agents: Dict[str, AgentDefinition] - Agent configurations
    - sub_session_manager: SubSessionManager - Running sessions with SubSession interface
    """
    
    def __init__(self, agent, observability_manager=None):
        self.agent = agent
        self.observability_manager = observability_manager
        self.sub_agents: Dict[str, AgentDefinition] = {}  # Agent definitions only
        self.sub_session_manager = SubSessionManager()    # Running sessions
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
        """
        Main orchestration loop.
        
        Similar to the original run_loop but uses the new architecture.
        """
        # Initialize Output Queue for merging streams
        self.output_queue = asyncio.Queue()
        
        # Initialize Main Session Context
        if session_context is None:
            from sagents.context.session_context import init_session_context
            session_context = init_session_context(
                session_id=session_id,
                user_id=user_id,
                workspace_root=session_manager.workspace_root,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                system_context=system_context,
                context_budget_config=context_budget_config
            )
        
        # Register orchestrator in session context
        session_context.orchestrator = self

        # Log tool_manager status for debugging
        logger.info(f"run_loop: session_context.tool_manager={session_context.tool_manager}")
        logger.info(f"run_loop: tool_manager param={tool_manager}")

        # Register main session in sub_session_manager
        main_session = SubSession(
            session_id=session_id,
            agent_id=self.agent.agent_name if hasattr(self.agent, 'agent_name') else "FibreAgent",
            agent_definition=AgentDefinition(
                name=self.agent.agent_name if hasattr(self.agent, 'agent_name') else "FibreAgent",
                system_prompt=self.agent.system_prefix or "",
                description="Main Fibre Agent"
            ),
            parent_session_id=None,
            session_context=session_context,
            model=self.agent.model,
            model_config=self.agent.model_config
        )
        self.sub_session_manager.register(main_session)
        
        # 1.1 Load Custom Agents from Configuration
        custom_sub_agents = getattr(session_context, 'custom_sub_agents', None) or \
                           session_context.agent_config.get("custom_sub_agents") or \
                           session_context.system_context.get("custom_sub_agents")
        if custom_sub_agents and isinstance(custom_sub_agents, list):
            logger.info(f"FibreOrchestrator: Found {len(custom_sub_agents)} custom agents to initialize.")
            for agent_cfg in custom_sub_agents:
                if isinstance(agent_cfg, dict):
                    agent_name = agent_cfg.get("name")
                    agent_system_prompt = agent_cfg.get("system_prompt", "")
                    agent_description = agent_cfg.get("description", "")
                    agent_tools = agent_cfg.get("available_tools")
                    agent_skills = agent_cfg.get("available_skills")
                    agent_workflows = agent_cfg.get("available_workflows")
                    agent_system_context = agent_cfg.get("system_context")
                else:
                    agent_name = getattr(agent_cfg, "name", None)
                    agent_system_prompt = getattr(agent_cfg, "system_prompt", "")
                    agent_description = getattr(agent_cfg, "description", "")
                    agent_tools = getattr(agent_cfg, "available_tools", None)
                    agent_skills = getattr(agent_cfg, "available_skills", None)
                    agent_workflows = getattr(agent_cfg, "available_workflows", None)
                    agent_system_context = getattr(agent_cfg, "system_context", None)
                
                if agent_name:
                    await self.spawn_agent(
                        parent_session_id=session_id,
                        name=agent_name,
                        system_prompt=agent_system_prompt,
                        description=agent_description,
                        available_tools=agent_tools,
                        available_skills=agent_skills,
                        available_workflows=agent_workflows,
                        system_context=agent_system_context
                    )
                    logger.info(f"FibreOrchestrator: Initialized custom sub-agent '{agent_name}'")
        
        # 2. Setup and run main agent loop
        try:
            main_session.update_status("running")
            
            # 2.1 Get Fibre System Prompt for main agent
            fibre_prompt = self._get_fibre_system_prompt_content(
                session_context=session_context,
                is_main_agent=True,
                custom_system_prompt=self.agent.system_prefix or ""
            )
            
            # 2.2 Inject Fibre Tools
            fibre_tools_impl = FibreTools()
            if tool_manager:
                tool_manager.register_tools_from_object(fibre_tools_impl)
            
            # 2.3 Initialize Container Agent
            # Use the complete fibre_prompt which already includes base_desc + system_mechanics + main_agent_rules
            container_agent = SimpleAgent(
                self.agent.model,
                self.agent.model_config,
                system_prefix=fibre_prompt
            )
            container_agent.agent_name = self.agent.agent_name if hasattr(self.agent, 'agent_name') else "FibreAgent"
            
            if self.observability_manager:
                from sagents.observability import AgentRuntime
                container_agent = AgentRuntime(container_agent, self.observability_manager)
            
            # 2.4 Process input messages
            if input_messages:
                for msg in input_messages:
                    if isinstance(msg, dict):
                        from sagents.context.messages.message import MessageChunk
                        msg_chunk = MessageChunk(
                            role=msg.get('role', 'user'),
                            content=msg.get('content', ''),
                            session_id=session_id
                        )
                        session_context.add_messages(msg_chunk)
                    else:
                        session_context.add_messages(msg)
            
            # 2.5 Run container agent
            if tool_manager:
                # Exclude sys_finish_task for main agent
                all_tools = tool_manager.list_all_tools_name()
                if 'sys_finish_task' in all_tools:
                    allowed_tools = [t for t in all_tools if t != 'sys_finish_task']
                    tool_manager = ToolProxy(tool_manager, allowed_tools)
                    logger.info("FibreOrchestrator: Using ToolProxy to exclude sys_finish_task for Main Agent")
            
            # Set max_loop_count
            if session_context.agent_config is None:
                session_context.agent_config = {}
            session_context.agent_config['maxLoopCount'] = max_loop_count
            
            # Producer/Consumer pattern for stream processing
            async def run_container_stream():
                try:
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
                    await self.output_queue.put(None)  # Sentinel
            
            # Start producer task
            producer_task = asyncio.create_task(run_container_stream())
            
            # Consumer loop
            try:
                while True:
                    chunks = await self.output_queue.get()
                    if chunks is None:
                        break
                    yield chunks
                
                # Wait for producer to finish cleanly
                await producer_task
                
                # Update status on completion
                if main_session.status != "interrupted":
                    main_session.update_status("completed")
                    
            except asyncio.CancelledError:
                logger.warning(f"FibreOrchestrator: Session {session_id} interrupted")
                main_session.update_status("interrupted")
                raise
            except Exception as e:
                logger.error(f"FibreOrchestrator: Session {session_id} failed: {e}", exc_info=True)
                main_session.update_status("error")
                raise
        finally:
            # Save session state
            main_session.save_state()
    
    def _get_fibre_system_prompt_content(
        self,
        session_context: SessionContext,
        is_main_agent: bool = True,
        agent_name: str = "",
        custom_system_prompt: str = ""
    ) -> str:
        """
        Get the Fibre System Prompt.
        
        Args:
            session_context: The session context
            is_main_agent: True for main agent (orchestrator), False for sub-agent (strand)
            agent_name: Name of the agent (for sub-agents)
            custom_system_prompt: Custom system prompt (for both main and sub-agents)
            
        Returns:
            Complete system prompt
        """
        
        # Determine language
        lang = session_context.get_language() if hasattr(session_context, 'get_language') else 'en'
        
        # Load prompt parts (must exist, will raise error if not found)
        pm = PromptManager()
        
        # 1. Base Description (custom_system_prompt)
        base_desc = custom_system_prompt
        
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
                    msgs.append(MessageChunk.from_dict(m))
                else:
                    msgs.append(m)
        return msgs

    # Methods called by FibreTools
    async def spawn_agent(self, parent_context, name, system_prompt, description="", 
                          available_tools=None, available_skills=None, available_workflows=None, system_context=None):
        
        # 1. Ensure unique name
        base_name = name
        counter = 1
        while name in self.sub_agents:
            name = f"{base_name}_{counter}"
            counter += 1
        
        if name != base_name:
            logger.info(f"FibreOrchestrator: Agent name '{base_name}' collision, renamed to '{name}'")
        
        logger.info(f"Registering agent definition: {name}")
        
        # 2. Generate complete system prompt for sub-agent
        parent_session = self.sub_session_manager.get(parent_session_id)
        if parent_session:
            complete_system_prompt = self._get_fibre_system_prompt_content(
                session_context=parent_session.session_context,
                is_main_agent=False,
                agent_name=name,
                custom_system_prompt=system_prompt
            )
        else:
            complete_system_prompt = system_prompt
        
        # 3. Create Agent Definition (configuration only)
        agent_def = AgentDefinition(
            name=name,
            system_prompt=complete_system_prompt,
            description=description,
            available_tools=available_tools,
            available_skills=available_skills,
            available_workflows=available_workflows,
            system_context=system_context
        )
        
        self.sub_agents[name] = agent_def
        
        # 3. Update parent session's available_sub_agents
        parent_session = self.sub_session_manager.get(parent_session_id)
        if parent_session:
            if 'available_sub_agents' not in parent_session.session_context.system_context:
                parent_session.session_context.system_context['available_sub_agents'] = []
            
            agent_info = {"id": name, "description": description or system_prompt[:100]}
            existing_ids = [a.get("id") for a in parent_session.session_context.system_context['available_sub_agents']]
            if name not in existing_ids:
                parent_session.session_context.system_context['available_sub_agents'].append(agent_info)
        
        return name

    async def delegate_tasks(
        self,
        tasks: List[Dict[str, Any]],
        caller_session_id: str
    ) -> str:
        """
        Execute multiple tasks in parallel using SubSession.run().
        
        Args:
            tasks: List of tasks with 'agent_id', 'content', 'session_id'
            caller_session_id: The session ID of the calling agent
        """
        import asyncio
        
        # Get caller's session to determine parent-child relationship
        caller_session = self.sub_session_manager.get(caller_session_id)
        if not caller_session:
            return f"Error: Caller session '{caller_session_id}' not found"
        
        # Pre-validation
        validation_errors = []
        for i, task in enumerate(tasks):
            agent_id = task.get('agent_id')
            session_id = task.get('session_id')
            
            if not agent_id or not task.get('content'):
                validation_errors.append(f"Task {i}: Invalid task format - missing agent_id or content")
                continue
            
            # Prevent self-delegation
            if agent_id == caller_session.agent_id:
                validation_errors.append(
                    f"Task {i}: Cannot delegate to yourself (agent '{agent_id}'). "
                    f"You should complete this task yourself or create a more specialized sub-agent."
                )
                continue
            
            if agent_id not in self.sub_agents:
                validation_errors.append(f"Task {i}: Agent '{agent_id}' not found")
                continue
            
            # Check if session is already running
            existing_session = self.sub_session_manager.get(session_id)
            if existing_session:
                if existing_session.is_active():
                    validation_errors.append(
                        f"Task {i}: Session '{session_id}' is currently running a task. "
                        f"Please wait for it to complete or use a different session ID."
                    )
                    continue
                # Check if session is bound to different agent
                if existing_session.agent_id != agent_id:
                    validation_errors.append(
                        f"Task {i}: Session '{session_id}' is already bound to agent '{existing_session.agent_id}', "
                        f"cannot be reused for agent '{agent_id}'."
                    )
                    continue
        
        if validation_errors:
            error_msg = "Task validation failed:\n" + "\n".join(f"  - {err}" for err in validation_errors)
            logger.warning(f"FibreOrchestrator: {error_msg}")
            return error_msg
        
        # Execute tasks using delegate_task
        async def _run_single_task(task):
            agent_id = task.get('agent_id')
            content = task.get('content')
            session_id = task.get('session_id')
            return await self.delegate_task(agent_id, content, session_id, caller_session_id)

        results = await asyncio.gather(*[_run_single_task(t) for t in tasks])
        
        # Format results
        final_output = []
        for i, result in enumerate(results):
            agent_id = tasks[i].get('agent_id')
            final_output.append(f"=== Result from {agent_id} ===\n{result}")
        
        return "\n\n".join(final_output)
    
    async def delegate_task(self, agent_id: str, content: str, session_id: str, caller_session_id: str) -> str:
        """
        Delegate a single task to a sub-agent.
        
        Args:
            agent_id: The agent definition ID
            content: Task content
            session_id: The session ID to use
            caller_session_id: The parent session ID
            
        Returns:
            Task result string
        """
        if agent_id not in self.sub_agents:
            return f"Error: Agent '{agent_id}' not found"
        
        # Get or create SubSession
        sub_session = await self._get_or_create_sub_session(
            session_id=session_id,
            agent_id=agent_id,
            parent_session_id=caller_session_id
        )
        
        if isinstance(sub_session, str):  # Error message
            return sub_session
        
        # Update status to running
        sub_session.update_status("running")
        
        try:
            task_result = None
            all_filtered_chunks = []
            # Stream the response
            async for chunks in sub_session.run_stream(content):
                filtered_chunks = [
                        c for c in chunks 
                        if c.session_id == sub_session.session_id and c.role == MessageRole.ASSISTANT.value
                    ]
                if filtered_chunks:
                    all_filtered_chunks.extend(filtered_chunks)
                # Push to output queue if available (for producer/consumer pattern)
                if self.output_queue:
                    await self.output_queue.put(chunks)
                
                # Check for sys_finish_task
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
            
            # If sys_finish_task was called, return its result
            if task_result:
                sub_session.update_status("completed")
                return f"SubSessionID: {session_id}\n{task_result}"

            # If sub-agent finished without calling sys_finish_task, generate summary using LLM
            try:
                if all_filtered_chunks:
                    accumulated_messages = MessageManager.merge_new_messages_to_old_messages(
                        all_filtered_chunks, []
                    )
                history_str = MessageManager.convert_messages_to_str(accumulated_messages)

                # Get prompt from PromptManager
                language = sub_session.session_context.get_language() if hasattr(sub_session.session_context, 'get_language') else "en"
                summary_prompt_template = PromptManager().get_agent_prompt(
                    agent='FibreAgent',
                    key='sub_agent_fallback_summary_prompt',
                    language=language
                )
                prompt = summary_prompt_template.format(history_str=history_str)

                # Use sub-agent's internal agent to generate summary
                messages_input = [{'role': 'user', 'content': prompt}]

                # Get executor and its internal agent
                executor = await sub_session._get_executor()
                if executor and executor.agent:
                    with session_manager.session_context(session_id):
                        response_stream = executor.agent._call_llm_streaming(
                            messages=messages_input,
                            session_id=session_id,
                            step_name="sub_agent_fallback_summary"
                        )

                        summary_content = ""
                        async for chunk in response_stream:
                            if chunk.choices and chunk.choices[0].delta.content:
                                summary_content += chunk.choices[0].delta.content

                    sub_session.update_status("completed")
                    return f"SubSessionID: {session_id}\nSub-agent finished without calling 'sys_finish_task'. AI Summary:\n{summary_content}"

            except Exception as e:
                sub_session.update_status("error")
                return f"Error generating summary: {e},{traceback.format_exc()}"

            # Fallback: return aggregated response
            # result_content = "".join([c.content for c in accumulated_chunks if c.content])
            # sub_session.update_status("completed")
            # return f"SubSessionID: {session_id}\nSub-agent finished without calling 'sys_finish_task'. Aggregated response:\n{result_content}"
            
        except Exception as e:
            logger.error(f"Error executing sub-agent task: {e}", exc_info=True)
            sub_session.update_status("error")
            return f"Error executing sub-agent task: {e},{traceback.format_exc()}"
        finally:
            sub_session.save_state()

    async def _get_or_create_sub_session(
        self,
        session_id: str,
        agent_id: str,
        parent_session_id: str
    ) -> Union[SubSession, str]:
        """
        Get existing SubSession or create a new one.
        
        Args:
            session_id: Session ID
            agent_id: Agent definition ID
            parent_session_id: Parent session ID
            
        Returns:
            SubSession instance or error message string
        """
        # Check if session already exists
        existing_session = self.sub_session_manager.get(session_id)
        if existing_session:
            return existing_session
        
        # Get agent definition
        if agent_id not in self.sub_agents:
            return f"Error: Agent '{agent_id}' not found"
        
        agent_def = self.sub_agents[agent_id]
        
        # Get parent session
        parent_session = self.sub_session_manager.get(parent_session_id)
        if not parent_session:
            return f"Error: Parent session '{parent_session_id}' not found"
        
        # Create sub-session workspace under parent's workspace
        import os
        workspace_root = os.path.join(
            parent_session.session_context.session_workspace,
            "sub_sessions",
        )
        os.makedirs(workspace_root, exist_ok=True)
        
        # Prepare system_context with shared agent_workspace
        sub_agent_system_context = copy.deepcopy(agent_def.system_context)
        sub_agent_system_context["agent_host_workspace_path"] = parent_session.session_context._agent_workspace_host_path

        # Log tool_manager status for debugging
        logger.info(f"_get_or_create_sub_session: parent tool_manager={parent_session.session_context.tool_manager}")
        logger.info(f"_get_or_create_sub_session: parent session_id={parent_session.session_id}")

        sub_session_context = init_session_context(
            session_id=session_id,
            user_id=parent_session.session_context.user_id,
            workspace_root=workspace_root,
            tool_manager=parent_session.session_context.tool_manager,
            skill_manager=parent_session.session_context.skill_manager,
            system_context=sub_agent_system_context
        )

        # Log after init
        logger.info(f"_get_or_create_sub_session: created sub_session_context.tool_manager={sub_session_context.tool_manager}")
        
        # Register orchestrator in session context
        sub_session_context.orchestrator = self
        
        # Create SubSession (which will lazily create FibreSubAgent)
        sub_session = SubSession(
            session_id=session_id,
            agent_id=agent_id,
            agent_definition=agent_def,
            parent_session_id=parent_session_id,
            session_context=sub_session_context,
            model=self.agent.model,
            model_config=self.agent.model_config
        )
        
        # Register in manager
        self.sub_session_manager.register(sub_session)
        
        return sub_session

    def get_session_hierarchy(self, session_id: str) -> Dict[str, Any]:
        """
        Get the session hierarchy tree starting from a session.
        
        Args:
            session_id: Root session ID
            
        Returns:
            Tree structure with session info and children
        """
        session = self.sub_session_manager.get(session_id)
        if not session:
            return {}
        
        children = self.sub_session_manager.get_by_parent(session_id)
        return {
            "session_id": session_id,
            "agent_id": session.agent_id,
            "status": session.status,
            "children": [self.get_session_hierarchy(child.session_id) for child in children]
        }

    def interrupt_session(self, session_id: str) -> bool:
        """
        Interrupt a session and all its children.
        
        Args:
            session_id: Session ID to interrupt
            
        Returns:
            True if interrupted, False if not found
        """
        return self.sub_session_manager.interrupt_session(session_id)
