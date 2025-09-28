import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.context.tasks.task_base import TaskBase
from sagents.context.tasks.task_manager import TaskManager
from sagents.utils.prompt_manager import PromptManager
import json
import uuid,re
from copy import deepcopy

class TaskDecomposeAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.SYSTEM_PREFIX_FIXED = PromptManager().task_decompose_system_prefix
        self.DECOMPOSE_PROMPT_TEMPLATE = """# 任务分解指南
通过用户的历史对话，来观察用户的需求或者任务

## 智能体的描述和要求
{agent_description}

## 用户历史对话
{task_description}

## 可用工具
{available_tools_str}

## 分解要求
1. 仅当任务复杂时才进行分解，如果任务本身非常简单，可以直接作为一个子任务，不要为了凑数量而强行拆分。
2. 子任务的分解要考虑可用的工具的能力范围。
3. 确保每个子任务都是原子性的，且尽量相互独立，避免人为拆分无实际意义的任务。
4. 考虑任务之间的依赖关系，输出的列表必须是有序的，按照优先级从高到低排序，优先级相同的任务按照依赖关系排序。
5. 输出格式必须严格遵守以下要求。
6. 如果有任务Thinking的过程，子任务要与Thinking的处理逻辑一致。
7. 子任务数量不要超过10个，较简单的子任务可以合并为一个子任务。
8. 子任务描述中不要直接说出工具的原始名称，使用工具描述来表达工具。
## 输出格式
```
<task_item>
子任务1描述
</task_item>
<task_item>
子任务2描述
</task_item>
```
"""
        self.SYSTEM_PREFIX_FIXED = """你是一个任务分解者，你需要根据用户需求，将复杂任务分解为清晰可执行的子任务。"""
        self.agent_name = "TaskDecomposeAgent"
        self.agent_description = "任务分解智能体，专门负责将复杂任务分解为可执行的子任务"
        logger.info("TaskDecomposeAgent 初始化完成")
    def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager
        
        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=10,max_length=self.max_history_context_length)
            recent_message_str = MessageManager.convert_messages_to_str(history_messages)        
        
        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"

        prompt = self.DECOMPOSE_PROMPT_TEMPLATE.format(
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
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
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

        yield from self._finalize_decomposition_result(full_response, message_id, task_manager)

    def _finalize_decomposition_result(self, 
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
    