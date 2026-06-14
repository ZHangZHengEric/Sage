from __future__ import annotations

import asyncio
import copy
import traceback
from typing import Any, AsyncGenerator, Dict, List, Optional

from sagents.agent.fibre.agent_definition import AgentDefinition
from sagents.agent.fibre.backend_client import FibreBackendClient
from sagents.agent.fibre.orchestrator import FibreOrchestrator
from sagents.agent.simple_agent import SimpleAgent
from sagents.agent.team.tools import TeamTools
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.messages.message_manager import MessageManager
from sagents.flow.schema import AgentFlow, AgentNode, SequenceNode
from sagents.context.session_context import SessionContext, SessionStatus
from sagents.observability import AgentRuntime
from sagents.skill import SkillProxy
from sagents.tool import ToolManager, ToolProxy
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager
from sagents.utils.subtask_summary import summarize_subtask_history


class TeamOrchestrator(FibreOrchestrator):
    """Orchestrator for Team mode.

    Team mode reuses Fibre's mature delegation/session execution machinery, but
    changes the contract:
    - no agent creation
    - only existing configured/backend agents can be members
    - backend member calls inherit the leader workspace through system_context
    """

    def __init__(self, agent, observability_manager=None):
        super().__init__(agent=agent, observability_manager=observability_manager)
        self.backend_client = FibreBackendClient()

    async def spawn_agent(self, *args, **kwargs) -> str:  # pyright: ignore[reportIncompatibleMethodOverride]
        return (
            "Error: Team mode does not allow creating new agents. "
            "Please delegate only to existing team members."
        )

    async def run_loop(
        self,
        session_context: SessionContext,
        max_loop_count: int,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        output_queue: asyncio.Queue[Optional[List[MessageChunk]]] = asyncio.Queue()
        self.output_queue = output_queue

        session_context.orchestrator = self
        main_session = self.session_manager.get(session_context.session_id)
        if main_session is None:
            raise RuntimeError(
                f"TeamOrchestrator: main session not found, session_id={session_context.session_id}"
            )

        await self._load_team_members(session_context)

        try:
            main_session.set_status(SessionStatus.RUNNING)

            team_prompt = self._get_team_system_prompt_content(
                session_context=session_context,
                custom_system_prompt=self.agent.system_prefix or "",
            )

            if session_context.tool_manager:
                session_context.tool_manager.register_tools_from_object(TeamTools())

            container_agent = SimpleAgent(
                self.agent.model, self.agent.model_config, system_prefix=team_prompt
            )
            container_agent.agent_name = getattr(self.agent, "agent_name", "TeamAgent")

            if self.observability_manager:
                container_agent = AgentRuntime(
                    container_agent, self.observability_manager
                )

            if session_context.agent_config is None:
                session_context.agent_config = {}
            session_context.agent_config["max_loop_count"] = max_loop_count

            async def run_container_stream():
                try:
                    async for chunks in container_agent.run_stream(
                        session_context=session_context,
                    ):
                        await output_queue.put(chunks)
                except Exception as e:
                    logger.error(f"Error in team container stream: {e}", exc_info=True)
                    raise
                finally:
                    await output_queue.put(None)

            producer_task = asyncio.create_task(run_container_stream())

            try:
                while True:
                    if main_session.should_interrupt():
                        logger.warning(
                            f"TeamOrchestrator: session {session_context.session_id} interrupted, stopping producer"
                        )
                        if not producer_task.done():
                            producer_task.cancel()
                        break
                    chunks = await output_queue.get()
                    if chunks is None:
                        break
                    if main_session.should_interrupt():
                        if not producer_task.done():
                            producer_task.cancel()
                        break
                    yield chunks

                if not producer_task.done():
                    await producer_task

                if main_session.should_interrupt():
                    main_session.set_status(SessionStatus.INTERRUPTED, cascade=False)

            except asyncio.CancelledError:
                main_session.set_status(SessionStatus.INTERRUPTED, cascade=False)
                if not producer_task.done():
                    producer_task.cancel()
                raise
            except Exception:
                main_session.set_status(SessionStatus.ERROR, cascade=False)
                if not producer_task.done():
                    producer_task.cancel()
                raise
        finally:
            try:
                if main_session and hasattr(main_session, "save_state"):
                    main_session.save_state()  # pyright: ignore[reportAttributeAccessIssue]
            except Exception as e:
                logger.debug(f"TeamOrchestrator: save_state failed: {e}")

    async def _load_team_members(self, session_context: SessionContext) -> None:
        configured_members = self._get_configured_team_members(session_context)
        current_agent_id = (
            session_context.agent_config.get("agent_id")
            if session_context.agent_config
            else None
        )
        user_id = getattr(session_context, "user_id", None)

        session_context.system_context["available_sub_agents"] = []
        self.sub_agents.clear()

        for member_cfg in configured_members or []:
            member = await self._resolve_existing_member(member_cfg, user_id=user_id)
            if not member:
                continue

            agent_id = member["agent_id"]
            if not agent_id or agent_id == current_agent_id:
                continue
            name = self._resolve_agent_name(member, agent_id)
            description = member.get("description", "")
            self.sub_agents[agent_id] = AgentDefinition(
                agent_id=agent_id,
                name=name,
                description=description,
                system_prompt=member.get("system_prompt", "") or "",
                available_tools=member.get("available_tools"),
                available_skills=member.get("available_skills"),
                available_workflows=member.get("available_workflows"),
                system_context=member.get("system_context"),
                backend_stored=bool(member.get("backend_stored")),
            )
            session_context.system_context["available_sub_agents"].append(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "description": description,
                }
            )

        logger.info(
            f"TeamOrchestrator: loaded {len(self.sub_agents)} existing team members"
        )

    @staticmethod
    def _get_configured_team_members(session_context: SessionContext) -> List[Any]:
        if getattr(session_context, "custom_sub_agents", None) is not None:
            return list(getattr(session_context, "custom_sub_agents") or [])
        agent_config = session_context.agent_config or {}
        if "custom_sub_agents" in agent_config:
            return list(agent_config.get("custom_sub_agents") or [])
        system_context = session_context.system_context or {}
        if "custom_sub_agents" in system_context:
            return list(system_context.get("custom_sub_agents") or [])
        return []

    async def _resolve_existing_member(
        self, member_cfg: Any, *, user_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if isinstance(member_cfg, dict):
            agent_id = member_cfg.get("agent_id") or member_cfg.get("id")
            base = dict(member_cfg)
        else:
            agent_id = getattr(member_cfg, "agent_id", None) or getattr(
                member_cfg, "id", None
            )
            base = {
                "agent_id": agent_id,
                "name": getattr(member_cfg, "name", ""),
                "description": getattr(member_cfg, "description", ""),
                "system_prompt": getattr(member_cfg, "system_prompt", ""),
                "available_tools": getattr(member_cfg, "available_tools", None),
                "available_skills": getattr(member_cfg, "available_skills", None),
                "available_workflows": getattr(member_cfg, "available_workflows", None),
                "system_context": getattr(member_cfg, "system_context", None),
                "agent_mode": getattr(member_cfg, "agent_mode", None)
                or getattr(member_cfg, "agentMode", None),
            }

        if not agent_id:
            logger.warning("TeamOrchestrator: skipping member without agent_id")
            return None

        backend_agent = None
        if self.backend_client and await self.backend_client.check_health():
            backend_agent = await self.backend_client.get_agent(
                agent_id, user_id=user_id
            )

        if backend_agent:
            backend_system_context = (
                backend_agent.get("systemContext")
                or backend_agent.get("system_context")
                or base.get("system_context")
                or {}
            )
            if isinstance(backend_system_context, dict):
                backend_system_context = copy.deepcopy(backend_system_context)
                backend_system_context["agent_mode"] = (
                    backend_agent.get("agentMode")
                    or backend_agent.get("agent_mode")
                    or base.get("agent_mode")
                    or backend_system_context.get("agent_mode")
                )
            return {
                "agent_id": backend_agent.get("agent_id")
                or backend_agent.get("id")
                or agent_id,
                "name": backend_agent.get("name") or base.get("name"),
                "description": backend_agent.get("description")
                or base.get("description", ""),
                "system_prompt": backend_agent.get("systemPrefix")
                or backend_agent.get("system_prompt")
                or base.get("system_prompt", ""),
                "available_tools": backend_agent.get("availableTools")
                or backend_agent.get("available_tools")
                or base.get("available_tools"),
                "available_skills": backend_agent.get("availableSkills")
                or backend_agent.get("available_skills")
                or base.get("available_skills"),
                "available_workflows": backend_agent.get("availableWorkflows")
                or backend_agent.get("available_workflows")
                or base.get("available_workflows"),
                "system_context": backend_system_context,
                "backend_stored": True,
            }

        # If backend is unavailable, allow explicit in-memory definitions supplied
        # by tests/SDK callers. Team mode still does not create agents.
        explicit_system_context = copy.deepcopy(base.get("system_context") or {})
        if isinstance(explicit_system_context, dict) and base.get("agent_mode"):
            explicit_system_context["agent_mode"] = base.get("agent_mode")
        return {
            "agent_id": agent_id,
            "name": base.get("name") or base.get("display_name") or agent_id,
            "description": base.get("description", ""),
            "system_prompt": base.get("system_prompt", ""),
            "available_tools": base.get("available_tools"),
            "available_skills": base.get("available_skills"),
            "available_workflows": base.get("available_workflows"),
            "system_context": explicit_system_context,
            "backend_stored": False,
        }

    def _get_team_system_prompt_content(
        self,
        session_context: SessionContext,
        custom_system_prompt: str = "",
    ) -> str:
        lang = (
            session_context.get_language()
            if hasattr(session_context, "get_language")
            else "en"
        )
        pm = PromptManager()
        localized_desc = pm.get_prompt(
            "team_agent_description", agent="TeamAgent", language=lang
        )
        team_mechanics = pm.get_prompt(
            "team_system_prompt", agent="TeamAgent", language=lang
        )
        parts = []
        if custom_system_prompt.strip():
            parts.append(custom_system_prompt.strip())
        else:
            parts.append(localized_desc)
        parts.append(team_mechanics)
        return "\n\n".join(p for p in parts if p)

    async def _delegate_task_via_backend(
        self,
        agent_id: str,
        content: str,
        session_id: str,
        caller_session_id: str,
        task_name: str,
        original_task: str,
    ) -> str:
        parent_session = self.sub_session_manager.get(caller_session_id)
        parent_session_context = (
            parent_session.session_context if parent_session else None
        )
        if parent_session_context:
            team_workspace = parent_session_context.sandbox_agent_workspace
        else:
            team_workspace = "/sage-workspace"

        original_task_section = (
            f"【用户最初任务需求】\n{original_task}\n\n" if original_task else ""
        )
        enhanced_content = f"""【消息发送方】
此任务由 Team Leader 发送给你。你是已有 Team Member，请在 Team Leader 的共享工作空间中完成任务。

{original_task_section}【你本次需要完成的子任务】
{content}

【Team 共享工作空间】
共享工作空间：{team_workspace}
"""

        messages = [{"role": "user", "content": enhanced_content}]
        system_context: Dict[str, Any] = {}
        if parent_session_context and hasattr(parent_session_context, "system_context"):
            parent_ctx = copy.deepcopy(parent_session_context.system_context)
            for key in (
                "task_workspace",
                "timestamp",
                "start_time",
                "created_at",
                "session_id",
                "parent_session_id",
                "当前AgentId",
                "custom_sub_agents",
                "available_sub_agents",
            ):
                parent_ctx.pop(key, None)
            system_context.update(parent_ctx)

        system_context["team_workspace"] = team_workspace
        system_context["team_workspace_mode"] = True
        system_context["session_id"] = session_id
        system_context["parent_session_id"] = caller_session_id

        user_id = (
            getattr(parent_session_context, "user_id", None)
            if parent_session_context
            else None
        )
        if user_id:
            system_context["user_id"] = user_id

        try:
            all_content_chunks: List[MessageChunk] = []
            async for chunks in self.backend_client.stream_chat(
                agent_id=agent_id,
                messages=messages,
                session_id=session_id,
                system_context=system_context,
                user_id=user_id,
                max_loop_count=parent_session_context.agent_config.get("max_loop_count")
                if parent_session_context
                else None,
                interrupt_event=parent_session.interrupt_event
                if parent_session
                else None,
            ):
                if parent_session and parent_session.should_interrupt():
                    await self.backend_client.interrupt_session(
                        session_id, user_id=user_id
                    )
                    break
                all_content_chunks.extend(
                    [
                        chunk
                        for chunk in chunks
                        if chunk.session_id == session_id
                        and chunk.role == MessageRole.ASSISTANT.value
                        and chunk.content
                        and chunk.type not in ("token_usage", "stream_end")
                    ]
                )

            if parent_session and parent_session.should_interrupt():
                return f"SubSessionID: {session_id}\nInterrupted by parent session"

            accumulated_messages = MessageManager.merge_new_messages_to_old_messages(
                all_content_chunks, []
            )
            history_str = MessageManager.convert_messages_to_str(accumulated_messages)
            return await summarize_subtask_history(
                agent=self.agent,
                session_id=session_id,
                summary_session_id=caller_session_id,
                history_str=history_str,
                language=parent_session_context.get_language()
                if parent_session_context
                and hasattr(parent_session_context, "get_language")
                else "en",
                task_description=content,
                subject_label="Team member",
                step_name="team_member_summary",
                empty_message=f"SubSessionID: {session_id}\nNo response from team member",
            )

        except Exception as e:
            logger.error(
                f"Team backend API call failed: {e}, falling back to internal execution"
            )
            return await self._delegate_task_internal(
                agent_id=agent_id,
                content=content,
                session_id=session_id,
                caller_session_id=caller_session_id,
                task_name=task_name,
                original_task=original_task,
            )

    async def _delegate_task_internal(
        self,
        agent_id: str,
        content: str,
        session_id: str,
        caller_session_id: str,
        task_name: str,
        original_task: str,
    ) -> str:
        sub_session = await self._get_or_create_sub_session(
            session_id=session_id,
            agent_id=agent_id,
            parent_session_id=caller_session_id,
        )
        if isinstance(sub_session, str):
            return sub_session

        original_task_section = (
            f"【用户最初任务需求】\n{original_task}\n\n" if original_task else ""
        )
        team_workspace = sub_session.session_context.sandbox_agent_workspace  # pyright: ignore[reportOptionalMemberAccess]
        enhanced_content = f"""{original_task_section}【你本次需要完成的 Team 子任务】
{content}

【Team 共享工作空间】
共享工作空间：{team_workspace}
"""
        input_messages = [
            MessageChunk(
                role=MessageRole.USER.value,
                content=enhanced_content,
                session_id=session_id,
            )
        ]

        sub_session.set_status(SessionStatus.RUNNING)
        all_filtered_chunks = []

        try:
            member_mode = sub_session.session_context.agent_config.get(  # pyright: ignore[reportOptionalMemberAccess]
                "agent_mode", "simple"
            )
            member_agent_key = (
                member_mode if member_mode in {"simple", "team", "fibre"} else "simple"
            )
            member_flow = AgentFlow(
                name=f"Team Member Flow - {agent_id}",
                root=SequenceNode(steps=[AgentNode(agent_key=member_agent_key)]),
            )

            async for chunks in sub_session.run_stream_with_flow(
                input_messages=input_messages,
                flow=member_flow,
                tool_manager=sub_session.session_context.tool_manager,  # pyright: ignore[reportOptionalMemberAccess]
                skill_manager=sub_session.session_context.skill_manager,  # pyright: ignore[reportOptionalMemberAccess]
                session_id=session_id,
                max_loop_count=sub_session.session_context.agent_config.get(  # pyright: ignore[reportOptionalMemberAccess]
                    "max_loop_count"
                ),
                deep_thinking=sub_session.session_context.agent_config.get(  # pyright: ignore[reportOptionalMemberAccess]
                    "deep_thinking", False
                ),
                agent_mode=member_mode,
            ):
                if sub_session.should_interrupt():
                    break
                filtered_chunks = [
                    c
                    for c in chunks
                    if c.session_id == session_id
                    and c.role == MessageRole.ASSISTANT.value
                ]
                if filtered_chunks:
                    all_filtered_chunks.extend(filtered_chunks)

            if sub_session.should_interrupt():
                return f"SubSessionID: {session_id}\nInterrupted by parent session"

            accumulated_messages = []
            if all_filtered_chunks:
                accumulated_messages = (
                    MessageManager.merge_new_messages_to_old_messages(
                        all_filtered_chunks, []
                    )
                )
            history_str = MessageManager.convert_messages_to_str(accumulated_messages)
            sub_session.set_status(SessionStatus.COMPLETED)
            return await summarize_subtask_history(
                agent=self.agent,
                session_id=session_id,
                summary_session_id=caller_session_id,
                history_str=history_str,
                language=sub_session.session_context.get_language()  # pyright: ignore[reportOptionalMemberAccess]
                if hasattr(sub_session.session_context, "get_language")
                else "en",
                task_description=content,
                subject_label="Team member",
                step_name="team_member_summary",
                empty_message=f"SubSessionID: {session_id}\nNo response from team member",
            )

        except asyncio.CancelledError:
            sub_session.request_interrupt("父会话中断", cascade=False)
            raise
        except Exception as e:
            logger.error(f"Error executing team member task: {e}", exc_info=True)
            sub_session.set_status(SessionStatus.ERROR)
            return f"Error executing team member task: {e},{traceback.format_exc()}"
        finally:
            if sub_session.session_context:
                await asyncio.to_thread(
                    sub_session.session_context.save,
                    session_status=sub_session.get_status(),
                    child_session_ids=list(sub_session.child_session_ids),
                    interrupt_reason=sub_session.interrupt_reason,
                )

    async def _get_or_create_sub_session(
        self, session_id: str, agent_id: str, parent_session_id: str
    ):
        existing_session = self.session_manager.get_live_session(session_id)
        if existing_session:
            return existing_session

        if agent_id not in self.sub_agents:
            return f"Error: Agent '{agent_id}' not found"

        agent_def = self.sub_agents[agent_id]
        parent_session = self.session_manager.get_live_session(parent_session_id)
        parent_workspace = None
        tool_manager = None
        skill_manager = None

        if parent_session and parent_session.session_context:
            parent_workspace = parent_session.session_context.sandbox_agent_workspace
            parent_tool_manager = parent_session.session_context.tool_manager
            parent_skill_manager = parent_session.session_context.skill_manager
            skill_manager = parent_skill_manager
            if agent_def.available_skills and parent_skill_manager is not None:
                skill_manager = SkillProxy(
                    parent_skill_manager,
                    agent_def.available_skills,
                )
            local_tool_manager = ToolManager(is_auto_discover=False, isolated=True)
            local_tool_manager.register_tools_from_object(TeamTools())
            if parent_tool_manager:
                if isinstance(parent_tool_manager, ToolManager):
                    tool_manager = ToolProxy([local_tool_manager, parent_tool_manager])
                else:
                    tool_manager = ToolProxy(
                        [local_tool_manager] + parent_tool_manager.tool_managers
                    )
            else:
                tool_manager = local_tool_manager

        sub_session = self.session_manager.get_or_create(
            session_id, session_space=self.session_manager.session_root_space
        )
        sub_session.configure_runtime(
            model=self.agent.model,
            model_config=self.agent.model_config,
            system_prefix=agent_def.system_prompt or "",
            session_root_space=self.session_manager.session_root_space,
            sandbox_agent_workspace=parent_workspace,
        )

        sub_agent_system_context = copy.deepcopy(agent_def.system_context or {})
        parent_context = (
            parent_session.session_context
            if parent_session and parent_session.session_context
            else None
        )
        if parent_context and parent_context.system_context:
            excluded_keys = {"todo_list", "session_id", "current_time"}
            for key, value in parent_context.system_context.items():
                if key not in excluded_keys and key not in sub_agent_system_context:
                    sub_agent_system_context[key] = copy.deepcopy(value)
        sub_agent_system_context["team_workspace"] = parent_workspace
        sub_agent_system_context["team_workspace_mode"] = True

        sub_session.session_context = await sub_session._ensure_session_context(
            session_id=session_id,
            user_id=parent_session.session_context.user_id  # pyright: ignore[reportOptionalMemberAccess]
            if parent_session
            else "unknown",
            system_context=sub_agent_system_context,
            context_budget_config=None,
            tool_manager=tool_manager,
            skill_manager=skill_manager,
            parent_session_id=parent_session_id,
        )

        if parent_session:
            parent_session.add_child_session(session_id)

        parent_agent_config = (
            parent_session.session_context.agent_config
            if parent_session and parent_session.session_context
            else {}
        )
        member_mode = (
            sub_agent_system_context.get("agent_mode")
            or sub_agent_system_context.get("agentMode")
            or "simple"
        )
        if member_mode not in {"simple", "team", "fibre"}:
            member_mode = "simple"
        sub_session.session_context.set_agent_config(
            model=parent_agent_config.get("llm_config", {}).get("model")
            or self.agent.model,
            model_config=self.agent.model_config,
            system_prefix=agent_def.system_prompt or "",
            available_tools=agent_def.available_tools
            or parent_agent_config.get("available_tools", []),
            available_skills=skill_manager.list_skills() if skill_manager else [],
            system_context=sub_agent_system_context,
            available_workflows=agent_def.available_workflows
            or parent_agent_config.get("available_workflows", {}),
            deep_thinking=parent_agent_config.get("deep_thinking", False),
            agent_mode=member_mode,
            more_suggest=parent_agent_config.get("more_suggest", False),
            max_loop_count=parent_agent_config.get("max_loop_count"),
            agent_id=agent_id,
        )
        sub_session.session_context.orchestrator = self
        return sub_session
