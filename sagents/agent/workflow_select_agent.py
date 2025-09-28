
import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator,Union
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import AgentToolSpec
from sagents.context.tasks.task_manager import TaskManager
from sagents.context.tasks.task_base import TaskBase, TaskStatus
from sagents.context.workflows import WorkflowManager
import json
import uuid
from copy import deepcopy
from openai import OpenAI




class WorkflowSelectAgent(AgentBase):
    def __init__(self, model: Optional[OpenAI] = None, model_config: Dict[str, Any] = ..., system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.WORKFLOW_SELECT_PROMPT =  """
你是一个工作流选择专家。请根据用户的对话历史，从提供的工作流模板中选择最合适的一个。
## agent的描述和要求
{agent_description}

## 对话历史
{conversation_history}

## 可用的工作流模板
{workflow_list}

## 任务要求
1. 仔细分析对话历史中用户的核心需求和任务类型
2. 对比各个工作流模板的适用场景
3. 选择匹配的工作流，或者判断没有合适的工作流

## 输出格式（JSON）
```json
{{
    "has_matching_workflow": true/false,
    "selected_workflow_index": 0
}}
```

请确保输出的JSON格式正确。本次输出只输出JSON字符串，不需要包含任何其他内容和解释。
如果没有合适的工作流，请设置has_matching_workflow为false。
selected_workflow_index 从0 开始计数
"""
        self.agent_name = "WorkflowSelectAgent"
        self.agent_description = "工作流选择智能体，专门负责基于当前状态选择最合适的工作流"
        logger.info("WorkflowSelectAgent 初始化完成")

    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        message_manager = session_context.message_manager
        
        if 'task_rewrite' in session_context.audit_status:
            recent_message_str = MessageManager.convert_messages_to_str([MessageChunk(
                role=MessageRole.USER.value,
                content = session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )])
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=3,max_length=self.max_history_context_length)
            recent_message_str = MessageManager.convert_messages_to_str(history_messages)
        
        # 使用WorkflowManager格式化工作流列表
        workflow_list = session_context.workflow_manager.format_workflow_list()

        prompt = self.WORKFLOW_SELECT_PROMPT.format(
            conversation_history=recent_message_str,
            workflow_list=workflow_list,
            agent_description=self.system_prefix,
        )

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                show_content=prompt,
                message_type=MessageType.GUIDE.value
            )
        ]
        all_content = ''
        for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                             session_id=session_id,
                                             step_name="workflow_select"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                all_content += llm_repsonse_chunk.choices[0].delta.content

        try:
            # 提取JSON部分
            logger.debug(f"WorkflowSelector: 原始LLM响应: {all_content}")
            json_start = all_content.find('{')
            json_end = all_content.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_content = all_content[json_start:json_end]
                result = json.loads(json_content)
                logger.debug(f"WorkflowSelector: 提取的JSON内容: {json_content}")
                has_matching = result.get('has_matching_workflow', False)
                selected_workflow_index = result.get('selected_workflow_index', 0)
                
                logger.info(f"WorkflowSelector: LLM分析结果 - 匹配: {has_matching}, 工作流索引: {selected_workflow_index}")
                if has_matching and selected_workflow_index >= 0:
                    selected_workflow = session_context.workflow_manager.get_workflow_by_index(selected_workflow_index)
                    if selected_workflow:
                        logger.info(f"WorkflowSelector: 工作流名称: {selected_workflow.name}")
                        selected_workflow_name = selected_workflow.name
                        guidance = session_context.workflow_manager.format_workflows_for_context([selected_workflow_name])
                        session_context.add_and_update_system_context({'workflow_guidance': guidance})
                else:
                    logger.info("WorkflowSelector: 未找到合适的工作流")
            else:
                logger.error("WorkflowSelector: 无法从LLM响应中提取JSON内容")
                
        except json.JSONDecodeError as e:
            logger.error(f"WorkflowSelector: JSON解析失败: {str(e)}")
            logger.error(f"WorkflowSelector: 原始响应: {all_content}")
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=f"WorkflowSelector: 无法从LLM响应中提取JSON内容，原始响应: {all_content}",
                message_id=str(uuid.uuid4()),
                show_content="",
                message_type=MessageType.GUIDE.value
            )]
