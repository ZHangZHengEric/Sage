import time
import traceback
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from sagents.context.messages.message import MessageChunk, MessageType
from sagents.skill import SkillManager, SkillProxy
from sagents.tool import ToolManager, ToolProxy
from sagents.utils.logger import logger
from sagents.flow.schema import AgentFlow, SequenceNode, ParallelNode, AgentNode, IfNode, SwitchNode, LoopNode
from sagents.session_runtime import get_global_session_manager


class SAgent:
    def __init__(self, session_root_space: str, enable_obs: bool = True, use_sandbox: bool = True):
        self.session_root_space = str(session_root_space)
        self.enable_obs = enable_obs
        self.use_sandbox = use_sandbox
        self.session_manager = get_global_session_manager(session_root_space=self.session_root_space, enable_obs=enable_obs)

    async def run_stream(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        model: Any,
        model_config: Dict[str, Any],
        system_prefix: str,
        agent_workspace: str,
        default_memory_type: str,
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        deep_thinking: Optional[Union[bool, str]] = None,
        max_loop_count: int = 50,
        agent_mode: Optional[str] = None,
        more_suggest: bool = False,
        force_summary: bool = False,
        system_context: Optional[Dict[str, Any]] = None,
        available_workflows: Optional[Dict[str, Any]] = None,
        context_budget_config: Optional[Dict[str, Any]] = None,
        custom_sub_agents: Optional[List[Dict[str, Any]]] = None,
        custom_flow: Optional[AgentFlow] = None,
    ) -> AsyncGenerator[List["MessageChunk"], None]:
        if not model:
            raise ValueError("run_stream 参数 model 不能为空")
        if not isinstance(model_config, dict) or not model_config:
            raise ValueError("run_stream 参数 model_config 必须是非空字典")
        if agent_workspace is None or str(agent_workspace).strip() == "":
            raise ValueError("run_stream 参数 agent_workspace 不能为空")
        if default_memory_type is None or str(default_memory_type).strip() == "":
            raise ValueError("run_stream 参数 default_memory_type 不能为空")

        logger.info(f"run_stream: system_context: {system_context}")
        start_time = time.time()
        first_show_time = None

        if not session_id and input_messages:
            first_msg = input_messages[0]
            if isinstance(first_msg, MessageChunk) and first_msg.session_id:
                session_id = first_msg.session_id
            elif isinstance(first_msg, dict) and first_msg.get("session_id"):
                session_id = first_msg.get("session_id")
        session_id = session_id or str(uuid.uuid4())

        for msg in input_messages:
            if isinstance(msg, MessageChunk) and not msg.session_id:
                msg.session_id = session_id
            elif isinstance(msg, dict) and not msg.get("session_id"):
                msg["session_id"] = session_id

        session = self.session_manager.get_or_create(session_id, use_sandbox=self.use_sandbox)
        session.configure_runtime(
            model=model,
            model_config=model_config,
            system_prefix=system_prefix,
            session_root_space=self.session_root_space,
            agent_workspace=str(agent_workspace),
            default_memory_type=default_memory_type,
        )

        if session.observability_manager:
            session.observability_manager.on_chain_start(session_id=session_id, input_data=input_messages)

        # 构建执行流程
        flow = custom_flow
        if flow is None:
            flow = self._build_default_flow(agent_mode=agent_mode, max_loop_count=max_loop_count)
            
        async for message_chunks in session.run_stream_safe(
                input_messages=input_messages,
                flow=flow,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                session_id=session_id,
                user_id=user_id,
                deep_thinking=deep_thinking,
                max_loop_count=max_loop_count,
                agent_mode=agent_mode,
                more_suggest=more_suggest,
                force_summary=force_summary,
                system_context=system_context,
                available_workflows=available_workflows or {},
                context_budget_config=context_budget_config,
                custom_sub_agents=custom_sub_agents,
            ):
            for message_chunk in message_chunks:
                if not message_chunk.session_id:
                    message_chunk.session_id = session_id
                if first_show_time is None:
                    try:
                        content = message_chunk.content
                        if content and str(content).strip():
                            first_show_time = time.time()
                            delta_ms = int((first_show_time - start_time) * 1000)
                            logger.info(f"SAgent: 会话首个可显示内容耗时 {delta_ms} ms")
                    except Exception as e:
                        logger.error(f"SAgent: 统计首个content耗时出错: {e}\n{traceback.format_exc()}")
                if message_chunk.content or message_chunk.tool_calls or message_chunk.type == MessageType.TOKEN_USAGE.value:
                    yield [message_chunk]

        total_ms = int((time.time() - start_time) * 1000)
        logger.info(f"SAgent: 会话完整执行耗时 {total_ms} ms", session_id)
        self.session_manager.close_session(session_id)

    def _build_default_flow(self, agent_mode: Optional[str], max_loop_count: int = 20) -> AgentFlow:
        """构建默认的执行流程，兼容原有逻辑"""
        
        # 1. 任务路由
        steps = [AgentNode(agent_key="task_router")]
        
        # 2. 深度思考 (可选)
        steps.append(IfNode(
            condition="is_deep_thinking",
            true_body=AgentNode(agent_key="task_analysis")
        ))
        
        # 3. 模式选择 (Switch)
        # 预定义多智能体循环体
        multi_agent_body = SequenceNode(steps=[
             AgentNode(agent_key="task_planning"),
             AgentNode(agent_key="tool_suggestion"),
             AgentNode(agent_key="task_executor"),
             AgentNode(agent_key="task_observation"),
             AgentNode(agent_key="task_completion_judge")
        ])

        # 预定义多智能体完整流程（包含总结）
        multi_agent_full = SequenceNode(steps=[
            AgentNode(agent_key="memory_recall"),
            LoopNode(
                condition="task_not_completed",
                max_loops=max_loop_count,
                body=multi_agent_body
            ),
            AgentNode(agent_key="task_summary")
        ])

        # 预定义简单模式
        simple_agent_body = SequenceNode(steps=[
            ParallelNode(branches=[
                AgentNode(agent_key="tool_suggestion"),
                AgentNode(agent_key="memory_recall"),
            ]),
            AgentNode(agent_key="simple"),
            IfNode(condition="need_summary", true_body=AgentNode(agent_key="task_summary"))
        ])

        fib_agent_body = SequenceNode(steps=[
            ParallelNode(branches=[
                AgentNode(agent_key="tool_suggestion"),
                AgentNode(agent_key="memory_recall"),
            ]),
            AgentNode(agent_key="fibre"),
        ])

        # 如果传入了 agent_mode，我们仍然使用 SwitchNode，因为 agent_mode 可能会在运行时被 Router 修改
        # 但我们需要确保 agent_mode 的默认值被正确处理
        # 这里 SwitchNode 的 variable 是 "agent_mode"，它会从 audit_status 或 system_context 中读取
        # run_stream_with_flow 会将传入的 agent_mode 设置到 audit_status 中
        
        steps.append(SwitchNode(
            variable="agent_mode",
            cases={
                "fibre": fib_agent_body,
                "simple": simple_agent_body,
                "multi": multi_agent_full
            },
            default=simple_agent_body # 默认为 simple
        ))
        
        # 4. 更多建议 (可选)
        steps.append(IfNode(
            condition="enable_more_suggest",
            true_body=AgentNode(agent_key="query_suggest")
        ))
        
        return AgentFlow(
            name="Standard Hybrid Flow",
            root=SequenceNode(steps=steps)
        )

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.session_manager.get_session_status(session_id)

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        return self.session_manager.list_active_sessions()

    def cleanup_session(self, session_id: str) -> bool:
        self.session_manager.close_session(session_id)
        return True

    def save_session(self, session_id: str) -> bool:
        return self.session_manager.save_session(session_id)

    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        return self.session_manager.interrupt_session(session_id, message=message)

    def get_tasks_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.session_manager.get_tasks_status(session_id)
