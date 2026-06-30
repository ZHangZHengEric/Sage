import asyncio
from typing import AsyncGenerator, List, Any, Optional
from sagents.flow.schema import (
    FlowNode,
    AgentNode,
    SequenceNode,
    ParallelNode,
    LoopNode,
    IfNode,
    SwitchNode,
)
from sagents.flow.conditions import ConditionRegistry
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionStatus


class _FlowExecutionTrace:
    def __init__(self) -> None:
        self.events: List[str] = []

    def add(self, event: str) -> None:
        self.events.append(event)

    def emit(self) -> None:
        if self.events:
            logger.info("FlowExecutor: Trace " + " -> ".join(self.events))


class FlowExecutor:
    """流程执行器：负责解析并执行 AgentFlow 定义"""

    def __init__(
        self,
        tool_manager: Optional[Any],
        session_runtime: Any,
        session_id: str,
        session_manager: Any,
    ):
        self.tool_manager = tool_manager
        self.runtime = session_runtime
        self.session_id = session_id
        self.session_manager = session_manager

        # 注册 ToDoTool 用于多智能体任务检查
        # self._todo_tool = ToDoTool()
        # if self.tool_manager:
        #     self.tool_manager.register_tools_from_object(self._todo_tool)

    @staticmethod
    def _is_terminal_session_state(session: Any) -> bool:
        try:
            return session.get_status() in {
                SessionStatus.INTERRUPTED,
                SessionStatus.ERROR,
            }
        except Exception:
            return False

    def _should_stop_now(self, session: Any, node_name: str) -> bool:
        if session.should_interrupt():
            logger.info(
                f"FlowExecutor: session {self.session_id} interrupted before executing {node_name}"
            )
            return True
        if self._is_terminal_session_state(session):
            logger.info(
                f"FlowExecutor: session {self.session_id} already in terminal state "
                f"{session.get_status().value}, stop executing {node_name}"
            )
            return True
        return False

    async def execute(self, node: FlowNode) -> AsyncGenerator[List[MessageChunk], None]:
        trace = _FlowExecutionTrace()
        try:
            async for chunk in self._execute_node(node, trace):
                yield chunk
        finally:
            trace.emit()

    async def _execute_node(
        self, node: FlowNode, trace: _FlowExecutionTrace
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """递归执行流程节点"""
        if self.session_manager is None:
            raise RuntimeError(
                f"FlowExecutor: session_manager 未初始化，session_id={self.session_id}"
            )
        session = self.session_manager.get_live_session(self.session_id)
        if session is None:
            raise RuntimeError(
                f"FlowExecutor: session 未绑定，session_id={self.session_id}"
            )
        ctx = session.get_context()
        if ctx is None:
            raise RuntimeError(
                f"FlowExecutor: session_context 未绑定，session_id={self.session_id}"
            )
        if self._should_stop_now(session, getattr(node, "node_type", "unknown")):
            return

        if isinstance(node, SequenceNode):
            trace.add("sequence")
            for step in node.steps:
                if self._should_stop_now(
                    session, getattr(step, "node_type", "unknown")
                ):
                    return
                async for chunk in self._execute_node(step, trace):
                    yield chunk
                if self._is_terminal_session_state(session):
                    logger.info(
                        f"FlowExecutor: session {self.session_id} reached terminal state "
                        f"{session.get_status().value} after sequence step '{getattr(step, 'node_type', 'unknown')}', stopping"
                    )
                    return

        elif isinstance(node, ParallelNode):
            # 并行执行所有分支
            trace.add(f"parallel(branches={len(node.branches)})")

            async def run_branch(branch: FlowNode) -> List[MessageChunk]:
                """执行单个分支并收集所有消息"""
                chunks = []
                async for chunk in self._execute_node(branch, trace):
                    chunks.extend(chunk)
                return chunks

            # 创建所有分支的任务
            tasks = [run_branch(branch) for branch in node.branches]

            # 并行执行并收集结果
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果（按分支顺序yield）
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"FlowExecutor: Branch {i} failed with error: {result}"
                    )
                    continue
                if result:
                    yield result  # pyright: ignore[reportReturnType]

            if self._is_terminal_session_state(session):
                logger.info(
                    f"FlowExecutor: session {self.session_id} reached terminal state "
                    f"{session.get_status().value} after parallel branches, stopping"
                )
                return

            trace.add(f"parallel_done({len(node.branches)})")

        elif isinstance(node, LoopNode):
            loop_count = 0
            # 检查初始条件
            while loop_count < node.max_loops:
                if self._should_stop_now(session, f"loop:{node.condition}"):
                    break
                # 在循环开始前检查条件
                if not ConditionRegistry.check(node.condition, ctx, session=session):
                    trace.add(f"loop({node.condition}=False)")
                    break

                trace.add(
                    f"loop({node.condition}=True,{loop_count + 1}/{node.max_loops})"
                )
                async for chunk in self._execute_node(node.body, trace):
                    yield chunk
                if self._is_terminal_session_state(session):
                    logger.info(
                        f"FlowExecutor: session {self.session_id} reached terminal state "
                        f"{session.get_status().value} during loop, stopping"
                    )
                    break
                loop_count += 1

            if loop_count >= node.max_loops:
                logger.warning(
                    f"FlowExecutor: Loop max iterations ({node.max_loops}) reached."
                )

        elif isinstance(node, IfNode):
            condition_met = ConditionRegistry.check(
                node.condition, ctx, session=session
            )
            trace.add(f"if({node.condition}={condition_met})")

            if condition_met:
                async for chunk in self._execute_node(node.true_body, trace):
                    yield chunk
            elif node.false_body:
                async for chunk in self._execute_node(node.false_body, trace):
                    yield chunk

        elif isinstance(node, SwitchNode):
            # 获取上下文变量值
            # 优先从 audit_status 获取，其次从 system_context 获取
            variable_value = ctx.audit_status.get(node.variable)
            if variable_value is None:
                variable_value = ctx.system_context.get(node.variable)

            if variable_value is None:
                error_msg = f"FlowExecutor: Switch variable '{node.variable}' not found in context."
                logger.error(error_msg)
                raise ValueError(error_msg)

            trace.add(f"switch({node.variable}={variable_value})")

            target_node = node.cases.get(str(variable_value))
            if target_node:
                async for chunk in self._execute_node(target_node, trace):
                    yield chunk
            elif node.default:
                async for chunk in self._execute_node(node.default, trace):
                    yield chunk
            else:
                logger.warning(
                    f"FlowExecutor: No matching case for switch '{node.variable}'={variable_value}, and no default."
                )

        elif isinstance(node, AgentNode):
            agent_key = node.agent_key
            if self._should_stop_now(session, f"agent '{agent_key}'"):
                return
            trace.add(f"agent({agent_key})")

            # 特殊处理 multi agent 需要的工具注册 (如果 agent_key 是 multi 相关的)
            # 但理论上应该在 Agent 内部处理，这里保持纯粹

            # 获取 Agent 实例
            # 注意：session_runtime._get_agent 是内部方法，这里我们需要访问
            try:
                agent = self.runtime._get_agent(agent_key)
            except KeyError:
                logger.error(
                    f"FlowExecutor: Agent '{agent_key}' not found in registry."
                )
                return

            # 如果有特殊配置，可能需要应用到 Agent (暂未实现完全覆盖，因 Agent 通常是单例或池化)
            # 这里直接执行
            phase_name = node.description or agent.agent_name

            async for message_chunks in self.runtime._execute_agent_phase(
                session_id=self.session_id,
                agent=agent,
                phase_name=phase_name,
                # override_config=node.override_config, # FlowNode definition does not have override_config yet
            ):
                if self._is_terminal_session_state(session):
                    logger.info(
                        f"FlowExecutor: session {self.session_id} reached terminal state "
                        f"{session.get_status().value} while running agent '{agent_key}', stopping"
                    )
                    return
                # 将消息添加到上下文 (这一步在 _execute_agent_phase 外部做还是内部做？)
                # 原逻辑是在外部做的: session_context.add_messages(message_chunks)
                # 所以这里我们也做
                ctx.add_messages(message_chunks)
                yield message_chunks

            if self._is_terminal_session_state(session):
                logger.info(
                    f"FlowExecutor: session {self.session_id} reached terminal state "
                    f"{session.get_status().value} after agent '{agent_key}', stopping"
                )
                return
