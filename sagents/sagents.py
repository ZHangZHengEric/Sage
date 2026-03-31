import os
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
from sagents.utils.sandbox.config import VolumeMount


class SAgent:
    def __init__(self, session_root_space: str, enable_obs: bool = True, sandbox_type: Optional[str] = None):
        self.session_root_space = str(session_root_space)
        self.enable_obs = enable_obs
        # 优先使用传入的参数，其次从环境变量读取，默认使用 local
        self.sandbox_type = sandbox_type or os.environ.get("SAGE_SANDBOX_MODE", "local")
        self.session_manager = get_global_session_manager(session_root_space=self.session_root_space, enable_obs=enable_obs)

    async def run_stream(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        model: Any,
        model_config: Dict[str, Any],
        system_prefix: str,
        default_memory_type: str,
        # 沙箱核心配置
        sandbox_type: Optional[str] = None,
        sandbox_agent_workspace: Optional[str] = None,
        volume_mounts: Optional[List[VolumeMount]] = None,
        sandbox_id: Optional[str] = None,
        # 其他参数
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
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
        """执行流式对话会话

        该方法启动一个 Agent 会话，处理输入消息并返回流式响应。
        支持多种沙箱模式（本地、远程、直通），可配置工具、技能、工作流等。

        Args:
            input_messages: 输入消息列表，可以是字典列表或 MessageChunk 对象列表
                示例: [{"role": "user", "content": "你好"}]
            model: LLM 模型客户端，必须提供
            model_config: 模型配置字典，必须包含 model、api_key、base_url 等
            system_prefix: 系统提示词前缀，用于定义 Agent 行为
            default_memory_type: 默认记忆类型，可选 "session" | "user" | "none"

            # 沙箱核心配置
            sandbox_type: 沙箱类型，可选 "local" | "remote" | "passthrough"
                - local: 本地沙箱，使用 venv + 进程隔离（推荐生产环境）
                - remote: 远程沙箱，使用 OpenSandbox 等远程服务
                - passthrough: 直通模式，无隔离，直接使用系统环境
            sandbox_agent_workspace: Agent 工作空间路径（沙箱内路径，所有模式必需）
                - 沙箱内 Agent 的工作目录，用于文件读写等操作
                - 示例: "/Users/xxx/.sage/agents/agent_001"
            volume_mounts: 卷挂载配置列表，用于映射宿主机路径到沙箱内
                - local/passthrough 模式下用于路径映射
                - remote 模式下可能不被支持
                - 示例: [VolumeMount("/host/data", "/sandbox/data")]
            sandbox_id: 远程沙箱 ID（remote 模式使用已有沙箱时）
                - 如果提供，连接到已有的远程沙箱
                - 如果不提供，将创建新的远程沙箱实例
                - 示例: "opensandbox-abc123"

            # 可选配置
            tool_manager: 工具管理器，控制 Agent 可调用的工具
            skill_manager: 技能管理器，控制 Agent 可使用的技能
            session_id: 会话 ID，用于持久化和恢复会话状态
            user_id: 用户 ID，用于多租户场景
            agent_id: Agent ID，用于标识当前 Agent
            deep_thinking: 是否启用深度思考模式
            max_loop_count: 最大循环次数，防止无限循环
            agent_mode: Agent 模式，可选 "simple" | "multi" | "fibre"
            more_suggest: 是否启用更多建议功能
            force_summary: 是否强制生成总结
            system_context: 系统上下文字典，注入额外信息到提示词
            available_workflows: 可用工作流配置
            context_budget_config: 上下文预算配置，控制 token 使用
            custom_sub_agents: 自定义子 Agent 配置列表
            custom_flow: 自定义执行流程（AgentFlow）

        Returns:
            异步生成器，产生 MessageChunk 列表

        Raises:
            ValueError: 当必需参数缺失或无效时

        Examples:
            # 本地沙箱模式（推荐）
            async for chunks in agent.run_stream(
                input_messages=[{"role": "user", "content": "你好"}],
                model=client,
                model_config={"model": "gpt-4", "api_key": "xxx"},
                system_prefix="你是一个助手",
                default_memory_type="session",
                sandbox_agent_workspace="/Users/xxx/.sage/agents/agent_001",
                volume_mounts=[VolumeMount("/host/data", "/sandbox/data")],
            ):
                for chunk in chunks:
                    print(chunk.content)

            # 远程沙箱模式
            async for chunks in agent.run_stream(
                input_messages=messages,
                model=client,
                model_config=config,
                system_prefix="你是一个助手",
                default_memory_type="session",
                sandbox_type="remote",
                sandbox_agent_workspace="/sage-workspace",  # 远程沙箱内的工作路径
                sandbox_id="opensandbox-abc123",  # 可选：连接已有沙箱
            ):
                ...
        """
        if not model:
            raise ValueError("run_stream 参数 model 不能为空")
        if not isinstance(model_config, dict) or not model_config:
            raise ValueError("run_stream 参数 model_config 必须是非空字典")
        if default_memory_type is None or str(default_memory_type).strip() == "":
            raise ValueError("run_stream 参数 default_memory_type 不能为空")
        default_memory_type = "session"
        
        # 确定沙箱类型（优先级：参数 > __init__ > 环境变量 > 默认）
        effective_sandbox_type = (
            sandbox_type or
            self.sandbox_type or
            os.environ.get("SAGE_SANDBOX_MODE", "local")
        )

        # 确保 volume_mounts 是列表
        if volume_mounts is None:
            volume_mounts = []

        # 根据沙箱类型验证参数
        if effective_sandbox_type == "local":
            # local 模式必须有 sandbox_agent_workspace
            if not sandbox_agent_workspace:
                raise ValueError("local 沙箱模式需要提供 sandbox_agent_workspace 参数")

        elif effective_sandbox_type == "remote":
            # remote 模式默认使用远程工作区根目录；sandbox_id 可选，不传时由 SessionContext 回退生成
            if not sandbox_agent_workspace:
                sandbox_agent_workspace = "/sage-workspace"

        elif effective_sandbox_type == "passthrough":
            # passthrough 模式必须有 sandbox_agent_workspace
            if not sandbox_agent_workspace:
                raise ValueError("passthrough 沙箱模式需要提供 sandbox_agent_workspace 参数")

        logger.info(f"run_stream: sandbox_type={effective_sandbox_type}, "
                   f"sandbox_id={sandbox_id}, "
                   f"volume_mounts_count={len(volume_mounts)}")
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

        session = self.session_manager.get_or_create(session_id, sandbox_type=effective_sandbox_type)
        session.configure_runtime(
            model=model,
            model_config=model_config,
            system_prefix=system_prefix,
            session_root_space=self.session_root_space,
            sandbox_agent_workspace=sandbox_agent_workspace,
            volume_mounts=volume_mounts,
            sandbox_id=sandbox_id,
            default_memory_type=default_memory_type,
            agent_id=agent_id,
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
            IfNode(
                condition="enable_plan",
                true_body=SequenceNode(steps=[
                    AgentNode(agent_key="plan"),
                    IfNode(
                        condition="plan_should_start_execution",
                        true_body=AgentNode(agent_key="fibre"),
                    ),
                ]),
                false_body=AgentNode(agent_key="fibre"),
            ),
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
