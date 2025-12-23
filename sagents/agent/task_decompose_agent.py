import json
import re
import uuid
from typing import Any, Dict, Generator, List, Optional

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext
from sagents.context.tasks.task_base import TaskBase
from sagents.context.tasks.task_manager import TaskManager
from sagents.tool.tool_manager import ToolManager
from sagents.utils.logger import logger
from sagents.utils.prompt_manager import PromptManager

from .agent_base import AgentBase


class TaskDecomposeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto('task_decompose_system_prefix')
        self.agent_name = "TaskDecomposeAgent"
        self.agent_description = "任务分解智能体，专门负责将复杂任务分解为可执行的子任务"
        logger.info("TaskDecomposeAgent 初始化完成")
    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        # 重新获取系统前缀，使用正确的语言
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto('task_decompose_system_prefix', language=session_context.get_language())
        
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager
        
        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=5,max_length=self.max_history_context_length)
            recent_message_str = MessageManager.convert_messages_to_str(history_messages)        
        
        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        prompt = PromptManager().get_agent_prompt_auto('decompose_template', language=session_context.get_language()).format(
            task_description=recent_message_str,
            available_tools_str=available_tools_str,
            agent_description=self.system_prefix,
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
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
                                    content='',
                                    message_id=message_id,
                                    show_content='\n- ',
                                    message_type=MessageType.TASK_DECOMPOSITION.value
                                )]
                            
                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content="",
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type=MessageType.TASK_DECOMPOSITION.value
                            )]
                        last_tag_type = delta_content_type

        async for chunk in self._finalize_decomposition_result(full_response, message_id, task_manager):
            yield chunk

    async def _finalize_decomposition_result(self, 
                                     full_response: str, 
                                     message_id: str,
                                     task_manager: Optional[TaskManager] = None) -> Generator[List[MessageChunk], None, None]:
        logger.debug("TaskDecomposeAgent: 处理最终任务分解结果")
        try:
            # 解析任务列表
            tasks = self._convert_xlm_to_json(full_response)
            logger.info(f"TaskDecomposeAgent: 成功分解为 {len(tasks)} 个子任务")
            
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
            result_content = '任务拆解规划：\n' + json.dumps({"tasks": tasks}, ensure_ascii=False)
            
            result_message = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=result_content,
                message_id=message_id,
                show_content='',
                message_type=MessageType.TASK_DECOMPOSITION.value
            )
            
            yield [result_message]
        except Exception as e:
            logger.error(f"TaskDecomposeAgent: 处理最终结果时发生错误: {str(e)}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"任务分解失败: {str(e)}",
                message_id=str(uuid.uuid4()),
                show_content=f"任务分解失败: {str(e)}",
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
    