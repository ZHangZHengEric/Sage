import asyncio
from typing import AsyncGenerator, List, Any, Optional
from sagents.flow.schema import (
    FlowNode, AgentNode, SequenceNode, ParallelNode, LoopNode, IfNode, SwitchNode
)
from sagents.flow.conditions import ConditionRegistry
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk
from sagents.tool import ToolManager, ToolProxy
from sagents.tool.impl.todo_tool import ToDoTool


class FlowExecutor:
    """流程执行器：负责解析并执行 AgentFlow 定义"""

    def __init__(self, session_context: Any, tool_manager: Optional[Any], session_runtime: Any, session_id: str):
        self.ctx = session_context
        self.tool_manager = tool_manager
        self.runtime = session_runtime
        self.session_id = session_id

        # 注册 ToDoTool 用于多智能体任务检查
        # self._todo_tool = ToDoTool()
        # if self.tool_manager:
        #     self.tool_manager.register_tools_from_object(self._todo_tool)

    async def execute(self, node: FlowNode) -> AsyncGenerator[List[MessageChunk], None]:
        """递归执行流程节点"""
        logger.debug(f"FlowExecutor: Executing node type '{node.node_type}'")

        if isinstance(node, SequenceNode):
            for step in node.steps:
                async for chunk in self.execute(step):
                    yield chunk

        elif isinstance(node, ParallelNode):
            # 并行执行所有分支
            logger.info(f"FlowExecutor: Running {len(node.branches)} branches in parallel")

            async def run_branch(branch: FlowNode) -> List[MessageChunk]:
                """执行单个分支并收集所有消息"""
                chunks = []
                async for chunk in self.execute(branch):
                    chunks.extend(chunk)
                return chunks

            # 创建所有分支的任务
            tasks = [run_branch(branch) for branch in node.branches]

            # 并行执行并收集结果
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果（按分支顺序yield）
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"FlowExecutor: Branch {i} failed with error: {result}")
                    continue
                if result:
                    yield result

            logger.info(f"FlowExecutor: Parallel execution completed for {len(node.branches)} branches")

        elif isinstance(node, LoopNode):
            loop_count = 0
            # 检查初始条件
            while loop_count < node.max_loops:
                # 在循环开始前检查条件
                if not ConditionRegistry.check(node.condition, self.ctx):
                    logger.info(f"FlowExecutor: Loop condition '{node.condition}' met (False), exiting loop.")
                    break

                logger.info(f"FlowExecutor: Loop iteration {loop_count + 1}/{node.max_loops}")
                async for chunk in self.execute(node.body):
                    yield chunk
                loop_count += 1

            if loop_count >= node.max_loops:
                logger.warning(f"FlowExecutor: Loop max iterations ({node.max_loops}) reached.")

        elif isinstance(node, IfNode):
            condition_met = ConditionRegistry.check(node.condition, self.ctx)
            logger.debug(f"FlowExecutor: If condition '{node.condition}' -> {condition_met}")

            if condition_met:
                async for chunk in self.execute(node.true_body):
                    yield chunk
            elif node.false_body:
                async for chunk in self.execute(node.false_body):
                    yield chunk

        elif isinstance(node, SwitchNode):
            # 获取上下文变量值
            # 优先从 audit_status 获取，其次从 system_context 获取
            variable_value = self.ctx.audit_status.get(node.variable)
            if variable_value is None:
                variable_value = self.ctx.system_context.get(node.variable)

            if variable_value is None:
                error_msg = f"FlowExecutor: Switch variable '{node.variable}' not found in context."
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.debug(f"FlowExecutor: Switch variable '{node.variable}' -> {variable_value}")

            target_node = node.cases.get(str(variable_value))
            if target_node:
                async for chunk in self.execute(target_node):
                    yield chunk
            elif node.default:
                async for chunk in self.execute(node.default):
                    yield chunk
            else:
                logger.warning(f"FlowExecutor: No matching case for switch '{node.variable}'={variable_value}, and no default.")

        elif isinstance(node, AgentNode):
            agent_key = node.agent_key
            logger.info(f"FlowExecutor: Running agent '{agent_key}'")

            # 特殊处理 multi agent 需要的工具注册 (如果 agent_key 是 multi 相关的)
            # 但理论上应该在 Agent 内部处理，这里保持纯粹

            # 获取 Agent 实例
            # 注意：session_runtime._get_agent 是内部方法，这里我们需要访问
            try:
                agent = self.runtime._get_agent(agent_key)
            except KeyError:
                logger.error(f"FlowExecutor: Agent '{agent_key}' not found in registry.")
                return

            # 如果有特殊配置，可能需要应用到 Agent (暂未实现完全覆盖，因 Agent 通常是单例或池化)
            # 这里直接执行
            phase_name = node.description or agent.agent_name

            async for message_chunks in self.runtime._execute_agent_phase(
                session_context=self.ctx,
                agent=agent,
                phase_name=phase_name,
                # override_config=node.override_config, # FlowNode definition does not have override_config yet
            ):
                # 将消息添加到上下文 (这一步在 _execute_agent_phase 外部做还是内部做？)
                # 原逻辑是在外部做的: session_context.add_messages(message_chunks)
                # 所以这里我们也做
                self.ctx.add_messages(message_chunks)
                yield message_chunks
