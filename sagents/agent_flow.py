# 该模块可以接受拼接的智能体的流程，按照流程运行执行体。

import traceback
from typing import List, AsyncGenerator
from sagents.agent.agent_base import AgentBase
from sagents.context.session_context import SessionContext, delete_session_context, init_session_context
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionStatus
from sagents.tool.tool_proxy import ToolProxy
import uuid
from typing import Dict, Any, Optional, Union
from sagents.utils.logger import logger
from sagents.utils.session_local import session_manager


class AgentFlow:
    def __init__(self, agent_list: List[AgentBase], workspace: str, memory_root: Optional[str] = None) -> None:
        self.agent_list = agent_list
        self.workspace = workspace
        self.memory_root = memory_root  # 如果为None则不使用本地记忆工具

    async def run_stream(self,
                         input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
                         tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
                         session_id: Optional[str] = None,
                         user_id: Optional[str] = None,
                         system_context: Optional[Dict[str, Any]] = None,
                         available_workflows: Optional[Dict[str, Any]] = {},
                         context_budget_config: Optional[Dict[str, Any]] = None) -> AsyncGenerator[List[MessageChunk], None]:
        """
        运行智能体流程，返回消息流
        Args:
            input_messages: 输入消息列表
            tool_manager: 工具管理器实例
            session_id: 会话ID
            user_id: 用户ID
            system_context: 系统上下文
            available_workflows: 可用工作流列表
            context_budget_config: 上下文预算配置

        Returns:
            消息流
        """
        try:
            # 初始化会话
            # 初始化该session 的context 管理器
            session_id = session_id or str(uuid.uuid4())
            session_context = init_session_context(
                session_id=session_id,
                user_id=user_id or "",
                workspace_root=self.workspace,
                memory_root=self.memory_root or "",
                context_budget_config=context_budget_config
            )
            with session_manager.session_context(session_id):
                logger.info(f"开始流式工作流，会话ID: {session_id}")
                # 设置agent配置信息到SessionContext
                session_context.set_agent_config(
                    model=None,
                    model_config={},
                    system_prefix=None,
                    workspace=self.workspace,
                    memory_root=self.memory_root or "",
                    available_tools=tool_manager.list_all_tools_name() if tool_manager else [],
                    system_context=system_context or {},
                    available_workflows=available_workflows or {},
                    deep_thinking=False,
                    multi_agent=False,
                    more_suggest=False,
                    max_loop_count=10
                )

                if system_context:
                    logger.info(f"SAgent: 设置了system_context参数: {system_context}")
                    session_context.add_and_update_system_context(system_context)

                if available_workflows:
                    if len(available_workflows.keys()) > 0:
                        logger.info(f"SAgent: 提供了 {len(available_workflows)} 个工作流模板: {list(available_workflows.keys())}")
                        session_context.workflow_manager.load_workflows_from_dict(available_workflows)

                session_context.status = SessionStatus.RUNNING
                initial_messages = self._prepare_initial_messages(input_messages)

                # 尝试初始化记忆
                session_context.init_user_memory_manager(tool_manager)

                # 判断initial_messages 的message 是否已经存在，没有的话添加，通过message_id 来进行判断
                logger.info(f"SAgent: 合并前message_manager的消息数量：{len(session_context.message_manager.messages)}")
                all_message_ids = [m.message_id for m in session_context.message_manager.messages]
                for message in initial_messages:
                    if message.message_id not in all_message_ids:
                        session_context.message_manager.add_messages(message)
                    else:
                        # 如果message 存在，更新，以新的message 为准
                        session_context.message_manager.update_messages(message)

                logger.info(f"SAgent: 合并后message_manager的消息数量：{len(session_context.message_manager.messages)}")

                # 准备历史上下文：分割、BM25重排序、预算限制并保存到system_context
                session_context.set_history_context()

                # 调用内部执行逻辑
                async for chunk in self.run_stream_internal(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id
                ):
                    yield chunk

        except Exception:
            logger.error(f"SAgent: 运行智能体流程时出错: {traceback.format_exc()}")
        finally:
            try:
                session_context.save()
            except Exception as save_error:
                logger.warning(f"traceback: {traceback.format_exc()}")
                logger.warning(f"SAgent: 保存会话状态 {session_id} 时出错: {save_error}")

            # 清理会话，防止内存泄漏
            try:
                delete_session_context(session_id)
                logger.info(f"SAgent: 已清理会话 {session_id}")
            except Exception as cleanup_error:
                logger.warning(f"SAgent: 清理会话 {session_id} 时出错: {cleanup_error}")

    async def run_stream_internal(self,
                                  session_context: SessionContext,
                                  tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
                                  session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        """
        内部运行逻辑，负责具体的 Agent 调度
        """
        for agent in self.agent_list:
            async for message_chunks in self._execute_agent_phase(
                session_context=session_context,
                tool_manager=tool_manager,
                session_id=session_id,
                agent=agent,
                phase_name=agent.agent_name
            ):
                # 过滤需要保存的消息：只保存属于当前会话的消息（session_id一致或为None）
                # 这样可以防止子Agent的流式消息（具有不同的session_id）被错误地添加到父Agent的历史记录中
                # 但所有消息都会被yield出去，以支持前端的流式展示
                messages_to_save = [
                    msg for msg in message_chunks
                    if msg.session_id is None or msg.session_id == session_id
                ]

                if messages_to_save:
                    session_context.message_manager.add_messages(messages_to_save)
                
                yield message_chunks

    async def _execute_agent_phase(self,
                                   session_context: SessionContext,
                                   tool_manager: Optional[Any],
                                   session_id: str,
                                   agent: AgentBase,
                                   phase_name: str):
        logger.info(f"SAgent: 使用 {agent.agent_description} 智能体")
        # 检查中断
        if session_context.status == SessionStatus.INTERRUPTED:
            logger.info(f"SAgent: {phase_name} 阶段被中断，会话ID: {session_id}")
            return

        for chunk in agent.run_stream(
            session_context=session_context,
            tool_manager=tool_manager,
            session_id=session_id,
        ):
            # 在每个块之间检查中断
            if session_context.status == SessionStatus.INTERRUPTED:
                logger.info(f"SAgent: {phase_name} 阶段在块处理中被中断，会话ID: {session_id}")
                return
            yield chunk

        logger.info(f"SAgent: {phase_name} 阶段完成")

    def _prepare_initial_messages(self, input_messages: Union[List[Dict[str, Any]], List[MessageChunk]]) -> List[MessageChunk]:
        """
        准备初始消息

        Args:
            input_messages: 输入消息列表

        Returns:
            List[MessageChunk]: 准备好的消息列表
        """
        logger.debug("SAgent: 准备初始消息")
        # 先检查input_message 格式以及类型
        if not isinstance(input_messages, list):
            raise ValueError("input_messages 必须是列表类型")
        # 检查每个消息的格式
        for msg in input_messages:
            if not isinstance(msg, (dict, MessageChunk)):
                raise ValueError("每个消息必须是字典或MessageChunk类型")
        # 对dict 的消息输入，转化成MessageChunk
        input_messages = [MessageChunk(**msg) if isinstance(msg, dict) else msg for msg in input_messages]
        # 清理过长的消息历史
        logger.info(f"SAgent: 初始化消息数量: {len(input_messages)}")
        return input_messages
