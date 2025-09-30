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

class TaskPlanningAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.SYSTEM_PREFIX_FIXED = PromptManager().task_planning_system_prefix
        self.PLANNING_PROMPT_TEMPLATE ="""# 任务规划指南

## 智能体的描述和要求
{agent_description}

## 完整任务描述
{task_description}

## 任务管理器状态
{task_manager_status}

## 近期完成工作
{completed_actions}

## 可用工具
{available_tools_str}

## 规划规则
1. 根据我们的当前任务以及近期完成工作，为了达到逐步完成任务管理器的未完成子任务或者完整的任务，清晰描述接下来要执行的具体的任务名称。
2. 确保接下来的任务可执行且可衡量
3. 优先使用现有工具
4. 设定明确的成功标准
5. 只输出以下格式的XLM，不要输出其他内容,不要输出```, <tag>标志位必须在单独一行
6. description中不要包含工具的真实名称
7. required_tools至少包含5个可能需要的工具的名称，最多10个。

## 输出格式
```
<next_step_description>
子任务的清晰描述，一段话不要有换行
</next_step_description>
<required_tools>
["tool1_name","tool2_name"]
</required_tools>
<expected_output>
预期结果描述，一段话不要有换行
</expected_output>
<success_criteria>
如何验证完成，一段话不要有换行
</success_criteria>
```
"""
        self.agent_name = "PlanningAgent"
        self.agent_description = "规划智能体，专门负责基于当前状态生成下一步执行计划"
        logger.info("PlanningAgent 初始化完成")
    
    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        task_manager = session_context.task_manager

        if 'task_rewrite' in session_context.audit_status:
            task_description_messages_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
            task_description_messages_str = MessageManager.convert_messages_to_str(history_messages)
        
        task_manager_status = task_manager.get_status_description() if task_manager else '无任务管理器'

        completed_actions_messages = message_manager.extract_after_last_stage_summary_messages(max_length=(self.max_model_input_len-MessageManager.calculate_str_token_length(task_description_messages_str) - MessageManager.calculate_str_token_length(task_manager_status))//2)
        completed_actions_messages_str = MessageManager.convert_messages_to_str(completed_actions_messages)

        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str =", ".join(available_tools_name) if available_tools_name else "无可用工具"


        prompt = self.PLANNING_PROMPT_TEMPLATE.format(
            task_description=task_description_messages_str,
            task_manager_status=task_manager_status,
            completed_actions=completed_actions_messages_str,
            available_tools_str=available_tools_str,
            agent_description=self.system_prefix
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.PLANNING.value
            )
        ]
        
        message_id = str(uuid.uuid4())
        unknown_content = ''
        all_content = ''
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="planning"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content + delta_content_char
                    # 判断delta_content的类型
                    tag_type = self._judge_delta_content_type(delta_content_all, all_content, ['next_step_description','required_tools','expected_output','success_criteria'])
                    all_content += delta_content_char
                    
                    if tag_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if tag_type in ['next_step_description','expected_output']:
                            if tag_type != last_tag_type:
                                yield [MessageChunk(
                                    role=MessageRole.ASSISTANT.value,
                                    content='',
                                    message_id=message_id,
                                    show_content='\n\n',
                                    message_type=MessageType.PLANNING.value
                                )]
                            
                            yield [MessageChunk(
                                role=MessageRole.ASSISTANT.value,
                                content="",
                                message_id=message_id,
                                show_content=delta_content_char,
                                message_type=MessageType.PLANNING.value
                            )]
                        last_tag_type = tag_type
        yield from self._finalize_planning_result(
            session_context=session_context,
            all_content=all_content, 
            message_id=message_id
        )
    def _finalize_planning_result(self, 
                                session_context: SessionContext,
                                all_content: str, 
                                message_id: str) -> Generator[List[MessageChunk], None, None]:
        logger.debug("PlanningAgent: 处理最终规划结果")
        
        try:
            response_json = self.convert_xlm_to_json(all_content)
            if "all_plannings" not in session_context.audit_status:
                session_context.audit_status['all_plannings'] = []
            session_context.audit_status['all_plannings'].append(response_json)
            logger.info(f"PlanningAgent: 规划结果: {response_json}")
            logger.info("PlanningAgent: 规划完成")
            
            result_message = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content='下一步规划: ' + json.dumps(response_json, ensure_ascii=False),
                message_id=message_id,
                show_content='',
                message_type=MessageType.PLANNING.value
            )
            yield [result_message]
            
        except Exception as e:
            logger.error(f"PlanningAgent: 处理最终结果时发生错误: {str(e)}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"任务规划失败: {str(e)}",
                message_id=str(uuid.uuid4()),
                show_content=f"任务规划失败: {str(e)}",
                message_type=MessageType.PLANNING.value
            )]

    def convert_xlm_to_json(self, xlm_content: str) -> Dict[str, Any]:
        logger.debug("PlanningAgent: 转换XML内容为JSON格式")
        logger.debug(f"PlanningAgent: XML内容: {xlm_content}")
        
        description = ''
        required_tools = '[]'
        expected_output = ''
        success_criteria = ''
        try:
            description = xlm_content.split('<next_step_description>')[1].split('</next_step_description>')[0].strip()
            required_tools = xlm_content.split('<required_tools>')[1].split('</required_tools>')[0].strip()
            expected_output = xlm_content.split('<expected_output>')[1].split('</expected_output>')[0].strip()
            success_criteria = xlm_content.split('<success_criteria>')[1].split('</success_criteria>')[0].strip()

        except Exception as e:
            logger.error(f"PlanningAgent: XML转JSON失败: {str(e)}")
            logger.error(f"PlanningAgent: XML转JSON失败的XML内容: {xlm_content}")
            
        result = {
            "next_step": {
                "description": description,
                "required_tools": required_tools,
                "expected_output": expected_output,
                "success_criteria": success_criteria
            }
        }
            
        logger.debug(f"PlanningAgent: XML转JSON完成: {result}")
        return result