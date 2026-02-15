from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.utils.prompt_manager import PromptManager
from sagents.utils.common_utils import ensure_list

import json
import uuid


class TaskPlanningAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "PlanningAgent"
        self.agent_description = "规划智能体，专门负责基于当前状态生成下一步执行计划"
        logger.debug("PlanningAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取系统前缀，使用正确的语言
        current_system_prefix = PromptManager().get_agent_prompt_auto('task_planning_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager
        
        recent_execution_messages = message_manager.extract_all_context_messages(recent_turns=10)
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            recent_execution_messages = MessageManager.compress_messages(recent_execution_messages, min(budget_info.get('active_budget', 8000), 4000))
        
        # 使用最近的消息作为任务描述，包含执行结果
        recent_execution_messages_str = MessageManager.convert_messages_to_str(recent_execution_messages)

        
        available_tools_name = tool_manager.list_all_tools_name() if tool_manager else []
        available_tools_str = ", ".join(available_tools_name) if available_tools_name else "无可用工具"
        prompt = PromptManager().get_agent_prompt_auto('planning_template', language=session_context.get_language()).format(
            recent_execution_messages=recent_execution_messages_str,
            available_tools_str=available_tools_str,
            agent_description=self.system_prefix
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language(), system_prefix_override=current_system_prefix),
            MessageChunk(
                role=MessageRole.USER.value,
                content=prompt,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.PLANNING.value
            )
        ]

        message_id = str(uuid.uuid4())
        all_content = ''
        async for llm_repsonse_chunk in self._call_llm_streaming(messages=llm_request_message,
                                                                 session_id=session_id,
                                                                 step_name="planning"):
            if len(llm_repsonse_chunk.choices) == 0:
                continue
            if llm_repsonse_chunk.choices[0].delta.content:
                delta_content = llm_repsonse_chunk.choices[0].delta.content
                all_content += delta_content

                yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=delta_content,
                    message_id=message_id,
                    message_type=MessageType.PLANNING.value
                )]
        
        # 记录规划结果
        logger.debug(f"PlanningAgent: 规划结果: {all_content}")
        if "all_plannings" not in session_context.audit_status:
            session_context.audit_status['all_plannings'] = []
        
        # 保存简单的文本规划结果
        session_context.audit_status['all_plannings'].append({
            "next_step": {
                "description": all_content,
                "required_tools": [], # 不再需要解析
                "expected_output": "",
                "success_criteria": ""
            }
        })