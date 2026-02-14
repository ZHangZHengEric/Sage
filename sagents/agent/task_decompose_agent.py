from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.context.tasks.task_base import TaskBase
from sagents.context.tasks.task_manager import TaskManager
from sagents.utils.prompt_manager import PromptManager
import json
import uuid
import re

class TaskDecomposeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskDecomposeAgent"
        self.agent_description = "任务分解智能体，专门负责将复杂任务分解为可执行的子任务"
        logger.debug("TaskDecomposeAgent 初始化完成")
    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取系统前缀，使用正确的语言
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_decompose_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=5)
            # 根据 active_budget 压缩消息
            budget_info = message_manager.context_budget_manager.budget_info
            if budget_info:
                history_messages = MessageManager.compress_messages(history_messages, budget_info.get('active_budget', 8000))
            recent_message_str = MessageManager.convert_messages_to_str(history_messages)        

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        prompt = PromptManager().get_agent_prompt_auto('decompose_template', language=session_context.get_language()).format(
            task_description=recent_message_str,
            available_tools_str=available_tools_str,
            agent_description=self.system_prefix,
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language(), system_prefix_override=current_system_prefix),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TASK_DECOMPOSITION.value
            )
        ]
        message_id = str(uuid.uuid4())
        unknown_content = ''
        full_response = ''
        last_tag_type = ''
        async for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="task_decompose"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content

                for delta_content_char in delta_content:
                    delta_content_all = unknown_content+ delta_content_char
                    delta_content_type = self._judge_delta_content_type(delta_content_all, full_response, ['task_item'])

                    full_response += delta_content_char
                    if delta_content_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if delta_content_type == 'task_item':
                            if last_tag_type != 'task_item':
                                yield [MessageChunk(
                                    role=MessageRole.ASSISTANT.value,
                                    content='\n- ',
                                    message_id=message_id,
                                    message_type=MessageType.TASK_DECOMPOSITION.value
                                )]

                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content=delta_content_all,
                                message_id=message_id,
                                message_type=MessageType.TASK_DECOMPOSITION.value
                            )]
                        last_tag_type = delta_content_type
        
        async for chunk in self._finalize_decomposition_result(full_response, message_id, task_manager, session_context):
            yield chunk

    async def _finalize_decomposition_result(self, 
                                     full_response: str, 
                                     message_id: str,
                                     task_manager: Optional[TaskManager] = None,
                                     session_context: SessionContext = None) -> AsyncGenerator[List[MessageChunk], None]:
        logger.debug("TaskDecomposeAgent: 处理最终任务分解结果")
        language = session_context.get_language() if session_context else 'zh'
        try:
            # 解析任务列表
            tasks = self._convert_xlm_to_json(full_response)
            logger.info(f"TaskDecomposeAgent: 成功分解为 {len(tasks)} 个子任务")

            # 将解析后的任务数据存储到 session_context.audit_status
            if session_context:
                if 'task_decomposition_results' not in session_context.audit_status:
                    session_context.audit_status['task_decomposition_results'] = []
                session_context.audit_status['task_decomposition_results'] = tasks
                logger.info("TaskDecomposeAgent: 已将任务分解结果存储到 session_context.audit_status")

            # 如果有TaskManager，将子任务存储到任务管理器中
            if task_manager:
                logger.info("TaskDecomposeAgent: 将分解的子任务存储到TaskManager")
                task_objects = []

                for i, task_data in enumerate(tasks):
                    # 创建TaskBase对象
                    task_obj = TaskBase(
                        description=task_data.get('description'),
                        task_type='subtask',
                        status='pending',
                        priority=i,  # 按分解顺序设置优先级
                        assigned_to='ExecutorAgent'
                    )
                    task_objects.append(task_obj)

                # 批量添加任务到TaskManager
                task_ids = task_manager.add_tasks_batch(task_objects)
                logger.info(f"TaskDecomposeAgent: 成功将 {len(task_ids)} 个子任务添加到TaskManager")

                # 将任务ID添加到原始任务数据中（用于后续引用）
                for task_data, task_id in zip(tasks, task_ids):
                    task_data['task_id'] = task_id

            # 返回最终结果（保持原有流式输出格式）
            planning_label = PromptManager().get_prompt(
                'task_decomposition_planning',
                agent='common',
                language=language,
                default='任务拆解规划：'
            )
            result_content = planning_label + '\n'
            for task in tasks:
                result_content += f"- {task.get('description', '')}\n"

            result_message = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=result_content,
                message_id=message_id,
                message_type=MessageType.TASK_DECOMPOSITION.value
            )

            yield [result_message]
        except Exception as e:
            logger.error(f"TaskDecomposeAgent: 处理最终结果时发生错误: {str(e)}")
            failed_message = PromptManager().get_prompt(
                'task_decomposition_failed',
                agent='common',
                language=language,
                default=f"任务分解失败: {str(e)}"
            )
            error_content = failed_message.format(error=str(e))
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=error_content,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TASK_DECOMPOSITION.value
            )]
    def _convert_xlm_to_json(self, content: str) -> List[Dict[str, Any]]:
        try:
            tasks = []
            task_items = re.findall(r'<task_item>(.*?)</task_item>', content, re.DOTALL)

            for item in task_items:
                task = {
                    "description": item.strip(),
                }
                tasks.append(task)

            logger.debug(f"TaskDecomposeAgent: XML转JSON完成，共提取 {len(tasks)} 个任务")
            return tasks

        except Exception as e:
            logger.error(f"TaskDecomposeAgent: XML转JSON失败: {str(e)}")
            raise
