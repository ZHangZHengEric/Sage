"""
New FibreOrchestrator Architecture

Separates Agent Definition from Session Runtime:
- sub_agents: Agent definitions (configuration only)
- sub_session_manager: Running sessions with SubSession interface
"""
from __future__ import annotations
import asyncio
import json
import os
import traceback
import uuid
from typing import List, Dict, Any, Optional, Union, AsyncGenerator, TYPE_CHECKING
import copy

if TYPE_CHECKING:
    from sagents.session_runtime import Session

from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.prompt_manager import PromptManager
from sagents.context.session_context import SessionContext, SessionStatus
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.agent.fibre.tools import FibreTools
from sagents.agent.fibre.agent_definition import AgentDefinition
from sagents.agent.fibre.backend_client import FibreBackendClient
from sagents.agent.simple_agent import SimpleAgent
from sagents.utils.logger import logger


class FibreOrchestrator:
    """
    The Core (FibreOrchestrator)
    
    Architecture:
    - sub_agents: Dict[str, AgentDefinition] - Agent configurations
    - sub_session_manager: SessionManager - Running sessions
    """
    
    def __init__(self, agent, observability_manager=None):
        self.agent = agent
        self.observability_manager = observability_manager
        self.sub_agents: Dict[str, AgentDefinition] = {}  # Agent definitions only

        # Use global session manager instance if available, or create one with default path
        # Actually, SessionManager is designed to be a singleton or shared instance per process usually
        # But here we might want to attach to the same session space as the main agent
        # The main agent's session manager is what we should use.
        # However, Orchestrator doesn't hold reference to the main session's manager directly.
        # But we can get it via get_global_session_manager

        from sagents.session_runtime import get_global_session_manager
        # We don't initialize with specific path here, assuming it's already initialized by main process
        # If not, it will use default.
        self.session_manager = get_global_session_manager()
        self.sub_session_manager = self.session_manager

        # Initialize backend client for API-based agent management
        self.backend_client = FibreBackendClient()

        self.output_queue: Optional[asyncio.Queue] = None

    @staticmethod
    def _resolve_agent_name(agent_cfg: Any, agent_id: Optional[str]) -> str:
        if isinstance(agent_cfg, dict):
            name = agent_cfg.get("name") or agent_cfg.get("display_name")
        else:
            name = getattr(agent_cfg, "name", None) or getattr(agent_cfg, "display_name", None)
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError(f"Sub-agent name is required, agent_id={agent_id}")
        return normalized

    async def run_loop(
        self,
        session_context: SessionContext,
        max_loop_count: int,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        Main orchestration loop.
        
        Similar to the original run_loop but uses the new architecture.
        """
        # Initialize Output Queue for merging streams
        self.output_queue = asyncio.Queue()
        
        # Initialize Main Session Context
        main_session = None

        # Register orchestrator in session context
        session_context.orchestrator = self

        # Log tool_manager status for debugging
        logger.info(f"run_loop: session_context.tool_manager={session_context.tool_manager}")

        # Register main session in sub_session_manager (actually just SessionManager now)
        # Main session is already created via SessionContext, but let's ensure it's tracked if needed
        # However, SubSessionManager logic was different. SessionManager tracks by ID.
        # We need to adapt the logic to use Session objects.
        
        # 1.1 Load Custom Agents from Configuration
        custom_sub_agents = getattr(session_context, 'custom_sub_agents', None) or \
                           session_context.agent_config.get("custom_sub_agents") or \
                           session_context.system_context.get("custom_sub_agents")
        logger.info(f"run_loop: custom_sub_agents={custom_sub_agents}")

        # If no custom_sub_agents, fetch from backend
        if not custom_sub_agents and self.backend_client and await self.backend_client.check_health():
            logger.info("FibreOrchestrator: No custom_sub_agents configured, fetching from backend...")
            try:
                # Get user_id from session context
                user_id = getattr(session_context, 'user_id', None)
                backend_agents = await self.backend_client.list_agents(user_id=user_id)
                # Filter out the current agent itself
                current_agent_id = session_context.agent_config.get("agent_id") if session_context.agent_config else None
                custom_sub_agents = [
                    {
                        "agent_id": agent.get("agent_id") if isinstance(agent, dict) else agent,
                        "name": self._resolve_agent_name(agent, agent.get("agent_id") if isinstance(agent, dict) else agent),
                        "description": agent.get("description", "") if isinstance(agent, dict) else "",
                        "system_prompt": agent.get("system_prompt", "") if isinstance(agent, dict) else "",
                        "available_tools": agent.get("available_tools") if isinstance(agent, dict) else None,
                        "available_skills": agent.get("available_skills") if isinstance(agent, dict) else None,
                        "available_workflows": agent.get("available_workflows") if isinstance(agent, dict) else None,
                        "system_context": agent.get("system_context") if isinstance(agent, dict) else None,
                    }
                    for agent in backend_agents
                    if ((agent.get("agent_id") if isinstance(agent, dict) else agent) != current_agent_id)
                ]
                logger.info(f"FibreOrchestrator: Fetched {len(custom_sub_agents)} agents from backend (excluding self)")
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"FibreOrchestrator: Failed to fetch agents from backend: {e}")
                custom_sub_agents = []

        if custom_sub_agents and isinstance(custom_sub_agents, list):
            logger.info(f"FibreOrchestrator: Found {len(custom_sub_agents)} custom agents to initialize.")
            for agent_cfg in custom_sub_agents:
                if isinstance(agent_cfg, dict):
                    agent_id = agent_cfg.get("agent_id")
                    agent_system_prompt = agent_cfg.get("system_prompt", "")
                    agent_description = agent_cfg.get("description", "")
                    agent_tools = agent_cfg.get("available_tools")
                    agent_skills = agent_cfg.get("available_skills")
                    agent_workflows = agent_cfg.get("available_workflows")
                    agent_system_context = agent_cfg.get("system_context")
                    agent_name = self._resolve_agent_name(agent_cfg, agent_id)
                else:
                    agent_id = getattr(agent_cfg, "agent_id") or getattr(agent_cfg, "name", None)
                    agent_system_prompt = getattr(agent_cfg, "system_prompt", "")
                    agent_description = getattr(agent_cfg, "description", "")
                    agent_tools = getattr(agent_cfg, "available_tools", None)
                    agent_skills = getattr(agent_cfg, "available_skills", None)
                    agent_workflows = getattr(agent_cfg, "available_workflows", None)
                    agent_system_context = getattr(agent_cfg, "system_context", None)
                    agent_name = self._resolve_agent_name(agent_cfg, agent_id)

                # Skip if agent_id is empty or agent already exists
                if not agent_id:
                    logger.warning("FibreOrchestrator: Skipping custom agent with empty agent_id")
                    continue

                # Check if agent already exists in backend or local memory
                agent_exists = False
                backend_agent = None
                if self.backend_client and await self.backend_client.check_health():
                    # Check backend
                    user_id = getattr(session_context, 'user_id', None)
                    backend_agent = await self.backend_client.get_agent(agent_id, user_id=user_id)
                    if backend_agent:
                        agent_exists = True
                        logger.info(f"FibreOrchestrator: Agent '{agent_id}' already exists in backend, skipping creation")
                if not agent_exists and agent_id in self.sub_agents:
                    # Check local memory
                    agent_exists = True
                    logger.info(f"FibreOrchestrator: Agent '{agent_id}' already exists in local memory, skipping creation")

                if agent_exists:
                    # 将agent_id name 和 description 添加到当前session_context 的system_context 变量中的available_sub_agents
                    if session_context.system_context.get("available_sub_agents"):
                        session_context.system_context["available_sub_agents"].append({
                            "agent_id": agent_id,
                            "name": agent_name,
                            "description": agent_description
                        })
                    else:
                        session_context.system_context["available_sub_agents"] = [{
                            "agent_id": agent_id,
                            "name": agent_name,
                            "description": agent_description
                        }]
                    
                    # 如果agent存在于后端但不在sub_agents中，需要创建一个轻量级的AgentDefinition
                    # 这样delegate_task时才能找到这个agent
                    if backend_agent and agent_id not in self.sub_agents:
                        logger.info(f"FibreOrchestrator: Adding backend agent '{agent_id}' to sub_agents for task delegation")
                        from sagents.agent.fibre.agent_definition import AgentDefinition
                        agent_def = AgentDefinition(
                            agent_id=agent_id,
                            name=agent_name,
                            description=agent_description,
                            system_prompt=agent_system_prompt,
                            backend_stored=True,
                            available_tools=agent_tools,
                            available_skills=agent_skills,
                            available_workflows=agent_workflows,
                            system_context=agent_system_context
                        )
                        self.sub_agents[agent_id] = agent_def
                    
                    continue

                await self.spawn_agent(
                    parent_session_id=session_context.session_id,
                    agent_id=agent_id,
                    system_prompt=agent_system_prompt,
                    description=agent_description,
                    available_tools=agent_tools,
                    available_skills=agent_skills,
                    available_workflows=agent_workflows,
                    system_context=agent_system_context
                )
                logger.info(f"FibreOrchestrator: Initialized custom sub-agent '{agent_id}'")
        
        # 2. Setup and run main agent loop
        try:
            # main_session.update_status("running") 
            # Session status is managed by SessionContext now
            if session_context:
                session_context.set_status(SessionStatus.RUNNING)
            
            # 2.1 Get Fibre System Prompt for main agent
            fibre_prompt = self._get_fibre_system_prompt_content(
                session_context=session_context,
                is_main_agent=True,
                custom_system_prompt=self.agent.system_prefix or ""
            )
            
            # 2.2 Inject Fibre Tools
            fibre_tools_impl = FibreTools()
            if session_context.tool_manager:
                session_context.tool_manager.register_tools_from_object(fibre_tools_impl)
            
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
                        
            # Set max_loop_count
            if session_context.agent_config is None:
                session_context.agent_config = {}
            session_context.agent_config['max_loop_count'] = max_loop_count
            
            # Producer/Consumer pattern for stream processing
            async def run_container_stream():
                try:
                    async for chunks in container_agent.run_stream(
                        session_context=session_context,
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
                if main_session and main_session.status != "interrupted":
                    main_session.update_status("completed")
                    
            except asyncio.CancelledError:
                logger.warning(f"FibreOrchestrator: Session {session_context.session_id} interrupted")
                if main_session:
                    main_session.update_status("interrupted")
                raise
            except Exception as e:
                logger.error(f"FibreOrchestrator: Session {session_context.session_id} failed: {e}", exc_info=True)
                if main_session:
                    main_session.update_status("error")
                raise
        finally:
            # Save session state
            if main_session:
                main_session.save_state()
    
    def _get_fibre_system_prompt_content(
        self,
        session_context: SessionContext,
        is_main_agent: bool = True,
        custom_system_prompt: str = "",
        include_system_mechanics: bool = True
    ) -> str:
        """
        Get the Fibre System Prompt.

        Args:
            session_context: The session context
            is_main_agent: True for main agent (orchestrator), False for sub-agent (strand)
            custom_system_prompt: Custom system prompt (for both main and sub-agents)
            include_system_mechanics: Whether to include fibre_system_prompt mechanics.
                Set to False for sub-agents that are FibreAgent themselves to avoid duplication.

        Returns:
            Complete system prompt
        """

        # Determine language
        lang = session_context.get_language() if hasattr(session_context, 'get_language') else 'en'

        # Load prompt parts (must exist, will raise error if not found)
        pm = PromptManager()

        # 1. Base Description (custom_system_prompt)
        base_desc = custom_system_prompt or ""

        # 2. System Mechanics (Shared) - only include if requested
        if include_system_mechanics:
            system_mechanics = pm.get_prompt('fibre_system_prompt', agent='FibreAgent', language=lang)
        else:
            system_mechanics = ""

        # 3. Common rules for both main and sub agents
        # Only include if system_mechanics is also included (i.e., not a FibreAgent sub-agent)
        if include_system_mechanics:
            common_rules = pm.get_prompt('common_agent_rules', agent='FibreAgent', language=lang)
        else:
            common_rules = ""

        # Combine for all agents
        parts = []
        if base_desc:
            parts.append(base_desc)
        if system_mechanics:
            parts.append(system_mechanics)
        if common_rules:
            parts.append(common_rules)

        return "\n\n".join(parts)

    async def spawn_agent(
        self,
        parent_session_id: str,
        agent_id: Optional[str] = None,
        system_prompt: str = "",
        name: str = "",
        description: str = "",
        available_tools=None,
        available_skills=None,
        available_workflows=None,
        system_context=None
    ) -> str:
        """
        Create a new agent definition.

        Priority:
        1. Try to store in backend via API (if available)
        2. Fallback to memory storage

        Args:
            parent_session_id: The session ID that is creating this agent
            agent_id: Agent ID (optional, will be auto-generated if not provided)
            system_prompt: System prompt
            name: Human-readable nickname for display (defaults to agent_id)
            description: Description
            available_tools: List of available tool names
            available_skills: List of available skill names
            available_workflows: List of available workflow names
            system_context: Additional system context

        Returns:
            agent_id: The created agent's ID
        """
        # 1. Generate or ensure unique agent_id
        if agent_id is None:
            # Auto-generate agent_id based on whether backend is available
            if self.backend_client and await self.backend_client.check_health():
                # For backend: use simple format, backend will assign final ID
                agent_id = f"agent_{uuid.uuid4().hex[:8]}"
            else:
                # For internal: use uuid
                agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        else:
            # Ensure unique agent_id
            base_agent_id = agent_id
            counter = 1
            while agent_id in self.sub_agents:
                agent_id = f"{base_agent_id}_{counter}"
                counter += 1

            if agent_id != base_agent_id:
                logger.info(f"FibreOrchestrator: Agent ID '{base_agent_id}' collision, renamed to '{agent_id}'")

        logger.info(f"Registering agent definition: {agent_id}")

        # 2. Get parent session for configuration
        parent_session = self.sub_session_manager.get(parent_session_id)

        # 3. Try to store in backend first (if available) to get final agent_id
        backend_stored = False
        llm_provider_id = None
        final_agent_id = agent_id  # Will be updated if backend returns different ID

        if self.backend_client and await self.backend_client.check_health():
            # Get available sub-agent IDs from parent session's custom_sub_agents
            available_sub_agent_ids = []
            if parent_session and parent_session.session_context:
                custom_sub_agents = getattr(parent_session.session_context, 'custom_sub_agents', []) or \
                                   parent_session.session_context.agent_config.get('custom_sub_agents', [])
                # Extract agent IDs from custom_sub_agents
                for agent_cfg in custom_sub_agents:
                    if isinstance(agent_cfg, dict):
                        agent_sub_id = agent_cfg.get('agent_id')  or agent_cfg.get('id')
                        if agent_sub_id:
                            available_sub_agent_ids.append(agent_sub_id)
                    else:
                        agent_sub_id = getattr(agent_cfg, 'agent_id', None) or getattr(agent_cfg, 'id', None)
                        if agent_sub_id:
                            available_sub_agent_ids.append(agent_sub_id)

            # If available_tools/skills/workflows not provided, get from parent session
            if available_tools is None and parent_session and parent_session.session_context:
                available_tools = parent_session.session_context.agent_config.get('available_tools', [])
            if available_skills is None and parent_session and parent_session.session_context:
                available_skills = parent_session.session_context.agent_config.get('available_skills', [])
            if available_workflows is None and parent_session and parent_session.session_context:
                available_workflows = parent_session.session_context.agent_config.get('available_workflows', {})

            # Create LLM provider from current agent's model configuration
            if self.agent and self.agent.model:
                try:
                    # Extract model configuration from the agent's model
                    model_base_url = getattr(self.agent.model, 'base_url', None)
                    model_api_key = getattr(self.agent.model, 'api_key', None)
                    model_name = self.agent.model_config.get('model') if self.agent.model_config else None

                    if model_base_url and model_api_key and model_name:
                        # Get user_id from parent session context
                        user_id = None
                        if parent_session and parent_session.session_context:
                            user_id = getattr(parent_session.session_context, 'user_id', None)
                        llm_provider_id = await self.backend_client.create_llm_provider(
                            base_url=str(model_base_url),
                            api_keys=[str(model_api_key)],
                            model=model_name,
                            user_id=user_id
                        )
                        if llm_provider_id:
                            logger.info(f"Created LLM provider '{llm_provider_id}' for agent '{agent_id}'")
                        else:
                            logger.warning(f"Failed to create LLM provider for agent '{agent_id}'")
                    else:
                        logger.warning(f"Missing model configuration for agent '{agent_id}': base_url={model_base_url is not None}, api_key={model_api_key is not None}, model={model_name is not None}")
                except Exception as e:
                    logger.warning(f"Error creating LLM provider: {e}")

            # Create agent in backend (without system_prompt first, we'll update later if needed)
            # Use a temporary system prompt
            # Check if sub-agent will be a FibreAgent (inherit agent_mode from parent)
            parent_agent_mode = parent_session.session_context.agent_config.get("agent_mode") if parent_session and parent_session.session_context else None
            is_sub_agent_fibre = parent_agent_mode == "fibre"
            
            temp_system_prompt = system_prompt
            if parent_session:
                # If sub-agent is FibreAgent, don't include system_mechanics to avoid duplication
                # because FibreAgent.__init__ will add its own system prompt
                temp_system_prompt = self._get_fibre_system_prompt_content(
                    session_context=parent_session.session_context,
                    is_main_agent=False,
                    custom_system_prompt=system_prompt,
                    include_system_mechanics=not is_sub_agent_fibre
                )

            # Get user_id from parent session context
            user_id = None
            if parent_session and parent_session.session_context:
                user_id = getattr(parent_session.session_context, 'user_id', None)
            backend_agent_id = await self.backend_client.create_agent(
                agent_id=agent_id,
                name=name,
                system_prompt=temp_system_prompt,
                description=description,
                available_tools=available_tools or [],
                available_skills=available_skills or [],
                available_workflows=available_workflows or {},
                system_context=system_context,
                available_sub_agent_ids=available_sub_agent_ids if available_sub_agent_ids else None,
                max_loop_count=parent_session.session_context.agent_config.get("max_loop_count") if parent_session and parent_session.session_context else None,
                llm_provider_id=llm_provider_id,
                user_id=user_id
            )
            if backend_agent_id:
                backend_stored = True
                final_agent_id = backend_agent_id
                logger.info(f"Agent '{final_agent_id}' stored in backend successfully")
            else:
                logger.warning("Failed to store agent in backend, falling back to memory storage")

        # 4. Generate final system prompt
        if parent_session:
            # If sub-agent is FibreAgent, don't include system_mechanics to avoid duplication
            complete_system_prompt = self._get_fibre_system_prompt_content(
                session_context=parent_session.session_context,
                is_main_agent=False,
                custom_system_prompt=system_prompt,
                include_system_mechanics=not is_sub_agent_fibre
            )
        else:
            complete_system_prompt = system_prompt

        # 5. Create Agent Definition (memory storage as fallback or supplement)
        agent_def = AgentDefinition(
            agent_id=final_agent_id,
            name=name,
            system_prompt=complete_system_prompt,
            description=description,
            available_tools=available_tools,
            available_skills=available_skills,
            available_workflows=available_workflows,
            system_context=system_context,
            backend_stored=backend_stored
        )

        self.sub_agents[final_agent_id] = agent_def

        # 6. Update parent session's available_sub_agents
        if parent_session:
            if 'available_sub_agents' not in parent_session.session_context.system_context:
                parent_session.session_context.system_context['available_sub_agents'] = []

            agent_info = {"agent_id": final_agent_id, "name": name, "description": description or system_prompt[:100]}
            existing_ids = [a.get("agent_id") for a in parent_session.session_context.system_context['available_sub_agents']]
            if agent_info["agent_id"] not in existing_ids:
                parent_session.session_context.system_context['available_sub_agents'].append(agent_info)

        return final_agent_id

    def _get_session_depth(self, session_id: str) -> int:
        """
        Get the depth of a session in the hierarchy.
        Root session has depth 0.
        """
        depth = 0
        current_session = self.sub_session_manager.get(session_id)
        
        while current_session and current_session.session_context:
            parent_session_id = current_session.session_context.system_context.get("parent_session_id")
            if not parent_session_id:
                break
            depth += 1
            current_session = self.sub_session_manager.get(parent_session_id)
            # Prevent infinite loop
            if depth > 100:
                break
        
        return depth

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
        if not caller_session or not caller_session.session_context:
            return f"Error: Caller session '{caller_session_id}' not found"

        # Get caller agent_id from session_context
        caller_agent_id = caller_session.session_context.agent_config.get("agent_id")
        
        # Check session depth - limit to 4 levels
        session_depth = self._get_session_depth(caller_session_id)
        if session_depth >= 4:
            return f"Error: Maximum delegation depth (4) reached. You are at level {session_depth}. Please complete the task yourself instead of delegating."
        
        # Track used session IDs to avoid conflicts within this batch
        used_session_ids = set()
        _session_counter = 0

        def generate_unique_session_id() -> str:
            """Generate a unique session ID based on caller_session_id"""
            nonlocal _session_counter
            base_id = f"{caller_session_id}_sub"
            # Check if already exists in session_manager
            session_id = f"{base_id}_{_session_counter}"
            while session_id in used_session_ids or self.sub_session_manager.get_session_workspace(session_id):
                _session_counter += 1
                session_id = f"{base_id}_{_session_counter}"
            used_session_ids.add(session_id)
            _session_counter += 1
            return session_id

        # Pre-validation and auto-generate session_id if needed
        validation_errors = []
        for i, task in enumerate(tasks):
            agent_id = task.get('agent_id')
            session_id = task.get('session_id')

            # Auto-generate session_id if not provided
            if not session_id:
                session_id = generate_unique_session_id()
                task['session_id'] = session_id
                logger.info(f"FibreOrchestrator: Auto-generated session_id '{session_id}' for task {i}")
            
            if not agent_id or not task.get('content'):
                validation_errors.append(f"Task {i}: Invalid task format - missing agent_id or content")
                continue
            
            # Prevent self-delegation
            if agent_id == caller_agent_id:
                validation_errors.append(
                    f"Task {i}: Cannot delegate to yourself (agent '{agent_id}'). "
                    f"You should complete this task yourself or create a more specialized sub-agent."
                )
                continue
            
            if agent_id not in self.sub_agents:
                validation_errors.append(f"Task {i}: Agent '{agent_id}' not found")
                continue
            
            # Check if session is already running (only for internal sessions)
            # Note: Backend-managed sessions are not tracked in sub_session_manager
            existing_session = self.sub_session_manager.get(session_id)
            if existing_session and existing_session.session_context:
                # Check if session is active via session_context status
                from sagents.context.session_context import SessionStatus
                if existing_session.session_context.status == SessionStatus.RUNNING:
                    validation_errors.append(
                        f"Task {i}: Session '{session_id}' is currently running a task. "
                        f"Please wait for it to complete or use a different session ID."
                    )
                    continue
                # Check if session is bound to different agent
                existing_agent_id = existing_session.session_context.agent_config.get("agent_id") if existing_session.session_context else None
                if existing_agent_id and existing_agent_id != agent_id:
                    validation_errors.append(
                        f"Task {i}: Session '{session_id}' is already bound to agent '{existing_agent_id}', "
                        f"cannot be reused for agent '{agent_id}'."
                    )
                    continue
            # Note: If existing_session is None, it could be:
            # 1. A new session (OK)
            # 2. A backend-managed session (OK - backend handles its own lifecycle)
        
        if validation_errors:
            error_msg = "Task validation failed:\n" + "\n".join(f"  - {err}" for err in validation_errors)
            logger.warning(f"FibreOrchestrator: {error_msg}")
            return error_msg
        
        # Execute tasks using delegate_task
        async def _run_single_task(task):
            agent_id = task.get('agent_id')
            content = task.get('content')
            session_id = task.get('session_id')
            task_name = task.get('task_name', agent_id)
            original_task = task.get('original_task', '')
            return await self.delegate_task(agent_id, content, session_id, caller_session_id, task_name, original_task)

        results = await asyncio.gather(*[_run_single_task(t) for t in tasks])

        # Format results
        final_output = []
        for i, result in enumerate(results):
            agent_id = tasks[i].get('agent_id')
            final_output.append(f"=== Result from {agent_id} ===\n{result}")
        
        return "\n\n".join(final_output)
    
    def _sanitize_task_name(self, name: str) -> str:
        """清理任务名，使其适合作为文件夹名"""
        import re
        # 替换非法字符
        illegal_chars = r'[\\/:*?"<>|]'
        sanitized = re.sub(illegal_chars, '_', name)
        # 截断
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
        return sanitized.strip() or "unnamed_task"

    async def _create_task_workspace(
        self,
        session_id: str,
        task_name: str,
        parent_session_id: Optional[str],
        session_context: SessionContext
    ) -> str:
        """
        创建任务工作目录（在沙箱内创建）

        Args:
            session_id: 会话 ID
            task_name: 任务名称
            parent_session_id: 父会话 ID（可选）
            session_context: 会话上下文

        Returns:
            任务工作目录的虚拟路径（沙箱内路径）
        """
        # 1. 清理任务名
        task_name = self._sanitize_task_name(task_name)

        # 2. 确定父目录（使用沙箱虚拟路径）
        if parent_session_id:
            # 子任务：在父任务的 sub_tasks 下创建
            # 从 parent session 的 system_context 中获取 task_workspace
            parent_session = self.sub_session_manager.get(parent_session_id)
            parent_workspace = None
            if parent_session and parent_session.session_context:
                parent_workspace = parent_session.session_context.system_context.get('task_workspace')

            if parent_workspace:
                base_path = os.path.join(parent_workspace, "sub_tasks")
            else:
                # 回退到 session_context 的 sandbox_agent_workspace
                base_path = os.path.join(session_context.sandbox_agent_workspace, "tasks")
        else:
            # 根任务：直接在 sandbox_agent_workspace/tasks 下创建
            base_path = os.path.join(session_context.sandbox_agent_workspace, "tasks")

        # 3. 获取任务路径
        task_path = os.path.join(base_path, task_name)

        # 4. 使用沙箱接口创建目录
        try:
            # 检查目录是否已存在
            exists = await session_context.sandbox.file_exists(task_path)
            if exists:
                logger.info(f"Reusing existing task workspace: {task_path} for session {session_id}")
            else:
                logger.info(f"Creating task workspace: {task_path}")

            # 创建任务目录结构
            await session_context.sandbox.ensure_directory(task_path)
            await session_context.sandbox.ensure_directory(os.path.join(task_path, "execution"))
            await session_context.sandbox.ensure_directory(os.path.join(task_path, "results"))
            await session_context.sandbox.ensure_directory(os.path.join(task_path, "sub_tasks"))

            logger.info(f"Created task workspace: {task_path}")
        except Exception as e:
            logger.error(f"Failed to create task workspace {task_path}: {e}")
            raise

        return task_path

    async def delegate_task(
        self,
        agent_id: str,
        content: str,
        session_id: str,
        caller_session_id: str,
        task_name: str = "",
        original_task: str = ""
    ) -> str:
        """
        Delegate a single task to a sub-agent.

        Priority:
        1. If agent is backend_stored and backend is available, use API call
        2. Fallback to internal session execution

        Args:
            agent_id: The agent definition ID
            content: Task content
            session_id: The session ID to use
            caller_session_id: The parent session ID
            task_name: The task name (for workspace folder)
            original_task: The original task description

        Returns:
            Task result string
        """
        effective_task_name = task_name if task_name else agent_id

        # ========== Strategy 1: Use Backend API (priority) ==========
        # Check if agent is stored in backend (system agents or previously created agents)
        agent_def = self.sub_agents.get(agent_id)
        if agent_def and agent_def.backend_stored and self.backend_client and await self.backend_client.check_health():
            logger.info(f"Using backend API for agent '{agent_id}' task execution")
            return await self._delegate_task_via_backend(
                agent_id=agent_id,
                content=content,
                session_id=session_id,
                caller_session_id=caller_session_id,
                task_name=effective_task_name,
                original_task=original_task
            )

        # ========== Strategy 2: Internal Session Execution (fallback) ==========
        # Only check sub_agents for internal execution
        if agent_id not in self.sub_agents:
            return f"Error: Agent '{agent_id}' not found"

        agent_def = self.sub_agents[agent_id]
        logger.info(f"Using internal execution for agent '{agent_id}'")
        return await self._delegate_task_internal(
            agent_id=agent_id,
            content=content,
            session_id=session_id,
            caller_session_id=caller_session_id,
            task_name=effective_task_name,
            original_task=original_task
        )

    async def _delegate_task_via_backend(
        self,
        agent_id: str,
        content: str,
        session_id: str,
        caller_session_id: str,
        task_name: str,
        original_task: str
    ) -> str:
        """
        Delegate task via backend API call.
        Does not manage sub-session state (simplified approach).
        """
        # Get parent session for workspace context
        parent_session = self.sub_session_manager.get(caller_session_id)
        parent_session_context = None
        if parent_session and parent_session.session_context:
            parent_session_context = parent_session.session_context

        # Create task workspace using the same logic as internal execution
        # For backend calls, we also create the directory in sandbox
        if parent_session_context:
            task_workspace = await self._create_task_workspace(
                session_id=session_id,
                task_name=task_name,
                parent_session_id=caller_session_id,
                session_context=parent_session_context
            )
            # Record task_workspace to parent session's system_context for sub-agents to access
            parent_session_context.system_context['task_workspace'] = task_workspace
        else:
            # Fallback: use a default virtual path
            task_workspace = os.path.join("/sage-workspace", "tasks", f"{task_name}_{session_id}")

        # Build enhanced content with workspace info
        original_task_section = f"【用户最初任务需求】\n{original_task}\n\n" if original_task else ""
        enhanced_content = f"""【消息发送方】
此任务由其他 Agent 发送给你。

{original_task_section}【你本次需要完成的子任务】
{content}

【子任务工作目录】
请在以下目录中执行任务，并将最终执行结果汇报整理保存到 {task_workspace}/results/：
工作目录：{task_workspace}
执行过程文件请放在：{task_workspace}/execution/
"""

        # Prepare messages for API
        messages = [{"role": "user", "content": enhanced_content}]

        # Prepare system_context with external_paths and parent session context
        # Get parent's external_paths and add current task workspace
        external_paths = []
        if parent_session_context and hasattr(parent_session_context, 'system_context'):
            parent_external_paths = parent_session_context.system_context.get('external_paths', [])
            external_paths.extend(parent_external_paths)
        # Add current task workspace to external_paths
        external_paths.append(task_workspace)

        # Start with parent session's system_context if available
        system_context = {}
        if parent_session_context and hasattr(parent_session_context, 'system_context'):
            parent_ctx = parent_session_context.system_context.copy()
            # Remove task_workspace (will be set to current task's workspace)
            parent_ctx.pop('task_workspace', None)
            # Remove time-related fields
            parent_ctx.pop('timestamp', None)
            parent_ctx.pop('start_time', None)
            parent_ctx.pop('created_at', None)
            # Remove fields that should be set for child session
            parent_ctx.pop('session_id', None)
            parent_ctx.pop('parent_session_id', None)
            # Remove internal/agent-specific fields that should not be passed to child
            parent_ctx.pop('当前AgentId', None)
            parent_ctx.pop('private_workspace', None)
            parent_ctx.pop('file_permission', None)
            system_context.update(parent_ctx)

        # Set external_paths (current task's workspace)
        system_context['external_paths'] = external_paths
        # Set child session specific fields
        system_context['session_id'] = session_id
        system_context['parent_session_id'] = caller_session_id
        # Copy user_id and response_language from parent if available
        user_id = None
        if parent_session_context:
            user_id = getattr(parent_session_context, 'user_id', None)
            system_context['user_id'] = user_id if user_id else "unknown"
            if hasattr(parent_session_context, 'system_context'):
                if 'response_language' in parent_session_context.system_context:
                    system_context['response_language'] = parent_session_context.system_context['response_language']

        # Collect response and process like internal execution
        task_result = None
        all_content_chunks = []

        try:
            async for chunks in self.backend_client.stream_chat(
                agent_id=agent_id,
                messages=messages,
                session_id=session_id,
                system_context=system_context,
                user_id=user_id,
                max_loop_count=parent_session_context.agent_config.get("max_loop_count") if parent_session_context else None,
            ):
                # Filter chunks for current session and assistant role
                # Skip non-content types like 'token_usage', 'stream_end'
                filtered_chunks = [
                    c for c in chunks
                    if c.session_id == session_id 
                    and c.role == MessageRole.ASSISTANT.value
                    and c.type not in ('token_usage', 'stream_end')
                ]
                if filtered_chunks:
                    all_content_chunks.extend(filtered_chunks)

                # Check for sys_finish_task in tool_calls
                for chunk in chunks:
                    if chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            func_name = tc.get("function", {}).get("name") if isinstance(tc, dict) else getattr(getattr(tc, "function", None), "name", None)
                            if func_name == "sys_finish_task":
                                args_str = tc.get("function", {}).get("arguments", "{}") if isinstance(tc, dict) else getattr(getattr(tc, "function", None), "arguments", "{}")
                                try:
                                    args = json.loads(args_str)
                                    task_result = f"Task finished: {args.get('status')}. Result: {args.get('result')}"
                                    logger.info(f"[Orchestrator] sys_finish_task called with status={args.get('status')}, result={args.get('result')}")
                                except Exception as e:
                                    logger.error(f"Error parsing sys_finish_task arguments: {e}")

            # If sys_finish_task was called, return its result
            if task_result:
                return f"SubSessionID: {session_id} , if you need to continue the task, please use this SubSessionID.\n{task_result}"

            # If no sys_finish_task, generate summary from accumulated content
            # Extract content from MessageChunk objects
            content_texts = [chunk.content for chunk in all_content_chunks if chunk.content]
            history_str = "\n".join(content_texts)

            # Debug logging
            logger.info(f"[DelegateTask Backend] Session: {session_id}, Agent: {agent_id}")
            logger.info(f"[DelegateTask Backend] Total chunks collected: {len(all_content_chunks)}")
            logger.info(f"[DelegateTask Backend] Chunks with content: {len(content_texts)}")
            logger.info(f"[DelegateTask Backend] Total content length: {len(history_str)} chars")
            if content_texts:
                logger.info(f"[DelegateTask Backend] First chunk preview: {content_texts[0][:100]}...")
                logger.info(f"[DelegateTask Backend] Last chunk preview: {content_texts[-1][:100]}...")

            if not history_str.strip():
                logger.warning(f"[DelegateTask Backend] No content received from sub-agent {agent_id}")
                return f"SubSessionID: {session_id}\nNo response from sub-agent"

            # Get prompt from PromptManager
            language = "zh"  # Default to Chinese, could be improved
            if parent_session and parent_session.session_context:
                language = parent_session.session_context.get_language() if hasattr(parent_session.session_context, 'get_language') else "zh"

            summary_prompt_template = PromptManager().get_agent_prompt(
                agent='FibreAgent',
                key='sub_agent_fallback_summary_prompt',
                language=language
            )
            prompt = summary_prompt_template.format(history_str=history_str)

            # Use main agent to generate summary (since we don't have sub_session)
            messages_input = [{'role': 'user', 'content': prompt}]

            # Try to use the main agent's LLM for summary
            try:
                # Get agent from main session (self.agent)
                if self.agent and hasattr(self.agent, '_call_llm_streaming'):
                    from sagents.session_runtime import session_scope
                    with session_scope(caller_session_id):
                        response_stream = self.agent._call_llm_streaming(
                            messages=messages_input,
                            session_id=caller_session_id,
                            step_name="sub_agent_fallback_summary"
                        )

                        summary_content = ""
                        async for chunk in response_stream:
                            if chunk.choices and chunk.choices[0].delta.content:
                                summary_content += chunk.choices[0].delta.content

                    return f"SubSessionID: {session_id}, if you need to continue the task, please use this SubSessionID.\nSub-agent finished without calling 'sys_finish_task'. AI Summary:\n{summary_content}"
                else:
                    # Fallback: return accumulated content directly
                    return f"SubSessionID: {session_id}, if you need to continue the task, please use this SubSessionID.\nSub-agent response:\n{history_str}"
            except Exception as e:
                logger.warning(f"Failed to generate summary via LLM: {e}")
                # Fallback: return accumulated content directly
                return f"SubSessionID: {session_id}, if you need to continue the task, please use this SubSessionID.\nSub-agent response:\n{history_str}"

        except Exception as e:
            logger.error(f"Backend API call failed: {e}, falling back to internal execution")
            # Fallback to internal execution
            return await self._delegate_task_internal(
                agent_id=agent_id,
                content=content,
                session_id=session_id,
                caller_session_id=caller_session_id,
                task_name=task_name,
                original_task=original_task
            )

    async def _delegate_task_internal(
        self,
        agent_id: str,
        content: str,
        session_id: str,
        caller_session_id: str,
        task_name: str,
        original_task: str
    ) -> str:
        """
        Delegate task via internal session execution (original implementation).
        """
        # Get or create SubSession
        sub_session = await self._get_or_create_sub_session(
            session_id=session_id,
            agent_id=agent_id,
            parent_session_id=caller_session_id
        )

        if isinstance(sub_session, str):  # Error message
            return sub_session

        # Create task workspace using task_name
        task_workspace = await self._create_task_workspace(
            session_id=session_id,
            task_name=task_name,
            parent_session_id=caller_session_id,
            session_context=sub_session.session_context
        )
        # Record task_workspace to sub-session's system_context for sub-agents to access
        sub_session.session_context.system_context['task_workspace'] = task_workspace

        # Build enhanced content with workspace info
        original_task_section = f"【用户最初任务需求】\n{original_task}\n\n" if original_task else ""
        enhanced_content = f"""{original_task_section}【你本次需要完成的子任务】
{content}

【子任务工作目录】
请在以下目录中执行任务，并将最终执行结果汇报整理保存到 {task_workspace}/results/：
工作目录：{task_workspace}
执行过程文件请放在：{task_workspace}/execution/
"""

        # Prepare input messages
        input_messages = [MessageChunk(role=MessageRole.USER.value, content=enhanced_content, session_id=session_id)]

        # Update status to running
        from sagents.context.session_context import SessionStatus
        sub_session.session_context.set_status(SessionStatus.RUNNING)

        try:
            task_result = None
            all_filtered_chunks = []

            # Use custom flow for sub-session
            from sagents.flow.schema import AgentFlow, SequenceNode, AgentNode

            simple_flow = AgentFlow(
                name=f"SubAgent Flow - {agent_id}",
                root=SequenceNode(steps=[AgentNode(agent_key="simple")])
            )

            logger.info(f"Starting sub-agent flow for {agent_id} session_id: {session_id}")
            # Stream the response
            async for chunks in sub_session.run_stream_with_flow(
                input_messages=input_messages,
                flow=simple_flow,
                tool_manager=sub_session.session_context.tool_manager,
                skill_manager=sub_session.session_context.skill_manager,
                session_id=session_id,
                max_loop_count=sub_session.session_context.agent_config.get("max_loop_count"),
                deep_thinking=sub_session.session_context.agent_config.get("deep_thinking", False),
                agent_mode=sub_session.session_context.agent_config.get("agent_mode", "simple")
            ):
                filtered_chunks = [
                        c for c in chunks
                        if c.session_id == session_id and c.role == MessageRole.ASSISTANT.value
                    ]
                if filtered_chunks:
                    all_filtered_chunks.extend(filtered_chunks)

                # Check for sys_finish_task (if tools are used)
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
                if sub_session.session_context:
                    sub_session.session_context.set_status(SessionStatus.COMPLETED)
                return f"SubSessionID: {session_id}\n{task_result}"

            # If sub-agent finished without calling sys_finish_task, generate summary using LLM
            accumulated_messages = []
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

                # Get agent from sub_session's agent registry
                agent = sub_session._get_agent("simple") if hasattr(sub_session, '_get_agent') else None
                if agent:
                    from sagents.session_runtime import session_scope
                    with session_scope(session_id):
                        response_stream = agent._call_llm_streaming(
                            messages=messages_input,
                            session_id=session_id,
                            step_name="sub_agent_fallback_summary"
                        )

                        summary_content = ""
                        async for chunk in response_stream:
                            if chunk.choices and chunk.choices[0].delta.content:
                                summary_content += chunk.choices[0].delta.content

                    sub_session.session_context.set_status(SessionStatus.COMPLETED)
                    return f"SubSessionID: {session_id}\nSub-agent finished without calling 'sys_finish_task'. AI Summary:\n{summary_content}"

            except Exception as e:
                sub_session.session_context.set_status(SessionStatus.ERROR)
                return f"Error generating summary: {e},{traceback.format_exc()}"

            # Fallback: return aggregated response
            # result_content = "".join([c.content for c in accumulated_chunks if c.content])
            # sub_session.update_status("completed")
            # return f"SubSessionID: {session_id}\nSub-agent finished without calling 'sys_finish_task'. Aggregated response:\n{result_content}"
            
        except Exception as e:
            logger.error(f"Error executing sub-agent task: {e}", exc_info=True)
            sub_session.session_context.set_status(SessionStatus.ERROR)
            return f"Error executing sub-agent task: {e},{traceback.format_exc()}"
        finally:
            # Save state via session_context
            if sub_session.session_context:
                sub_session.session_context.save()

    async def _get_or_create_sub_session(
        self,
        session_id: str,
        agent_id: str,
        parent_session_id: str
    ) -> Union[Session, str]:
        """
        Get existing Session or create a new one (replacing SubSession).
        
        Args:
            session_id: Session ID
            agent_id: Agent definition ID
            parent_session_id: Parent session ID
            
        Returns:
            Session instance or error message string
        """
        # Check if session already exists in global manager
        existing_session = self.session_manager.get(session_id)
        if existing_session:
            logger.warning(f"Session {session_id} already exists. Returning existing session.")
            return existing_session
        
        # Get agent definition
        if agent_id not in self.sub_agents:
            return f"Error: Agent '{agent_id}' not found"
        
        agent_def = self.sub_agents[agent_id]
        
        # Get parent session
        parent_session = self.session_manager.get(parent_session_id)
        
        # Prepare system_context with shared workspace
        # Use parent's sandbox_agent_workspace if available
        parent_sandbox_agent_workspace = None
        tool_manager = None
        skill_manager = None

        if parent_session:
            parent_sandbox_agent_workspace = parent_session.session_context.sandbox_agent_workspace
            parent_tool_manager = parent_session.session_context.tool_manager
            skill_manager = parent_session.session_context.skill_manager

            # 确保子会话有 tool_manager，继承父会话的工具
            if parent_tool_manager:
                # 检查父会话是否有 sys_finish_task
                parent_tools = parent_tool_manager.list_all_tools_name() if hasattr(parent_tool_manager, 'list_all_tools_name') else []
                if "sys_finish_task" not in parent_tools:
                    # 父会话没有 sys_finish_task，需要添加
                    fibre_tools_impl = FibreTools()
                    local_tool_manager = ToolManager(is_auto_discover=False, isolated=True)
                    local_tool_manager.register_tools_from_object(fibre_tools_impl)
                    if isinstance(parent_tool_manager, ToolManager):
                        tool_manager = ToolProxy([local_tool_manager, parent_tool_manager])
                    else:
                        tool_manager = ToolProxy([local_tool_manager] + parent_tool_manager.tool_managers)
                else:
                    # 父会话已有 sys_finish_task，直接继承
                    tool_manager = parent_tool_manager
            else:
                # 父会话没有 tool_manager，创建新的
                tool_manager = ToolManager()
                fibre_tools_impl = FibreTools()
                tool_manager.register_tools_from_object(fibre_tools_impl)

        else:
             # Handle orphaned sub-sessions (no parent)
             # For now we leave parent_sandbox_agent_workspace as None or we could initialize a new one if needed
             # parent_sandbox_agent_workspace = ...
             pass

        # Create sub-session via global manager
        # We pass the parent_session's session_space as the workspace root for the sub-session

        sub_session = self.session_manager.get_or_create(session_id, session_space=self.session_manager.session_root_space) # Pass root space
        sub_session.configure_runtime(
            model=self.agent.model,
            model_config=self.agent.model_config,
            system_prefix=agent_def.system_prompt or "",
            session_root_space=self.session_manager.session_root_space,
            sandbox_agent_workspace=parent_sandbox_agent_workspace
        )

        # Initialize context if needed
        # configure_runtime only sets parameters, we need to ensure context is created with those params
        # But _ensure_session_context is usually called inside run_stream.
        # However, for sub-session, we might want to ensure context structure NOW, especially for orchestrator linkage.
        
        # Let's manually ensure context, similar to run_stream logic but without execution
        sub_agent_system_context = copy.deepcopy(agent_def.system_context)
        
        # Inherit context_budget_config from parent session
        parent_context = parent_session.session_context if parent_session and parent_session.session_context else None
        # context_budget_config is passed to MessageManager, not stored in SessionContext
        context_budget_config = None
        
        # Merge parent session's system_context (excluding specific keys)
        if parent_context and parent_context.system_context:
            excluded_keys = {"todo_list", "session_id", "current_time"}
            for key, value in parent_context.system_context.items():
                if key not in excluded_keys and key not in sub_agent_system_context:
                    sub_agent_system_context[key] = copy.deepcopy(value)
        
        sub_session.session_context = await sub_session._ensure_session_context(
             session_id=session_id,
             user_id=parent_session.session_context.user_id if parent_session else "unknown",
             system_context=sub_agent_system_context,
             context_budget_config=context_budget_config,
             tool_manager=tool_manager,
             skill_manager=skill_manager,
             parent_session_id=parent_session_id
        )
        logger.info(f"[Orchestrator] Created sub-session {session_id} and system context {sub_session.session_context.system_context}")
        
        # Set agent_config with agent_id for Fibre (inherit from parent session)
        parent_agent_config = parent_session.session_context.agent_config if parent_session and parent_session.session_context else {}
        sub_session.session_context.set_agent_config(
            model=parent_agent_config.get("llm_config", {}).get("model") or self.agent.model,
            model_config=self.agent.model_config,
            system_prefix=agent_def.system_prompt or "",
            available_tools=parent_agent_config.get("available_tools", []),
            available_skills=parent_agent_config.get("available_skills", []),
            system_context=sub_agent_system_context,
            available_workflows=parent_agent_config.get("available_workflows", {}),
            deep_thinking=parent_agent_config.get("deep_thinking", False),
            agent_mode=parent_agent_config.get("agent_mode"),
            more_suggest=parent_agent_config.get("more_suggest", False),
            max_loop_count=parent_agent_config.get("max_loop_count"),
            agent_id=agent_id,
        )
        
        # Register orchestrator reference
        sub_session.session_context.orchestrator = self 

        return sub_session

    def get_session_hierarchy(self, session_id: str) -> Dict[str, Any]:
        """
        Get the session hierarchy tree starting from a session.
        
        Args:
            session_id: Root session ID
            
        Returns:
            Tree structure with session info and children
        """
        # SessionManager doesn't support get_by_parent directly yet
        # We need to iterate over sessions or add index to SessionManager
        # For now, let's iterate since sub_session_manager only holds sessions for this orchestrator
        
        session = self.session_manager.get(session_id)
        if not session:
            return {}
        
        # We need to know parent-child relationship.
        # SessionContext holds parent_session_id and child_session_ids
        # But we need access to SessionContext
        
        ctx = session.session_context
        if not ctx:
            return {}
            
        # Get status from context
        status = ctx.status.value if ctx.status else "unknown"
        
        # Get children
        children = []
        # Need to fix: SessionContext might not maintain child_session_ids automatically
        # Orchestrator logic should probably maintain this or we scan all sessions
        
        # Scan all sessions in manager to find children
        # This is inefficient but works for now
        # list_active_sessions returns dicts, not objects.
        # We need access to objects.

        # Let's rely on child_session_ids if it's maintained.
        # If not, we iterate self.session_manager._sessions (internal access)
        
        for s_id, sess in self.session_manager._sessions.items():
            if sess.session_context:
                parent_id = sess.session_context.system_context.get("parent_session_id")
                if parent_id == session_id:
                    children.append(self.get_session_hierarchy(s_id))
            
        return {
            "session_id": session_id,
            # "agent_id": session.agent_id, # Session object doesn't have agent_id directly, maybe in context or tags
            "status": status,
            "children": children
        }

    def interrupt_session(self, session_id: str) -> bool:
        """
        Interrupt a session and all its children.
        
        Args:
            session_id: Session ID to interrupt
            
        Returns:
            True if interrupted, False if not found
        """
        return self.session_manager.interrupt_session(session_id)
